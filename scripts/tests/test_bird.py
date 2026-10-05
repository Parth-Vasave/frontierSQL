"""Tests for scripts/bird.py that need neither the download nor a database."""

from __future__ import annotations

import pytest

from scripts.bird import LoadError, table_schemas, without_owners

DUMP = [
    "CREATE TABLE public.account (\n",
    "    account_id bigint NOT NULL\n",
    ");\n",
    "ALTER TABLE public.account OWNER TO xiaolongli;\n",
    "ALTER SEQUENCE public.cards_id_seq OWNER TO xiaolongli;\n",
    "COPY public.posts (id, body) FROM stdin;\n",
    "1\tALTER TABLE public.x OWNER TO someone;\n",  # data that looks like a statement
    "\\.\n",
    "ALTER TABLE ONLY public.account ADD CONSTRAINT account_pkey PRIMARY KEY (account_id);\n",
]


def test_owner_statements_are_dropped_but_copy_data_is_untouched() -> None:
    assert list(without_owners(DUMP)) == [DUMP[0], DUMP[1], DUMP[2], DUMP[5], DUMP[6], DUMP[7], DUMP[8]]


def test_tables_map_to_their_bird_database_in_lower_case() -> None:
    dev_tables = [
        {"db_id": "formula_1", "table_names_original": ["races", "lapTimes"]},
        {"db_id": "financial", "table_names_original": ["order"]},
    ]
    assert table_schemas(dev_tables) == {"races": "formula_1", "laptimes": "formula_1", "order": "financial"}


def test_a_table_in_two_databases_is_refused() -> None:
    dev_tables = [
        {"db_id": "a", "table_names_original": ["users"]},
        {"db_id": "b", "table_names_original": ["Users"]},
    ]
    with pytest.raises(LoadError, match="users"):
        table_schemas(dev_tables)
