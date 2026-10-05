from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.agent.controller import AgentController, AgentResult
from app.api.rate_limit import RateLimiter, client_address
from app.api.schemas import AddDatabaseRequest, DatabaseInfo, HealthResponse, QueryRequest
from app.config import Settings, get_settings
from app.database.connections import (
    ConnectionConfig,
    ConnectionRegistry,
    ConnectionStatus,
    DatabaseConnection,
    DatabaseNotReadyError,
    UnsupportedDatabaseError,
)
from app.database.profile import DatabaseProfile
from app.observability import log_event

router = APIRouter(prefix="/api")
logger = logging.getLogger("app.api")


def get_registry(request: Request) -> ConnectionRegistry:
    return request.app.state.registry


Registry = Annotated[ConnectionRegistry, Depends(get_registry)]


def _get_connection(registry: ConnectionRegistry, database_id: str) -> DatabaseConnection:
    try:
        return registry.get(database_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown database {database_id!r}") from None


def get_agent(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> AgentController:
    llm = request.app.state.llm
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No LLM configured: set LLM_API_KEY.")
    return AgentController(
        llm,
        max_rows=settings.max_rows,
        max_retries=settings.max_retries,
        answer_llm=llm if settings.answer_mode == "llm" else None,
    )


def rate_limit(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    decision = limiter.hit(client_address(request, settings.trusted_proxy_hops))
    if decision.allowed:
        return
    # The client address is not logged: the scope and wait are enough to see limits being hit.
    log_event(
        logger,
        "rate limited",
        logging.WARNING,
        scope=decision.scope,
        retry_after_seconds=decision.retry_after_seconds,
    )
    message = (
        "Too many questions from this client."
        if decision.scope == "client"
        else "The service's question budget is used up for now."
    )
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"{message} Try again in {decision.retry_after_seconds} s.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


# Rate limiting runs first, so a limited request never reaches the LLM.
@router.post("/query", response_model=AgentResult, dependencies=[Depends(rate_limit)])
def query(
    body: QueryRequest, registry: Registry, agent: Annotated[AgentController, Depends(get_agent)]
) -> AgentResult:
    if body.database_id is not None:
        connection = _get_connection(registry, body.database_id)
    else:
        ready = [
            c
            for c in registry.all()
            if c.status is ConnectionStatus.READY or c.verify() is ConnectionStatus.READY
        ]
        if not ready:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No database is ready.")
        connection = ready[0]
    try:
        definitions = (body.definitions or "").strip() or None
        return agent.run(body.question.strip(), connection, body.history, definitions)
    except DatabaseNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("/health", response_model=HealthResponse)
def health(response: Response, registry: Registry) -> HealthResponse:
    statuses = {}
    for connection in registry.all():
        statuses[connection.config.id] = (
            connection.verify() if connection.status is not ConnectionStatus.READY else connection.status
        )
    healthy = bool(statuses) and all(s is ConnectionStatus.READY for s in statuses.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if healthy else "degraded", databases=statuses)


@router.get("/databases", response_model=list[DatabaseInfo])
def list_databases(registry: Registry) -> list[DatabaseInfo]:
    for connection in registry.all():
        if connection.status is ConnectionStatus.UNAVAILABLE:  # never checked yet, or down: try now
            connection.verify()
    return [DatabaseInfo.from_connection(c) for c in registry.all()]


@router.get("/databases/{database_id}/profile", response_model=DatabaseProfile)
def database_profile(database_id: str, registry: Registry, refresh: bool = False) -> DatabaseProfile:
    connection = _get_connection(registry, database_id)
    try:
        return connection.profile(refresh=refresh)
    except DatabaseNotReadyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post("/databases", response_model=DatabaseInfo, status_code=status.HTTP_201_CREATED)
def add_database(
    body: AddDatabaseRequest, registry: Registry, settings: Annotated[Settings, Depends(get_settings)]
) -> DatabaseInfo:
    if not settings.allow_ui_connections:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Adding databases from the UI is disabled. Set ALLOW_UI_CONNECTIONS=true (local use only).",
        )
    config = ConnectionConfig(
        id=registry.new_id(body.name),
        name=body.name,
        url=body.url,
        source="ui",
        sampling=body.sampling,
        schemas=body.schemas,
    )
    try:
        connection = registry.add(config)
    except (UnsupportedDatabaseError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    info = DatabaseInfo.from_connection(connection)
    if connection.status is not ConnectionStatus.READY:
        registry.remove(config.id)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": f"Database not added: it is {connection.status.value}.", "issues": info.issues},
        )
    return info
