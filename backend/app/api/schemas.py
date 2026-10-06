from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from app.agent.sql_generator import MAX_HISTORY_TURNS, Turn
from app.database.connections import ConnectionStatus, DatabaseConnection
from app.database.profile import SamplingMode


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    databases: dict[str, ConnectionStatus]


class DatabaseInfo(BaseModel):
    """Public view of a connection. Never includes the URL or credentials."""

    id: str
    name: str
    dialect: str
    source: Literal["config", "ui"]
    sampling: SamplingMode
    status: ConnectionStatus
    issues: list[str]
    allowed_columns: list[str]  # sensitive-looking columns the owner allowed (allow_columns)

    @classmethod
    def from_connection(cls, connection: DatabaseConnection) -> DatabaseInfo:
        return cls(
            id=connection.config.id,
            name=connection.config.name,
            dialect=connection.adapter.backend,
            source=connection.config.source,
            sampling=connection.config.sampling,
            status=connection.status,
            issues=connection.issues,
            allowed_columns=connection.config.allow_columns,
        )


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    database_id: str | None = None  # defaults to the first ready database
    # Earlier turns of the conversation, oldest first, for follow-up questions ("what about
    # China?"). The client keeps the conversation; the server stores nothing between requests.
    history: list[Turn] = Field(default=[], max_length=MAX_HISTORY_TURNS)
    # The user's definitions of terms used in the question ("active customer = ordered in the
    # last 90 days"), applied literally. Untrusted user input, like the question.
    definitions: str | None = Field(default=None, max_length=2000)


class AddDatabaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: SecretStr
    sampling: SamplingMode = SamplingMode.SAFE
    schemas: list[str] | None = None
