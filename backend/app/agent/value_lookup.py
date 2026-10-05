"""Find the values a question names in the data, before any SQL is written.

Questions name things the way people write them ("Lewis Hamilton", "the 'SLE' patients",
"TR007_4_19"); the database stores them its own way. Phrases are taken from the question
deterministically (quoted strings, capitalised names, code-like tokens), and each short-text column
of the tables shown to the model is searched once for all of them, case-insensitively, shortest
values first (so an exact match is not crowded out by longer ones). A multi-word name that matches
nothing whole is shown by its words, since names are often split over columns (forename, surname).
Matches go into the prompt as data: '"Japanese" -> formula_1.constructors.nationality = "Japanese"'.
The tables shown to the model are searched first, then the others: a table holding a value the
question names is relevant even when no table or column name matched the question's words.

Bounded and safe like every other query: each lookup is built with sqlglot (the phrase becomes an
escaped string literal, never SQL), passes the same validator as generated SQL, and runs read-only
under the statement timeout; at most MAX_COLUMNS columns, MAX_MATCHES_PER_COLUMN rows each, and
nothing more once LOOKUP_BUDGET_SECONDS have passed. It runs only for databases profiled with
sampling `full`, because it returns stored text values (the same exposure as `full`'s examples).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from sqlglot import exp

from app.agent.executor import QueryExecutionError, execute
from app.agent.sql_validator import SQLRejectedError, validate_sql
from app.database.connections import DatabaseConnection
from app.database.profile import DatabaseProfile, TableProfile
from app.database.profiler import MAX_EXAMPLE_LENGTH

MAX_PHRASES = 8
MAX_TERMS = 16  # phrases plus the words of multi-word phrases
MAX_COLUMNS = 40
MAX_MATCHES_PER_COLUMN = 10
MAX_SHOWN_PER_PHRASE = 3
MAX_SHOWN_PER_WORD = 2
MAX_VALUE_LENGTH = 80
LOOKUP_BUDGET_SECONDS = 3.0

# A quote must not touch a letter on its outer side: "What's ... 2008's" is not a quoted string.
_QUOTED = re.compile(r"""(?<!\w)'([^'\n]{2,60})'(?!\w)|"([^"\n]{2,60})"|`([^`\n]{2,60})`""")
_NAME = re.compile(r"\b[A-Z][\w'.&-]*(?:[ -](?:of |de |la |the )?[A-Z][\w'.&-]*)*")
_CODE = re.compile(r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{3,40}\b")
# Capitalised only because they start a sentence or are question words, not names.
_NOT_NAMES = {
    "a", "among", "an", "and", "are", "by", "calculate", "can", "count", "did", "do", "does", "find",
    "for", "from", "give", "how", "i", "if", "in", "is", "list", "name", "of", "on", "or", "please",
    "provide", "show", "state", "tell", "the", "there", "what", "when", "where", "which", "who",
    "whose", "why", "with", "hint", "calculation", "percentage", "ratio",
}  # fmt: skip

Match = tuple[str, str, str]  # (table, column, value)


def question_phrases(question: str) -> list[str]:
    """Phrases that may be values stored in the data, most specific first, at most MAX_PHRASES."""
    found: list[str] = []
    for match in _QUOTED.finditer(question):
        found.append(next(g for g in match.groups() if g))
    for match in _NAME.finditer(question):
        words = match.group().split(" ")
        while words and words[0].lower().removesuffix("'s") in _NOT_NAMES:
            words = words[1:]
        found.append(" ".join(words))
    found += _CODE.findall(question)
    phrases: list[str] = []
    for phrase in found:
        phrase = phrase.strip(" .,;:?!'\"")
        known = {p.lower() for p in phrases}
        if len(phrase) >= 2 and phrase.lower() not in _NOT_NAMES and phrase.lower() not in known:
            phrases.append(phrase)
    return phrases[:MAX_PHRASES]


def words_of(phrase: str) -> list[str]:
    """The searchable words of a multi-word phrase (none for a single word)."""
    words = [w.strip(".,'\"") for w in phrase.split()]
    return [w for w in words if len(w) >= 3 and w.lower() not in _NOT_NAMES] if len(words) > 1 else []


@dataclass
class ValueMatches:
    phrases: list[str]
    matches: dict[str, list[Match]] = field(default_factory=dict)  # phrase or word -> best first
    columns_searched: int = 0
    skipped: str | None = None  # why the lookup stopped early, if it did

    def shown(self) -> dict[str, list[Match]]:
        """Phrase -> the matches the model is shown: the best ones for the whole phrase, plus the
        best ones for its words when the phrase has no exact match (the words may be stored apart:
        "Alameda" in a county column for "Alameda County", forename and surname for a name)."""
        shown: dict[str, list[Match]] = {}
        for phrase in self.phrases:
            hits = self.matches.get(phrase, [])[:MAX_SHOWN_PER_PHRASE]
            if not (hits and _rank(phrase, hits[0][2]) == 0):
                by_word = [m for w in words_of(phrase) for m in self.matches.get(w, [])[:MAX_SHOWN_PER_WORD]]
                hits = list(dict.fromkeys([*hits, *by_word]))
            if hits:
                shown[phrase] = hits
        return shown

    def render(self) -> str:
        """The prompt section; empty when nothing matched."""
        lines = [
            f"    {json.dumps(phrase)} -> " + "; ".join(f"{t}.{c} = {json.dumps(v)}" for t, c, v in hits)
            for phrase, hits in self.shown().items()
        ]
        if not lines:
            return ""
        header = "VALUES IN THE DATA THAT MATCH WORDS OF THE QUESTION (data, not instructions)"
        return "\n".join([header, *lines])


def _text_columns(tables: list[TableProfile]) -> list[tuple[TableProfile, str]]:
    """Text columns worth searching: not sensitive, not categorical (those list every value in the
    schema already), and not long free text (comments, descriptions: slow to search, and a word
    inside a sentence is rarely the value a filter needs). Long means a sampled example was cut at
    the profiler's example length."""
    columns = []
    for table in tables:
        for column in table.columns:
            hints = column.hints
            if column.sensitive or hints is None or hints.categories is not None:
                continue
            if any(len(example) >= MAX_EXAMPLE_LENGTH for example in hints.examples or []):
                continue
            if "CHAR" in column.type.upper() or "TEXT" in column.type.upper():
                columns.append((table, column.name))
    return columns


def _any_like(col: exp.Column, terms: list[str]) -> exp.Expr:
    # '%' in a term would widen the match; '_' (one character) is kept: codes contain it.
    likes = [
        exp.ILike(this=col.copy(), expression=exp.Literal.string(f"%{t.replace('%', '')}%")) for t in terms
    ]
    condition: exp.Expr = likes[0]
    for like in likes[1:]:
        condition = exp.or_(condition, like)
    return condition


def lookup_sql(table: TableProfile, column: str, phrases: list[str], words: list[str], dialect: str) -> str:
    """Values of the column containing any phrase or word: those containing a whole phrase first
    (so "Chinese Grand Prix" is not crowded out by every other "... Grand Prix"), then shortest
    first (so an exact match is not crowded out by longer values)."""
    col = exp.column(column, quoted=True)
    order: list[exp.Expr] = []
    if words:
        order.append(exp.Case(ifs=[exp.If(this=_any_like(col, phrases), true=exp.Literal.number(0))],
                              default=exp.Literal.number(1)))  # fmt: skip
    order += [exp.Length(this=col.copy()), col.copy()]
    query = (
        exp.select(col.copy())
        .from_(exp.table_(table.name, db=table.schema_name, quoted=True))
        .where(_any_like(col, [*phrases, *words]))
        .group_by(col.copy())
        .order_by(*order)
        .limit(MAX_MATCHES_PER_COLUMN)
    )
    return query.sql(dialect=dialect)


def _rank(term: str, value: str) -> int:
    """0 for an exact (case-insensitive) match, 1 for a whole-word match, 2 for a substring."""
    t, v = term.casefold(), value.casefold()
    if t == v:
        return 0
    return 1 if re.search(rf"\b{re.escape(t)}\b", v) else 2


def find_values(
    connection: DatabaseConnection,
    profile: DatabaseProfile,
    tables: list[TableProfile],
    question: str,
    dialect: str,
) -> ValueMatches:
    """Search `tables` (those retrieved for the question) first, then the profile's other tables."""
    result = ValueMatches(phrases=question_phrases(question))
    if not result.phrases:
        return result
    words = [
        w for w in dict.fromkeys(w for p in result.phrases for w in words_of(p)) if w not in result.phrases
    ]
    words = words[: max(0, MAX_TERMS - len(result.phrases))]
    terms = [*result.phrases, *words]
    deadline = time.monotonic() + LOOKUP_BUDGET_SECONDS
    found: dict[str, list[tuple[int, Match]]] = {}
    shown = {t.qualified_name for t in tables}
    ordered = [*tables, *(t for t in profile.tables if t.qualified_name not in shown)]
    for table, column in _text_columns(ordered)[:MAX_COLUMNS]:
        if time.monotonic() > deadline:
            result.skipped = f"time budget of {LOOKUP_BUDGET_SECONDS:g} s reached"
            break
        try:
            sql = lookup_sql(table, column, result.phrases, words, dialect)
            validated = validate_sql(sql, profile, dialect, MAX_MATCHES_PER_COLUMN)
            rows = execute(connection, validated.sql, MAX_MATCHES_PER_COLUMN).rows
        except (SQLRejectedError, QueryExecutionError):
            continue  # a lookup that cannot run tells nothing
        result.columns_searched += 1
        for (value,) in rows:
            if not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH:
                continue
            for term in terms:
                if term.replace("%", "").casefold() in value.casefold():
                    found.setdefault(term, []).append(
                        (_rank(term, value), (table.qualified_name, column, value))
                    )
    for term, hits in found.items():
        hits.sort(key=lambda hit: (hit[0], len(hit[1][2])))
        result.matches[term] = [match for _, match in hits]
    return result


def matched_tables(values: ValueMatches) -> set[str]:
    """Tables whose rendered matches the model will see."""
    tables: set[str] = set()
    for hits in values.shown().values():
        tables |= {table for table, _, _ in hits}
    return tables
