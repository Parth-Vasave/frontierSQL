"""Runner and report (Milestone 11): resumable, quota-aware, honest about what was not run."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from app.agent.controller import AgentResult, QueryError, QueryMetadata, TraceEvent
from evaluation.report import compute, render
from evaluation.run import is_provider_failure, load_records, run_items, safety_items

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
