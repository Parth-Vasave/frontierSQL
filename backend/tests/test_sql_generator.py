"""Plan + SQL output of the generator: parsing, the SQL-or-question rule, and the plan check."""

from __future__ import annotations

import json

import pytest

from app.agent.sql_generator import SYSTEM_PROMPT, GeneratedSQL, QueryPlan, check_plan
from app.llm.client import LLMError, parse_output

PLAN = {
    "intent": "ranking",
    "tables": ["public.co2_emissions", "public.countries"],
    "metrics": ["co2_emissions.co2"],
    "filters": ["year = 2023", "entity_type = 'country'"],
    "group_by": [],
    "order_by": "co2 DESC",
    "limit": 5,
    "assumptions": ["'countries' excludes regions and income groups"],
}


def test_reply_with_plan_and_sql_is_parsed() -> None:
    reply = {"plan": PLAN, "sql": "SELECT 1", "clarification_question": None, "explanation": "x"}
    generated = parse_output(json.dumps(reply), GeneratedSQL)
    assert generated.plan is not None and generated.plan.intent == "ranking"
    assert generated.plan.assumptions == ["'countries' excludes regions and income groups"]


def test_reply_without_plan_is_tolerated() -> None:
    assert parse_output('{"sql": "SELECT 1", "explanation": "x"}', GeneratedSQL).plan is None


def test_clarification_reply_is_parsed() -> None:
    reply = {"plan": PLAN, "sql": None, "clarification_question": "Total or per capita?", "explanation": "x"}
    assert parse_output(json.dumps(reply), GeneratedSQL).clarification_question == "Total or per capita?"


@pytest.mark.parametrize(
    "reply",
    [
        {"sql": "SELECT 1", "clarification_question": "Which year?", "explanation": "x"},  # both
        {"plan": {**PLAN, "intent": "delete"}, "sql": "SELECT 1", "explanation": "x"},  # unknown intent
        {"plan": {**PLAN, "filters": ["x" * 301]}, "sql": "SELECT 1", "explanation": "x"},  # oversized
    ],
)
def test_invalid_replies_are_rejected(reply: dict) -> None:
    with pytest.raises(LLMError):
        parse_output(json.dumps(reply), GeneratedSQL)


def test_consistent_plan_has_no_warnings() -> None:
    plan = QueryPlan.model_validate(PLAN)
    assert check_plan(plan, ["public.countries", "public.co2_emissions"], 5) == []


def test_plan_mismatches_are_reported() -> None:
    plan = QueryPlan.model_validate({**PLAN, "tables": ["co2_emissions", "ghg_emissions"], "limit": 10})
    warnings = check_plan(plan, ["public.co2_emissions", "public.countries"], 5)
    assert warnings == [
        "planned tables not used by the SQL: ghg_emissions",
        "SQL uses tables not in the plan: countries",
        "planned limit 10, query limit 5",
    ]


def test_prompt_asks_for_plan_assumptions_and_sparing_clarification() -> None:
    prompt = SYSTEM_PROMPT.format(dialect="postgres", max_rows=100)
    assert '"plan"' in prompt and '"assumptions"' in prompt and '"clarification_question"' in prompt
    assert "reasonable default" in prompt and "LIMIT 100" in prompt


def test_prompt_asks_for_exactly_the_requested_answer() -> None:
    prompt = SYSTEM_PROMPT.format(dialect="postgres", max_rows=100)
    assert "Return only the columns the question asks for" in prompt
    assert "Do not round, cast or reformat" in prompt
    assert "return each entity once" in prompt
    assert "Do not add conditions the question does not state" in prompt


def test_definitions_are_given_before_the_question_and_applied_literally() -> None:
    from app.agent.schema_retriever import SchemaContext
    from app.agent.sql_generator import build_user_prompt

    context = SchemaContext(tables=[], text="TABLE t")
    prompt = build_user_prompt(
        "How many active customers?", context, definitions="active = ordered in 90 days"
    )
    assert prompt.endswith(
        "Definitions given with the question:\nactive = ordered in 90 days\n\n"
        "Question: How many active customers?"
    )
    assert "Definitions" not in build_user_prompt("How many?", context)
    assert "Apply the definitions given with the question literally" in SYSTEM_PROMPT


def test_repair_prompt_contains_the_failure_and_a_hint() -> None:
    from app.agent.schema_retriever import SchemaContext
    from app.agent.sql_generator import FailedAttempt, build_repair_prompt

    failed = FailedAttempt(
        sql="SELECT slow FROM t",
        stage="execution",
        reason="timeout",
        message="canceling statement due to statement timeout",
        plan=QueryPlan.model_validate(PLAN),
    )
    prompt = build_repair_prompt("How much?", SchemaContext(tables=[], text="TABLE t"), failed)
    assert prompt.startswith("Schema:\nTABLE t\n\nQuestion: How much?")
    assert "SELECT slow FROM t" in prompt and "failed (timeout)" in prompt
    assert "cheaper query" in prompt and '"intent":"ranking"' in prompt
    assert "Do not repeat the same SQL" in prompt


def test_validation_failure_is_described_as_a_rejection() -> None:
    from app.agent.schema_retriever import SchemaContext
    from app.agent.sql_generator import FailedAttempt, build_repair_prompt

    failed = FailedAttempt("SELECT * FROM t", "validation", "star", "SELECT * is not allowed")
    prompt = build_repair_prompt("q", SchemaContext(tables=[], text=""), failed)
    assert "rejected by the SQL safety validator (star)" in prompt and "Name the columns" in prompt
    assert "Your previous plan:\n(none)" in prompt
