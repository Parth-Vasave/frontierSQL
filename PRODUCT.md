# Product

## Platform

web

## Stack

Vite + React + TypeScript + Tailwind + Recharts (confirmed by the owner; matches the earlier,
since-removed Milestone 12 attempt — see commit `ae1cca7`).

## Users

Dual audience, confirmed by the owner as "both":

- **Analysts asking real questions.** Someone who wants an answer from data without writing SQL:
  they type a question in plain language, see the SQL that ran, the result, a chart, and a
  grounded answer, and can ask follow-ups. Initially this means the bundled demo database (Our
  World in Data CO2 & GHG emissions, 1750-2024, 242 countries); the backend is database-agnostic
  and profiles whatever is connected.
- **People evaluating the engineering.** Recruiters, collaborators, and other developers who land
  on the project (e.g. from a GitHub link or a demo) to judge the quality of the work itself, not
  just get an answer. The frontend has to read as credible engineering, not a marketing surface.

## Product Purpose

Turn a natural-language question about a connected relational database into a safe, validated SQL
query, execute it read-only, and return a grounded natural-language answer plus a chart and the
full reasoning trace (plan, SQL, validation, checks). It exists to demonstrate that an LLM can
generate SQL without being trusted with anything: every generated query passes deterministic
safety validation before it ever reaches the database.

## Positioning

Most visible text-to-SQL tools sell speed and a chat box; the LLM's SQL is the safety mechanism by
omission. This project's mechanism is the opposite and is falsifiable: an AST validator
(sqlglot) rejects anything that is not a single read-only SELECT against known tables/columns, a
read-only database role and statement timeout back that up independently, every generated query is
re-derived from the validated tree before it runs, and there's an offline adversarial safety suite
(28 attack statements) plus a 78-question evaluation harness with result-based scoring — recorded,
not claimed. A neighboring "AI analyst" product could not truthfully copy "we never trust the
LLM's SQL, and here's the test suite that proves it."

## Operating Context

- Local dev: `docker compose up` (Postgres 16 + FastAPI backend + a seed step that downloads,
  cleans, and loads the pinned OWID dataset). The frontend is a separate Vite dev server / static
  build talking to the backend's JSON API.
- Database connections come from a config file (`databases.toml`) or, in local/self-hosted mode
  (`ALLOW_UI_CONNECTIONS=true`), can be added at runtime through the API — never through checked-in
  credentials.
- Core interaction: ask a question -> see resolved plan/assumptions -> SQL -> execution trace ->
  deterministic result checks -> chart -> grounded answer. Up to 3 prior turns can be sent back as
  `history` for follow-up questions; the server keeps no server-side conversation state.
- Existing API surface the frontend consumes: `POST /api/query`, `GET /api/health`,
  `GET /api/databases`, `GET /api/databases/{id}/profile`, `POST /api/databases` (local mode only).

## Capabilities and Constraints

- Backend is feature-complete through Milestone 11: SQL generation, AST validation,
  LIMIT enforcement, auto-repair (max 2 retries), deterministic result checks with missing-value
  probes, grounded answer generation with unit tracking, deterministic chart selection, structured
  tracing, rate limiting. All of this is real and already exercised by tests and live checks.
  Frontend can rely on it as source of truth for surfaced states.
  - Rate limiting: `RATE_LIMIT_PER_MINUTE` per client (default 10), `RATE_LIMIT_PER_DAY` across all
    clients (default 200) — the frontend must design for a real, user-facing 429 with `Retry-After`.
  - Errors the frontend must present, each with its own recovery: rate limited, provider error,
    validation rejection, timeout, API unreachable, no LLM configured, clarification needed,
    unanswerable/no-result question.
- The 78-question evaluation suite has one complete run with a real LLM (2026-10-04,
  `openai/gpt-oss-120b`, 74/78 answers correct; see EVALUATION_PLAN.md). The frontend must never
  display invented accuracy/quality numbers. If evaluation results are shown at all, they must be
  read from the actual recorded report, with the run, model and date they came from.
- The frontend (Milestone 12) lives in `frontend/`. An earlier build was removed and remains in git
  history at commit `ae1cca7` / `50ee27e` as reference only.
- The code is MIT-licensed and public at https://github.com/Parth-Vasave/frontiersql.
  Star, contributor and usage counts must never be invented.

## Brand Commitments

The owner was explicit: this should read as an **open-source solo project, not a SaaS product**.
No marketing chrome, no invented logos/testimonials/pricing/customer counts, no gradient hero
selling a category. Credibility comes from showing real engineering (trace, safety checks, tests)
plainly, not from persuading a visitor. No name/pseudonym for authorship has been decided.

Interface convention (owner decision, 2026-10-04): the app uses the familiar chat-app layout of
Claude.ai / ChatGPT — conversations listed in a left sidebar, a settings menu pinned bottom-left
(database switching, connecting a database, schema, theme, help), and a soft, rounded chat look.
This replaces the earlier "console transcript" look. There are no user accounts: chats are kept in
the visitor's own browser. Convention is the commitment here; the distinctiveness lives in what
each answer exposes, not in an unusual layout.

## Evidence on Hand

- Dataset: Our World in Data, "CO2 and Greenhouse Gas Emissions" (CC BY 4.0), pinned commit
  `382ee6c662b0ece26e111f263b44c029afad7787`, 1750-2024, 254 entities (242 after cleaning), 50,411
  rows x 79 source columns (`data/README.md`). Real, citable, safe to reference directly.
- Repository: https://github.com/Parth-Vasave/frontiersql (MIT). Do not fabricate usage
  or star metrics.
- Recorded evaluation: offline safety suite 28/28 blocked (2026-10-04) and one complete question
  suite run, 74/78 (2026-10-04). EVALUATION_PLAN.md is the source of truth.

## Product Principles

1. Never trust the LLM's SQL — the validator and the read-only role are real and are the story;
   don't hide them behind a friendly chat box.
2. Show the reasoning, not just the answer — every answer carries a visible verification summary
   (validated, read-only, checks, timing) that opens into the plan, SQL, checks and trace; warnings
   and retries are never hidden behind it.
3. Report evaluation and safety status exactly as run; a partial or not-yet-run result says so.
4. Read-only and safe by default, for any database the user connects — not just the OWID demo.
5. Earn credibility as one person's rigorous work, not through SaaS marketing conventions.

## Accessibility & Inclusion

No product-specific requirement established beyond ordinary web accessibility (keyboard
operability, visible focus, sufficient contrast, reduced-motion support).
