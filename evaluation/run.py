"""Run the evaluation and write one JSON record per question (resumable).

    # the question suite (needs an LLM key; ~1-4 LLM calls per question)
    python -m evaluation.run --suite questions --delay 15
    # continue a run that stopped (quota, crash): already scored questions are skipped
    python -m evaluation.run --suite questions --run-id 20260926-120000
    # adversarial SQL through validator + read-only database, no LLM calls
    python -m evaluation.run --suite sql-safety
    # BIRD Mini-Dev (load it first, see evaluation/bird.py): per BIRD database, or all 75 tables
    python -m evaluation.run --dataset bird --databases formula_1,financial --delay 5
    python -m evaluation.run --dataset bird --scope all --evidence off
    # BIRD's other dev questions, for tuning: a fixed sample stratified by database and difficulty
    python -m evaluation.run --dataset bird --split dev --sample 300 --daily-tokens 200000
    # metrics
    python -m evaluation.report evaluation/results/<run-id>.jsonl

The database is DATABASE_URL (the read-only sql_agent account on the pinned OWID data; BIRD runs
use the database `bird` on the same server with the same account). The run is
refused when its row counts differ from those the ground truth was built on. Provider failures
(rate limits, outages) are recorded as "not run", never as wrong answers; after several in a row
the run stops and can be resumed later. A used-up daily quota stops the run at once; a short
per-minute limit is waited out (as long as the provider asks, up to two minutes) and the question
is asked again.

Before running, the expected token use is printed: tokens per question as measured in earlier runs
of the same model and dataset (never assumed), against --daily-tokens when given.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.agent.controller import AgentController, AgentResult
from app.agent.sql_generator import Turn
from app.config import get_settings
from app.database.connections import ConnectionConfig, ConnectionRegistry, DatabaseConnection
from app.llm.client import LLMClient, OpenAICompatibleClient, ScriptedLLMClient
from evaluation import EVAL_DIR, ROOT, bird
from evaluation.dataset import dataset_commit, fingerprint, load_expected, load_questions
from evaluation.safety_sql import ADVERSARIAL_SQL
from evaluation.scoring import DEFAULT_REL_TOL, Outcome, score, set_match

RESULTS_DIR = EVAL_DIR / "results"
MAX_ROWS_RECORDED = 50
MAX_TEXT_RECORDED = 1000
PROVIDER_FAILURE_PREFIXES = ("LLM provider returned HTTP", "LLM request failed")
# A per-minute limit is waited out when the provider asks for at most this long, this many times.
MAX_RATE_LIMIT_WAIT_SECONDS = 120
MAX_RATE_LIMIT_WAITS = 2
LLM_STEPS = ("sql_generation", "sql_repair", "answer_generation")

Ask = Callable[[dict[str, Any]], AgentResult]
# Extra verdicts for a scored question (BIRD's official metrics, see evaluation/bird.py).
Official = Callable[[dict[str, Any], AgentResult], dict[str, Any]]


@dataclass
class RunSummary:
    attempted: int = 0
    scored: int = 0
    provider_failures: int = 0
    stopped_early: bool = False
    integrity_ok: bool = True


def is_provider_failure(result: AgentResult) -> bool:
    """The LLM provider could not be reached or refused (quota, outage): not the agent's answer."""
    return (
        result.status == "error"
        and result.error is not None
        and result.error.category == "llm_error"
        and result.error.message.startswith(PROVIDER_FAILURE_PREFIXES)
    )


def outcome_of(result: AgentResult) -> Outcome:
    return Outcome(
        status=result.status,
        columns=result.columns,
        rows=result.rows,
        error_category=result.error.category if result.error else None,
        response_text=result.model_dump_json(),
    )


def quota_exhausted(result: AgentResult) -> bool:
    return is_provider_failure(result) and result.error is not None and result.error.code == "quota_exhausted"


def rate_limit_wait(result: AgentResult) -> int | None:
    """Seconds to wait before asking again, for a short per-minute limit; None otherwise."""
    error = result.error
    if not is_provider_failure(result) or error is None or error.code != "rate_limit":
        return None
    wait = error.retry_after_seconds
    return wait if wait is not None and wait <= MAX_RATE_LIMIT_WAIT_SECONDS else None


def llm_usage(result: AgentResult) -> dict[str, Any]:
    """LLM calls and tokens of one question, from the trace (None when the provider gave no counts)."""
    calls = [e for e in result.trace if e.step in LLM_STEPS and e.status != "skipped"]
    prompt = [e.detail["prompt_tokens"] for e in calls if e.detail.get("prompt_tokens") is not None]
    completion = [
        e.detail["completion_tokens"] for e in calls if e.detail.get("completion_tokens") is not None
    ]
    return {
        "llm_calls": len(calls),
        "prompt_tokens": sum(prompt) if prompt else None,
        "completion_tokens": sum(completion) if completion else None,
    }


def failed_steps(result: AgentResult) -> list[dict[str, Any]]:
    """What went wrong on the way (each one triggered a repair or ended the question)."""
    failures = []
    for event in result.trace:
        if event.status != "failed" or event.step == "completed":
            continue
        detail = event.detail
        reason = detail.get("code") or detail.get("category") or detail.get("checks") or detail.get("error")
        failures.append(
            {
                "step": event.step,
                "attempt": detail.get("attempt"),
                "reason": reason if isinstance(reason, list) else str(reason)[:200],
            }
        )
    return failures


def _text(value: str | None) -> str | None:
    return value[:MAX_TEXT_RECORDED] if value is not None else None


def timed_out(result: AgentResult) -> bool:
    return any(
        e.step == "query_execution" and e.status == "failed" and e.detail.get("category") == "timeout"
        for e in result.trace
    )


def load_records(path: Path) -> dict[str, dict[str, Any]]:
    """Latest record per question id."""
    records: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if "id" in record:
                records[record["id"]] = record
    return records


def run_items(
    items: list[dict[str, Any]],
    ask: Ask,
    expected: dict[str, list[dict[str, Any]]],
    path: Path,
    meta: dict[str, Any],
    secrets: list[str],
    delay_seconds: float = 0.0,
    max_provider_failures: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    check_integrity: Callable[[], dict[str, int]] | None = None,
    log: Callable[[str], None] = print,
    resume_command: str | None = None,
    official: Official | None = None,
    tokens_per_question: tuple[float, str] | None = None,
    daily_tokens: int | None = None,
) -> RunSummary:
    summary = RunSummary()
    done = {i for i, r in load_records(path).items() if not r.get("provider_failure")}
    pending = [item for item in items if item["id"] not in done]
    already = len(done & {i["id"] for i in items})
    log(f"{len(items)} items, {already} already done, {len(pending)} to run -> {path}")
    if pending:
        log(token_estimate(len(pending), tokens_per_question, daily_tokens))
    before = check_integrity() if check_integrity else None
    consecutive_failures = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    for position, item in enumerate(pending):
        if position and delay_seconds:
            sleep(delay_seconds)
        started = time.perf_counter()
        result = ask(item)
        for _ in range(MAX_RATE_LIMIT_WAITS):
            wait = rate_limit_wait(result)
            if wait is None:
                break
            log(f"  {item['id']} rate limited; asking again in {wait} s")
            sleep(wait)
            started = time.perf_counter()
            result = ask(item)
        latency_ms = int((time.perf_counter() - started) * 1000)
        summary.attempted += 1
        provider_failure = is_provider_failure(result)
        record: dict[str, Any] = {
            "id": item["id"],
            "category": item["category"],
            "expected_behavior": item["expected_behavior"],
            "question": item["question"],
            **({"db_id": item["db_id"]} if "db_id" in item else {}),
            "status": result.status,
            "provider_failure": provider_failure,
            "error_category": result.error.category if result.error else None,
            "error_code": result.error.code if result.error else None,
            "error": result.error.message[:300] if result.error else None,
            "sql": result.sql,
            "columns": result.columns,
            "rows": result.rows[:MAX_ROWS_RECORDED],
            "row_count": len(result.rows),
            "truncated": result.metadata.truncated,
            "retry_count": result.metadata.retry_count,
            "timed_out": timed_out(result),
            # Why the agent answered as it did: its own explanation, clarification question and
            # plan (structured artifacts, never chain-of-thought), the result checks that fired,
            # and every failed step on the way.
            "explanation": _text(result.explanation),
            "clarification_question": _text(result.clarification_question),
            "plan": result.plan.model_dump() if result.plan else None,
            "checks": [c.code for c in result.checks],
            "failed_steps": failed_steps(result),
            **llm_usage(result),
            "latency_ms": latency_ms,
            "request_id": result.metadata.request_id,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **meta,
        }
        if provider_failure:
            summary.provider_failures += 1
            consecutive_failures += 1
            record.update(correct=None, reason="not run: " + (result.error.message if result.error else ""))
        else:
            consecutive_failures = 0
            summary.scored += 1
            verdict = score(item, expected.get(item["id"]), outcome_of(result), secrets)
            record.update(
                correct=verdict.correct, reason=verdict.reason, safety_violation=verdict.safety_violation
            )
            if item["expected_behavior"] == "query":
                # BIRD's row-set rule with tolerant values, as a second opinion (see scoring.set_match).
                rel_tol = item.get("ground_truth", {}).get("rel_tol", DEFAULT_REL_TOL)
                record["set_correct"] = result.status == "success" and any(
                    set_match(e, result.columns, result.rows, rel_tol) for e in expected.get(item["id"]) or []
                )
            if official is not None:
                record.update(official(item, result))
        with path.open("a") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        mark = "not run" if provider_failure else ("ok" if record["correct"] else "WRONG")
        log(f"  {item['id']} {mark:7} {record['reason'][:90]}")
        resume = (
            resume_command or f"python -m evaluation.run --suite {meta['suite']} --run-id {meta['run_id']}"
        )
        if quota_exhausted(result):
            summary.stopped_early = True
            wait = result.error.retry_after_seconds if result.error else None
            when = (
                f"after {(datetime.now(UTC) + timedelta(seconds=wait)).isoformat(timespec='minutes')}"
                if wait is not None
                else "when the provider's quota resets"
            )
            log(f"Stopped: the provider's quota is used up (not a per-minute limit). Resume {when} with:")
            log(f"  {resume}")
            break
        if consecutive_failures >= max_provider_failures:
            summary.stopped_early = True
            log(f"Stopped after {consecutive_failures} provider failures in a row (quota or outage).")
            log(f"Resume later with: {resume}")
            break
    if check_integrity and before is not None:
        after = check_integrity()
        summary.integrity_ok = before == after
        if not summary.integrity_ok:
            with path.open("a") as handle:
                handle.write(
                    json.dumps({"type": "integrity_violation", "before": before, "after": after}) + "\n"
                )
            log("SAFETY: the database changed during the run!")
    return summary


def token_estimate(pending: int, per_question: tuple[float, str] | None, daily_tokens: int | None) -> str:
    """One line: the tokens this run is expected to use, from measured use only."""
    if per_question is None:
        return "Token use: unknown (no earlier run of this model and dataset recorded token counts)."
    tokens, source = per_question
    total = round(pending * tokens)
    line = f"Token use: about {total:,} ({pending} questions x {tokens:,.0f}, measured in {source})"
    if daily_tokens:
        days = total / daily_tokens
        line += f"; {days:.1f} x the daily budget of {daily_tokens:,}"
        if days > 1:
            line += ": the run will stop at the quota and need resuming on later days"
    return line + "."


def measured_tokens_per_question(
    dataset: str, model: str, answers: str, results_dir: Path = RESULTS_DIR
) -> tuple[float, str] | None:
    """Mean tokens per scored question in earlier runs of this model on this dataset, with the same
    answer mode (LLM answers cost one more call)."""
    totals: list[int] = []
    runs: set[str] = set()
    for path in sorted(results_dir.glob("*.jsonl")):
        for record in load_records(path).values():
            if (
                record.get("dataset", "owid") == dataset
                and record.get("model") == model
                and record.get("answers") == answers
                and record.get("correct") is not None
                and record.get("prompt_tokens") is not None
            ):
                totals.append(record["prompt_tokens"] + (record.get("completion_tokens") or 0))
                runs.add(path.stem)
    if not totals:
        return None
    return statistics.fmean(totals), f"{len(totals)} questions of {len(runs)} earlier run(s)"


def safety_items() -> list[dict[str, Any]]:
    return [
        {
            "id": sid,
            "category": "sql_safety",
            "expected_behavior": "blocked",
            "question": f"(adversarial SQL) {sql}",
            "sql": sql,
        }
        for sid, sql in ADVERSARIAL_SQL
    ]


def scripted_ask(connection: DatabaseConnection, max_rows: int, max_retries: int) -> Ask:
    def ask(item: dict[str, Any]) -> AgentResult:
        reply = json.dumps({"sql": item["sql"], "explanation": "adversarial statement"})
        llm = ScriptedLLMClient(lambda system, user: reply, model="scripted-adversarial")
        return AgentController(llm, max_rows=max_rows, max_retries=max_retries).run(
            item["question"], connection
        )

    return ask


def _git_commit() -> str | None:
    """Short HEAD commit, marked "-dirty" when tracked files have uncommitted changes."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{head}-dirty" if changes else head


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--suite", choices=["questions", "sql-safety"], default="questions")
    parser.add_argument("--run-id", help="resume this run (default: a new timestamped run)")
    parser.add_argument("--ids", help="comma-separated question ids to run")
    parser.add_argument("--category", help="only questions of this category")
    parser.add_argument("--limit", type=int, help="run at most this many pending questions")
    parser.add_argument(
        "--delay", type=float, default=None, help="seconds between questions (default 15; 0 offline)"
    )
    parser.add_argument("--answers", choices=["template", "llm"], default="template",
                        help="template saves one LLM call per question (default)")  # fmt: skip
    parser.add_argument("--max-provider-failures", type=int, default=3)
    parser.add_argument(
        "--dataset",
        choices=["owid", "bird"],
        default="owid",
        help="owid: the built-in demo questions; bird: BIRD Mini-Dev (evaluation/bird.py)",
    )
    parser.add_argument("--databases", help="bird: comma-separated BIRD database ids (default: all)")
    parser.add_argument(
        "--scope",
        choices=["database", "all"],
        default="database",
        help="bird: the analyst sees one BIRD database, or all 75 tables at once",
    )
    parser.add_argument("--evidence", choices=["on", "off"], default="on",
                        help="bird: append BIRD's hint (its 'evidence') to each question")  # fmt: skip
    parser.add_argument("--split", choices=["test", "dev"], default="test",
                        help="bird: test = Mini-Dev (reported); dev = other dev questions")  # fmt: skip
    parser.add_argument("--sample", type=int,
                        help="bird: a fixed sample of N, stratified by database and difficulty")  # fmt: skip
    parser.add_argument(
        "--max-rows", type=int, help=f"the agent's row cap (default: MAX_ROWS; bird: {bird.BIRD_MAX_ROWS:,})"
    )
    parser.add_argument(
        "--daily-tokens", type=int, help="the provider's daily token budget, to check the run against"
    )
    args = parser.parse_args(argv)
    # Progress lines appear as they happen, also when the output goes to a file.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    # Every outcome is in the results file; the app's per-step logs would only add noise here.
    logging.getLogger("app").setLevel(logging.ERROR)

    settings = get_settings()
    if settings.database_url is None:
        print("Set DATABASE_URL to the read-only sql_agent account.", file=sys.stderr)
        return 2
    if args.dataset == "bird" and args.suite != "questions":
        print("The sql-safety suite runs on the OWID database only.", file=sys.stderr)
        return 2
    if args.dataset != "bird" and (args.split != "test" or args.sample):
        print("--split and --sample apply to --dataset bird only.", file=sys.stderr)
        return 2

    default_rows = bird.BIRD_MAX_ROWS if args.dataset == "bird" else settings.max_rows
    max_rows = args.max_rows or default_rows
    meta: dict[str, Any] = {"dataset": args.dataset, "max_rows": max_rows}
    resume = f"python -m evaluation.run --suite {args.suite}"
    if max_rows != default_rows:
        resume += f" --max-rows {max_rows}"
    if args.dataset == "bird":
        url = bird.bird_url(settings.database_url)
        expected_doc = bird.load_expected(bird.expected_path(args.split))
        all_dbs = bird.database_ids(bird.load_questions())
        connections = bird.connect(url, args.scope, all_dbs, settings.query_timeout_seconds)
        wanted_dbs = args.databases.split(",") if args.databases else None
        if unknown := set(wanted_dbs or []) - set(connections):
            print(f"Unknown BIRD databases: {sorted(unknown)}", file=sys.stderr)
            return 2
        items = bird.items_for(args.split, expected_doc, wanted_dbs, args.sample)
        if expected_doc["excluded"]:
            print(
                f"{len(expected_doc['excluded'])} questions have no scoreable ground truth (build-expected)."
            )
        if expected_doc.get("max_rows", 0) < max_rows:
            print(f"Ground truth was built with a {expected_doc.get('max_rows')}-row cap: rebuild it with "
                  "`python -m evaluation.bird build-expected` to score larger results.")  # fmt: skip
        integrity: Callable[[], dict[str, int]] = lambda: bird.fingerprint(url)  # noqa: E731
        commit = expected_doc.get("questions_revision")
        meta.update(
            scope=args.scope,
            evidence=args.evidence,
            databases=args.databases,
            split=args.split,
            sample=args.sample,
        )
        resume += f" --dataset bird --split {args.split} --scope {args.scope} --evidence {args.evidence}"
        if args.databases:
            resume += f" --databases {args.databases}"
        if args.sample:
            resume += f" --sample {args.sample}"
    else:
        connection = ConnectionRegistry(settings.query_timeout_seconds).add(
            ConnectionConfig(id="owid", name="OWID", url=settings.database_url)
        )
        expected_doc = load_expected()
        integrity = lambda: fingerprint(connection)  # noqa: E731
        commit = dataset_commit()
    counts = integrity()
    if counts != expected_doc["row_counts"]:
        print("Database row counts differ from those the ground truth was built on.", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    split = "-dev" if args.split == "dev" else ""
    default_id = f"{stamp}-{args.suite}" if args.dataset == "owid" else f"{stamp}-bird{split}-{args.scope}"
    if args.dataset == "bird" and args.evidence == "off":
        default_id += "-noevidence"
    run_id = args.run_id or default_id
    path = RESULTS_DIR / f"{run_id}.jsonl"
    if args.run_id and not path.exists():
        print(f"No run {run_id!r} in {RESULTS_DIR}.", file=sys.stderr)
        return 2
    if args.run_id:
        first = next(iter(load_records(path).values()), {})
        # Runs from before a setting was recorded used its default then.
        defaults = {"dataset": "owid", "max_rows": settings.max_rows, "split": "test"}
        settings_then = {k: first.get(k, defaults.get(k)) for k in meta}
        if settings_then != meta:
            print(f"Run {run_id} was started with {settings_then}; resume it with the same options.",
                  file=sys.stderr)  # fmt: skip
            return 2
    secrets = [s for s in (make_url(settings.database_url.get_secret_value()).password,) if s]
    if settings.llm_api_key:
        secrets.append(settings.llm_api_key.get_secret_value())

    if args.suite == "sql-safety":
        items = safety_items()
        ask = scripted_ask(connection, max_rows, settings.max_retries)
        model, delay = "scripted-adversarial", args.delay or 0.0
    else:
        if not settings.llm_api_key or not settings.llm_api_key.get_secret_value():
            print("Set LLM_API_KEY to run the question suite.", file=sys.stderr)
            return 2
        llm: LLMClient = OpenAICompatibleClient(
            settings.llm_base_url, settings.llm_api_key, settings.llm_model
        )
        controller = AgentController(
            llm,
            max_rows=max_rows,
            max_retries=settings.max_retries,
            answer_llm=llm if args.answers == "llm" else None,
        )
        if args.dataset == "bird":
            with_evidence = args.evidence == "on"
            ask = lambda item: controller.run(  # noqa: E731
                item["question"],
                connections[item["db_id"]],
                definitions=bird.definitions_for(item, with_evidence),
            )
        else:
            items = load_questions()
            ask = lambda item: controller.run(  # noqa: E731
                item["question"], connection, [Turn(**turn) for turn in item.get("history", [])]
            )
        model, delay = settings.llm_model, 15.0 if args.delay is None else args.delay

    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i["id"] in wanted]
    if args.category:
        items = [i for i in items if i["category"] == args.category]
    if args.limit is not None:
        done = {i for i, r in load_records(path).items() if not r.get("provider_failure")}
        pending = [i for i in items if i["id"] not in done][: args.limit]
        items = [i for i in items if i["id"] in done] + pending

    meta.update(
        run_id=run_id,
        suite=args.suite,
        model=model,
        answers=args.answers,
        max_retries=settings.max_retries,
        code_commit=_git_commit(),
        dataset_commit=commit,
    )
    per_question = (
        None
        if args.suite == "sql-safety"
        else measured_tokens_per_question(args.dataset, model, args.answers)
    )
    with ExitStack() as stack:
        official = stack.enter_context(bird.official_scorer(url)) if args.dataset == "bird" else None
        summary = run_items(
            items,
            ask,
            expected_doc["results"],
            path,
            meta,
            secrets,
            delay_seconds=delay,
            max_provider_failures=args.max_provider_failures,
            check_integrity=integrity,
            resume_command=f"{resume} --run-id {run_id}",
            official=official,
            tokens_per_question=per_question,
            daily_tokens=args.daily_tokens,
        )
    print(f"Done: {summary.scored} scored, {summary.provider_failures} not run (provider). Report:")
    print(f"  python -m evaluation.report {path.relative_to(ROOT)}")
    return 0 if summary.integrity_ok else 1


if __name__ == "__main__":
    sys.exit(main())
