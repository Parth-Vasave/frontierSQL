"""BIRD Mini-Dev as an evaluation dataset: questions, connections and ground truth.

The data is loaded by `python -m scripts.bird` into the database `bird` on the same server as
DATABASE_URL, one schema per BIRD database. The analyst connects as the same read-only sql_agent
account, in one of two scopes:

* `database`: one connection per BIRD database, limited to its schema (BIRD's own setting);
* `all`: one connection over all 11 schemas (75 tables), so schema retrieval has to find the
  right tables first.

Ground truth is BIRD's SQL, run on the read-only account with search_path set to the question's
schema (it uses unqualified table names):

    python -m evaluation.bird build-expected [--show]

The questions and results are CC BY-SA 4.0 and are not committed: they live under data/.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url

# The conversion the agent's own results go through, so expected and actual values compare alike.
from app.agent.executor import _json_safe
from app.config import get_settings
from app.database.connections import ConnectionConfig, ConnectionRegistry, DatabaseConnection
from evaluation import ROOT

RAW_DIR = ROOT / "data" / "raw" / "bird"
QUESTIONS = RAW_DIR / "mini_dev_pg.json"
MANIFEST = RAW_DIR / "bird.manifest.json"
EXPECTED = ROOT / "data" / "processed" / "bird" / "expected.json"
DATABASE = "bird"
GROUND_TRUTH_TIMEOUT_SECONDS = 60

Scope = Literal["database", "all"]


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    """BIRD questions in the shape of evaluation/questions.json, plus db_id and evidence."""
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python -m scripts.bird download` first.")
    return [
        {
            "id": f"B{q['question_id']:04d}",
            "category": q["difficulty"],
            "db_id": q["db_id"],
            "question": q["question"],
            "evidence": q.get("evidence") or "",
            "expected_behavior": "query",
            # BIRD's execution accuracy compares sets of rows, so row order never counts.
            "ground_truth": {"sql": q["SQL"], "order_matters": False},
        }
        for q in json.loads(path.read_text())
    ]


def question_text(item: dict[str, Any], evidence: bool) -> str:
    """The question as asked: with BIRD's evidence (its hint for this question) appended, or not."""
    if evidence and item.get("evidence"):
        return f"{item['question']}\nHint: {item['evidence']}"
    return str(item["question"])


def database_ids(items: list[dict[str, Any]]) -> list[str]:
    return sorted({item["db_id"] for item in items})


def bird_url(database_url: SecretStr) -> SecretStr:
    """The sql_agent URL of DATABASE_URL, pointed at the database `bird` on the same server."""
    url = make_url(database_url.get_secret_value()).set(database=DATABASE)
    return SecretStr(url.render_as_string(hide_password=False))


def connect(
    url: SecretStr, scope: Scope, db_ids: list[str], timeout_seconds: float
) -> dict[str, DatabaseConnection]:
    """BIRD database id -> the connection a question about it is asked on."""
    registry = ConnectionRegistry(timeout_seconds)
    if scope == "all":
        everything = registry.add(ConnectionConfig(id="bird", name="BIRD (all)", url=url, schemas=db_ids))
        return dict.fromkeys(db_ids, everything)
    return {
        db_id: registry.add(ConnectionConfig(id=db_id, name=f"BIRD {db_id}", url=url, schemas=[db_id]))
        for db_id in db_ids
    }


def fingerprint(url: SecretStr) -> dict[str, int]:
    """Row count of every BIRD table: ground truth is only valid on the data it was built from."""
    counts: dict[str, int] = {}
    with psycopg.connect(_libpq(url), options="-c default_transaction_read_only=on") as conn:
        tables = conn.execute(
            "SELECT schemaname, tablename FROM pg_tables"
            " WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2"
        ).fetchall()
        for schema, table in tables:
            query = sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
            row = conn.execute(query).fetchone()
            counts[f"{schema}.{table}"] = row[0] if row else 0
    return counts


def _libpq(url: SecretStr) -> str:
    return make_url(url.get_secret_value()).set(drivername="postgresql").render_as_string(hide_password=False)


def run_ground_truth(conn: psycopg.Connection, db_id: str, query: str, max_rows: int) -> dict[str, Any]:
    """Run BIRD's SQL for one question; never raises for a query error, records it instead."""
    try:
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(db_id)))
        cursor = conn.execute(query)
        columns = [d.name for d in cursor.description or []]
        fetched = cursor.fetchmany(max_rows + 1)
    except psycopg.errors.QueryCanceled:
        return {"error": f"timed out after {GROUND_TRUTH_TIMEOUT_SECONDS}s"}
    except psycopg.Error as exc:
        return {"error": str(exc).strip().splitlines()[0][:300]}
    finally:
        conn.rollback()  # each question in its own read-only transaction; nothing to keep
    if len(fetched) > max_rows:
        return {"error": f"more than {max_rows} rows (MAX_ROWS): the agent's result would be cut off"}
    return {"columns": columns, "rows": [[_json_safe(v) for v in row] for row in fetched]}


def build_expected(url: SecretStr, max_rows: int, show: bool = False) -> dict[str, Any]:
    questions = load_questions()
    results: dict[str, list[dict[str, Any]]] = {}
    excluded: dict[str, str] = {}
    options = (
        f"-c default_transaction_read_only=on -c statement_timeout={GROUND_TRUTH_TIMEOUT_SECONDS * 1000}"
    )
    with psycopg.connect(_libpq(url), options=options) as conn:
        for item in questions:
            outcome = run_ground_truth(conn, item["db_id"], item["ground_truth"]["sql"], max_rows)
            if "error" in outcome:
                excluded[item["id"]] = outcome["error"]
            else:
                results[item["id"]] = [outcome]
            if show:
                print(f"{item['id']} [{item['db_id']}] {item['question']}\n    {outcome}")
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    return {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": "bird-mini-dev",
        "questions_revision": manifest.get("questions", {}).get("revision"),
        "max_rows": max_rows,
        "row_counts": fingerprint(url),
        "results": results,
        "excluded": excluded,  # question id -> why its ground truth cannot be scored
    }


def load_expected(path: Path = EXPECTED) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `python -m evaluation.bird build-expected` first.")
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-expected", help="run BIRD's ground-truth SQL and save the results")
    build.add_argument("--show", action="store_true", help="print every expected result")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("Set DATABASE_URL to the read-only sql_agent account (its server has `bird`).")
    document = build_expected(bird_url(settings.database_url), settings.max_rows, show=args.show)
    EXPECTED.parent.mkdir(parents=True, exist_ok=True)
    EXPECTED.write_text(json.dumps(document, indent=1, default=str) + "\n")
    print(f"Wrote {len(document['results'])} expected results to {EXPECTED.relative_to(ROOT)}")
    for qid, reason in sorted(document["excluded"].items()):
        print(f"  excluded {qid}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
