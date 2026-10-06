"""LLM access behind one small interface.

OpenAICompatibleClient talks to any OpenAI-compatible chat-completions endpoint (Gemini,
Groq, OpenRouter, Ollama, ...). Every reply must be a JSON object that validates against
the Pydantic model the caller asks for: model output is never used unvalidated.

Transient provider failures (rate limits, overload) are retried a bounded number of times
with a short wait, so a free-tier hiccup does not fail the whole question. A failure that waiting
will not fix (a daily or account quota used up) is not retried, and is reported as such: LLMError.code says
what kind of failure it was, and retry_after_seconds when the provider said how long to wait.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.observability import log_event

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("app.llm")

# Rate limited, or the provider is overloaded / briefly unavailable.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
# A quota for the whole day (or the account) is used up: retrying within minutes cannot help.
# Groq says "tokens per day (TPD)", Gemini "...PerDay..." quota ids, OpenAI "insufficient_quota".
_EXHAUSTED_QUOTA = re.compile(r"per ?day|\([tr]pd\)|daily|insufficient_quota", re.IGNORECASE)
# How long the provider asks us to wait, when it says so in the body ("try again in 7m12.5s",
# Gemini's "retryDelay": "41s") rather than in a Retry-After header.
_TRY_AGAIN_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?", re.IGNORECASE)
_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')
# Provider error codes are reported only when they look like an identifier ("rate_limit_exceeded").
_PROVIDER_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,39}")
MAX_RETRY_AFTER_SECONDS = 2 * 24 * 3600


class LLMError(RuntimeError):
    """The LLM call failed. Unusable output is the LLMOutputError subclass.

    `code` classifies a provider failure: "quota_exhausted" (a daily or account quota; waiting
    minutes will not help),
    "rate_limit", "unavailable" (5xx), "auth" (401/403), "http_<status>" or "network".
    """

    def __init__(self, message: str, code: str | None = None, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class LLMOutputError(LLMError):
    """The provider replied, but the reply is not the structured output we asked for.

    This is a model-output failure, not a provider failure: it is worth one more try with a
    short description of what was wrong. Its message is derived only from safe metadata (the
    error type and the field names the expected model declares); the raw reply is never quoted,
    because it is untrusted text.
    """


@dataclass(frozen=True)
class LLMCall:
    """Metadata of one call, recorded for reproducibility (never the API key)."""

    model: str
    duration_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1


class LLMClient(Protocol):
    model: str

    def complete_json(
        self, system: str, user: str, output: type[T], temperature: float = 0.0
    ) -> tuple[T, LLMCall]: ...


def _describe_validation_error(exc: ValidationError, output: type[BaseModel]) -> str:
    """A safe summary of a schema mismatch, built only from trusted information.

    The reply is untrusted, so only field names declared by `output` and pydantic's own error
    types are reported; the model's keys, values and messages are never included.
    """
    fields = set(output.model_fields)
    problems = []
    for error in exc.errors()[:10]:
        location = [part for part in error.get("loc", ()) if isinstance(part, str) and part in fields]
        problems.append(f"{'.'.join(location) or 'reply'} ({error.get('type', 'invalid')})")
    return ", ".join(problems)


def parse_output(content: object, output: type[T]) -> T:
    # Providers can answer 200 with no text at all (a refusal, a tool call): unusable output too.
    if not isinstance(content, str) or not content.strip():
        raise LLMOutputError(f"Model reply was empty; expected a {output.__name__} object")
    text = content.strip()
    if text.startswith("```"):  # some models wrap JSON in a Markdown fence despite instructions
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise LLMOutputError(f"Model reply was not valid JSON; expected a {output.__name__} object") from None
    try:
        return output.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputError(
            f"Model reply is not a valid {output.__name__}: {_describe_validation_error(exc, output)}"
        ) from None


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        max_wait_seconds: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.max_attempts = max_attempts
        self.max_wait_seconds = max_wait_seconds
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def complete_json(
        self, system: str, user: str, output: type[T], temperature: float = 0.0
    ) -> tuple[T, LLMCall]:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        started = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.post("chat/completions", json=payload)
            except httpx.HTTPError as exc:
                raise LLMError(f"LLM request failed: {exc.__class__.__name__}", code="network") from None
            if response.status_code not in TRANSIENT_STATUS or attempt >= self.max_attempts:
                break
            if _quota_exhausted(response):
                break  # retrying a used-up daily quota only burns time
            wait = self._retry_wait(response, attempt)
            if wait > self.max_wait_seconds:
                break  # e.g. a per-minute quota: waiting that long inside a request is worse than failing
            self._sleep(wait)
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            logger,
            "llm call",
            logging.INFO if response.status_code == 200 else logging.WARNING,
            model=self.model,
            http_status=response.status_code,
            attempts=attempt,
            duration_ms=duration_ms,
        )
        if response.status_code != 200:
            raise _provider_error(response, attempt)
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("LLM provider returned an unexpected response shape") from None
        usage = body.get("usage") or {}
        call = LLMCall(
            self.model, duration_ms, usage.get("prompt_tokens"), usage.get("completion_tokens"), attempt
        )
        return parse_output(content, output), call

    @staticmethod
    def _retry_wait(response: httpx.Response, attempt: int) -> float:
        """Seconds to wait: the provider's Retry-After if given, else 1s, 2s, 4s, ..."""
        try:
            return max(0.0, float(response.headers.get("retry-after", "")))
        except ValueError:
            return float(2 ** (attempt - 1))


def _quota_exhausted(response: httpx.Response) -> bool:
    return response.status_code == 429 and bool(_EXHAUSTED_QUOTA.search(response.text))


def _retry_after(response: httpx.Response) -> int | None:
    """Seconds the provider asked us to wait (header, then body), or None if it did not say."""
    seconds: float | None = None
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        if match := _TRY_AGAIN_IN.search(response.text):
            hours, minutes, secs = (float(g) if g else 0.0 for g in match.groups())
            seconds = hours * 3600 + minutes * 60 + secs if any(match.groups()) else None
        elif match := _RETRY_DELAY.search(response.text):
            seconds = float(match.group(1))
    if seconds is None or not 0 <= seconds <= MAX_RETRY_AFTER_SECONDS:
        return None
    return int(-(-seconds // 1))  # whole seconds, rounded up


def _provider_code(response: httpx.Response) -> str | None:
    """The provider's own error code or type ("rate_limit_exceeded", "RESOURCE_EXHAUSTED")."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = (body[0] if isinstance(body, list) and body else body) or {}
    error = error.get("error") if isinstance(error, dict) else None
    if not isinstance(error, dict):
        return None
    for key in ("code", "type", "status"):
        value = error.get(key)
        if isinstance(value, str) and _PROVIDER_CODE.fullmatch(value):
            return value
    return None


def _provider_error(response: httpx.Response, attempts: int) -> LLMError:
    """An LLMError built from safe metadata only: the body can echo request details (and
    account ids), so it is never quoted; only a classification and an identifier-like code."""
    status = response.status_code
    if _quota_exhausted(response):
        code = "quota_exhausted"
    elif status == 429:
        code = "rate_limit"
    elif status >= 500:
        code = "unavailable"
    elif status in (401, 403):
        code = "auth"
    else:
        code = f"http_{status}"
    retry_after = _retry_after(response) if status == 429 or status >= 500 else None
    notes = [n for n in (_provider_code(response),) if n]
    if code == "quota_exhausted":
        notes.append("quota used up")
    if retry_after is not None:
        notes.append(f"retry in {retry_after} s")
    tries = f" after {attempts} attempts" if attempts > 1 else ""
    details = f" ({'; '.join(notes)})" if notes else ""
    return LLMError(f"LLM provider returned HTTP {status}{tries}{details}", code, retry_after)


class ScriptedLLMClient:
    """Deterministic stand-in for tests and offline development.

    `script` receives (system, user) and returns the raw text the model would have replied.
    """

    def __init__(self, script: Callable[[str, str], str], model: str = "scripted") -> None:
        self.model = model
        self.script = script
        self.calls: list[tuple[str, str]] = []
        self.temperatures: list[float] = []

    def complete_json(
        self, system: str, user: str, output: type[T], temperature: float = 0.0
    ) -> tuple[T, LLMCall]:
        self.calls.append((system, user))
        self.temperatures.append(temperature)
        return parse_output(self.script(system, user), output), LLMCall(self.model, 0)
