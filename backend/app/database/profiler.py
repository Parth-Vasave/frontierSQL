"""Build a DatabaseProfile for any database SQLAlchemy can reflect.

Structure comes from reflection (no data is read). Value hints come from bounded,
read-only aggregate queries whose extent is set by the connection's SamplingMode.
Sampling runs under the same statement timeout as agent queries and a total time
budget, so profiling a large database degrades to "fewer hints" rather than hanging.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Column, Connection, MetaData, Table, func, inspect, select
from sqlalchemy import types as sqltypes
from sqlalchemy.exc import DBAPIError, NoSuchTableError

from app.database.adapters import DatabaseAdapter
from app.database.profile import (
    ColumnProfile,
    DatabaseProfile,
    Relationship,
    SamplingMode,
    TableProfile,
    ValueHints,
)

MAX_CATEGORIES = 20
MAX_CATEGORY_LENGTH = 40
MAX_EXAMPLES = 3
MAX_EXAMPLE_LENGTH = 60

# Matches whole name parts: "email", "user_email", "password_hash" -- but not "emailed_at_count".
_SENSITIVE = re.compile(
    r"(^|_)(password|passwd|pwd|secret|token|api_?key|access_?key|private_?key|salt|ssn"
    r"|social_security|credit_?card|card_?number|cvv|iban|email|e_?mail|phone|mobile"
    r"|address|dob|date_of_birth|birth_?date)(_|$)"
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def is_sensitive(column_name: str) -> bool:
    snake = _CAMEL_BOUNDARY.sub("_", column_name).lower()
    return bool(_SENSITIVE.search(snake))


def fingerprint(tables: Iterable[TableProfile], relationships: Iterable[Relationship]) -> str:
    """Hash of the structure only (not hints or row counts): changes when the schema changes."""
    structure = {
        "tables": [
            [t.qualified_name, t.kind, [[c.name, c.type, c.nullable, c.primary_key] for c in t.columns]]
            for t in sorted(tables, key=lambda t: t.qualified_name)
        ],
        "relationships": sorted(
            [r.from_table, r.from_columns, r.to_table, r.to_columns] for r in relationships if not r.inferred
        ),
    }
    return hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()


def infer_relationships(tables: list[TableProfile], declared: list[Relationship]) -> list[Relationship]:
    """Guess joins for `<name>_id` columns without a foreign key: orders.customer_id -> customers.id."""
    by_name: dict[str, TableProfile] = {t.name.lower(): t for t in tables}
    declared_keys = {(r.from_table, tuple(r.from_columns)) for r in declared}
    inferred = []
    for table in tables:
        for column in table.columns:
            match = re.fullmatch(r"(.+?)_?id", column.name.lower())
            if not match or column.primary_key or (table.qualified_name, (column.name,)) in declared_keys:
                continue
            stem = match.group(1)
            for candidate in (stem, f"{stem}s", f"{stem}es", stem.removesuffix("y") + "ies"):
                target = by_name.get(candidate)
                if target is None or target is table:
                    continue
                pk = [c.name for c in target.columns if c.primary_key]
                if len(pk) == 1:
                    inferred.append(
                        Relationship(
                            from_table=table.qualified_name,
                            from_columns=[column.name],
                            to_table=target.qualified_name,
                            to_columns=pk,
                            inferred=True,
                        )
                    )
                    break
    return inferred


def _is_numeric_or_temporal(type_: sqltypes.TypeEngine) -> bool:
    # Float (REAL, DOUBLE PRECISION) is listed on its own: since SQLAlchemy 2.1 it is not a Numeric.
    return isinstance(
        type_, (sqltypes.Numeric, sqltypes.Float, sqltypes.Integer, sqltypes.Date, sqltypes.DateTime)
    )


def _is_text(type_: sqltypes.TypeEngine) -> bool:
    return isinstance(type_, (sqltypes.String, sqltypes.Enum))


class Profiler:
    def __init__(
        self,
        adapter: DatabaseAdapter,
        sampling: SamplingMode = SamplingMode.SAFE,
        schemas: list[str] | None = None,
        time_budget_seconds: float = 30.0,
    ) -> None:
        self.adapter = adapter
        self.sampling = sampling
        self.schemas = schemas
        self.time_budget_seconds = time_budget_seconds

    def profile(self, conn: Connection, database_id: str) -> DatabaseProfile:
        tables, declared, reflected = self.reflect(conn)
        relationships = declared + infer_relationships(tables, declared)
        notes: list[str] = []
        if self.sampling is not SamplingMode.OFF:
            self._sample(conn, tables, reflected, notes)
        return DatabaseProfile(
            database_id=database_id,
            dialect=self.adapter.backend,
            sampling=self.sampling,
            fingerprint=fingerprint(tables, relationships),
            tables=tables,
            relationships=relationships,
            notes=notes,
        )

    def reflect(self, conn: Connection) -> tuple[list[TableProfile], list[Relationship], dict[str, Table]]:
        """Structure only: no table data is read."""
        inspector = inspect(conn)
        default_schema = inspector.default_schema_name  # None: the engine has no default schema
        schemas = self.schemas or ([default_schema] if default_schema else [])
        tables: list[TableProfile] = []
        relationships: list[Relationship] = []
        reflected: dict[str, Table] = {}
        for schema in schemas:
            readable = self.adapter.readable_tables(conn, schema)
            row_counts = self.adapter.estimate_row_counts(conn, schema)
            names = [(n, "table") for n in inspector.get_table_names(schema=schema)]
            names += [(n, "view") for n in inspector.get_view_names(schema=schema)]
            for name, kind in sorted(names):
                if readable is not None and name not in readable:
                    continue
                try:
                    table = Table(name, MetaData(), schema=schema, autoload_with=conn)
                except NoSuchTableError:
                    continue
                reflected[f"{schema}.{name}"] = table
                tables.append(self._table_profile(table, kind, row_counts.get(name)))
                relationships.extend(self._foreign_keys(table))
        return tables, relationships, reflected

    @staticmethod
    def _table_profile(table: Table, kind: str, estimated_rows: int | None) -> TableProfile:
        return TableProfile(
            schema_name=table.schema or "",
            name=table.name,
            kind=kind,
            comment=table.comment,
            estimated_rows=estimated_rows,
            columns=[
                ColumnProfile(
                    name=c.name,
                    type=str(c.type),
                    nullable=bool(c.nullable),
                    comment=c.comment,
                    primary_key=c.primary_key,
                    sensitive=is_sensitive(c.name),
                )
                for c in table.columns
            ],
        )

    @staticmethod
    def _foreign_keys(table: Table) -> list[Relationship]:
        relationships = []
        for fk in table.foreign_key_constraints:
            target = fk.referred_table
            relationships.append(
                Relationship(
                    from_table=f"{table.schema}.{table.name}",
                    from_columns=[c.name for c in fk.columns],
                    to_table=f"{target.schema or table.schema}.{target.name}",
                    to_columns=[e.column.name for e in fk.elements],
                )
            )
        return relationships

    def _sample(
        self, conn: Connection, tables: list[TableProfile], reflected: dict[str, Table], notes: list[str]
    ) -> None:
        conn.rollback()  # end the reflection transaction; each sample runs in its own
        deadline = time.monotonic() + self.time_budget_seconds
        for profile in tables:
            if time.monotonic() > deadline:
                notes.append(
                    f"Sampling time budget reached; no value hints from {profile.qualified_name} on."
                )
                return
            table = reflected[profile.qualified_name]
            try:
                self._sample_table(conn, table, profile)
            except DBAPIError as exc:
                conn.rollback()
                reason = type(getattr(exc, "orig", exc)).__name__
                notes.append(f"No value hints for {profile.qualified_name} ({reason}).")

    def _sample_table(self, conn: Connection, table: Table, profile: TableProfile) -> None:
        columns = {c.name: c for c in profile.columns if not c.sensitive}
        ranged = [table.c[name] for name in columns if _is_numeric_or_temporal(table.c[name].type)]
        texts = [table.c[name] for name in columns if _is_text(table.c[name].type)]

        # One aggregate pass per table: row count, null counts and min/max of ranged columns.
        aggregates = [func.count().label("__rows")]
        for col in [*ranged, *texts]:
            aggregates.append(func.count(col).label(f"n_{col.name}"))
        for col in ranged:
            aggregates += [func.min(col).label(f"min_{col.name}"), func.max(col).label(f"max_{col.name}")]
        self.adapter.begin_read_only(conn)
        stats = conn.execute(select(*aggregates).select_from(table)).mappings().one()
        conn.rollback()
        total = stats["__rows"]
        if total == 0:
            return

        for col in [*ranged, *texts]:
            hints = ValueHints(null_fraction=round(1 - stats[f"n_{col.name}"] / total, 4))
            if col in ranged:
                hints.min, hints.max = stats[f"min_{col.name}"], stats[f"max_{col.name}"]
            else:
                self._text_hints(conn, table, col, hints)
            columns[col.name].hints = hints

    def _text_hints(self, conn: Connection, table: Table, col: Column, hints: ValueHints) -> None:
        self.adapter.begin_read_only(conn)
        distinct: list[Any] = list(
            conn.execute(
                select(col).where(col.is_not(None)).group_by(col).order_by(col).limit(MAX_CATEGORIES + 1)
            ).scalars()
        )
        conn.rollback()
        values = [str(v) for v in distinct]
        if len(values) <= MAX_CATEGORIES and all(len(v) <= MAX_CATEGORY_LENGTH for v in values):
            hints.categories = values
        elif self.sampling is SamplingMode.FULL:
            hints.examples = [v[:MAX_EXAMPLE_LENGTH] for v in values[:MAX_EXAMPLES]]
