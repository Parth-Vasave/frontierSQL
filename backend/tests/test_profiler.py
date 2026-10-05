"""Profiler unit tests (no database) and integration tests on two differently shaped schemas."""

from __future__ import annotations

import psycopg
import pytest
from pydantic import SecretStr

from app.database.connections import ConnectionConfig, ConnectionRegistry, ConnectionStatus
from app.database.profile import ColumnProfile, Relationship, SamplingMode, TableProfile
from app.database.profiler import fingerprint, infer_relationships, is_sensitive


@pytest.mark.parametrize(
    "name",
    ["password", "password_hash", "email", "user_email", "phone", "apiKey", "api_key", "ssn", "ip_address"],
)
def test_sensitive_names(name: str) -> None:
    assert is_sensitive(name)


@pytest.mark.parametrize(
    "name", ["co2", "population", "entity_type", "status", "emailed", "tokenizer_version"]
)
def test_non_sensitive_names(name: str) -> None:
    assert not is_sensitive(name)


def _table(name: str, *columns: tuple[str, bool]) -> TableProfile:
    return TableProfile(
        schema_name="s",
        name=name,
        kind="table",
        columns=[ColumnProfile(name=c, type="INTEGER", nullable=False, primary_key=pk) for c, pk in columns],
    )


def test_infer_relationships_from_names() -> None:
    customers = _table("customers", ("id", True))
    categories = _table("categories", ("id", True))
    orders = _table(
        "orders", ("id", True), ("customer_id", False), ("category_id", False), ("batch_id", False)
    )
    inferred = infer_relationships([customers, categories, orders], declared=[])
    assert {(r.from_columns[0], r.to_table) for r in inferred} == {
        ("customer_id", "s.customers"),
        ("category_id", "s.categories"),
    }
    assert all(r.inferred for r in inferred)


def test_declared_foreign_keys_are_not_duplicated() -> None:
    customers = _table("customers", ("id", True))
    orders = _table("orders", ("id", True), ("customer_id", False))
    declared = [
        Relationship(
            from_table="s.orders", from_columns=["customer_id"], to_table="s.customers", to_columns=["id"]
        )
    ]
    assert infer_relationships([customers, orders], declared) == []


def test_fingerprint_tracks_structure_only() -> None:
    table = _table("t", ("id", True))
    base = fingerprint([table], [])
    table.estimated_rows = 99
    assert fingerprint([table], []) == base
    table.columns.append(ColumnProfile(name="x", type="TEXT", nullable=True))
    assert fingerprint([table], []) != base


# --- integration -------------------------------------------------------------------------


def _connect(url: str, sampling: SamplingMode = SamplingMode.SAFE, schemas: list[str] | None = None):
    registry = ConnectionRegistry(timeout_seconds=2)
    return registry.add(
        ConnectionConfig(id="t", name="t", url=SecretStr(url), sampling=sampling, schemas=schemas)
    )


def test_read_only_account_is_ready(pg) -> None:
    connection = _connect(pg.agent)
    assert connection.status is ConnectionStatus.READY
    assert connection.privileges is not None and connection.privileges.blocking == []


def test_owner_account_is_rejected(pg) -> None:
    connection = _connect(pg.admin)
    assert connection.status is ConnectionStatus.REJECTED
    assert any("modify tables" in issue for issue in connection.issues)


def test_granting_one_write_privilege_gets_the_account_rejected(pg) -> None:
    with psycopg.connect(pg.admin, autocommit=True) as conn:
        conn.execute("GRANT INSERT ON shop.orders TO sql_agent")
        try:
            connection = _connect(pg.agent)
        finally:
            conn.execute("REVOKE INSERT ON shop.orders FROM sql_agent")
    assert connection.status is ConnectionStatus.REJECTED
    assert any("shop.orders" in issue for issue in connection.issues)


def test_owid_shaped_schema_is_reflected_with_units_and_keys(pg) -> None:
    profile = _connect(pg.agent, schemas=["public"]).profile()
    tables = {t.name: t for t in profile.tables}
    assert set(tables) == {"countries", "country_indicators", "co2_emissions", "ghg_emissions"}
    co2 = {c.name: c for c in tables["co2_emissions"].columns}
    assert "million tonnes" in (co2["co2"].comment or "")
    assert {(r.from_table, r.to_table) for r in profile.relationships if not r.inferred} == {
        ("public.co2_emissions", "public.countries"),
        ("public.country_indicators", "public.countries"),
        ("public.ghg_emissions", "public.countries"),
    }


def test_shop_schema_profile(pg) -> None:
    profile = _connect(pg.agent, schemas=["shop"]).profile()
    tables = {t.name: {c.name: c for c in t.columns} for t in profile.tables}

    assert set(tables) == {"customers", "orders", "order_items"}  # secret_audit is not readable
    customers, orders = tables["customers"], tables["orders"]

    assert customers["email"].sensitive and customers["email"].hints is None
    assert customers["password_hash"].sensitive and customers["password_hash"].hints is None
    assert customers["segment"].hints.categories == ["online", "retail", "wholesale"]
    assert customers["full_name"].hints.categories is None  # 25 distinct values: free text
    assert customers["full_name"].hints.examples is None  # not in safe mode
    assert orders["status"].hints.categories == ["placed", "returned", "shipped"]
    assert (orders["total"].hints.min, orders["total"].hints.max) == (10, 600)
    assert str(orders["ordered_at"].hints.min) == "2024-01-02"
    # Floating-point columns are ranged too (SQLAlchemy 2.1's Float is not a Numeric).
    weight = tables["order_items"]["weight_kg"].hints
    assert (weight.min, weight.max, weight.null_fraction) == (0.5, 2.0, 0)

    relationships = {(r.from_table, r.from_columns[0], r.to_table, r.inferred) for r in profile.relationships}
    assert ("shop.order_items", "order_id", "shop.orders", False) in relationships
    assert ("shop.orders", "customer_id", "shop.customers", True) in relationships


def test_sampling_off_reads_no_values(pg) -> None:
    profile = _connect(pg.agent, sampling=SamplingMode.OFF, schemas=["shop"]).profile()
    assert all(c.hints is None for t in profile.tables for c in t.columns)


def test_sampling_full_adds_short_examples_but_never_sensitive(pg) -> None:
    profile = _connect(pg.agent, sampling=SamplingMode.FULL, schemas=["shop"]).profile()
    customers = {c.name: c for c in next(t for t in profile.tables if t.name == "customers").columns}
    assert customers["full_name"].hints.examples == ["Customer 01", "Customer 02", "Customer 03"]
    assert customers["email"].hints is None
    # Examples are the most frequent values (then alphabetical), not just the first ones.
    orders = {c.name: c for c in next(t for t in profile.tables if t.name == "orders").columns}
    assert orders["note"].hints.examples == ["gift wrap", "note 1", "note 11"]


def test_profile_is_cached_until_the_schema_changes(pg) -> None:
    connection = _connect(pg.agent, schemas=["shop"])
    first = connection.profile()
    assert connection.profile() is first
    with psycopg.connect(pg.admin, autocommit=True) as conn:
        conn.execute("ALTER TABLE shop.orders ADD COLUMN channel text")
        try:
            second = connection.profile()
        finally:
            conn.execute("ALTER TABLE shop.orders DROP COLUMN channel")
    assert second is not first and second.fingerprint != first.fingerprint
    assert "channel" in {c.name for t in second.tables for c in t.columns}
