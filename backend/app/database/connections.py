"""Registry of the databases the analyst can query.

Databases come from a TOML config file (DATABASES_CONFIG), from DATABASE_URL as a single
default, or, only when ALLOW_UI_CONNECTIONS is enabled, from the API at runtime.
Every connection is verified before use: an account that can modify data is refused.
Connection URLs are secrets: they are never returned by the API or written to logs.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.database.adapters import DatabaseAdapter, PrivilegeReport, UnsupportedDatabaseError, get_adapter
from app.database.profile import DatabaseProfile, SamplingMode
from app.database.profiler import Profiler, fingerprint

logger = logging.getLogger(__name__)

_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,47}$"


class ConnectionStatus(StrEnum):
    READY = "ready"
    REJECTED = "rejected"  # reachable, but the account is not read-only
    UNAVAILABLE = "unavailable"  # could not connect (retried on next use)


class DatabaseNotReadyError(RuntimeError):
    pass


class ConnectionConfig(BaseModel):
    id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    url: SecretStr
    source: Literal["config", "ui"] = "config"
    sampling: SamplingMode = SamplingMode.SAFE
    schemas: list[str] | None = None
    # Columns whose names look sensitive (dob, email, ...) but which the owner allows the agent to
    # use: "schema.table.column" or "table.column". Listed in the database's public status.
    allow_columns: list[str] = []

    @field_validator("allow_columns")
    @classmethod
    def _qualified_names(cls, entries: list[str]) -> list[str]:
        for entry in entries:
            parts = entry.split(".")
            if len(parts) not in (2, 3) or not all(parts):
                raise ValueError(f"allow_columns entry {entry!r}: use table.column or schema.table.column")
        return entries


def _normalize_scheme(url: str) -> str:
    # Many hosts (Heroku, Neon, Supabase) hand out postgres:// URLs.
    return re.sub(r"^postgres://", "postgresql://", url.strip())


class DatabaseConnection:
    def __init__(
        self, config: ConnectionConfig, timeout_seconds: float, profile_budget_seconds: float
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.profile_budget_seconds = profile_budget_seconds
        try:
            url = make_url(_normalize_scheme(config.url.get_secret_value()))
        except ArgumentError:
            raise ValueError("Invalid database URL") from None
        self.adapter: DatabaseAdapter = get_adapter(url.get_backend_name())
        self.engine: Engine = create_engine(
            self.adapter.normalize_url(url),
            poolclass=NullPool,  # short-lived connections suit serverless hosting
            connect_args=self.adapter.connect_args(timeout_seconds),
        )
        self.status = ConnectionStatus.UNAVAILABLE
        self.privileges: PrivilegeReport | None = None
        self.error: str | None = None
        self._profile: DatabaseProfile | None = None
        self._lock = threading.Lock()

    @property
    def issues(self) -> list[str]:
        if self.error:
            return [self.error]
        if self.privileges:
            return [*self.privileges.blocking, *self.privileges.warnings]
        return []

    def verify(self) -> ConnectionStatus:
        try:
            with self.engine.connect() as conn:
                self.privileges = self.adapter.check_privileges(conn)
        except SQLAlchemyError as exc:
            # Driver messages can contain host and user names; keep them in server logs only.
            logger.warning("database %s unavailable: %s", self.config.id, exc.__class__.__name__)
            self.status, self.error = ConnectionStatus.UNAVAILABLE, "Could not connect to the database."
            return self.status
        self.error = None
        if self.privileges.is_read_only:
            self.status = ConnectionStatus.READY
        else:
            self.status = ConnectionStatus.REJECTED
            logger.warning("database %s rejected: account is not read-only", self.config.id)
        return self.status

    def ensure_ready(self) -> None:
        if self.status is ConnectionStatus.UNAVAILABLE:
            self.verify()
        if self.status is not ConnectionStatus.READY:
            raise DatabaseNotReadyError(f"Database {self.config.id!r} is {self.status.value}.")

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        self.ensure_ready()
        with self.engine.connect() as conn:
            yield conn

    def profile(self, refresh: bool = False) -> DatabaseProfile:
        """Return the cached profile, rebuilding it when asked or when the schema changed."""
        with self._lock, self.connect() as conn:
            profiler = Profiler(
                self.adapter,
                self.config.sampling,
                self.config.schemas,
                self.profile_budget_seconds,
                self.config.allow_columns,
            )
            if self._profile is not None and not refresh:
                tables, declared, _ = profiler.reflect(conn)  # cheap: structure only
                if fingerprint(tables, declared) == self._profile.fingerprint:
                    return self._profile
            self._profile = profiler.profile(conn, self.config.id)
            return self._profile

    def dispose(self) -> None:
        self.engine.dispose()


class ConnectionRegistry:
    def __init__(self, timeout_seconds: float, profile_budget_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.profile_budget_seconds = profile_budget_seconds
        self._connections: dict[str, DatabaseConnection] = {}
        self._lock = threading.Lock()

    def add(self, config: ConnectionConfig, verify: bool = True) -> DatabaseConnection:
        connection = DatabaseConnection(config, self.timeout_seconds, self.profile_budget_seconds)
        with self._lock:
            if config.id in self._connections:
                raise ValueError(f"Database id {config.id!r} already exists")
            self._connections[config.id] = connection
        if verify:
            connection.verify()
        return connection

    def remove(self, database_id: str) -> None:
        with self._lock:
            connection = self._connections.pop(database_id)
        connection.dispose()

    def get(self, database_id: str) -> DatabaseConnection:
        try:
            return self._connections[database_id]
        except KeyError:
            raise KeyError(f"Unknown database {database_id!r}") from None

    def all(self) -> list[DatabaseConnection]:
        return list(self._connections.values())

    def new_id(self, name: str) -> str:
        stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "db"
        return f"{stem}-{secrets.token_hex(3)}"

    def load_config_file(self, path: Path, environ: dict[str, str]) -> None:
        """Load [[databases]] entries. URLs are read from env vars named by url_env, never from the file."""
        data = tomllib.loads(path.read_text())
        for entry in data.get("databases", []):
            entry = dict(entry)
            env_name = entry.pop("url_env", None)
            if "url" in entry:
                raise ValueError(
                    f"{path}: put connection URLs in environment variables (url_env), not in the file"
                )
            if not env_name or not environ.get(env_name):
                raise ValueError(
                    f"{path}: database {entry.get('id')!r} needs url_env pointing to a set variable"
                )
            try:
                config = ConnectionConfig(url=SecretStr(environ[env_name]), source="config", **entry)
            except ValidationError as exc:
                raise ValueError(f"{path}: invalid database entry {entry.get('id')!r}: {exc}") from None
            self.add(config, verify=False)


def build_registry(
    *,
    timeout_seconds: float,
    profile_budget_seconds: float,
    config_path: Path | None,
    default_url: SecretStr | None,
    environ: dict[str, str],
) -> ConnectionRegistry:
    registry = ConnectionRegistry(timeout_seconds, profile_budget_seconds)
    if config_path is not None:
        registry.load_config_file(config_path, environ)
    elif default_url is not None:
        registry.add(ConnectionConfig(id="default", name="Default database", url=default_url), verify=False)
    return registry


__all__ = [
    "ConnectionConfig",
    "ConnectionRegistry",
    "ConnectionStatus",
    "DatabaseConnection",
    "DatabaseNotReadyError",
    "UnsupportedDatabaseError",
    "build_registry",
]
