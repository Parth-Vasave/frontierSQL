"""Shared fixtures.

Unit tests need no database. Integration tests (marked by using `pg`) need an EMPTY,
disposable PostgreSQL database: TEST_ADMIN_DATABASE_URL (postgresql:// URL of an owner able to
create roles) and
TEST_SQL_AGENT_PASSWORD. They reset the cluster-wide sql_agent role; never use production.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

# Tests must never need real credentials; settings only require a syntactically valid URL.
os.environ.setdefault("DATABASE_URL", "postgresql://sql_agent:unused@localhost:5432/unused")

ROOT = Path(__file__).resolve().parents[2]

# A second, differently shaped schema: no FK on orders.customer_id, sensitive columns,
# a categorical column, free text with many values, and a table sql_agent cannot read.
SHOP_SCHEMA = """
DROP SCHEMA IF EXISTS shop CASCADE;
CREATE SCHEMA shop;
CREATE TABLE shop.customers (
    id integer PRIMARY KEY, full_name text NOT NULL, email text, password_hash text,
    segment text NOT NULL
);
COMMENT ON TABLE shop.customers IS 'Registered customers.';
CREATE TABLE shop.orders (
    id integer PRIMARY KEY, customer_id integer NOT NULL, status text NOT NULL,
    total numeric(10, 2) NOT NULL, ordered_at date NOT NULL
);
CREATE TABLE shop.order_items (
    id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES shop.orders (id),
    product text NOT NULL, quantity integer NOT NULL, weight_kg real
);
CREATE TABLE shop.secret_audit (id integer PRIMARY KEY, note text);
INSERT INTO shop.customers
SELECT i, 'Customer ' || lpad(i::text, 2, '0'), 'c' || i || '@example.test', 'hash' || i,
       (ARRAY['retail', 'wholesale', 'online'])[1 + i % 3]
FROM generate_series(1, 25) AS i;
INSERT INTO shop.orders
SELECT i, 1 + i % 25, (ARRAY['placed', 'shipped', 'returned'])[1 + i % 3], 10 * i,
       DATE '2024-01-01' + i
FROM generate_series(1, 60) AS i;
INSERT INTO shop.order_items
SELECT i, 1 + i % 60, 'Product ' || (i % 5), 1 + i % 4, 0.5 * (1 + i % 4) FROM generate_series(1, 120) AS i;
GRANT USAGE ON SCHEMA shop TO sql_agent;
GRANT SELECT ON shop.customers, shop.orders, shop.order_items TO sql_agent;
"""


@dataclass(frozen=True)
class PgUrls:
    admin: str
    agent: str


@pytest.fixture(scope="session")
def pg() -> Iterator[PgUrls]:
    admin = os.environ.get("TEST_ADMIN_DATABASE_URL")
    password = os.environ.get("TEST_SQL_AGENT_PASSWORD")
    if not admin or not password:
        pytest.skip("TEST_ADMIN_DATABASE_URL / TEST_SQL_AGENT_PASSWORD not set")
    env = {
        **os.environ,
        "ADMIN_DATABASE_URL": admin,
        "SQL_AGENT_PASSWORD": password,
        "QUERY_TIMEOUT_SECONDS": "2",
    }
    subprocess.run([str(ROOT / "database" / "init" / "00_init.sh")], env=env, check=True, capture_output=True)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(SHOP_SCHEMA)
    agent = make_url(admin).set(username="sql_agent", password=password)
    yield PgUrls(admin=admin, agent=agent.render_as_string(hide_password=False))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS shop CASCADE")
