"""Deterministic checks on a query result, before it is turned into an answer.

A result can be valid SQL output and still be wrong: a ranking that starts with NULLs, or an
empty result because a filter value is misspelled ('USA' where the data says 'United States').
These checks catch such cases without an LLM. Checks marked `repairable` are fed back to the
repair loop; the others are notes for the answer step and the user.

Missing-value probes run only for empty results. Each probe is a one-row existence query built
from the syntax tree, validated like any generated SQL and run on the same read-only connection.
Probes never send database values to the model: only the model's own literal is echoed back.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal

import sqlglot
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from app.agent.executor import QueryExecutionError, QueryResult, execute
from app.agent.sql_validator import SQLRejectedError, profile_schema, validate_sql
from app.database.connections import DatabaseConnection
from app.database.profile import DatabaseProfile

MAX_PROBES = 3
MAX_HINT_VALUES = 5


class ResultCheck(BaseModel):
    code: str
    severity: Literal["info", "warning"]
    message: str
    column: str | None = None
    repairable: bool = False  # worth one more attempt through the repair loop


def _order_column_index(tree: exp.Expr, columns: list[str]) -> int | None:
    """Index of the output column the query is primarily ordered by, if it can be told."""
    order = tree.args.get("order")
    if not isinstance(tree, exp.Select) or order is None or not order.expressions:
        return None
    key = order.expressions[0].this
    if isinstance(key, exp.Literal) and key.is_int:  # ORDER BY 2
        index = int(key.this) - 1
        return index if 0 <= index < len(columns) else None
    for index, projection in enumerate(tree.expressions):
        if index >= len(columns):
            break
        if isinstance(key, exp.Column) and not key.table and key.name == projection.alias_or_name:
            return index
        if projection.unalias() == key:
            return index
    return None


def is_empty(result: QueryResult) -> bool:
    """No rows, or one row of only NULLs and zeros: what COUNT/SUM/AVG give over no matching rows."""
    return result.row_count == 0 or (
        result.row_count == 1 and all(value is None or value == 0 for value in result.rows[0])
    )


def check_result(
    result: QueryResult, sql: str, dialect: str, limit: int, limit_action: str
) -> list[ResultCheck]:
    """Checks that need only the result and the SQL (no database access)."""
    checks: list[ResultCheck] = []
    if result.row_count == 0:
        checks.append(
            ResultCheck(code="empty_result", severity="info", message="The query returned no rows.")
        )
        return checks
    if is_empty(result):
        checks.append(
            ResultCheck(
                code="empty_aggregate",
                severity="info",
                message="Only NULL or zero values: possibly no rows matched the filters.",
            )
        )
        return checks

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError:
        tree = None
    index = _order_column_index(tree, result.columns) if tree is not None else None
    if index is not None and result.rows[0][index] is None:
        column = result.columns[index]
        checks.append(
            ResultCheck(
                code="null_first_in_ranking",
                severity="warning",
                message=f"The result is ordered by {column}, but its first row has no value for it.",
                column=column,
                repairable=True,
            )
        )

    if result.row_count > 1:
        for index, column in enumerate(result.columns):
            if all(row[index] is None for row in result.rows):
                checks.append(
                    ResultCheck(
                        code="all_null_column",
                        severity="warning",
                        message=f"{column} has no value in any row; the data may not cover this.",
                        column=column,
                    )
                )

    if result.truncated or (result.row_count == limit and limit_action != "kept"):
        checks.append(
            ResultCheck(
                code="limit_reached",
                severity="info",
                message=f"The result stops at the row limit ({result.row_count} rows); more rows may exist.",
            )
        )

    distinct = {tuple(_hashable(v) for v in row) for row in result.rows}
    if len(distinct) < result.row_count:
        checks.append(
            ResultCheck(
                code="duplicate_rows",
                severity="info",
                message=f"{result.row_count - len(distinct)} row(s) are exact duplicates of others.",
            )
        )
    return checks


def _hashable(value: Any) -> Any:
    return repr(value) if isinstance(value, (list, dict)) else value


def _string_filters(tree: exp.Expr) -> Iterator[tuple[exp.Table, str, str, exp.Literal]]:
    """(table, column, operator, literal) for each `column = 'text'`, `column IN ('text', ...)`
    and `column [I]LIKE 'pattern'` filter on a real table column, in WHERE and JOIN conditions of
    every scope. Negated patterns (NOT LIKE) are left out: matching nothing is not a problem there."""
    for scope in traverse_scope(tree):
        conditions = [scope.expression.args.get("where")]
        conditions += [join.args.get("on") for join in scope.expression.args.get("joins") or []]
        for condition in conditions:
            if condition is None:
                continue
            for node in condition.find_all(exp.EQ, exp.In, exp.Like, exp.ILike):
                operator = {exp.Like: "LIKE", exp.ILike: "ILIKE"}.get(type(node), "=")
                if operator != "=" and (node.args.get("negate") or isinstance(node.parent, exp.Not)):
                    continue  # NOT LIKE: sqlglot marks it with `negate` (older versions wrap it in Not)
                if isinstance(node, exp.In):
                    pairs = [(node.this, value) for value in node.expressions]
                elif operator == "=":
                    pairs = [(node.this, node.expression), (node.expression, node.this)]
                else:
                    pairs = [(node.this, node.expression)]
                for column, literal in pairs:
                    if not (isinstance(column, exp.Column) and isinstance(literal, exp.Literal)):
                        continue
                    source = scope.sources.get(column.table)
                    # A real table, not a CTE or subquery scope, nor a set-returning function.
                    if not isinstance(source, exp.Table) or isinstance(source.this, exp.Func):
                        continue
                    if literal.is_string:
                        yield source, column.name, operator, literal


def probe_missing_values(
    connection: DatabaseConnection, profile: DatabaseProfile, sql: str, dialect: str
) -> list[ResultCheck]:
    """For an empty result: which text values in the filters do not exist in their column at all?"""
    try:
        tree = qualify(
            sqlglot.parse_one(sql, read=dialect),
            schema=profile_schema(profile, dialect),
            dialect=dialect,
            validate_qualify_columns=False,
            quote_identifiers=False,
        )
    except SqlglotError:
        return []

    checks: list[ResultCheck] = []
    seen: set[tuple[str, str, str, str]] = set()
    for table, column, operator, literal in _string_filters(tree):
        key = (f"{table.db}.{table.name}", column, operator, literal.this)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_PROBES:
            break
        node = {"=": exp.EQ, "LIKE": exp.Like, "ILIKE": exp.ILike}[operator]
        probe = (
            exp.select(exp.Literal.number(1).as_("found"))
            .from_(exp.table_(table.name, db=table.db))
            .where(node(this=exp.column(column), expression=literal.copy()))
            .limit(1)
        )
        try:
            validated = validate_sql(probe.sql(dialect=dialect), profile, dialect, 1)
            found = execute(connection, validated.sql, 1).row_count > 0
        except (SQLRejectedError, QueryExecutionError):
            continue  # a probe that cannot run proves nothing
        if not found:
            shown = literal.this if len(literal.this) <= 60 else literal.this[:57] + "..."
            checks.append(
                ResultCheck(
                    code="missing_value",
                    severity="warning",
                    message=f"No row in {key[0]} has {column} {operator} '{shown}'."
                    + _stored_values_hint(profile, table, column),
                    column=column,
                    repairable=True,
                )
            )
    return checks


def _stored_values_hint(profile: DatabaseProfile, table: exp.Table, column: str) -> str:
    """How the column's values are written, from the profile only: these values were already shown
    to the model with the schema, so the hint reveals no new data."""
    for candidate in profile.tables:
        if (candidate.schema_name, candidate.name) != (table.db, table.name):
            continue
        for col in candidate.columns:
            if col.name.lower() == column.lower() and col.hints and not col.sensitive:
                values = col.hints.categories or col.hints.examples or []
                if values:
                    listed = ", ".join(f"'{v}'" for v in values[:MAX_HINT_VALUES])
                    more = ", ..." if len(values) > MAX_HINT_VALUES else ""
                    return f" Stored values look like: {listed}{more}."
    return ""
