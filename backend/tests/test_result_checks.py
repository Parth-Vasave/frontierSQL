"""Deterministic result checks (Milestone 7)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.agent.executor import QueryResult
from app.agent.result_checks import check_result, is_empty, probe_missing_values
from app.database.connections import ConnectionConfig, ConnectionRegistry


def result(columns: list[str], rows: list[list[Any]], truncated: bool = False) -> QueryResult:
    return QueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated, duration_ms=1)


def codes(
    res: QueryResult, sql: str = "SELECT a, b FROM t", limit: int = 100, action: str = "kept"
) -> list[str]:
    return [c.code for c in check_result(res, sql, "postgres", limit, action)]


def test_clean_result_has_no_checks() -> None:
    assert codes(result(["a", "b"], [[1, "x"], [2, "y"]])) == []


def test_empty_result() -> None:
    assert codes(result(["a"], [])) == ["empty_result"]


@pytest.mark.parametrize("row", [[None], [0], [0, None]])
def test_aggregate_over_nothing_counts_as_empty(row: list[Any]) -> None:
    res = result(["n", "m"][: len(row)], [row])
    assert is_empty(res) and codes(res) == ["empty_aggregate"]


def test_a_single_nonzero_value_is_not_empty() -> None:
    assert not is_empty(result(["n"], [[3]]))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name, co2 AS amount FROM t ORDER BY amount DESC",  # by alias
        "SELECT name, co2 FROM t ORDER BY co2 DESC",  # by column
        "SELECT name, co2 FROM t ORDER BY 2 DESC",  # by position
        "SELECT name, co2 / pop AS pc FROM t ORDER BY co2 / pop DESC",  # by expression
    ],
)
def test_ranking_led_by_null_is_repairable(sql: str) -> None:
    res = result(["name", "value"], [["A", None], ["B", 5]])
    checks = check_result(res, sql, "postgres", 100, "kept")
    assert [(c.code, c.repairable) for c in checks] == [("null_first_in_ranking", True)]


def test_ranking_with_a_value_first_is_fine() -> None:
    res = result(["name", "value"], [["B", 5], ["A", None]])
    assert codes(res, "SELECT name, co2 FROM t ORDER BY co2 DESC") == []


def test_all_null_column() -> None:
    res = result(["year", "gdp"], [[2023, None], [2024, None]])
    checks = check_result(res, "SELECT year, gdp FROM t", "postgres", 100, "kept")
    assert [(c.code, c.column, c.repairable) for c in checks] == [("all_null_column", "gdp", False)]


def test_limit_reached_only_when_the_limit_was_not_asked_for() -> None:
    rows = [[i] for i in range(10)]
    assert codes(result(["a"], rows), limit=10, action="added") == ["limit_reached"]
    assert codes(result(["a"], rows), limit=10, action="clamped") == ["limit_reached"]
    assert codes(result(["a"], rows), limit=10, action="kept") == []  # "top 10" asked for 10 rows


TOP5_IN_CTE = (
    "WITH top5 AS (SELECT id, name FROM c ORDER BY population DESC LIMIT 5) "
    "SELECT t.name, g.total FROM top5 AS t JOIN g ON g.id = t.id WHERE g.total IS NOT NULL "
    "ORDER BY t.name LIMIT 1000"
)
TOP5 = "WITH top5 AS (SELECT co2 FROM t ORDER BY co2 DESC LIMIT 5)"
FOUR_ROWS = [["A", 1], ["B", 2], ["C", 3], ["D", 4]]


@pytest.mark.parametrize(
    ("sql", "action"),
    [
        ("SELECT name, co2 FROM t ORDER BY co2 DESC LIMIT 5", "kept"),
        ("SELECT name, co2 FROM t ORDER BY co2 DESC FETCH FIRST 5 ROWS ONLY", "kept"),
        (TOP5_IN_CTE, "added"),  # Q052: top 5 picked in a CTE, then a filter drops one
        ("SELECT s.name, s.co2 FROM (SELECT name, co2 FROM t ORDER BY co2 DESC LIMIT 5) AS s", "added"),
    ],
)
def test_top_n_with_fewer_rows_warns(sql: str, action: str) -> None:
    checks = check_result(result(["name", "v"], FOUR_ROWS), sql, "postgres", 1000, action)
    found = [(c.code, c.severity, c.repairable) for c in checks]
    assert found == [("fewer_than_requested", "warning", False)]
    assert checks[0].message.startswith("The query asks for the top 5 but returned 4;")


@pytest.mark.parametrize(
    ("sql", "action", "limit"),
    [
        ("SELECT name, co2 FROM t ORDER BY co2 DESC LIMIT 1000", "added", 1000),  # only the row cap
        ("SELECT name, co2 FROM t ORDER BY co2 DESC LIMIT 1000", "clamped", 1000),  # asked for too many
        ("SELECT name, co2 FROM t LIMIT 5", "kept", 5),  # no ranking
        ("SELECT name, co2 FROM t ORDER BY co2 DESC LIMIT 4", "kept", 4),  # got all it asked for
        # The outer query aggregates the top 5: one row is the expected shape.
        (f"{TOP5} SELECT SUM(co2) FROM top5", "added", 1000),
        (f"{TOP5} SELECT DISTINCT co2 FROM top5", "added", 1000),
        # A top-N used only as a filter does not set the number of output rows.
        ("SELECT name, co2 FROM t WHERE id IN (SELECT id FROM t ORDER BY co2 DESC LIMIT 5)", "added", 1000),
    ],
)
def test_no_top_n_warning_otherwise(sql: str, action: str, limit: int) -> None:
    assert "fewer_than_requested" not in codes(result(["name", "v"], FOUR_ROWS), sql, limit, action)


def test_duplicate_rows() -> None:
    assert codes(result(["a"], [[1], [1], [2]])) == ["duplicate_rows"]


@pytest.mark.parametrize(
    "projection",
    [
        "m.first_name || ' ' || m.last_name AS full_name",
        "CONCAT(first_name, ' ', last_name) AS full_name",
        "CONCAT_WS(' ', first_name, last_name) AS full_name",
        "TRIM(first_name || ' ' || COALESCE(last_name, '')) AS full_name",
    ],
)
def test_concatenated_columns_are_repairable(projection: str) -> None:
    res = result(["id", "full_name"], [[1, "Ada Lovelace"]])
    checks = check_result(res, f"SELECT id, {projection} FROM member AS m", "postgres", 100, "kept")
    assert [(c.code, c.column, c.repairable) for c in checks] == [("joined_columns", "full_name", True)]
    assert checks[0].message == "full_name joins first_name and last_name into one text value."


def test_concatenated_columns_in_the_final_select_of_a_cte_query() -> None:
    sql = "WITH m AS (SELECT * FROM member) SELECT city || ', ' || country AS place FROM m"
    checks = check_result(result(["place"], [["Oslo, Norway"]]), sql, "postgres", 100, "kept")
    assert [c.message for c in checks] == ["place joins city and country into one text value."]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT '$' || price AS price FROM t",  # one column with a label: a format
        "SELECT COUNT(DISTINCT a || b) AS pairs FROM t",  # computed over, not returned
        "SELECT STRING_AGG(first_name || ' ' || last_name, ', ') AS names FROM t",
        "SELECT (SELECT a || b FROM u LIMIT 1) AS x FROM t",  # inside a subquery
        "WITH k AS (SELECT a || '-' || b AS key FROM t) SELECT key FROM k",  # a key built in a CTE
    ],
)
def test_other_concatenation_is_not_reported(sql: str) -> None:
    assert codes(result(["x"], [["v"]]), sql) == []


# --- missing-value probes (integration) --------------------------------------------------


@pytest.fixture
def shop(pg):
    registry = ConnectionRegistry(timeout_seconds=2)
    return registry.add(ConnectionConfig(id="shop", name="Shop", url=SecretStr(pg.agent), schemas=["shop"]))


def probe(shop, sql: str) -> list[str]:
    return [c.message for c in probe_missing_values(shop, shop.profile(), sql, "postgres")]


def test_misspelled_value_is_found(shop) -> None:
    assert probe(shop, "SELECT id FROM shop.orders WHERE status = 'Shipped' LIMIT 5") == [
        "No row in shop.orders has status = 'Shipped'. "
        "Stored values look like: 'placed', 'returned', 'shipped'."
    ]


def test_existing_values_are_not_reported(shop) -> None:
    assert probe(shop, "SELECT id FROM shop.orders WHERE status = 'shipped' AND total > 999999 LIMIT 5") == []


def test_values_in_joins_aliases_and_in_lists_are_probed(shop) -> None:
    sql = (
        "SELECT o.id FROM shop.orders o JOIN shop.customers c ON c.id = o.customer_id AND c.segment = 'vip' "
        "WHERE o.status IN ('placed', 'lost') LIMIT 5"
    )
    assert sorted(probe(shop, sql)) == [
        "No row in shop.customers has segment = 'vip'. "
        "Stored values look like: 'online', 'retail', 'wholesale'.",
        "No row in shop.orders has status = 'lost'. "
        "Stored values look like: 'placed', 'returned', 'shipped'.",
    ]


def test_values_inside_ctes_and_subqueries_are_probed(shop) -> None:
    sql = (
        "WITH s AS (SELECT id FROM shop.orders WHERE status = 'gone') "
        "SELECT id FROM s WHERE id IN (SELECT order_id FROM shop.order_items WHERE product = 'Nope') LIMIT 5"
    )
    assert sorted(probe(shop, sql)) == [
        "No row in shop.order_items has product = 'Nope'. Stored values look like: 'Product 0', 'Product 1', "
        "'Product 2', 'Product 3', 'Product 4'.",
        "No row in shop.orders has status = 'gone'. "
        "Stored values look like: 'placed', 'returned', 'shipped'.",
    ]


def test_like_patterns_that_match_nothing_are_found(shop) -> None:
    # A pattern written in the wrong format matches nothing; the hint shows the stored format.
    sql = (
        "SELECT id FROM shop.order_items WHERE product LIKE 'product-%' AND product NOT LIKE 'zz%' "
        "AND product ILIKE 'product %' LIMIT 5"
    )
    assert probe(shop, sql) == [
        "No row in shop.order_items has product LIKE 'product-%'. Stored values look like: 'Product 0', "
        "'Product 1', 'Product 2', 'Product 3', 'Product 4'."
    ]  # NOT LIKE is not probed; the ILIKE pattern matches rows


def test_cte_columns_and_numbers_are_not_probed(shop) -> None:
    sql = (
        "WITH s AS (SELECT status AS st FROM shop.orders) SELECT st FROM s WHERE st = 'zzz' AND 1 = 1 LIMIT 5"
    )
    assert probe(shop, sql) == []  # 'st' belongs to a CTE, not a table column


def test_probes_are_capped(shop) -> None:
    sql = "SELECT id FROM shop.orders WHERE status IN ('a', 'b', 'c', 'd', 'e') LIMIT 5"
    assert len(probe(shop, sql)) == 3
