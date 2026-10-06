"""BIRD's official metrics against a real database (the OWID fixture stands in for a BIRD schema).

The scorer runs the agent's SQL and the ground-truth SQL again, so this checks that it does so on
the read-only account: a write in the "answer" fails and changes nothing.
"""

from __future__ import annotations

from typing import Any, Literal

from app.agent.controller import AgentResult, QueryMetadata
from app.database.connections import DatabaseConnection
from evaluation.bird import official_scorer
from evaluation.dataset import fingerprint

GOLD = "SELECT name FROM countries WHERE iso_code IN ('IND', 'CHN')"
ITEM: dict[str, Any] = {"id": "B1", "db_id": "public", "ground_truth": {"sql": GOLD}}


def answer(sql: str | None, status: Literal["success", "error", "unanswerable"] = "success") -> AgentResult:
    meta = QueryMetadata(database_id="x", dialect="postgres", model="m", prompt_version="p")
    return AgentResult(status=status, question="q", sql=sql, metadata=meta)


def test_answers_are_scored_by_running_both_queries_again(owid: DatabaseConnection) -> None:
    before = fingerprint(owid)
    with official_scorer(owid.config.url) as score:
        same = score(ITEM, answer("SELECT name FROM countries WHERE iso_code IN ('CHN', 'IND') LIMIT 50000"))
        extra = score(ITEM, answer("SELECT name, iso_code FROM countries WHERE iso_code IN ('IND', 'CHN')"))
        no_sql = score(ITEM, answer(None, "unanswerable"))
        failed = score(ITEM, answer("SELECT name FROM countries", "error"))
        write = score(ITEM, answer("DELETE FROM countries"))
        bad_gold = score({**ITEM, "ground_truth": {"sql": "SELECT nope FROM countries"}}, answer(GOLD))
        after_error = score(ITEM, answer(GOLD))  # the connection is usable after failed queries

    assert same == {"ex_correct": True, "soft_f1": 1.0}
    assert extra["ex_correct"] is False and 0 < extra["soft_f1"] < 1
    assert extra["ex_miss"] == "extra columns"
    assert no_sql == {"ex_correct": False, "soft_f1": 0.0, "ex_miss": "no result (unanswerable)"}
    assert failed == {"ex_correct": False, "soft_f1": 0.0, "ex_miss": "no result (error)"}
    assert write["ex_correct"] is False and write["official_error"].startswith("answer: ")
    assert write["ex_miss"] == "answer failed"
    assert "read-only" in write["official_error"]
    assert bad_gold["ex_correct"] is None and bad_gold["official_error"].startswith("ground truth: ")
    assert after_error["ex_correct"] is True
    assert fingerprint(owid) == before


def test_scoring_sessions_run_without_parallel_query(owid: DatabaseConnection) -> None:
    """Parallel aggregation adds floats in a different order on each run (see SCORING_OPTIONS)."""
    item = {**ITEM, "ground_truth": {"sql": "SELECT current_setting('max_parallel_workers_per_gather')"}}
    with official_scorer(owid.config.url) as score:
        assert score(item, answer("SELECT '0'::text"))["ex_correct"] is True
