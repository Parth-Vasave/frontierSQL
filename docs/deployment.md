# Deployment: Neon + Render + Vercel + Groq

A public setup that fits in free tiers: **Neon** for PostgreSQL, **Render** for the FastAPI
backend, **Vercel** for the frontend and **Groq** for the LLM. Any other container host works the
same way for the backend (see [Other hosts](#other-hosts)).

> **Status: this setup has not been run end to end.** Every command, setting and file reference
> below was checked against the repository, but not against live Neon, Render, Vercel or Groq
> accounts. Run the [post-deployment checks](#7-post-deployment-checks) before you rely on it, and
> please open an issue for anything that differs. Free-tier limits change; the figures below were
> taken from the providers' documentation in October 2026.

```text
browser ──▶ Vercel (static frontend)
   │
   └──── fetch ──▶ Render (FastAPI) ──▶ Neon PostgreSQL, as the read-only sql_agent role
                        │
                        └──▶ Groq (OpenAI-compatible API, openai/gpt-oss-120b)
```

The browser calls the backend directly; Vercel only serves the built files. The frontend never
talks to the database, and the backend connects only as `sql_agent`.

**What the free tiers mean in practice**

- **Render** stops a free web service after about 15 minutes without traffic. The next request
  starts it again, which takes up to a minute (the app also re-profiles the database at startup).
- **Neon** suspends an idle database after a few minutes; it wakes in about a second.
- **Groq**'s free tier for `openai/gpt-oss-120b` allows 8K tokens per minute and 200K tokens per
  day. That, not the hosting, limits how much the demo can be used. See
  [Rate limits](#5-rate-limits-and-llm-budget).

## Before you start

- Accounts on Neon, Render and Vercel (all can sign in with GitHub), and a Groq API key from
  <https://console.groq.com/keys>.
- On your machine: a clone of this repository, Python 3.11+, and `psql`.
- Two passwords: Neon generates the owner's; you choose the one for `sql_agent`.

Secrets belong only in the Render environment and in your shell. Never in Vercel, in a commit, or
in a screenshot.

## 1. Create the database and the read-only role

1. In Neon, create a project. Choose the region closest to where the backend will run
   (`render.yaml` uses Render's Ohio region; Neon's matching region is AWS US East 2, Ohio).
2. Click **Connect**, **turn off "Connection pooling"**, and copy the connection string. It
   connects as the database **owner** and looks like
   `postgresql://<owner>:<password>@<endpoint>.<region>.aws.neon.tech/<db>?sslmode=require`.
   The host must **not** contain `-pooler`. The pooled endpoint runs PgBouncer in transaction
   mode, which does not support the per-session settings the backend sends when it connects
   (`default_transaction_read_only`, `statement_timeout`).
3. From your clone, create the schema and the `sql_agent` role with the repository's init script.
   It runs `database/schema.sql`, then `database/permissions.sql`:

   ```bash
   export ADMIN_DATABASE_URL='postgresql://<owner>:<password>@<endpoint>.<region>.aws.neon.tech/<db>?sslmode=require'
   export SQL_AGENT_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=')"   # keep it for step 3
   export QUERY_TIMEOUT_SECONDS=5          # optional; becomes sql_agent's statement_timeout
   ./database/init/00_init.sh
   ```

   `permissions.sql` is idempotent: re-run the script to rotate the `sql_agent` password or change
   the timeout. It gives `sql_agent` `SELECT` on the four data tables and nothing else.

4. **Check that `sql_agent` really cannot write.** Connect **as `sql_agent`**, never as the owner.
   The first command turns the session's read-only default off, so the second one tests the
   missing privileges rather than read-only mode. They must be separate `-c` options: in one
   string they run as one transaction, which has already started read-only.

   ```bash
   export AGENT_URL="postgresql://sql_agent:${SQL_AGENT_PASSWORD}@${ADMIN_DATABASE_URL##*@}"
   psql "$AGENT_URL" -c "SET default_transaction_read_only = off" -c "CREATE TABLE should_fail (id int);"
   ```

   This must fail with `permission denied for schema public`. `cannot execute CREATE TABLE in a
   read-only transaction` means read-only mode stopped it and the privileges were not tested. If
   it succeeds, you connected as the wrong role: drop the table and check the URL. The same checks run in CI against a disposable database
   (`scripts/tests/test_database.py`).

## 2. Load the data

The seed runs as the **owner** (`ADMIN_DATABASE_URL`), never as `sql_agent`:

```bash
pip install -r scripts/requirements.txt
python -m scripts.ingest_data      # downloads the pinned OWID commit and checks both SHA-256 hashes
python -m scripts.clean_data       # writes data/processed/*.csv and cleaning_report.json
python -m scripts.seed_database    # uses ADMIN_DATABASE_URL from step 1
```

The cleaned data is about 30 MB, well inside Neon's free storage. Existing rows are skipped
(`ON CONFLICT ... DO NOTHING`); `python -m scripts.seed_database --replace` truncates the four
tables and reloads them. `data/README.md` describes the dataset and the cleaning rules.

## 3. Deploy the backend on Render

The repository has a Blueprint, [`render.yaml`](../render.yaml): one free Docker web service built
from `backend/Dockerfile`, health-checked on `/api/health`, with the Groq settings and rate limits
filled in. It rebuilds only when something under `backend/` changes.

1. Push your copy of the repository to GitHub. In Render, choose **New → Blueprint**, connect the
   repository, and Render reads `render.yaml`. Change `region` in the file first if your Neon
   database is not in Ohio.
2. Render asks for the three values the file leaves out:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql://sql_agent:<SQL_AGENT_PASSWORD>@<endpoint>.<region>.aws.neon.tech/<db>?sslmode=require`. **The read-only role and the direct (non-`-pooler`) host.** A connection that can modify data is refused. |
   | `LLM_API_KEY` | Your Groq key. Secret, backend only. |
   | `CORS_ORIGINS` | `["https://<app>.vercel.app"]`. **A JSON list**, quotes and brackets included. You get the Vercel URL in step 4; until then put `["http://localhost:5173"]` and change it afterwards. A bare or comma-separated value stops the backend from starting. |

3. Apply the Blueprint. The service gets a URL like `https://ai-sql-analyst-api.onrender.com`.
   The container listens on the `PORT` Render provides. `/api/health` answers 503 until the
   database is reachable, and Render only routes traffic to the service once it answers 200.

The Blueprint also sets `LLM_BASE_URL=https://api.groq.com/openai/v1`,
`LLM_MODEL=openai/gpt-oss-120b`, `ALLOW_UI_CONNECTIONS=false`, `TRUSTED_PROXY_HOPS=0`,
`ANSWER_MODE=llm` and the rate limits from step 5. Optional: `QUERY_TIMEOUT_SECONDS` (default 5,
max 60), `MAX_ROWS` (1000, max 10,000), `MAX_RETRIES` (2, max 5), `LOG_LEVEL` (`INFO`).
`.env.example` documents every setting; the backend reads them in `backend/app/config.py`.

Never set `ADMIN_DATABASE_URL`, `POSTGRES_PASSWORD` or `SQL_AGENT_PASSWORD` on the backend. Only
the seed and the init script need them, and they run from your machine.

## 4. Deploy the frontend on Vercel

1. **Add New → Project → Import Git Repository**, and set the **root directory** to `frontend`.
   [`frontend/vercel.json`](../frontend/vercel.json) sets the Vite build (`npm run build`, output
   `dist`) and redirects `/chat` to `/chat/`.
2. Set one environment variable: `VITE_API_BASE_URL=https://<service>.onrender.com`, with no
   trailing slash. The frontend calls `${VITE_API_BASE_URL}/api/...`. Deploy.
3. Back in Render, set `CORS_ORIGINS` to the exact Vercel origin, for example
   `["https://<app>.vercel.app"]` or `["https://<app>.vercel.app","https://<your-domain>"]`. Never
   `["*"]`. Render redeploys the service when a variable changes.

There is no rewrite or proxy on Vercel, so `VITE_API_BASE_URL` is required in production; the
`/api` proxy in `vite.config.ts` only exists in the dev server. Vercel's preview deployments get
other origins, so they cannot call the backend unless you add them to `CORS_ORIGINS`.

> Every `VITE_*` variable is compiled into the JavaScript bundle and readable by anyone. The
> backend URL is the only value the frontend needs. Never put an API key, database URL or password
> in Vercel.

## 5. Rate limits and LLM budget

`POST /api/query` is limited before any LLM call is made: `RATE_LIMIT_PER_MINUTE` per client
address, and `RATE_LIMIT_PER_DAY` for all clients together. One question uses between 1 and
`MAX_RETRIES + 2` LLM calls (4 with the defaults): SQL generation, up to `MAX_RETRIES` repairs, and
the written answer when `ANSWER_MODE=llm`.

`render.yaml` sizes the limits to Groq's free tier for `openai/gpt-oss-120b` (8K tokens per
minute, 200K tokens per day). In a 10-question BIRD dev run with that model (template answers),
a question used a median of about 2,500 tokens and up to 5,500. Allowing about 5,000 tokens per question with the
written answer gives:

- `RATE_LIMIT_PER_DAY=40`: about 200K tokens in the worst case.
- `RATE_LIMIT_PER_MINUTE=3`: at most about 15K tokens a minute, so a burst can still hit Groq's
  per-minute limit. The client retries short provider waits itself, and a question that still
  fails reports a rate-limit error rather than a wrong answer.

Raise them if Groq's limits page for your account shows more, or with a paid plan.
`ANSWER_MODE=template` saves one call per question.

**`TRUSTED_PROXY_HOPS`** says how many proxies in front of the app append the client address to
`X-Forwarded-For`. With `0`, the header is ignored and the TCP peer is used. That can't be spoofed,
but behind Render's proxy the peer is the proxy, so **visitors share the per-minute limit**. With a
3-per-minute limit sized to the provider's quota, that is what you want anyway. Keep `0` unless you
have confirmed a fixed hop count for your setup: a value that is too high lets clients choose their
own address by forging the header.

The limiter keeps its windows **in memory, per process**: with several instances, each enforces
its own limits, so the effective limits multiply. The free plan runs one instance; keep it that way
until [#7](https://github.com/Parth-Vasave/frontiersql/issues/7) adds a shared store. A
restart (including Render's spin-down) resets the windows.

**Data sent to Groq:** the schema, sampled values and up to 30 result rows for the written answer.
That is fine for the public OWID data. Check the provider's data-use terms before connecting a
private database.

## 6. Security checklist

- [ ] The backend's `DATABASE_URL` uses `sql_agent` and the direct Neon host, and the write check
      in step 1 failed as expected
- [ ] `ALLOW_UI_CONNECTIONS=false`
- [ ] `CORS_ORIGINS` lists only your frontend origin(s), as a JSON list
- [ ] The only Vercel variable is `VITE_API_BASE_URL`
- [ ] The rate limits fit your LLM quota, and only one backend instance runs
- [ ] Owner credentials (`ADMIN_DATABASE_URL`) exist only on your machine

The application enforces the rest: AST validation of every query, the read-only role and session,
the statement timeout, row limits, the retry cap, and logs without questions, SQL, rows, URLs or
keys. The [Security model](../README.md#security-model) describes each layer.

## 7. Post-deployment checks

```bash
API=https://<service>.onrender.com

curl -s "$API/api/health"
# {"status":"ok","databases":{"default":"ready"}}    (503 and "degraded" while a database is down)
# The first request after the service has slept can take up to a minute.

curl -s "$API/api/query" -H 'content-type: application/json' \
  -d '{"question": "Top 5 CO2 emitters in 2023"}'
# "status": "success", with the plan, the validated SQL, rows, chart, answer and trace

curl -s "$API/api/query" -H 'content-type: application/json' \
  -d '{"question": "Delete every row in the countries table"}'
# expect "unanswerable" (refused) or "error" (rejected SQL); nothing is written either way

curl -s -o /dev/null -w '%{http_code}\n' "$API/api/databases" \
  -H 'content-type: application/json' -d '{"name": "x", "url": "postgresql://u:p@example.com/db"}'
# 403: adding databases is disabled
```

With a single `DATABASE_URL` the database id is `default`. Requests without `database_id` use the
first ready database.

Then open the Vercel URL, ask a question, and check in the browser's network tab that requests go
to the Render domain and that no response contains a key or password. Locally,
`grep -rE "LLM_API_KEY|DATABASE_URL|PASSWORD" frontend/dist` after `npm run build` should find
nothing.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Backend exits at startup with `error parsing value for field "cors_origins"` | `CORS_ORIGINS` is not a JSON list. Use `["https://<app>.vercel.app"]`. |
| Browser shows CORS errors | The Vercel origin is missing from `CORS_ORIGINS`, or has a trailing slash or a different domain (preview deployments have their own). |
| `/api/health` returns 503 with `"rejected"` | `DATABASE_URL` uses an account that can modify data. Use `sql_agent`. |
| `/api/health` returns 503 with `"unavailable"` | The URL, password or `sslmode` is wrong, or the host is the `-pooler` endpoint. Use the direct connection string. |
| `POST /api/query` returns 503 `No LLM configured: set LLM_API_KEY.` | `LLM_API_KEY` is empty. |
| `POST /api/query` returns 503 `No database is ready.` | No configured database is ready. Check `/api/health`. |
| `POST /api/query` returns 404 `Unknown database` | Wrong `database_id`. It is `default` with a single `DATABASE_URL`. |
| `POST /api/query` returns 429 | A rate limit was hit. The `Retry-After` header says when to retry. |
| Answers fail with an LLM rate-limit or "quota used up" error | Groq's per-minute or daily token limit. Lower the rate limits or wait for the quota to reset. |
| `POST /api/query` returns 422 | The question is empty or longer than 500 characters. |
| The seed fails with a permission error | `ADMIN_DATABASE_URL` points at `sql_agent`. Seeding needs the owner. |
| `00_init.sh` stops with `SQL_AGENT_PASSWORD must be set` | Export `SQL_AGENT_PASSWORD` first. |

## Other hosts

Any host that runs a Dockerfile can run `backend/Dockerfile` with `backend` as the build context:
Railway, Fly.io, Koyeb, Google Cloud Run. The container listens on `$PORT` when the host sets it
and on 8000 otherwise. All of them put a proxy in front of the app, so the `TRUSTED_PROXY_HOPS`
advice above applies. The variables, the CORS setting and the checks are the same. Any other
OpenAI-compatible LLM provider works by changing `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`;
size the rate limits to its quota.
