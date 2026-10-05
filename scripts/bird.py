"""Download and load the BIRD Mini-Dev benchmark (PostgreSQL version) for evaluation.

BIRD Mini-Dev (https://github.com/bird-bench/mini_dev, CC BY-SA 4.0) is 500 text-to-SQL questions
over 11 databases with hand-checked ground-truth SQL. Its PostgreSQL dump puts all 75 tables in
one `public` schema; `load` moves each BIRD database's tables into a schema of its own (e.g.
`formula_1`), so the analyst can be pointed at one BIRD database or at all of them.

Usage:
    python -m scripts.bird download     # pinned files, SHA-256 verified, into data/raw/bird/
    ADMIN_DATABASE_URL=postgresql://... python -m scripts.bird load [--replace]

`load` runs as the database OWNER (ADMIN_DATABASE_URL, any database on the server), never as
sql_agent: it creates the database `bird` next to it, loads the dump with psql, and grants the
existing sql_agent role CONNECT and SELECT only. The data is downloaded, never committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.ingest_data import IntegrityError

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "bird"
MANIFEST_NAME = "bird.manifest.json"
DATABASE = "bird"

# The full Mini-Dev package (SQLite, MySQL and PostgreSQL versions), as linked from the BIRD
# Mini-Dev README. Only the PostgreSQL dump and the table list are extracted from it.
PACKAGE_URL = "https://drive.usercontent.google.com/download?id=13VLWIwpw5E3d5DUkMvzw7hvHE67a4XkG&export=download&confirm=t"
PACKAGE_SHA256 = "aeb211c0e39010bbdae3838bb5e8bd27dc446ed77495b1709f85ccc9bf67f2be"
PACKAGE_MEMBERS = {
    "minidev/MINIDEV_postgresql/BIRD_dev.sql": "BIRD_dev.sql",
    "minidev/MINIDEV/dev_tables.json": "dev_tables.json",
}
# Questions from the Hugging Face copy, pinned to a revision: it is newer than the package's copy
# and fixes one ground-truth query (question 1000 sorts a text column without casting it).
QUESTIONS_REVISION = "f65faf4ae3b638c1fa6df1d3370c8d92c8366301"
QUESTIONS_URL = (
    f"https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/{QUESTIONS_REVISION}"
    "/data/mini_dev_pg-00000-of-00001.json"
)
QUESTIONS_SHA256 = "7fa740ef9225389cff6c34432120e8325d0ca3008d73db1ae38731234bc10da7"
QUESTIONS_FILE = "mini_dev_pg.json"

_OWNER = re.compile(r"^ALTER \S+ .* OWNER TO \S+;$")
_COPY_START = re.compile(r"^COPY \S+ \(.*\) FROM stdin;$")


class LoadError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(url: str, target: Path, expected: str, verify: bool) -> str:
    """Stream url to target (the package is ~800 MB, too big for memory) and check its SHA-256."""
    partial = target.with_suffix(target.suffix + ".part")
    print(f"Downloading {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: {url}: {exc}") from exc
    digest = _sha256(partial)
    if verify and digest != expected:
        partial.unlink()
        raise IntegrityError(f"{target.name}: sha256 {digest} does not match the pinned {expected}.")
    partial.replace(target)
    return digest


def download(raw_dir: Path = RAW_DIR, verify: bool = True, keep_package: bool = False) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    package = raw_dir / "minidev.zip"
    package_digest = _download_file(PACKAGE_URL, package, PACKAGE_SHA256, verify)
    with zipfile.ZipFile(package) as archive:
        for member, name in PACKAGE_MEMBERS.items():
            with archive.open(member) as src, (raw_dir / name).open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    if not keep_package:
        package.unlink()
    questions_digest = _download_file(QUESTIONS_URL, raw_dir / QUESTIONS_FILE, QUESTIONS_SHA256, verify)

    manifest = {
        "source": "BIRD Mini-Dev (PostgreSQL)",
        "repository": "https://github.com/bird-bench/mini_dev",
        "license": "CC BY-SA 4.0",
        "downloaded_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "verified_against_pinned_hashes": verify,
        "package": {"url": PACKAGE_URL, "sha256": package_digest, "members": list(PACKAGE_MEMBERS)},
        "questions": {"url": QUESTIONS_URL, "revision": QUESTIONS_REVISION, "sha256": questions_digest},
    }
    (raw_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def table_schemas(dev_tables: list[dict]) -> dict[str, str]:
    """Postgres table name -> BIRD database id. The dump folds the SQLite names to lower case."""
    mapping: dict[str, str] = {}
    for database in dev_tables:
        for table in database["table_names_original"]:
            name = table.lower()
            if name in mapping:
                raise LoadError(f"table {name} belongs to both {mapping[name]} and {database['db_id']}")
            mapping[name] = database["db_id"]
    return mapping


def without_owners(lines: Iterable[str]) -> Iterator[str]:
    """The dump's lines minus `ALTER ... OWNER TO <role>;` (that role exists only on the authors'
    machine). COPY data is passed through untouched, whatever it contains."""
    in_copy = False
    for line in lines:
        bare = line.rstrip("\n")
        if in_copy:
            in_copy = bare != "\\."
        elif _COPY_START.match(bare):
            in_copy = True
        elif _OWNER.match(bare):
            continue
        yield line


def _database_url(admin_url: str, dbname: str) -> str:
    return make_conninfo(admin_url, dbname=dbname)


def _create_database(admin_url: str, replace: bool) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone()
        if exists and not replace:
            raise LoadError(f"database {DATABASE!r} already exists; use --replace to drop and reload it")
        if exists:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DATABASE)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))


def _load_dump(bird_url: str, dump: Path) -> None:
    psql = os.environ.get("PSQL", "psql")
    if shutil.which(psql) is None:
        raise LoadError("psql not found (install the PostgreSQL client or set PSQL)")
    # -o: the dump's `SELECT setval(...)` results are noise; errors still go to stderr.
    command = [psql, "-X", "-q", "-o", os.devnull, "-v", "ON_ERROR_STOP=1", "-d", bird_url]
    with subprocess.Popen(command, stdin=subprocess.PIPE, text=True, encoding="utf-8") as proc:
        assert proc.stdin is not None
        with dump.open(encoding="utf-8") as fh:
            proc.stdin.writelines(without_owners(fh))
        proc.stdin.close()
        if proc.wait() != 0:
            raise LoadError(f"psql failed loading {dump.name}")


def _organise_and_grant(bird_url: str, mapping: dict[str, str]) -> dict[str, dict[str, int]]:
    """Move each table into its BIRD database's schema and grant sql_agent SELECT. One transaction."""
    with psycopg.connect(bird_url) as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'sql_agent'").fetchone() is None:
            raise LoadError("role sql_agent does not exist; set up the main database first (00_init.sh)")
        loaded = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
        tables = {name for (name,) in loaded}
        if tables != set(mapping):
            raise LoadError(
                f"dump tables differ from dev_tables.json: missing {sorted(set(mapping) - tables)}, "
                f"unexpected {sorted(tables - set(mapping))}"
            )
        dbname = conn.info.dbname
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO sql_agent").format(sql.Identifier(dbname)))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for schema in sorted(set(mapping.values())):
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO sql_agent").format(sql.Identifier(schema)))
        for table, schema in sorted(mapping.items()):
            conn.execute(
                sql.SQL("ALTER TABLE public.{} SET SCHEMA {}").format(
                    sql.Identifier(table), sql.Identifier(schema)
                )
            )
        for schema in sorted(set(mapping.values())):
            conn.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO sql_agent").format(sql.Identifier(schema))
            )
    with psycopg.connect(bird_url, autocommit=True) as conn:
        conn.execute("ANALYZE")  # row estimates for the profiler and plans for the ground-truth SQL
        counts: dict[str, dict[str, int]] = {}
        for table, schema in sorted(mapping.items()):
            query = sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
            row = conn.execute(query).fetchone()
            counts.setdefault(schema, {})[table] = row[0] if row else 0
    return counts


def load(admin_url: str, raw_dir: Path = RAW_DIR, replace: bool = False) -> dict[str, dict[str, int]]:
    dump, tables_file = raw_dir / "BIRD_dev.sql", raw_dir / "dev_tables.json"
    if not dump.exists() or not tables_file.exists():
        raise LoadError(f"{raw_dir} has no BIRD files; run `python -m scripts.bird download` first")
    mapping = table_schemas(json.loads(tables_file.read_text()))
    if conninfo_to_dict(admin_url).get("dbname") == DATABASE:
        raise LoadError(f"ADMIN_DATABASE_URL must name a database other than {DATABASE!r}")
    _create_database(admin_url, replace)
    bird_url = _database_url(admin_url, DATABASE)
    print(f"Loading {dump.name} into database {DATABASE!r} (a few minutes)", file=sys.stderr)
    _load_dump(bird_url, dump)
    return _organise_and_grant(bird_url, mapping)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("download", help="download the pinned BIRD Mini-Dev files")
    get.add_argument("--no-verify", action="store_true", help="skip the pinned SHA-256 checks")
    get.add_argument("--keep-package", action="store_true", help="keep the 800 MB zip after extraction")
    put = commands.add_parser("load", help="load them into the database 'bird' (ADMIN_DATABASE_URL)")
    put.add_argument("--replace", action="store_true", help="drop and reload an existing 'bird' database")
    for sub in (get, put):
        sub.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    try:
        if args.command == "download":
            download(args.raw_dir, verify=not args.no_verify, keep_package=args.keep_package)
            print(f"Wrote the BIRD Mini-Dev files and {MANIFEST_NAME} to {args.raw_dir}")
        else:
            admin_url = os.environ.get("ADMIN_DATABASE_URL")
            if not admin_url:
                print("error: set ADMIN_DATABASE_URL (the database owner)", file=sys.stderr)
                return 2
            counts = load(admin_url, args.raw_dir, replace=args.replace)
            total = sum(sum(c.values()) for c in counts.values())
            print(f"Loaded {sum(map(len, counts.values()))} tables in {len(counts)} schemas, {total:,} rows")
    except (IntegrityError, LoadError, RuntimeError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
