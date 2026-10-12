"""Application settings, loaded from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Databases the analyst can query: a TOML file of [[databases]] entries, or a single
    # DATABASE_URL. Always read-only accounts; accounts that can modify data are refused.
    databases_config: Path | None = None
    database_url: SecretStr | None = None
    # Lets users add databases through the UI/API. Local or self-hosted use only: never
    # enable on a public deployment (it lets anyone make the server connect anywhere).
    allow_ui_connections: bool = False
    profile_time_budget_seconds: float = Field(default=30, gt=0, le=300)

    query_timeout_seconds: float = Field(default=5, gt=0, le=60)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_rows: int = Field(default=1000, ge=1, le=10_000)
    # "llm": natural-language answers written by the LLM (one extra call per question) and checked
    # against the rows; "template": answers built from the rows without the LLM.
    answer_mode: Literal["llm", "template"] = "llm"
    # Candidate queries per question: above 1, the result most candidates agree on wins (about
    # 2-3x the LLM calls and tokens of one candidate). See app/agent/controller.py.
    sql_candidates: int = Field(default=1, ge=1, le=5)

    # Any OpenAI-compatible chat-completions endpoint (Groq, Gemini, OpenRouter, Ollama, ...).
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gemini-3.8-flash"
    # Cap on each reply, reasoning included. Unset: the provider's default. Set it where the
    # provider reserves the cap against its rate limits before running a request (Cerebras).
    llm_max_output_tokens: int | None = Field(default=None, ge=256, le=65_536)
    # For reasoning models (gpt-oss: low, medium, high). Unset: the provider's default.
    llm_reasoning_effort: Literal["low", "medium", "high"] | None = None
    # Spaces LLM calls out to stay under a small per-minute request limit (a trial tier).
    # Unset: calls are not spaced (the provider's 429s are still retried or reported).
    llm_requests_per_minute: int | None = Field(default=None, ge=1, le=10_000)

    # Limits on POST /api/query, the endpoint that spends LLM quota (see app/api/rate_limit.py).
    # 0 turns a limit off. Per process: several workers or instances each enforce their own.
    rate_limit_per_minute: int = Field(default=10, ge=0, le=10_000)  # per client address
    rate_limit_per_day: int = Field(default=200, ge=0, le=1_000_000)  # all clients together
    # Reverse proxies in front of the app that append the client address to X-Forwarded-For
    # (1 behind a single load balancer). 0: rate-limit by the TCP peer and ignore the header,
    # which any client can set.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
