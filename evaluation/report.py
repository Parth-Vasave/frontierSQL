"""Compute the evaluation metrics from a results file. Every number comes from recorded outcomes.

    python -m evaluation.report evaluation/results/<run-id>.jsonl

Questions that were not run (provider failures, or never reached) are reported as such and are
excluded from every rate; a partial run is labelled partial.

BIRD runs lead with BIRD's own metrics (execution accuracy and Soft F1, see evaluation/bird.py).
The hand review in evaluation/bird_review.json (questions whose ground truth we believe is wrong
or ambiguous) is shown NEXT to them, never folded into them.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation import EVAL_DIR, bird
from evaluation.dataset import load_questions
from evaluation.run import load_records
from evaluation.safety_sql import ADVERSARIAL_SQL

REVIEW = EVAL_DIR / "bird_review.json"


def load_review(path: Path = REVIEW) -> dict[str, dict[str, str]]:
    """Question id -> {"verdict", "note"} from the hand review; empty when there is none."""
    return json.loads(path.read_text())["questions"] if path.exists() else {}


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})" if denominator else "n/a (none run)"


def _official(records: list[dict[str, Any]]) -> str:
    scored = [r for r in records if r.get("ex_correct") is not None]
    return _rate(sum(r["ex_correct"] for r in scored), len(scored))


def _review_breakdown(scored: list[dict[str, Any]], review: dict[str, dict[str, str]]) -> dict[str, Any]:
    """How the run did on the questions the hand review flagged, and on all the others."""
    graded = [r for r in scored if r.get("ex_correct") is not None]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in graded:
        groups[review[r["id"]]["verdict"] if r["id"] in review else "not flagged"].append(r)
    return {verdict: _official(rs) for verdict, rs in sorted(groups.items())}


def compute(
    records: dict[str, dict[str, Any]],
    planned_ids: list[str],
    integrity_violations: int,
    review: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    scored = [r for r in records.values() if r.get("correct") is not None]
    not_run = [i for i in planned_ids if i not in records or records[i].get("correct") is None]

    def of(behaviour: str) -> list[dict[str, Any]]:
        return [r for r in scored if r["expected_behavior"] == behaviour]

    executes = [r for r in scored if r["expected_behavior"] in {"query", "empty"}]
    latencies = [r["latency_ms"] for r in scored]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_database: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in scored:
        by_category[r["category"]].append(r)
        if "db_id" in r:
            by_database[r["db_id"]].append(r)
    set_scored = [r for r in scored if r.get("set_correct") is not None]
    violations = sum(1 for r in scored if r.get("safety_violation")) + integrity_violations
    refusals = [r for r in of("refuse") if r["status"] != "success"]
    official = [r for r in scored if r.get("ex_correct") is not None]
    f1s = [r["soft_f1"] for r in official if r.get("soft_f1") is not None]
    tokens = [
        r["prompt_tokens"] + (r.get("completion_tokens") or 0)
        for r in scored
        if r.get("prompt_tokens") is not None
    ]
    calls = [r["llm_calls"] for r in scored if r.get("llm_calls") is not None]
    first = next(iter(records.values()), {})
    return {
        "run_id": first.get("run_id"),
        "suite": first.get("suite"),
        "dataset": first.get("dataset", "owid"),
        "scope": first.get("scope"),
        "evidence": first.get("evidence"),
        "split": ("dev (tuning set, not a reportable result)" if first.get("split") == "dev" else "Mini-Dev")
        + (f", sample of {first['sample']}" if first.get("sample") else ""),
        "model": first.get("model"),
        "code_commit": first.get("code_commit"),
        "dataset_commit": first.get("dataset_commit"),
        "answers": first.get("answers"),
        "max_rows": first.get("max_rows"),
        "planned": len(planned_ids),
        "scored": len(scored),
        "not_run": len(not_run),
        "complete": not not_run,
        "correct": sum(r["correct"] for r in scored),
        "accuracy": _rate(sum(r["correct"] for r in scored), len(scored)),
        "execution_success": _rate(sum(r["status"] == "success" for r in executes), len(executes)),
        "result_correctness": _rate(sum(r["correct"] for r in of("query")), len(of("query"))),
        "set_match": _rate(sum(r["set_correct"] for r in set_scored), len(set_scored)),
        "official_scored": len(official),
        "execution_accuracy": _official(official),
        "soft_f1": f"{statistics.fmean(f1s):.1%}" if f1s else "n/a (none run)",
        "official_by_category": {c: _official(rs) for c, rs in sorted(by_category.items()) if _scored_ex(rs)},
        "official_by_database": {d: _official(rs) for d, rs in sorted(by_database.items()) if _scored_ex(rs)},
        "review": _review_breakdown(scored, review) if review and official else {},
        "ex_misses": _miss_shapes(official),
        "tokens_per_question": round(statistics.fmean(tokens)) if tokens else None,
        "tokens_recorded": len(tokens),
        "llm_calls_per_question": round(statistics.fmean(calls), 2) if calls else None,
        "empty_result_accuracy": _rate(sum(r["correct"] for r in of("empty")), len(of("empty"))),
        "clarification_accuracy": _rate(sum(r["correct"] for r in of("clarify")), len(of("clarify"))),
        "refusal_rate": _rate(len(refusals), len(of("refuse"))),
        "blocked_rate": _rate(sum(r["correct"] for r in of("blocked")), len(of("blocked"))),
        "retry_rate": _rate(sum(r["retry_count"] > 0 for r in scored), len(scored)),
        "timeout_rate": _rate(sum(bool(r["timed_out"]) for r in scored), len(scored)),
        "safety_violations": violations,
        "safety_violation_rate": _rate(violations, len(scored)),
        "latency_ms_avg": round(statistics.fmean(latencies)) if latencies else None,
        "latency_ms_median": round(statistics.median(latencies)) if latencies else None,
        "by_category": {
            c: _rate(sum(r["correct"] for r in rs), len(rs)) for c, rs in sorted(by_category.items())
        },
        "by_database": {
            d: _rate(sum(r["correct"] for r in rs), len(rs)) for d, rs in sorted(by_database.items())
        },
        "wrong": sorted((r["id"], r["reason"]) for r in scored if not r["correct"]),
    }


def _miss_shapes(official: list[dict[str, Any]]) -> dict[str, int]:
    """How the official-EX misses differ from the ground truth (bird.miss_shape), most common first.
    Runs recorded before the scorer stored it: `python -m evaluation.bird misses <results>`."""
    shapes = Counter(r.get("ex_miss", "not recorded") for r in official if r["ex_correct"] is False)
    return dict(shapes.most_common())


def _scored_ex(records: list[dict[str, Any]]) -> bool:
    return any(r.get("ex_correct") is not None for r in records)


def render(m: dict[str, Any]) -> str:
    status = "complete" if m["complete"] else f"PARTIAL: {m['not_run']} of {m['planned']} not run"
    lines = [
        f"Run {m['run_id']} ({m['suite']}, {status})",
        f"Model: {m['model']} | answers: {m['answers']}",
        *(
            [f"Dataset: BIRD {m['split']} | scope: {m['scope']} | evidence: {m['evidence']}"]
            if m["dataset"] == "bird"
            else []
        ),
        f"Code commit: {m['code_commit']} | dataset commit: {m['dataset_commit']}"
        + (f" | row cap: {m['max_rows']:,}" if m.get("max_rows") else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Questions scored | {m['scored']} of {m['planned']} |",
        *(
            [
                f"| **Execution accuracy (BIRD's official EX)** | **{m['execution_accuracy']}** |",
                f"| Soft F1 (BIRD Mini-Dev) | {m['soft_f1']} |",
            ]
            if m["official_scored"]
            else []
        ),
        f"| Answer accuracy | {m['accuracy']} |",
        f"| SQL execution success | {m['execution_success']} |",
        f"| Result correctness | {m['result_correctness']} |",
        f"| Set match (BIRD's row-set rule, tolerant values) | {m['set_match']} |",
        f"| Empty-result accuracy | {m['empty_result_accuracy']} |",
        f"| Clarification accuracy | {m['clarification_accuracy']} |",
        f"| Refusal rate (safety questions) | {m['refusal_rate']} |",
        f"| Adversarial SQL blocked | {m['blocked_rate']} |",
        f"| Retry rate | {m['retry_rate']} |",
        f"| Timeout rate | {m['timeout_rate']} |",
        f"| Safety violations | {m['safety_violation_rate']} |",
        f"| Latency avg / median | {m['latency_ms_avg']} / {m['latency_ms_median']} ms |",
        f"| Tokens per question | {_tokens(m)} |",
        f"| LLM calls per question | {m['llm_calls_per_question'] or 'not recorded'} |",
        "",
        "| Category | Correct |",
        "|---|---|",
        *(f"| {c} | {v} |" for c, v in m["by_category"].items()),
    ]
    if m["by_database"]:
        official = m["official_by_database"]
        lines += [
            "",
            "| Database | Correct | Official EX |",
            "|---|---|---|",
            *(f"| {d} | {v} | {official.get(d, 'n/a')} |" for d, v in m["by_database"].items()),
        ]
    if m["official_by_category"]:
        lines += [
            "",
            "| Difficulty | Official EX |",
            "|---|---|",
            *(f"| {c} | {v} |" for c, v in m["official_by_category"].items()),
        ]
    if m["review"]:
        lines += [
            "",
            "Hand review (evaluation/bird_review.json): our judgement of BIRD's ground truth, shown",
            "beside the official score and never applied to it.",
            "",
            "| Ground truth, by our review | Official EX |",
            "|---|---|",
            *(f"| {verdict} | {v} |" for verdict, v in m["review"].items()),
        ]
    if m["ex_misses"]:
        lines += [
            "",
            "| Official EX miss, by how the result differs | Questions |",
            "|---|---|",
            *(f"| {shape} | {count} |" for shape, count in m["ex_misses"].items()),
        ]
    if m["wrong"]:
        lines += ["", "Wrong:", *(f"- {i}: {reason}" for i, reason in m["wrong"])]
    return "\n".join(lines)


def _tokens(m: dict[str, Any]) -> str:
    if m["tokens_per_question"] is None:
        return "not recorded"
    return f"{m['tokens_per_question']:,} (over {m['tokens_recorded']} questions)"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--json", action="store_true", help="print the metrics as JSON")
    args = parser.parse_args(argv)
    records = load_records(args.results)
    lines = args.results.read_text().splitlines()
    integrity = sum(1 for line in lines if json.loads(line).get("type") == "integrity_violation")
    suite = next(iter(records.values()), {}).get("suite", "questions")
    # Always measured against the whole suite: a run of some questions is reported as partial.
    first = next(iter(records.values()), {})
    review = None
    if first.get("dataset") == "bird":
        review = load_review()
        # BIRD: the questions the run was started for (split, databases, sample), as the runner chose them.
        split = first.get("split", "test")
        databases = first["databases"].split(",") if first.get("databases") else None
        expected = bird.load_expected(bird.expected_path(split))
        planned = [q["id"] for q in bird.items_for(split, expected, databases, first.get("sample"))]
    elif suite == "sql-safety":
        planned = [sid for sid, _ in ADVERSARIAL_SQL]
    else:
        planned = [q["id"] for q in load_questions()]
    metrics = compute(records, planned, integrity, review)
    print(json.dumps(metrics, indent=1) if args.json else render(metrics))


if __name__ == "__main__":
    main()
