"""Deterministic safety validation of generated SQL, before anything reaches the database.

LLM output is never trusted. A query is accepted only if its syntax tree (parsed by sqlglot
in the connection's dialect) is a single read-only SELECT over tables and columns of the
database profile, uses only allowed functions, and has a LIMIT no larger than MAX_ROWS.
The SQL that runs is regenerated from the validated tree, never the model's original text,
so what executes is exactly what was checked.

This is the second layer. The first is the database account itself: read-only, SELECT on
allow-listed tables only, statement timeout (see database/permissions.sql).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.schema import MappingSchema

from app.database.profile import DatabaseProfile, TableProfile

_SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "mysql", "performance_schema", "sys"}

# Node types that write, change schema or session state, or lock rows -- rejected anywhere in
# the tree, including inside CTEs (PostgreSQL allows `WITH x AS (DELETE ... RETURNING *)`).
_FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = (
    exp.DML,  # INSERT, UPDATE, DELETE, MERGE
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Command,  # anything sqlglot could not parse properly: EXPLAIN ANALYZE, VACUUM, GRANT, ...
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,  # SELECT ... INTO creates a table
    exp.Lock,  # FOR UPDATE / FOR SHARE
)

# Functions sqlglot does not model come back as exp.Anonymous; only these are allowed.
# Functions sqlglot does model (aggregates, window, string, date, math) are allowed unless denied.
ALLOWED_UNMODELED_FUNCTIONS = frozenset(
    {
        "age", "cardinality", "every", "generate_series", "json_build_object", "jsonb_agg", "make_date",
        "regexp_match",
    }
)  # fmt: skip
# Defense in depth: never allowed, whatever sqlglot makes of them (sleeps, file and network
# access, large objects, configuration, server and session introspection).
_DENIED_PREFIXES = ("pg_", "lo_", "dblink", "file_", "set_config", "current_setting", "query_to_xml")


class RejectionCode(StrEnum):
    SYNTAX = "syntax"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_SELECT = "not_select"
    FORBIDDEN_OPERATION = "forbidden_operation"
    SYSTEM_TABLE = "system_table"
    UNKNOWN_TABLE = "unknown_table"
    AMBIGUOUS_TABLE = "ambiguous_table"
    UNKNOWN_COLUMN = "unknown_column"
    STAR = "star"
    WHOLE_ROW = "whole_row"
    FORBIDDEN_FUNCTION = "forbidden_function"
    INVALID_LIMIT = "invalid_limit"


class SQLRejectedError(ValueError):
    def __init__(self, code: RejectionCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str  # regenerated from the validated tree: this is what runs
    tables: list[str]  # qualified names of the database tables read
    limit: int
    limit_action: Literal["kept", "added", "clamped"]
    float_casts: int = 0  # NUMERIC casts in a division computed as DOUBLE PRECISION instead


def _reject(code: RejectionCode, message: str) -> SQLRejectedError:
    return SQLRejectedError(code, message)


def _parse(sql: str, dialect: str) -> exp.Query:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError as exc:
        raise _reject(RejectionCode.SYNTAX, f"SQL could not be parsed: {str(exc).splitlines()[0]}") from None
    if not statements:
        raise _reject(RejectionCode.SYNTAX, "No SQL statement found.")
    if len(statements) > 1:
        raise _reject(RejectionCode.MULTIPLE_STATEMENTS, "Only a single statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise _reject(RejectionCode.NOT_SELECT, f"Only SELECT queries are allowed, not {tree.key.upper()}.")
    return tree


def _check_forbidden_nodes(tree: exp.Expr) -> None:
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise _reject(
                RejectionCode.FORBIDDEN_OPERATION, f"{node.key.upper()} is not allowed in a read-only query."
            )


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _check_functions(tree: exp.Expr) -> None:
    for node in tree.find_all(exp.Func):
        name = _function_name(node)
        if name.startswith(_DENIED_PREFIXES) or (
            isinstance(node, exp.Anonymous) and name not in ALLOWED_UNMODELED_FUNCTIONS
        ):
            raise _reject(RejectionCode.FORBIDDEN_FUNCTION, f"Function {name}() is not allowed.")


def _identifier(node: exp.Expr | None) -> str | None:
    """Name as the database sees it: unquoted identifiers fold to lower case."""
    if not isinstance(node, exp.Identifier):
        return None
    return node.name if node.quoted else node.name.lower()


class _Tables:
    def __init__(self, profile: DatabaseProfile) -> None:
        self.by_qualified = {(t.schema_name, t.name): t for t in profile.tables}
        self.by_name: dict[str, list[TableProfile]] = {}
        for table in profile.tables:
            self.by_name.setdefault(table.name, []).append(table)

    def resolve(self, table: exp.Table) -> TableProfile:
        """Match a table reference to the profile, and schema-qualify it in the tree."""
        name = _identifier(table.this) or table.name
        schema = _identifier(table.args.get("db"))
        display = f"{schema}.{name}" if schema else name
        if table.args.get("catalog") is not None:
            raise _reject(RejectionCode.UNKNOWN_TABLE, f"Cross-database table {table.sql()} is not allowed.")
        if (schema or "") in _SYSTEM_SCHEMAS or (schema or name).startswith("pg_"):
            raise _reject(RejectionCode.SYSTEM_TABLE, f"System table {display} is not allowed.")
        if schema is not None:
            match = self.by_qualified.get((schema, name))
            if match is None:
                raise _reject(RejectionCode.UNKNOWN_TABLE, f"Table {display} is not available.")
            return match
        candidates = self.by_name.get(name, [])
        if not candidates:
            raise _reject(RejectionCode.UNKNOWN_TABLE, f"Table {name} is not available.")
        if len(candidates) > 1:
            raise _reject(
                RejectionCode.AMBIGUOUS_TABLE, f"Table {name} exists in several schemas; qualify it."
            )
        # Qualify it, so the query does not depend on the session's search_path.
        table.set("db", exp.to_identifier(candidates[0].schema_name))
        return candidates[0]


def _check_tables(tree: exp.Expr, profile: DatabaseProfile) -> list[str]:
    """Every table reference must be a CTE in scope, a set-returning function, or a profile table."""
    tables = _Tables(profile)
    accounted: set[int] = set()
    used: list[str] = []
    try:
        scopes = traverse_scope(tree)
    except SqlglotError as exc:
        raise _reject(RejectionCode.SYNTAX, f"SQL could not be analysed: {exc}") from None
    for scope in scopes:
        for table in scope.tables:
            if isinstance(scope.sources.get(table.alias_or_name), Scope):
                accounted.add(id(table))  # reference to a CTE defined in scope
        for source in scope.sources.values():
            if not isinstance(source, exp.Table) or id(source) in accounted:
                continue
            accounted.add(id(source))
            if isinstance(source.this, exp.Func):  # e.g. FROM generate_series(...): checked as a function
                continue
            match = tables.resolve(source)
            if match.qualified_name not in used:
                used.append(match.qualified_name)
    for table in tree.find_all(exp.Table):
        if id(table) not in accounted:  # never let a reference slip through unchecked
            raise _reject(RejectionCode.UNKNOWN_TABLE, f"Could not resolve table reference {table.sql()}.")
    return used


def profile_schema(profile: DatabaseProfile, dialect: str) -> MappingSchema:
    """The profile as a sqlglot schema. Sensitive columns are left out, so they are unknown."""
    mapping: dict[str, Any] = {}  # schema -> table -> column -> type
    for table in profile.tables:
        columns = {c.name: "unknown" for c in table.columns if not c.sensitive}
        mapping.setdefault(table.schema_name, {})[table.name] = columns
    return MappingSchema(mapping, dialect=dialect)


def _check_columns(tree: exp.Expr, profile: DatabaseProfile, dialect: str) -> None:
    """Resolve every column against the profile (sensitive columns are unknown to it)."""
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise _reject(RejectionCode.STAR, "SELECT * is not allowed; name the columns.")

    try:
        qualified = qualify(
            tree.copy(),
            schema=profile_schema(profile, dialect),
            dialect=dialect,
            validate_qualify_columns=True,
            quote_identifiers=False,
        )
    except OptimizeError as exc:
        raise _reject(RejectionCode.UNKNOWN_COLUMN, str(exc).split(". Line:")[0] + ".") from None

    # A bare table alias used as a value (`SELECT c`, `c::text`, `json_build_object('r', c)`) is a
    # whole-row reference: it returns every column of the row, sensitive ones included.
    whole_row = next(qualified.find_all(exp.TableColumn), None)
    if whole_row is not None:
        raise _reject(
            RejectionCode.WHOLE_ROW,
            f"{whole_row.name!r} is a table, not a column; whole-row references are not allowed.",
        )
    # After qualification every real column carries its table; an unqualified name left
    # outside the projection list must be an output alias (ORDER BY total).
    for column in qualified.find_all(exp.Column):
        select = column.find_ancestor(exp.Select)
        if column.table or select is None:
            continue
        in_projection = any(column is c for e in select.expressions for c in e.find_all(exp.Column))
        if in_projection or column.name not in {e.alias_or_name for e in select.expressions}:
            raise _reject(RejectionCode.UNKNOWN_COLUMN, f"Column {column.name!r} could not be resolved.")


def _enforce_limit(tree: exp.Query, max_rows: int) -> tuple[int, Literal["kept", "added", "clamped"]]:
    fetch = tree.args.get("limit")
    if fetch is None:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        return max_rows, "added"
    if isinstance(fetch, exp.Fetch):  # FETCH FIRST [n] ROWS ONLY; no count means one row
        value = fetch.args.get("count") or exp.Literal.number(1)
    else:
        value = fetch.expression
    if not (isinstance(value, exp.Literal) and value.is_int):
        raise _reject(RejectionCode.INVALID_LIMIT, "LIMIT must be a whole number.")
    requested = int(value.this)
    if requested <= max_rows:
        return requested, "kept"
    tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return max_rows, "clamped"


# Arithmetic between a cast and the division it feeds: CAST(x AS NUMERIC) * 100 / total.
_ARITHMETIC = (exp.Paren, exp.Mul, exp.Add, exp.Sub, exp.Neg)


def _float_divisions(tree: exp.Expr) -> int:
    """Compute ratios in floating point: CAST(x AS NUMERIC) without precision, where it only serves
    a division, becomes CAST(x AS DOUBLE PRECISION). Models cast to NUMERIC to avoid integer
    division; the result then comes back as an arbitrary-precision decimal where a ratio or a
    percentage is expected to be a float (BIRD's answers are, and an exact comparison of
    0.0657... as decimal and as float fails). A cast with precision (NUMERIC(10, 2)) is a
    deliberate choice and stays, and so does any cast that is not part of a division."""
    rewritten = 0
    for cast in list(tree.find_all(exp.Cast)):
        to = cast.args.get("to")
        if not isinstance(to, exp.DataType) or to.this != exp.DataType.Type.DECIMAL or to.expressions:
            continue
        node: exp.Expr = cast
        while isinstance(node.parent, _ARITHMETIC):
            node = node.parent
        if isinstance(node.parent, exp.Div):
            cast.set("to", exp.DataType.build("DOUBLE PRECISION"))
            rewritten += 1
    return rewritten


def validate_sql(sql: str, profile: DatabaseProfile, dialect: str, max_rows: int) -> ValidatedSQL:
    """Accept or reject generated SQL. Raises SQLRejectedError with a machine-readable code."""
    tree = _parse(sql, dialect)
    _check_forbidden_nodes(tree)
    _check_functions(tree)
    tables = _check_tables(tree, profile)
    _check_columns(tree, profile, dialect)
    limit, action = _enforce_limit(tree, max_rows)
    casts = _float_divisions(tree)
    return ValidatedSQL(
        sql=tree.sql(dialect=dialect), tables=tables, limit=limit, limit_action=action, float_casts=casts
    )
