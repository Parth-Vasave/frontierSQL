"""BIRD questions in the evaluation's own format (evaluation/bird.py); no download or database."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from evaluation.bird import (
    bird_url,
    definitions_for,
    execution_accuracy,
    items_for,
    load_dev_questions,
    load_questions,
    only_nulls,
    soft_f1,
    stratified_sample,
    translate_sqlite,
)

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


def test_evidence_is_given_as_definitions_only_when_asked_and_present(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps(RAW))
    with_hint, without_hint = load_questions(path)
    assert definitions_for(with_hint, evidence=True) == "won = position 1"
    assert definitions_for(with_hint, evidence=False) is None
    assert definitions_for(without_hint, evidence=True) is None


def test_bird_url_keeps_the_account_and_server() -> None:
    url = bird_url(SecretStr("postgresql://sql_agent:p%40ss@db.example:5433/emissions"))
    assert url.get_secret_value() == "postgresql://sql_agent:p%40ss@db.example:5433/bird"


def test_execution_accuracy_compares_sets_of_rows_exactly() -> None:
    gold = [("Hamilton", Decimal("1.50")), ("Vettel", 2)]
    assert execution_accuracy([("Vettel", 2), ("Hamilton", Decimal("1.5"))], gold)  # order, 1.5 == 1.50
    assert execution_accuracy([("Vettel", 2), ("Vettel", 2), ("Hamilton", 1.5)], gold)  # duplicates
    assert not execution_accuracy([("hamilton", Decimal("1.5")), ("Vettel", 2)], gold)  # case counts
    assert not execution_accuracy([(2, "Vettel"), (Decimal("1.5"), "Hamilton")], gold)  # column order
    assert not execution_accuracy([("Hamilton",), ("Vettel",)], gold)  # missing column
    assert not execution_accuracy([(Decimal("0.333"),)], [(1 / 3,)])  # no tolerance
    assert execution_accuracy([], [])


# Expected values worked out by hand from the definition in BIRD's evaluation_f1.py (and checked
# against that script during development).
@pytest.mark.parametrize(
    ("predicted", "gold", "expected"),
    [
        ([(1, "a")], [(1, "a")], 1.0),
        ([], [], 1.0),
        ([], [(1,)], 0.0),
        ([(1,)], [], 0.0),
        ([(1, "x")], [(1,)], 2 / 3),  # an extra column: precision 1/2, recall 1
        ([(1,), (2,)], [(1,)], 2 / 3),  # an extra row
        ([(1,), (1,)], [(1,)], 1.0),  # duplicates are dropped first
        ([("a", 1)], [(1, "a")], 1.0),  # values are found anywhere in the paired row
        ([(2,), (1,)], [(1,), (2,)], 0.0),  # rows are paired by position, not matched
    ],
)
def test_soft_f1_follows_bird_mini_dev(predicted: list, gold: list, expected: float) -> None:
    assert soft_f1(predicted, gold) == pytest.approx(expected)


def test_only_null_ground_truths_are_recognised() -> None:
    assert only_nulls([[None]]) and only_nulls([[None, None], [None, None]])
    assert not only_nulls([]) and not only_nulls([[None, 0]])


def test_the_hand_review_file_is_well_formed() -> None:
    from evaluation.report import REVIEW

    document = json.loads(REVIEW.read_text())
    assert document["questions"], "the review lists questions"
    for qid, entry in document["questions"].items():
        assert re.fullmatch(r"B\d{4}", qid), qid
        assert entry["verdict"] in document["verdicts"], qid
        assert entry["note"].strip(), qid


NAMES = {"driverstandings": "driverstandings", "points": "points", "patient": "patient",
         "first date": "First Date", "sex": "sex", "name": "name", "order": "order"}  # fmt: skip


def test_sqlite_ground_truth_is_translated_with_postgres_spelling_and_semantics() -> None:
    # SQLite ignores identifier case; PostgreSQL needs the schema's spelling ("First Date" quoted).
    assert translate_sqlite("SELECT `First Date` FROM Patient WHERE SEX = 'F'", NAMES) == (
        "SELECT \"First Date\" FROM patient WHERE sex = 'F'"
    )
    assert (
        translate_sqlite("SELECT Points FROM driverStandings", NAMES) == "SELECT points FROM driverstandings"
    )
    # A reserved word that SQLite needed quoted stays quoted.
    assert translate_sqlite('SELECT "order" FROM patient', NAMES) == 'SELECT "order" FROM patient'
    # SQLite's LIKE ignores ASCII case.
    assert translate_sqlite("SELECT name FROM patient WHERE name LIKE 'a%'", NAMES) == (
        "SELECT name FROM patient WHERE name ILIKE 'a%'"
    )
    # PostgreSQL rounds to decimals only on numeric.
    assert translate_sqlite("SELECT ROUND(AVG(points), 2) FROM driverstandings", NAMES) == (
        "SELECT ROUND(CAST(AVG(points) AS DECIMAL), 2) FROM driverstandings"
    )
    # SQLite sorts NULLs first when ascending; PostgreSQL last unless told.
    assert translate_sqlite("SELECT name FROM patient ORDER BY points", NAMES).endswith("NULLS FIRST")


def _items(counts: dict[tuple[str, str], int]) -> list[dict]:
    return [
        {"id": f"D{db[0]}{level[0]}{i:03d}", "db_id": db, "category": level}
        for (db, level), n in counts.items()
        for i in range(n)
    ]


def test_stratified_sample_is_fixed_and_keeps_the_mix() -> None:
    items = _items({("a", "simple"): 60, ("a", "moderate"): 20, ("b", "simple"): 15, ("b", "challenging"): 5})
    sample = stratified_sample(items, 20)
    assert len(sample) == 20 and sample == stratified_sample(list(items), 20)
    mix = {(i["db_id"], i["category"]) for i in sample}
    assert mix == {("a", "simple"), ("a", "moderate"), ("b", "simple"), ("b", "challenging")}
    assert sum(i["db_id"] == "a" and i["category"] == "simple" for i in sample) == 12
    assert [i["id"] for i in sample] == [i["id"] for i in items if i in sample]  # original order kept
    assert stratified_sample(items, 500) == items


def test_dev_questions_leave_out_the_test_questions(tmp_path: Path) -> None:
    test, dev = tmp_path / "test.json", tmp_path / "dev.json"
    test.write_text(json.dumps(RAW))  # question ids 7 and 1234
    reworded = {**RAW[0], "question": "Who won, reworded?"}
    other = {**RAW[1], "question_id": 8}
    dev.write_text(json.dumps([reworded, RAW[1], other]))
    assert [q["id"] for q in load_dev_questions(dev, test)] == ["D0008"]


def test_dev_items_carry_the_translated_ground_truth(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = [
        {"id": "D0001", "db_id": "x", "category": "simple", "ground_truth": {"sql": "SELECT `A` FROM t"}},
        {"id": "D0002", "db_id": "x", "category": "simple", "ground_truth": {"sql": "SELECT julianday(d)"}},
    ]
    monkeypatch.setattr("evaluation.bird.load_dev_questions", lambda: questions)
    expected = {"excluded": {"D0002": "function julianday(date) does not exist"},
                "ground_truth_sql": {"D0001": 'SELECT "A" FROM t'}}  # fmt: skip
    (item,) = items_for("dev", expected)
    assert item["id"] == "D0001" and item["ground_truth"]["sql"] == 'SELECT "A" FROM t'
