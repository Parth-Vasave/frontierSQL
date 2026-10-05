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


def test_duplicate_rows() -> None:
    assert codes(result(["a"], [[1], [1], [2]])) == ["duplicate_rows"]


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
