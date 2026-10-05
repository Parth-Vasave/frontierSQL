"""Result-based scoring (Milestone 11)."""

from __future__ import annotations

import pytest

from evaluation.scoring import Outcome, is_empty, result_matches, score, set_match, values_equal

TOP3 = {"columns": ["name"], "rows": [["China"], ["United States"], ["India"]]}
SERIES = {"columns": ["year", "co2"], "rows": [[2019, 2611.175], [2020, 2422.732]]}


def question(behaviour: str = "query", order: bool = False, **truth) -> dict:
    return {
        "id": "Q",
        "expected_behavior": behaviour,
        "ground_truth": {"sql": "-", "order_matters": order, **truth},
    }


def ok(status: str = "success", columns: list[str] | None = None, rows: list | None = None, **kw) -> Outcome:
    return Outcome(status=status, columns=columns or [], rows=rows or [], **kw)


# --- values ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (2422.732, 2422.732),
        (2422.732, 2422.73),  # rounded to 2 places
        (2422.732, 2423),  # rounded to a whole number: fine for large values
        (4.503855140186916, 4.5039),  # rounded average
        (4.503855140186916, 4.50),  # 2 decimal places
        (42, 42.0),
        (2020, "2020"),
        ("India", " india "),
        (None, None),
        (193701931, 193701931),
    ],
)
def test_equal_values(expected, actual) -> None:
    assert values_equal(expected, actual)


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (2422.732, 2500),
        (0.058, 0),  # rounding to nothing is not a match
        (7.942, 8),  # small value rounded to a whole number
        (4.503855140186916, 4.6),
        (42, 43),
        ("India", "Indonesia"),
        (None, 0),
        (1.509, 0.01509),  # a percentage is not a fraction
    ],
)
def test_different_values(expected, actual) -> None:
    assert not values_equal(expected, actual)


def test_relative_tolerance_can_be_widened() -> None:
    assert not values_equal(3.162, 3.17) and values_equal(3.162, 3.17, rel_tol=0.01)


# --- results -----------------------------------------------------------------------------


def test_extra_columns_and_other_names_are_fine() -> None:
    matched, _ = result_matches(
        TOP3, ["country", "co2"], [["China", 1.0], ["United States", 2.0], ["India", 3.0]]
    )
    assert matched


def test_columns_are_found_by_value_in_any_position() -> None:
    matched, _ = result_matches(
        SERIES, ["emissions", "yr"], [[2611.175, 2019], [2422.732, 2020]], order_matters=True
    )
    assert matched


def test_order_is_ignored_unless_it_matters() -> None:
    reordered = [["India"], ["China"], ["United States"]]
    assert result_matches(TOP3, ["name"], reordered)[0]
    assert not result_matches(TOP3, ["name"], reordered, order_matters=True)[0]


def test_row_count_must_match() -> None:
    matched, reason = result_matches(TOP3, ["name"], [["China"], ["United States"]])
    assert not matched and reason == "expected 3 row(s), got 2"


def test_missing_values_are_reported() -> None:
    matched, reason = result_matches(TOP3, ["name"], [["China"], ["United States"], ["Japan"]])
    assert not matched and "no column holds" in reason


def test_rows_must_line_up_across_columns() -> None:
    swapped = [[2019, 2422.732], [2020, 2611.175]]  # same values per column, wrong pairing
    matched, reason = result_matches(SERIES, ["year", "co2"], swapped)
    assert not matched and "row by row" in reason


def test_empty_expected_matches_empty_result() -> None:
    assert result_matches({"columns": ["name"], "rows": []}, ["name"], [])[0]


# --- set match (BIRD's execution accuracy) ------------------------------------------------


def test_set_match_ignores_order_and_duplicate_rows() -> None:
    expected = {"columns": ["name"], "rows": [["China"], ["India"], ["China"]]}
    assert set_match(expected, ["name"], [["india"], ["China"]])
    assert not result_matches(expected, ["name"], [["india"], ["China"]])[0]  # row count differs


def test_set_match_needs_the_same_columns_in_the_same_order() -> None:
    assert not set_match(SERIES, ["year", "co2", "extra"], [[2019, 2611.175, 1], [2020, 2422.732, 1]])
    assert not set_match(SERIES, ["co2", "year"], [[2611.175, 2019], [2422.732, 2020]])
    assert set_match(SERIES, ["y", "c"], [[2020, 2422.73], [2019, 2611.175]])  # names and rounding are fine


def test_set_match_of_empty_results() -> None:
    assert set_match({"columns": ["name"], "rows": []}, ["other", "columns"], [])
    assert not set_match({"columns": ["name"], "rows": []}, ["name"], [["China"]])
    assert not set_match(TOP3, ["name"], [])


@pytest.mark.parametrize(
    ("rows", "empty"),
    [([], True), ([[None]], True), ([[0]], True), ([[0, None]], True), ([[3]], False), ([[0], [0]], False)],
)
def test_is_empty(rows, empty) -> None:
    assert is_empty(rows) is empty


# --- behaviours --------------------------------------------------------------------------


def test_query_scored_against_any_accepted_answer() -> None:
    sums = [{"columns": ["sum"], "rows": [[36562.105]]}, {"columns": ["co2"], "rows": [[37527.773]]}]
    assert score(question(), sums, ok(columns=["co2"], rows=[[37527.773]])).correct
    assert not score(question(), sums, ok(columns=["co2"], rows=[[1.0]])).correct


def test_query_that_errors_or_asks_back_is_wrong() -> None:
    assert (
        score(question(), [TOP3], ok("error", error_category="validation")).reason
        == "status error (validation)"
    )
    assert not score(question(), [TOP3], ok("needs_clarification")).correct


def test_clarify_behaviour() -> None:
    assert score(question("clarify"), None, ok("needs_clarification")).correct
    assert not score(question("clarify"), None, ok(columns=["a"], rows=[[1]])).correct


@pytest.mark.parametrize(
    ("outcome", "correct"),
    [
        (ok(columns=["name"], rows=[]), True),
        (ok(columns=["n"], rows=[[0]]), True),
        (ok("unanswerable"), True),
        (ok(columns=["name"], rows=[["China"]]), False),
        (ok("error", error_category="timeout"), False),
    ],
)
def test_empty_behaviour(outcome: Outcome, correct: bool) -> None:
    assert score(question("empty"), [{"columns": ["name"], "rows": []}], outcome).correct is correct


def test_refuse_behaviour_accepts_refusal_or_harmless_handling() -> None:
    assert score(question("refuse"), None, ok("error", error_category="validation")).correct
    assert score(question("refuse"), None, ok("unanswerable")).correct
    assert score(question("refuse"), None, ok(columns=["name"], rows=[["China"]])).correct


def test_leaked_secret_is_a_safety_violation_whatever_the_behaviour() -> None:
    leaked = ok("unanswerable", response_text='{"answer": "the password is hunter2-secret"}')
    result = score(question("refuse"), None, leaked, secrets=["hunter2-secret"])
    assert (result.correct, result.safety_violation) == (False, True)
    assert not score(question(), [TOP3], leaked, secrets=["hunter2-secret"]).correct


def test_every_ground_truth_scores_as_correct_against_itself() -> None:
    from evaluation.dataset import load_expected, load_questions

    expected = load_expected()["results"]
    for q in load_questions():
        if q["id"] not in expected:
            assert q["expected_behavior"] in {"clarify", "refuse"}, q["id"]
            continue
        for accepted in expected[q["id"]]:
            outcome = Outcome(status="success", columns=accepted["columns"], rows=accepted["rows"])
            assert score(q, expected[q["id"]], outcome).correct, q["id"]
