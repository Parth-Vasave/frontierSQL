# Security policy

The analyst runs SQL drafted by an LLM, so safety depends on deterministic code and database
permissions, not on the model. The [Security model](README.md#security-model) in the README
describes each layer.

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/Parth-Vasave/frontiersql/security/advisories/new),
not in a public issue.

Especially useful: SQL the validator accepts but should reject (writes, system catalogs, denied
functions, sensitive columns, reads outside the profiled tables), ways around the row limit or
statement timeout, and secrets or query data that reach the frontend or the logs.

Include the question or SQL, the configuration (`MAX_ROWS`, sampling mode, `ALLOW_UI_CONNECTIONS`)
and what happened. A failing case for `backend/tests` or the offline safety suite
(`python -m evaluation.run --suite sql-safety`) is ideal.

This is a personal project maintained in spare time: reports are acknowledged as soon as possible
and fixed on `main`. There are no versioned releases to backport to.

## Out of scope

- `ALLOW_UI_CONNECTIONS=true` on a public deployment. It is documented as local-only because it
  lets the server connect to arbitrary hosts.
- Wrong answers that are not a safety issue (open a regular issue).
- Data sent to the configured LLM provider within the documented sampling mode.
