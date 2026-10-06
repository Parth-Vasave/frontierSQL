"""Runner and report (Milestone 11): resumable, quota-aware, honest about what was not run."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from app.agent.controller import AgentResult, QueryError, QueryMetadata, TraceEvent
from app.agent.result_checks import ResultCheck
from app.agent.sql_generator import QueryPlan
from evaluation.report import compute, render
from evaluation.run import (
    is_provider_failure,
    load_records,
    measured_tokens_per_question,
    run_items,
    safety_items,
    token_estimate,
)

META = {
    "run_id": "t",
    "suite": "questions",
    "model": "m",
    "answers": "template",
    "code_commit": "c",
    "dataset_commit": "d",
}
QUESTIONS: list[dict[str, Any]] = [
    {"id": "Q1", "category": "ranking", "expected_behavior": "query", "question": "top?",
     "ground_truth": {"sql": "-", "order_matters": True}},
    {"id": "Q2", "category": "ambiguous", "expected_behavior": "clarify", "question": "trend?"},
    {"id": "Q3", "category": "no_result", "expected_behavior": "empty", "question": "none?"},
]  # fmt: skip
EXPECTED: dict[str, list[dict[str, Any]]] = {
    "Q1": [{"columns": ["name"], "rows": [["China"], ["India"]]}],
    "Q3": [{"columns": ["name"], "rows": []}],
}


def result(
    status: Literal["success", "needs_clarification", "unanswerable", "error"] = "success",
    rows: list[list[Any]] | None = None,
    error: QueryError | None = None,
    retries: int = 0,
    trace: Sequence[TraceEvent] = (),
) -> AgentResult:
    meta = QueryMetadata(
        database_id="x", dialect="postgres", model="m", prompt_version="p", retry_count=retries
    )
    return AgentResult(
        status=status,
        question="q",
        columns=["name"],
        rows=rows or [],
        error=error,
        trace=list(trace),
        metadata=meta,
    )


QUOTA = QueryError(category="llm_error", message="LLM provider returned HTTP 429 after 3 attempts")
DAILY_QUOTA = QueryError(
    category="llm_error",
    message="LLM provider returned HTTP 429 (quota used up; retry in 600 s)",
    code="quota_exhausted",
    retry_after_seconds=600,
)
PER_MINUTE = QueryError(
    category="llm_error",
    message="LLM provider returned HTTP 429 after 3 attempts (retry in 30 s)",
    code="rate_limit",
    retry_after_seconds=30,
)


def good(item) -> AgentResult:
    return {
        "Q1": result(rows=[["China"], ["India"]], retries=1),
        "Q2": result("needs_clarification"),
        "Q3": result(rows=[]),
    }[item["id"]]


def run(tmp_path: Path, ask, **kw):
    lines: list[str] = []
    summary = run_items(QUESTIONS, ask, EXPECTED, tmp_path / "r.jsonl", META, [], log=lines.append, **kw)
    return summary, load_records(tmp_path / "r.jsonl"), lines


def test_records_are_scored_and_written(tmp_path: Path) -> None:
    summary, records, _ = run(tmp_path, good)
    assert (summary.scored, summary.provider_failures) == (3, 0)
    assert [records[i]["correct"] for i in ("Q1", "Q2", "Q3")] == [True, True, True]
    assert records["Q1"]["retry_count"] == 1 and records["Q1"]["model"] == "m"
    # Query questions also get BIRD's set-based verdict; other behaviours do not.
    assert records["Q1"]["set_correct"] is True and "set_correct" not in records["Q2"]


def test_bird_records_carry_their_database_and_are_reported_per_database(tmp_path: Path) -> None:
    items = [
        {"id": "B1", "category": "simple", "db_id": "formula_1", "expected_behavior": "query",
         "question": "q1", "ground_truth": {"sql": "-", "order_matters": False}},
        {"id": "B2", "category": "challenging", "db_id": "financial", "expected_behavior": "query",
         "question": "q2", "ground_truth": {"sql": "-", "order_matters": False}},
    ]  # fmt: skip
    expected = {
        "B1": [{"columns": ["name"], "rows": [["China"], ["China"]]}],
        "B2": [{"columns": ["name"], "rows": [["India"]]}],
    }
    answers = {"B1": result(rows=[["China"]]), "B2": result(rows=[["India"]])}
    run_items(items, lambda item: answers[item["id"]], expected, tmp_path / "b.jsonl", META, [], log=print)
    records = load_records(tmp_path / "b.jsonl")
    assert records["B1"]["db_id"] == "formula_1"
    # B1: one row where the ground truth has a duplicate: wrong by row count, right as a set.
    assert (records["B1"]["correct"], records["B1"]["set_correct"]) == (False, True)
    metrics = compute(records, ["B1", "B2"], integrity_violations=0)
    assert metrics["by_database"] == {"financial": "1/1 (100%)", "formula_1": "0/1 (0%)"}
    assert metrics["set_match"] == "2/2 (100%)" and metrics["accuracy"] == "1/2 (50%)"
    assert "| formula_1 | 0/1 (0%) |" in render(metrics)


def test_provider_failures_are_not_run_and_stop_the_run(tmp_path: Path) -> None:
    summary, records, lines = run(
        tmp_path, lambda item: result("error", error=QUOTA), max_provider_failures=2
    )
    assert summary.stopped_early and summary.provider_failures == 2 and summary.scored == 0
    assert records["Q1"]["correct"] is None and records["Q1"]["provider_failure"]
    assert "Q3" not in records
    assert any("--run-id t" in line for line in lines)


def test_model_errors_are_scored_not_skipped(tmp_path: Path) -> None:
    bad_json = QueryError(
        category="llm_error", message="Model reply is not a valid GeneratedSQL: ValidationError"
    )
    assert not is_provider_failure(result("error", error=bad_json))
    _, records, _ = run(tmp_path, lambda item: result("error", error=bad_json))
    assert records["Q1"]["correct"] is False and not records["Q1"]["provider_failure"]


def test_resume_skips_scored_questions_and_retries_provider_failures(tmp_path: Path) -> None:
    calls: list[str] = []
    first = iter([good(QUESTIONS[0]), result("error", error=QUOTA), result("error", error=QUOTA)])

    def ask_first(item: dict[str, Any]) -> AgentResult:
        calls.append(item["id"])
        return next(first)

    run(tmp_path, ask_first, max_provider_failures=5)
    assert calls == ["Q1", "Q2", "Q3"]

    calls.clear()

    def ask_good(item: dict[str, Any]) -> AgentResult:
        calls.append(item["id"])
        return good(item)

    summary, records, _ = run(tmp_path, ask_good)
    assert calls == ["Q2", "Q3"]  # Q1 was already scored
    assert all(records[i]["correct"] for i in ("Q1", "Q2", "Q3"))


def test_pacing_between_questions_only(tmp_path: Path) -> None:
    sleeps: list[float] = []
    run(tmp_path, good, delay_seconds=15, sleep=sleeps.append)
    assert sleeps == [15, 15]


def test_database_changes_are_recorded(tmp_path: Path) -> None:
    counts = iter([{"countries": 242}, {"countries": 0}])
    summary, _, _ = run(tmp_path, good, check_integrity=lambda: next(counts))
    assert not summary.integrity_ok
    last = json.loads((tmp_path / "r.jsonl").read_text().splitlines()[-1])
    assert last["type"] == "integrity_violation"


def test_report_metrics_come_from_records_only(tmp_path: Path) -> None:
    timeout = TraceEvent(
        step="query_execution", status="failed", duration_ms=5000, detail={"category": "timeout"}
    )
    answers = {"Q1": result(rows=[["India"], ["China"]], trace=[timeout]), "Q2": result("error", error=QUOTA)}
    run(tmp_path, lambda item: answers.get(item["id"], good(item)), max_provider_failures=5)
    metrics = compute(load_records(tmp_path / "r.jsonl"), ["Q1", "Q2", "Q3", "Q4"], integrity_violations=0)
    assert (metrics["scored"], metrics["not_run"], metrics["complete"]) == (2, 2, False)
    assert metrics["accuracy"] == "1/2 (50%)"  # Q1 in the wrong order, Q3 right
    assert metrics["clarification_accuracy"] == "n/a (none run)"
    assert metrics["timeout_rate"] == "1/2 (50%)"
    assert metrics["wrong"] == [("Q1", "values match column by column but not row by row in order")]
    text = render(metrics)
    assert "PARTIAL: 2 of 4 not run" in text and "| Answer accuracy | 1/2 (50%) |" in text


def test_safety_items_are_all_expected_to_be_blocked() -> None:
    items = safety_items()
    assert len(items) >= 25 and {i["expected_behavior"] for i in items} == {"blocked"}
    assert len({i["id"] for i in items}) == len(items)


def test_records_explain_the_answer_and_count_llm_use(tmp_path: Path) -> None:
    trace = [
        TraceEvent(step="sql_generation", status="success", duration_ms=5,
                   detail={"attempt": 1, "prompt_tokens": 900, "completion_tokens": 100}),
        TraceEvent(step="result_validation", status="failed", duration_ms=1,
                   detail={"attempt": 1, "checks": ["missing_filter_value"]}),
        TraceEvent(step="sql_repair", status="success", duration_ms=5,
                   detail={"attempt": 2, "prompt_tokens": 1100, "completion_tokens": 120}),
        TraceEvent(step="answer_generation", status="skipped", duration_ms=0, detail={}),
    ]  # fmt: skip
    answer = result(rows=[["China"], ["India"]], retries=1, trace=trace)
    answer.explanation = "Top two by total CO2."
    answer.plan = QueryPlan(intent="ranking", tables=["public.co2"], assumptions=["latest year"])
    answer.checks = [ResultCheck(code="limit_applied", severity="info", message="m")]
    _, records, _ = run(tmp_path, lambda item: answer if item["id"] == "Q1" else good(item))
    record = records["Q1"]
    assert record["explanation"] == "Top two by total CO2."
    assert record["plan"]["tables"] == ["public.co2"] and record["plan"]["assumptions"] == ["latest year"]
    assert record["checks"] == ["limit_applied"]
    assert record["failed_steps"] == [
        {"step": "result_validation", "attempt": 1, "reason": ["missing_filter_value"]}
    ]
    assert (record["llm_calls"], record["prompt_tokens"], record["completion_tokens"]) == (2, 2000, 220)
    # Without token counts from the provider, tokens are unknown, not zero.
    assert records["Q2"]["prompt_tokens"] is None and records["Q2"]["llm_calls"] == 0


def test_a_used_up_daily_quota_stops_the_run_at_once(tmp_path: Path) -> None:
    summary, records, lines = run(
        tmp_path, lambda item: result("error", error=DAILY_QUOTA), max_provider_failures=3
    )
    assert summary.stopped_early and summary.attempted == 1
    assert records["Q1"]["provider_failure"] and records["Q1"]["error_code"] == "quota_exhausted"
    assert "Q2" not in records
    assert any("quota is used up" in line for line in lines)
    assert any("--run-id t" in line for line in lines)


def test_a_per_minute_limit_is_waited_out_and_the_question_asked_again(tmp_path: Path) -> None:
    sleeps: list[float] = []
    asked: list[str] = []

    def ask(item: dict[str, Any]) -> AgentResult:
        asked.append(item["id"])
        return result("error", error=PER_MINUTE) if asked.count(item["id"]) == 1 else good(item)

    summary, records, _ = run(tmp_path, ask, sleep=sleeps.append)
    assert asked == ["Q1", "Q1", "Q2", "Q2", "Q3", "Q3"] and sleeps == [30, 30, 30]
    assert summary.provider_failures == 0 and all(r["correct"] for r in records.values())


def test_a_long_per_minute_wait_is_not_waited_out(tmp_path: Path) -> None:
    long_wait = PER_MINUTE.model_copy(update={"retry_after_seconds": 3600})
    sleeps: list[float] = []
    summary, _, _ = run(tmp_path, lambda item: result("error", error=long_wait), sleep=sleeps.append)
    assert sleeps == [] and summary.provider_failures == 3


def test_official_verdicts_are_added_to_scored_records_only(tmp_path: Path) -> None:
    seen: list[str] = []

    def official(item: dict[str, Any], answer: AgentResult) -> dict[str, Any]:
        seen.append(item["id"])
        return {"ex_correct": item["id"] == "Q1", "soft_f1": 1.0 if item["id"] == "Q1" else 0.5}

    answers = {"Q2": result("error", error=QUOTA)}
    summary = run_items(
        QUESTIONS, lambda item: answers.get(item["id"], good(item)), EXPECTED, tmp_path / "r.jsonl", META, [],
        log=print, official=official, max_provider_failures=5,
    )  # fmt: skip
    records = load_records(tmp_path / "r.jsonl")
    assert summary.scored == 2 and seen == ["Q1", "Q3"]  # never for a question that was not run
    assert records["Q1"]["ex_correct"] is True and "ex_correct" not in records["Q2"]
    metrics = compute(records, ["Q1", "Q2", "Q3"], integrity_violations=0)
    assert metrics["execution_accuracy"] == "1/2 (50%)" and metrics["soft_f1"] == "75.0%"


def test_token_estimate_uses_measured_use_only(tmp_path: Path) -> None:
    assert "unknown" in token_estimate(100, None, 200_000)
    line = token_estimate(150, (2000.0, "96 questions of 1 earlier run(s)"), 200_000)
    assert "about 300,000" in line and "1.5 x the daily budget" in line and "resuming" in line
    assert "budget" not in token_estimate(10, (2000.0, "x"), None)

    old = [
        {"id": "B1", "dataset": "bird", "model": "m", "answers": "template", "correct": True,
         "prompt_tokens": 1800, "completion_tokens": 200},
        {"id": "B2", "dataset": "bird", "model": "m", "answers": "template", "correct": None,
         "prompt_tokens": 50, "completion_tokens": 0},  # not run: not counted
        {"id": "B3", "dataset": "bird", "model": "other", "answers": "template", "correct": False,
         "prompt_tokens": 9000, "completion_tokens": 0},
        {"id": "B4", "dataset": "bird", "model": "m", "answers": "template", "correct": False,
         "prompt_tokens": 2600, "completion_tokens": 400},
    ]  # fmt: skip
    (tmp_path / "old.jsonl").write_text("\n".join(json.dumps(r) for r in old) + "\n")
    assert measured_tokens_per_question("bird", "m", "template", tmp_path) == (
        2500.0,
        "2 questions of 1 earlier run(s)",
    )
    assert measured_tokens_per_question("bird", "m", "llm", tmp_path) is None
    assert measured_tokens_per_question("owid", "m", "template", tmp_path) is None


def test_bird_report_leads_with_the_official_metric_and_shows_the_review_beside_it(tmp_path: Path) -> None:
    def record(qid: str, db: str, category: str, ex: bool, correct: bool) -> dict[str, Any]:
        return {"id": qid, "db_id": db, "category": category, "expected_behavior": "query",
                "status": "success", "correct": correct, "reason": "r", "set_correct": ex,
                "ex_correct": ex, "soft_f1": 1.0 if ex else 0.0, "retry_count": 0,
                "timed_out": False, "latency_ms": 10, "dataset": "bird", "max_rows": 50000,
                "prompt_tokens": 1500, "completion_tokens": 500, "llm_calls": 1}  # fmt: skip

    records = {
        "B1": record("B1", "formula_1", "simple", True, True),
        "B2": record("B2", "formula_1", "moderate", False, True),
        "B3": {**record("B3", "financial", "simple", False, False), "ex_miss": "extra columns"},
    }
    review = {"B2": {"verdict": "ground_truth_error", "note": "n"}}
    metrics = compute(records, ["B1", "B2", "B3"], integrity_violations=0, review=review)
    assert metrics["execution_accuracy"] == "1/3 (33%)" and metrics["accuracy"] == "2/3 (67%)"
    assert metrics["official_by_category"] == {"moderate": "0/1 (0%)", "simple": "1/2 (50%)"}
    assert metrics["review"] == {"ground_truth_error": "0/1 (0%)", "not flagged": "1/2 (50%)"}
    assert metrics["tokens_per_question"] == 2000 and metrics["llm_calls_per_question"] == 1
    assert metrics["ex_misses"] == {"extra columns": 1, "not recorded": 1}  # B2 predates ex_miss
    text = render(metrics)
    assert "| **Execution accuracy (BIRD's official EX)** | **1/3 (33%)** |" in text
    assert "| formula_1 | 2/2 (100%) | 1/2 (50%) |" in text
    assert "| ground_truth_error | 0/1 (0%) |" in text and "row cap: 50,000" in text
    assert "| Tokens per question | 2,000 (over 3 questions) |" in text
    assert "| extra columns | 1 |" in text
