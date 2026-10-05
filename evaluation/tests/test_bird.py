"""BIRD questions in the evaluation's own format (evaluation/bird.py); no download or database."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr

from evaluation.bird import bird_url, load_questions, question_text

RAW = [
    {"question_id": 7, "db_id": "formula_1", "question": "Who won?", "evidence": "won = position 1",
     "SQL": "SELECT forename FROM drivers", "difficulty": "simple"},
    {"question_id": 1234, "db_id": "financial", "question": "How many?", "evidence": "",
     "SQL": "SELECT count(*) FROM loan", "difficulty": "challenging"},
]  # fmt: skip


def test_questions_are_converted(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps(RAW))
    first, second = load_questions(path)
    assert first == {
        "id": "B0007",
        "category": "simple",
        "db_id": "formula_1",
        "question": "Who won?",
        "evidence": "won = position 1",
        "expected_behavior": "query",
        "ground_truth": {"sql": "SELECT forename FROM drivers", "order_matters": False},
    }
    assert second["id"] == "B1234" and second["category"] == "challenging"


def test_evidence_is_appended_only_when_asked_and_present(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps(RAW))
    with_hint, without_hint = load_questions(path)
    assert question_text(with_hint, evidence=True) == "Who won?\nHint: won = position 1"
    assert question_text(with_hint, evidence=False) == "Who won?"
    assert question_text(without_hint, evidence=True) == "How many?"


def test_bird_url_keeps_the_account_and_server() -> None:
    url = bird_url(SecretStr("postgresql://sql_agent:p%40ss@db.example:5433/emissions"))
    assert url.get_secret_value() == "postgresql://sql_agent:p%40ss@db.example:5433/bird"
