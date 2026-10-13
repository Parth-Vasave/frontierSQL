from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.rate_limit import RateLimiter
from app.api.routes import router
from app.config import get_settings
from app.database.connections import build_registry
from app.llm.client import OpenAICompatibleClient
from app.observability import REQUEST_ID_HEADER, configure_logging
from app.observability import install as install_observability


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    registry = build_registry(
        timeout_seconds=settings.query_timeout_seconds,
        profile_budget_seconds=settings.profile_time_budget_seconds,
        config_path=settings.databases_config,
        default_url=settings.database_url,
        environ=dict(os.environ),
    )
    app.state.registry = registry
    app.state.llm = (
        OpenAICompatibleClient(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            max_output_tokens=settings.llm_max_output_tokens,
            reasoning_effort=settings.llm_reasoning_effort,
            requests_per_minute=settings.llm_requests_per_minute,
        )
        if settings.llm_api_key and settings.llm_api_key.get_secret_value()
        else None
    )
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)
    yield
    for connection in registry.all():
        connection.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="FrontierSQL", version="0.1.0", lifespan=lifespan)
    install_observability(app)  # request IDs + request logs; added before CORS so CORS wraps it
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.include_router(router)
    return app


app = create_app()
