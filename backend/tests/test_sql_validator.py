"""SQL safety validation: what must be rejected, what must pass, and how LIMIT is enforced.

Unit tests use the real OWID profile (structure only, tests/fixtures/owid_profile.json) plus a
small shop schema with a sensitive column. The integration test runs accepted SQL on PostgreSQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.agent.executor import execute
from app.agent.sql_validator import RejectionCode, SQLRejectedError, validate_sql
from app.database.connections import ConnectionConfig, ConnectionRegistry
from app.database.profile import ColumnProfile, DatabaseProfile, TableProfile

FIXTURES = Path(__file__).parent / "fixtures"
MAX_ROWS = 1000


def _owid_profile() -> DatabaseProfile:
    return DatabaseProfile.model_validate_json((FIXTURES / "owid_profile.json").read_text())


def _with_shop(profile: DatabaseProfile) -> DatabaseProfile:
    customers = TableProfile(
        schema_name="shop",
        name="customers",
        kind="table",
        columns=[
            ColumnProfile(name="id", type="INTEGER", nullable=False, primary_key=True),
            ColumnProfile(name="full_name", type="TEXT", nullable=False),
            ColumnProfile(name="email", type="TEXT", nullable=True, sensitive=True),
        ],
    )
    return profile.model_copy(update={"tables": [*profile.tables, customers]})


PROFILE = _with_shop(_owid_profile())


def validate(sql: str, profile: DatabaseProfile = PROFILE):
    return validate_sql(sql, profile, "postgres", MAX_ROWS)


def rejected(sql: str, profile: DatabaseProfile = PROFILE) -> RejectionCode:
    with pytest.raises(SQLRejectedError) as info:
        validate(sql, profile)
    return info.value.code


# SQL that gemini-3.8-flash / gemini-3.5-flash generated for real questions on 2026-09-26.
# All returned correct results, so the validator must accept them.
REAL_LLM_QUERIES = [
    "SELECT c.name AS country, e.co2 AS co2_emissions FROM public.co2_emissions AS e JOIN public.countries AS c "
    "ON e.country_id = c.id WHERE e.year = 2023 AND c.entity_type = 'country' AND e.co2 IS NOT NULL "
    "ORDER BY e.co2 DESC LIMIT 5;",
    "SELECT c.name, e.year, e.co2 AS co2_emissions_mt FROM public.co2_emissions AS e JOIN public.countries AS c "
    "ON e.country_id = c.id WHERE c.name = 'World' AND e.year = 2000 LIMIT 1;",
    "SELECT c.name AS country, e.co2_per_capita FROM public.co2_emissions AS e JOIN public.countries AS c "
    "ON e.country_id = c.id WHERE c.entity_type = 'country' AND e.year = 2022 AND e.co2_per_capita IS NOT NULL "
    "ORDER BY e.co2_per_capita DESC LIMIT 1;",
    "SELECT e.year, e.co2, e.co2_growth_abs, e.co2_growth_prct FROM public.co2_emissions AS e "
    "JOIN public.countries AS c ON e.country_id = c.id WHERE c.name = 'India' AND e.year BETWEEN 2010 AND 2020 "
    "ORDER BY e.year ASC LIMIT 1000;",
    "SELECT c.name AS income_group, e.co2_per_capita FROM public.co2_emissions AS e JOIN public.countries AS c "
    "ON e.country_id = c.id WHERE c.entity_type = 'income_group' AND e.year = 2020 AND (c.name ILIKE "
    "'High%income%' OR (c.name ILIKE 'Low%income%' AND c.name NOT ILIKE '%middle%')) "
    "ORDER BY e.co2_per_capita DESC LIMIT 10;",
    "SELECT c.name AS continent, ce.coal_co2 FROM public.co2_emissions ce JOIN public.countries c "
    "ON ce.country_id = c.id WHERE ce.year = 2022 AND c.name IN ('Africa', 'Asia', 'Europe', 'North America', "
    "'Oceania', 'South America') AND ce.coal_co2 IS NOT NULL ORDER BY ce.coal_co2 DESC LIMIT 1;",
    "SELECT c.name, g.methane FROM public.ghg_emissions AS g JOIN public.countries AS c ON g.country_id = c.id "
    "WHERE c.entity_type = 'country' AND g.year = 2020 AND g.methane > 100 ORDER BY g.methane DESC LIMIT 1000;",
    "SELECT count(*) AS country_count FROM public.country_indicators AS ci JOIN public.countries AS c "
    "ON ci.country_id = c.id WHERE c.entity_type = 'country' AND ci.year = 2022 AND ci.population > 100000000 "
    "LIMIT 1;",
    "SELECT c.name, e.year, e.share_global_co2 FROM public.co2_emissions e JOIN public.countries c "
    "ON e.country_id = c.id WHERE c.name = 'Germany' AND e.year = 1960;",
    "WITH co2_1990 AS (SELECT country_id, co2 AS co2_1990 FROM public.co2_emissions WHERE year = 1990), "
    "co2_2020 AS (SELECT country_id, co2 AS co2_2020 FROM public.co2_emissions WHERE year = 2020) "
    "SELECT c.name AS country_name, c1990.co2_1990, c2020.co2_2020, (c2020.co2_2020 - c1990.co2_1990) AS "
    "co2_increase FROM public.countries c JOIN co2_1990 c1990 ON c.id = c1990.country_id JOIN co2_2020 c2020 "
    "ON c.id = c2020.country_id WHERE c.entity_type = 'country' AND c1990.co2_1990 IS NOT NULL AND "
    "c2020.co2_2020 IS NOT NULL ORDER BY co2_increase DESC LIMIT 10;",
]


@pytest.mark.parametrize("sql", REAL_LLM_QUERIES)
def test_real_llm_queries_are_accepted(sql: str) -> None:
    result = validate(sql)
    assert result.tables and all(t.startswith("public.") for t in result.tables)
    assert validate(result.sql).sql == result.sql  # the regenerated SQL is itself valid and stable


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM countries WHERE id IN (SELECT country_id FROM co2_emissions WHERE co2 > 1000) LIMIT 5",
        "SELECT year, sum(co2) AS total FROM co2_emissions GROUP BY year HAVING sum(co2) > 0 ORDER BY total LIMIT 5",
        "SELECT c.name, rank() OVER (ORDER BY e.co2 DESC) AS r FROM co2_emissions e "
        "JOIN countries c ON c.id = e.country_id WHERE e.year = 2020 LIMIT 5",
        "SELECT name FROM countries UNION SELECT full_name FROM shop.customers LIMIT 5",
        "SELECT DISTINCT ON (c.entity_type) c.entity_type, c.name FROM countries c ORDER BY c.entity_type, c.name",
        "SELECT c.name FROM countries c WHERE EXISTS (SELECT 1 FROM ghg_emissions g WHERE g.country_id = c.id)",
        "SELECT y FROM generate_series(1990, 2000) AS y LIMIT 5",
        "SELECT count(*) AS n, count(DISTINCT id) AS d FROM shop.customers",
        "SELECT name FROM countries WHERE name = ' :not_a_parameter' LIMIT 1",
    ],
)
def test_ordinary_analytical_queries_are_accepted(sql: str) -> None:
    validate(sql)


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        # writes and schema changes, directly or hidden in a CTE
        ("DELETE FROM countries", RejectionCode.NOT_SELECT),
        ("UPDATE countries SET name = 'x'", RejectionCode.NOT_SELECT),
        ("INSERT INTO countries (name) VALUES ('x')", RejectionCode.NOT_SELECT),
        ("DROP TABLE countries", RejectionCode.NOT_SELECT),
        ("ALTER TABLE countries ADD COLUMN x int", RejectionCode.NOT_SELECT),
        ("TRUNCATE countries", RejectionCode.NOT_SELECT),
        ("CREATE TABLE x AS SELECT name FROM countries", RejectionCode.NOT_SELECT),
        ("GRANT SELECT ON countries TO public", RejectionCode.NOT_SELECT),
        ("COPY countries TO '/tmp/out'", RejectionCode.NOT_SELECT),
        ("EXPLAIN ANALYZE SELECT name FROM countries", RejectionCode.NOT_SELECT),
        ("SET statement_timeout = 0", RejectionCode.NOT_SELECT),
        ("WITH d AS (DELETE FROM countries RETURNING id) SELECT id FROM d", RejectionCode.FORBIDDEN_OPERATION),
        ("WITH u AS (UPDATE countries SET name = 'x' RETURNING id) SELECT id FROM u",
         RejectionCode.FORBIDDEN_OPERATION),
        ("SELECT name INTO stolen FROM countries", RejectionCode.FORBIDDEN_OPERATION),
        ("SELECT name FROM countries FOR UPDATE", RejectionCode.FORBIDDEN_OPERATION),
        # several statements
        ("SELECT name FROM countries; DROP TABLE countries", RejectionCode.MULTIPLE_STATEMENTS),
        ("SELECT 1; SELECT 2", RejectionCode.MULTIPLE_STATEMENTS),
        # system catalogs and tables outside the profile
        ("SELECT rolname FROM pg_roles", RejectionCode.SYSTEM_TABLE),
        ("SELECT usename, passwd FROM pg_catalog.pg_shadow", RejectionCode.SYSTEM_TABLE),
        ("SELECT table_name FROM information_schema.tables", RejectionCode.SYSTEM_TABLE),
        ("SELECT id FROM shop.secret_audit", RejectionCode.UNKNOWN_TABLE),
        ("SELECT id FROM otherdb.public.countries", RejectionCode.UNKNOWN_TABLE),
        # a CTE in a subquery must not hide the outer reference to a real table
        ("SELECT rolname FROM pg_roles, (WITH pg_roles AS (SELECT 1 AS a) SELECT a FROM pg_roles) x",
         RejectionCode.SYSTEM_TABLE),
        # columns that do not exist or are sensitive (hidden from the model, so unknown)
        ("SELECT nonexistent FROM countries", RejectionCode.UNKNOWN_COLUMN),
        ("SELECT email FROM shop.customers", RejectionCode.UNKNOWN_COLUMN),
        ("SELECT c.id FROM shop.customers c WHERE c.email LIKE '%@%'", RejectionCode.UNKNOWN_COLUMN),
        ("SELECT id FROM shop.customers ORDER BY email", RejectionCode.UNKNOWN_COLUMN),
        # everything-at-once reads that would include sensitive columns
        ("SELECT * FROM shop.customers", RejectionCode.STAR),
        ("SELECT c.* FROM shop.customers c", RejectionCode.STAR),
        ("SELECT json_build_object('r', c.*) FROM shop.customers c", RejectionCode.STAR),
        ("SELECT c FROM shop.customers c", RejectionCode.WHOLE_ROW),
        ("SELECT json_build_object('row', c) FROM shop.customers c", RejectionCode.WHOLE_ROW),
        ("SELECT c.id FROM shop.customers c WHERE c::text LIKE '%@%'", RejectionCode.WHOLE_ROW),
        # dangerous or unknown functions
        ("SELECT pg_sleep(10)", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT name FROM countries WHERE pg_sleep(1) IS NULL", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT pg_read_file('/etc/passwd')", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT current_setting('data_directory')", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT set_config('statement_timeout', '0', false)", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT dblink('host=evil', 'SELECT 1')", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT lo_import('/etc/passwd')", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT pg_terminate_backend(1)", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT PG_SLEEP(1)", RejectionCode.FORBIDDEN_FUNCTION),
        ("SELECT row_to_json(c) FROM shop.customers c", RejectionCode.FORBIDDEN_FUNCTION),
        # malformed
        ("SELEC name FROM countries", RejectionCode.SYNTAX),
        ("", RejectionCode.SYNTAX),
        ("SELECT name FROM countries LIMIT (SELECT 5)", RejectionCode.INVALID_LIMIT),
    ],
)  # fmt: skip
def test_unsafe_sql_is_rejected(sql: str, code: RejectionCode) -> None:
    assert rejected(sql) == code


def test_comment_tricks_do_not_hide_a_second_statement() -> None:
    assert rejected("SELECT name FROM countries /* ; */ ; DROP TABLE countries --") == (
        RejectionCode.MULTIPLE_STATEMENTS
    )


def test_unqualified_tables_are_schema_qualified() -> None:
    result = validate("SELECT name FROM countries LIMIT 3")
    assert result.sql == "SELECT name FROM public.countries LIMIT 3"
    assert result.tables == ["public.countries"]


def test_table_name_in_several_schemas_must_be_qualified() -> None:
    countries = next(t for t in PROFILE.tables if t.name == "countries")
    twin = countries.model_copy(update={"schema_name": "archive"})
    profile = PROFILE.model_copy(update={"tables": [*PROFILE.tables, twin]})
    assert rejected("SELECT name FROM countries", profile) == RejectionCode.AMBIGUOUS_TABLE
    assert validate("SELECT name FROM archive.countries", profile).tables == ["archive.countries"]


def test_cte_names_are_not_mistaken_for_tables() -> None:
    result = validate(
        "WITH big AS (SELECT country_id FROM co2_emissions WHERE co2 > 1000) SELECT country_id FROM big"
    )
    assert result.tables == ["public.co2_emissions"]


# --- LIMIT enforcement -------------------------------------------------------------------


def test_missing_limit_is_added() -> None:
    result = validate("SELECT name FROM countries")
    assert (result.limit, result.limit_action) == (MAX_ROWS, "added")
    assert result.sql.endswith(f"LIMIT {MAX_ROWS}")


def test_smaller_limit_is_kept() -> None:
    result = validate("SELECT name FROM countries LIMIT 5")
    assert (result.limit, result.limit_action) == (5, "kept")


def test_larger_limit_is_clamped() -> None:
    result = validate("SELECT name FROM countries LIMIT 999999 OFFSET 10")
    assert (result.limit, result.limit_action) == (MAX_ROWS, "clamped")
    assert f"LIMIT {MAX_ROWS}" in result.sql and "OFFSET 10" in result.sql


def test_limit_all_is_replaced() -> None:
    assert validate("SELECT name FROM countries LIMIT ALL").limit_action == "added"


def test_fetch_first_is_clamped() -> None:
    result = validate("SELECT name FROM countries FETCH FIRST 50000 ROWS ONLY")
    assert (result.limit, result.limit_action) == (MAX_ROWS, "clamped")
    assert validate("SELECT name FROM countries FETCH FIRST ROW ONLY").limit == 1


def test_limit_applies_to_the_whole_union() -> None:
    result = validate("SELECT name FROM countries UNION ALL SELECT full_name FROM shop.customers")
    assert result.sql.endswith(f"LIMIT {MAX_ROWS}")
    assert result.limit_action == "added"


# --- ratios in floating point -----------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "CAST(COUNT(*) AS NUMERIC) / COUNT(*)",
        "CAST(COUNT(*) AS DECIMAL) * 100 / NULLIF(COUNT(*), 0)",
        "(CAST(COUNT(*) AS DECIMAL)) / COUNT(*)",
        "COUNT(*) / COUNT(*)::numeric",
    ],
)
def test_numeric_casts_in_a_division_become_double_precision(expression: str) -> None:
    result = validate(f"SELECT {expression} AS share FROM countries")
    assert result.float_casts == 1
    assert "DOUBLE PRECISION" in result.sql and "DECIMAL" not in result.sql
    validate(result.sql)  # what runs is still a valid query


@pytest.mark.parametrize(
    "expression",
    [
        "CAST(COUNT(*) AS NUMERIC(10, 2)) / COUNT(*)",  # a chosen precision stays
        "CAST(COUNT(*) AS NUMERIC)",  # no division
        "SUM(CAST(LENGTH(name) AS NUMERIC)) / COUNT(*)",  # inside an aggregate: not the ratio itself
    ],
)
def test_other_numeric_casts_are_left_alone(expression: str) -> None:
    result = validate(f"SELECT {expression} AS value FROM countries")
    assert result.float_casts == 0 and "DOUBLE PRECISION" not in result.sql


def test_inner_limits_do_not_count_as_the_outer_limit() -> None:
    result = validate("SELECT name FROM countries WHERE id IN (SELECT country_id FROM co2_emissions LIMIT 5)")
    assert result.limit_action == "added"


# --- integration: accepted SQL runs on PostgreSQL ----------------------------------------


@pytest.fixture
def owid_like(pg):
    """The pg fixture's database: the OWID schema (possibly holding test rows) and the shop schema."""
    registry = ConnectionRegistry(timeout_seconds=2)
    config = ConnectionConfig(id="t", name="T", url=SecretStr(pg.agent), schemas=["public", "shop"])
    return registry.add(config)


@pytest.mark.parametrize("sql", REAL_LLM_QUERIES)
def test_regenerated_sql_returns_the_same_result_as_the_original(owid_like, sql: str) -> None:
    validated = validate_sql(sql, owid_like.profile(), "postgres", MAX_ROWS)
    original = execute(owid_like, sql, MAX_ROWS)
    regenerated = execute(owid_like, validated.sql, MAX_ROWS)
    assert (regenerated.columns, regenerated.rows) == (original.columns, original.rows)


def test_sensitive_column_in_real_profile_is_rejected(owid_like) -> None:
    profile = owid_like.profile()
    assert rejected("SELECT email FROM shop.customers", profile) == RejectionCode.UNKNOWN_COLUMN
    assert rejected("SELECT id FROM shop.secret_audit", profile) == RejectionCode.UNKNOWN_TABLE
