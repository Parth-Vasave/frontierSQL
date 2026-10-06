"""Orchestrates one question: schema retrieval -> value lookup -> plan + SQL generation ->
validation -> execution -> result checks -> answer and chart.

A repairable failure (validator rejection, database error, or a result check such as a
misspelled filter value) is fed back to the model for a corrected query, at most max_retries
times; every repaired query is validated again. If a repair ends worse than an earlier
executed result, that earlier result is returned.

With candidates > 1 (opt-in: N times the LLM calls), the whole generate-validate-execute-repair
chain runs once per candidate, the first at temperature 0 and the others sampled, and the result
most candidates agree on wins (see _select). Every candidate goes through the same validator,
read-only connection, timeout and row cap; more candidates never mean less checking.

Each step appends a structured TraceEvent (what happened, how long it took, key outputs),
never the model's reasoning.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.agent.answer import (
    ANSWER_PROMPT_VERSION,
    AnswerSource,
    generate_answer,
    template_answer,
    ungrounded_numbers,
)
from app.agent.chart import ChartSpec, choose_chart
from app.agent.executor import QueryExecutionError, QueryResult, execute
from app.agent.result_checks import ResultCheck, _hashable, check_result, is_empty, probe_missing_values
from app.agent.schema_retriever import SchemaContext, build_context, with_tables
from app.agent.sql_generator import (
    MAX_HISTORY_TURNS,
    PROMPT_VERSION,
    REPAIR_PROMPT_VERSION,
    FailedAttempt,
    QueryPlan,
    Turn,
    check_plan,
    generate_sql,
    repair_sql,
)
from app.agent.sql_validator import RejectionCode, SQLRejectedError, validate_sql
from app.agent.units import column_units
from app.agent.value_lookup import find_values, matched_tables
from app.database.adapters import ErrorCategory
from app.database.connections import DatabaseConnection
from app.database.profile import DatabaseProfile, SamplingMode
from app.llm.client import LLMClient, LLMError, LLMOutputError
from app.observability import current_request_id, log_event

logger = logging.getLogger("app.agent")


TraceStatus = Literal["success", "failed", "skipped"]


class TraceEvent(BaseModel):
    step: str
    status: TraceStatus
    duration_ms: int
    detail: dict[str, Any] = {}


class QueryError(BaseModel):
    category: str
    message: str
    code: str | None = None  # finer reason, e.g. the validator's rejection code
    retry_after_seconds: int | None = None  # LLM provider failures: how long the provider asked to wait


class QueryMetadata(BaseModel):
    database_id: str
    dialect: str
    model: str
    prompt_version: str
    tables_used: list[str] = []
    execution_time_ms: int | None = None
    row_count: int | None = None
    truncated: bool = False
    retry_count: int = 0
    request_id: str | None = None  # matches the X-Request-ID header and the log lines


class AgentResult(BaseModel):
    status: Literal["success", "needs_clarification", "unanswerable", "error"]
    question: str
    resolved_question: str | None = None  # a follow-up restated in full by the model
    answer: str | None = None
    answer_source: AnswerSource | None = None
    clarification_question: str | None = None
    explanation: str | None = None
    plan: QueryPlan | None = None
    sql: str | None = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    column_units: dict[str, str] = {}  # result column -> unit, where traced from column comments
    chart_suggestion: str | None = None  # the model's suggestion (a tie-breaker only)
    chart: ChartSpec | None = None  # the chart chosen deterministically from the result (Milestone 9)
    checks: list[ResultCheck] = []  # deterministic result checks (Milestone 7)
    error: QueryError | None = None
    trace: list[TraceEvent] = []
    metadata: QueryMetadata


class _Trace:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.candidate: int | None = None  # set while one of several candidates is being solved

    def record(self, step: str, status: TraceStatus = "success", duration_ms: int = 0, **detail: Any) -> None:
        if self.candidate is not None:
            detail = {"candidate": self.candidate, **detail}
        self.events.append(TraceEvent(step=step, status=status, duration_ms=duration_ms, detail=detail))
        level = logging.WARNING if status == "failed" else logging.INFO
        log_event(logger, "agent step", level, step=step, status=status, duration_ms=duration_ms, **detail)

    @contextmanager
    def timed(self) -> Iterator[list[int]]:
        started = time.perf_counter()
        elapsed = [0]
        try:
            yield elapsed
        finally:
            elapsed[0] = int((time.perf_counter() - started) * 1000)


# Failures worth one more try with the error fed back to the model. Writes, stacked statements
# and permission errors are not: the model's intent was unsafe, and asking again will not fix that.
REPAIRABLE_REJECTIONS = frozenset(RejectionCode) - {
    RejectionCode.NOT_SELECT,
    RejectionCode.FORBIDDEN_OPERATION,
    RejectionCode.MULTIPLE_STATEMENTS,
}
REPAIRABLE_ERRORS = frozenset(
    {
        ErrorCategory.TIMEOUT,
        ErrorCategory.SYNTAX,
        ErrorCategory.UNDEFINED_COLUMN,
        ErrorCategory.UNDEFINED_TABLE,
        ErrorCategory.UNDEFINED_FUNCTION,
        ErrorCategory.TYPE_MISMATCH,
        ErrorCategory.DATA_ERROR,
    }
)


# Sampling temperature of every candidate after the first (which is the temperature-0 answer).
CANDIDATE_TEMPERATURE = 0.7


class AgentController:
    def __init__(
        self,
        llm: LLMClient,
        max_rows: int,
        max_retries: int = 2,
        answer_llm: LLMClient | None = None,
        candidates: int = 1,
    ) -> None:
        """answer_llm writes natural-language answers; without it, answers come from a template.
        candidates > 1 generates several queries and returns the result most of them agree on."""
        if candidates < 1:
            raise ValueError("candidates must be at least 1")
        self.llm = llm
        self.max_rows = max_rows
        self.max_retries = max_retries
        self.answer_llm = answer_llm
        self.candidates = candidates

    def run(
        self,
        question: str,
        connection: DatabaseConnection,
        history: Sequence[Turn] = (),
        definitions: str | None = None,
    ) -> AgentResult:
        """Answer `question`; `history` holds earlier turns of the conversation, oldest first, and
        `definitions` the user's definitions of terms ("active customer = ordered in the last 90
        days"), applied literally. Both are untrusted user input, like the question."""
        history = list(history)[-MAX_HISTORY_TURNS:]
        trace = _Trace()
        trace.record(
            "question_received",
            question_length=len(question),
            history_turns=len(history),
            definitions_length=len(definitions or ""),
        )
        meta = QueryMetadata(
            database_id=connection.config.id,
            dialect=connection.adapter.sqlglot_dialect,
            model=self.llm.model,
            prompt_version=PROMPT_VERSION,
            request_id=current_request_id(),
        )

        with trace.timed() as ms:
            profile = connection.profile()
            # Earlier questions too: "what about China?" alone names no table or metric.
            context = build_context(profile, " ".join([*(t.question for t in history), question]))
        meta.tables_used = context.table_names
        trace.record("schema_retrieval", duration_ms=ms[0], tables=context.table_names)

        # Stored values that match words of the question (sampling full only: it returns data).
        # Tables holding them join the schema shown to the model.
        if connection.config.sampling is SamplingMode.FULL:
            with trace.timed() as ms:
                asked = f"{question}\n{definitions}" if definitions else question
                values = find_values(connection, profile, context.tables, asked, meta.dialect)
                added = matched_tables(values) - set(context.table_names)
                context = with_tables(profile, context, added)
                if section := values.render():
                    context = SchemaContext(tables=context.tables, text=f"{context.text}\n{section}")
            meta.tables_used = context.table_names
            trace.record(
                "value_lookup",
                duration_ms=ms[0],
                phrases=len(values.phrases),
                columns_searched=values.columns_searched,
                matches=sum(map(len, values.matches.values())),  # counts only: phrases are the user's words
                tables_added=sorted(added),
                stopped=values.skipped,
            )

        solved: list[_Solved] = []
        for index in range(self.candidates):
            trace.candidate = index + 1 if self.candidates > 1 else None
            temperature = 0.0 if index == 0 else CANDIDATE_TEMPERATURE
            attempt = self._solve(
                question, connection, profile, context, meta, trace, history, definitions, temperature
            )
            if _provider_failed(attempt.outcome):
                # The first candidate's failure is the answer, as with one candidate. A later one's
                # (e.g. the quota ran out) leaves the decision to the candidates that completed.
                if index == 0:
                    solved.append(attempt)
                break
            solved.append(attempt)
            if _decided(solved, self.candidates - index - 1):
                break
        trace.candidate = None
        chosen = solved[0] if len(solved) == 1 else self._select(solved, trace)
        return self._finish(chosen, question, connection, trace, history)

    def _select(self, solved: list[_Solved], trace: _Trace) -> _Solved:
        """The result most candidates agree on: candidates are grouped by their rows (as a set, as
        execution accuracy compares them) or by declining the same way (clarification,
        unanswerable); errors do not vote. The largest group wins, ties go to the group of the
        earliest candidate, and that group's earliest candidate is returned."""
        with trace.timed() as ms:
            groups: dict[Any, list[int]] = {}
            for index, attempt in enumerate(solved):
                key = _vote_key(attempt.outcome)
                if key is not None:
                    groups.setdefault(key, []).append(index)
            ranked = sorted(groups.values(), key=lambda members: (-len(members), members[0]))
            chosen = ranked[0][0] if ranked else 0
        trace.record(
            "candidate_selection",
            duration_ms=ms[0],
            candidates=len(solved),
            planned=self.candidates,
            statuses=[a.outcome.status for a in solved],
            groups=[[i + 1 for i in members] for members in ranked],
            chosen=chosen + 1,
            agreement=len(ranked[0]) if ranked else 0,
        )
        return solved[chosen]

    def _finish(
        self,
        chosen: _Solved,
        question: str,
        connection: DatabaseConnection,
        trace: _Trace,
        history: Sequence[Turn],
    ) -> AgentResult:
        outcome = chosen.outcome
        outcome.resolved_question = chosen.resolved
        if outcome.status == "success":
            # Numbers the user wrote in earlier turns may appear in the answer; numbers only in
            # the model's restatement may not (it is generated text, not the user's).
            user_text = " ".join([*(t.question for t in history), question])
            self._answer(outcome, connection, trace, user_text)
            with trace.timed() as ms:
                outcome.chart = choose_chart(outcome.columns, outcome.rows, outcome.chart_suggestion)
            trace.record(
                "chart_selection", duration_ms=ms[0], type=outcome.chart.type, reason=outcome.chart.reason
            )
        status: TraceStatus = "failed" if outcome.status == "error" else "success"
        trace.record("completed", status, retries=outcome.metadata.retry_count, **chosen.detail)
        outcome.trace = trace.events
        return outcome

    def _solve(
        self,
        question: str,
        connection: DatabaseConnection,
        profile: DatabaseProfile,
        context: SchemaContext,
        base_meta: QueryMetadata,
        trace: _Trace,
        history: Sequence[Turn],
        definitions: str | None,
        temperature: float,
    ) -> _Solved:
        """One candidate: generate, validate, execute and check, repairing up to max_retries times."""
        meta = base_meta.model_copy(deep=True)
        # The most recent executed result. A repair that ends worse (an error, or no SQL at all)
        # must not throw away a result that ran: it is returned instead, with its checks.
        best: AgentResult | None = None
        resolved: str | None = None  # the model's restatement of a follow-up question

        def done(outcome: AgentResult, **detail: Any) -> _Solved:
            if outcome.status != "success" and best is not None:
                outcome = best
                detail = {"reason": "a repair attempt did not improve on an earlier result; returning it"}
                outcome.metadata.retry_count = meta.retry_count
            return _Solved(outcome, detail, resolved)

        failed: FailedAttempt | None = None
        for attempt in range(1, self.max_retries + 2):
            meta.retry_count = attempt - 1
            step = "sql_generation" if failed is None else "sql_repair"
            try:
                with trace.timed() as ms:
                    if failed is None:
                        generated, call = generate_sql(
                            self.llm,
                            question,
                            context,
                            meta.dialect,
                            self.max_rows,
                            history,
                            definitions,
                            temperature,
                        )
                    else:
                        generated, call = repair_sql(
                            self.llm,
                            question,
                            context,
                            meta.dialect,
                            self.max_rows,
                            failed,
                            history,
                            definitions,
                            temperature,
                        )
            except LLMOutputError as exc:
                # The provider replied, but the reply was not usable structured output. That is a
                # repairable model-output failure: retry within the same budget, feeding back only
                # the sanitized description (never the raw reply, which may hold injected text).
                trace.record(step, "failed", ms[0], attempt=attempt, error=str(exc))
                if attempt > self.max_retries:
                    return done(self._error(question, meta, "llm_output", str(exc)))
                failed = FailedAttempt("", "generation", "invalid_model_output", str(exc), None)
                continue
            except LLMError as exc:
                # A genuine provider failure (network, auth, rate limit): fail fast, no retry.
                trace.record(step, "failed", ms[0], attempt=attempt, error=str(exc), code=exc.code)
                return done(
                    self._error(question, meta, "llm_error", str(exc), exc.code, exc.retry_after_seconds)
                )
            trace.record(
                step,
                duration_ms=ms[0],
                attempt=attempt,
                model=call.model,
                prompt_version=PROMPT_VERSION if failed is None else REPAIR_PROMPT_VERSION,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                provider_attempts=call.attempts,
                intent=generated.plan.intent if generated.plan else None,
            )
            plan = generated.plan
            if history and generated.resolved_question:
                resolved = generated.resolved_question.strip() or None

            if generated.clarification_question is not None:
                outcome = AgentResult(
                    status="needs_clarification",
                    question=question,
                    clarification_question=generated.clarification_question,
                    explanation=generated.explanation,
                    plan=plan,
                    metadata=meta,
                )
                return done(outcome, reason="question is ambiguous; clarification requested")
            if generated.sql is None:
                outcome = AgentResult(
                    status="unanswerable",
                    question=question,
                    answer=generated.explanation,
                    explanation=generated.explanation,
                    plan=plan,
                    metadata=meta,
                )
                return done(outcome, reason="question cannot be answered from this database")
            if failed is not None and failed.stage != "generation" and _same_sql(generated.sql, failed.sql):
                trace.record(step, "failed", 0, attempt=attempt, error="repair returned the same SQL")
                return done(self._failed(question, meta, failed))

            # Never trust generated SQL: only a validated, rewritten query reaches the database.
            try:
                with trace.timed() as ms:
                    validated = validate_sql(generated.sql, profile, meta.dialect, self.max_rows)
            except SQLRejectedError as exc:
                trace.record(
                    "sql_validation", "failed", ms[0], attempt=attempt, code=exc.code, error=exc.message
                )
                failed = FailedAttempt(generated.sql, "validation", exc.code, exc.message, plan)
                if exc.code not in REPAIRABLE_REJECTIONS or attempt > self.max_retries:
                    return done(self._failed(question, meta, failed, generated.explanation))
                continue
            meta.tables_used = validated.tables
            trace.record(
                "sql_validation",
                duration_ms=ms[0],
                attempt=attempt,
                tables=validated.tables,
                limit=validated.limit,
                limit_action=validated.limit_action,
                plan_warnings=(
                    check_plan(plan, validated.tables, validated.limit) if plan else ["no plan returned"]
                ),
            )

            try:
                result: QueryResult = execute(connection, validated.sql, self.max_rows)
            except QueryExecutionError as exc:
                trace.record(
                    "query_execution",
                    "failed",
                    exc.duration_ms,
                    attempt=attempt,
                    category=exc.category,
                    error=exc.message,
                )
                failed = FailedAttempt(validated.sql, "execution", exc.category, exc.message, plan)
                if exc.category not in REPAIRABLE_ERRORS or attempt > self.max_retries:
                    return done(self._failed(question, meta, failed, generated.explanation))
                continue

            meta.execution_time_ms, meta.row_count, meta.truncated = (
                result.duration_ms,
                result.row_count,
                result.truncated,
            )
            trace.record(
                "query_execution",
                duration_ms=result.duration_ms,
                attempt=attempt,
                rows=result.row_count,
                truncated=result.truncated,
            )

            with trace.timed() as ms:
                checks = check_result(
                    result, validated.sql, meta.dialect, validated.limit, validated.limit_action
                )
                if is_empty(result):
                    checks += probe_missing_values(connection, profile, validated.sql, meta.dialect)
            repairable = [c for c in checks if c.repairable]
            trace.record(
                "result_validation",
                "failed" if repairable else "success",
                ms[0],
                attempt=attempt,
                checks=[c.code for c in checks],
            )
            best = AgentResult(
                status="success",
                question=question,
                explanation=generated.explanation,
                plan=plan,
                sql=validated.sql,
                columns=result.columns,
                rows=result.rows,
                column_units=_units_by_column(
                    result.columns, column_units(validated.sql, profile, meta.dialect)
                ),
                chart_suggestion=generated.chart_suggestion,
                checks=checks,
                metadata=meta.model_copy(deep=True),
            )
            if repairable and attempt <= self.max_retries:
                message = " ".join(c.message for c in repairable)
                failed = FailedAttempt(validated.sql, "result", repairable[0].code, message, plan)
                continue
            return done(best)
        raise AssertionError("unreachable: the last attempt always returns")

    def _answer(
        self, outcome: AgentResult, connection: DatabaseConnection, trace: _Trace, user_text: str
    ) -> None:
        """Set outcome.answer: from the LLM when allowed and grounded, otherwise from the template.

        `user_text` is everything the user wrote (this question and earlier ones): numbers in it
        count as grounded."""
        fallback = template_answer(outcome.columns, outcome.rows, outcome.checks, outcome.column_units)
        if self.answer_llm is None:
            reason = "answers from the LLM are disabled"
        elif connection.config.sampling is SamplingMode.OFF:
            reason = "this database does not allow data to be sent to the LLM (sampling off)"
        else:
            try:
                with trace.timed() as ms:
                    generated, call = generate_answer(
                        self.answer_llm,
                        outcome.resolved_question or outcome.question,
                        outcome.columns,
                        outcome.rows,
                        outcome.plan,
                        outcome.checks,
                        outcome.column_units,
                    )
            except LLMError as exc:
                trace.record("answer_generation", "failed", ms[0], error=str(exc), fallback="template")
                outcome.answer, outcome.answer_source = fallback, "template"
                return
            ungrounded = ungrounded_numbers(generated.answer, user_text, outcome.rows, outcome.plan)
            detail: dict[str, Any] = {
                "model": call.model,
                "prompt_version": ANSWER_PROMPT_VERSION,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "provider_attempts": call.attempts,
            }
            if not ungrounded:
                trace.record("answer_generation", duration_ms=ms[0], source="llm", **detail)
                outcome.answer, outcome.answer_source = generated.answer, "llm"
                return
            # A number the rows do not contain is a hallucination risk: never show it.
            trace.record(
                "answer_generation",
                "failed",
                ms[0],
                source="template",
                ungrounded_numbers=ungrounded[:10],
                **detail,
            )
            outcome.answer, outcome.answer_source = fallback, "template"
            return
        trace.record("answer_generation", "skipped", 0, source="template", reason=reason)
        outcome.answer, outcome.answer_source = fallback, "template"

    def _failed(
        self,
        question: str,
        meta: QueryMetadata,
        failed: FailedAttempt,
        explanation: str | None = None,
    ) -> AgentResult:
        if failed.stage == "validation":
            result = self._error(question, meta, "validation", failed.message, code=failed.reason)
        else:
            result = self._error(question, meta, failed.reason, failed.message)
        result.sql, result.explanation, result.plan = failed.sql, explanation, failed.plan
        return result

    @staticmethod
    def _error(
        question: str,
        meta: QueryMetadata,
        category: str,
        message: str,
        code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> AgentResult:
        return AgentResult(
            status="error",
            question=question,
            error=QueryError(
                category=str(category), message=message, code=code, retry_after_seconds=retry_after_seconds
            ),
            metadata=meta,
        )


def _same_sql(a: str, b: str) -> bool:
    return " ".join(a.split()).rstrip(";").lower() == " ".join(b.split()).rstrip(";").lower()


def _units_by_column(columns: list[str], units: list[str | None]) -> dict[str, str]:
    if len(units) != len(columns):
        return {}  # the query could not be traced column by column
    return {column: unit for column, unit in zip(columns, units, strict=True) if unit is not None}


@dataclass(frozen=True)
class _Solved:
    """One candidate's outcome, the detail for its "completed" event, and its restated question."""

    outcome: AgentResult
    detail: dict[str, Any]
    resolved: str | None


def _provider_failed(outcome: AgentResult) -> bool:
    return outcome.error is not None and outcome.error.category == "llm_error"


def _vote_key(outcome: AgentResult) -> Any:
    """What a candidate's outcome is compared by: its rows as a set (row order and duplicates
    ignored, like execution accuracy), or the way it declined. None for errors (no vote)."""
    if outcome.status == "success":
        return ("rows", frozenset(tuple(_hashable(v) for v in row) for row in outcome.rows))
    if outcome.status in ("needs_clarification", "unanswerable"):
        return (outcome.status,)
    return None


def _decided(solved: list[_Solved], remaining: int) -> bool:
    """True when the candidates still to come cannot change which group is largest."""
    sizes = sorted(
        Counter(k for a in solved if (k := _vote_key(a.outcome)) is not None).values(), reverse=True
    )
    if not sizes:
        return remaining == 0
    runner_up = sizes[1] if len(sizes) > 1 else 0
    return sizes[0] > runner_up + remaining
