import { useEffect, useState, type ReactNode } from 'react'
import { CopyButton } from '../components/CopyButton'
import { GithubIcon, MonitorIcon, MoonIcon, ShieldCheckIcon, SunIcon } from '../components/icons'
import { Verification } from '../components/Verification'
import { useTheme, type ThemePreference } from '../hooks/useTheme'
import {
  BLOCKED_STATEMENTS,
  LATENCY_MEDIAN_MS,
  MISSES,
  QUESTION_METRICS,
  QUESTION_RUN,
  REPO_URL,
  repoFile,
  SAFETY_RUN,
  SAFETY_VIOLATIONS,
  type Ratio,
} from './evaluation'
import { RECORDED_ANSWER, RECORDED_AT } from './recordedAnswer'
import { Replay } from './Replay'

export const CHAT_URL = `${import.meta.env.BASE_URL}chat/`

const STEPS: { name: string; kind: string; text: string }[] = [
  {
    name: 'Plan and draft',
    kind: 'LLM',
    text: 'One call returns a structured plan (intent, tables, metrics, filters, assumptions) and the SQL. When no reading of the question is a reasonable default, it asks a clarifying question instead.',
  },
  {
    name: 'Validate',
    kind: 'deterministic',
    text: 'sqlglot parses the SQL into a syntax tree: one read-only SELECT, only tables and columns the profiler found, functions from an allow-list, LIMIT added or clamped. The SQL that runs is regenerated from the checked tree.',
  },
  {
    name: 'Execute',
    kind: 'deterministic',
    text: 'On a database account that cannot write, with a statement timeout and a row cap enforced in the SQL and again in the client.',
  },
  {
    name: 'Check the result',
    kind: 'deterministic',
    text: 'Empty results, aggregates over nothing, rankings led by NULL and misspelled filter values are caught. A repairable failure goes back to the model at most twice, and every repair is validated again.',
  },
  {
    name: 'Answer',
    kind: 'LLM, checked',
    text: 'One to three sentences. Every number must appear in the returned rows; otherwise a template answer built from the rows is used.',
  },
]

const DEFENSES: { term: string; text: string }[] = [
  { term: 'Read-only role', text: 'The API connects as a role with SELECT on the data tables only. Connecting an account that can write is refused.' },
  { term: 'Timeout and row cap', text: 'Every query carries a statement timeout and a row limit, enforced in the database and again client-side.' },
  { term: 'Bounded repair', text: 'At most two repair attempts, each validated like the first. Unsafe intent is never retried.' },
  { term: 'Rate limits', text: 'Per-client and global limits on questions, so a public instance has a fixed LLM budget.' },
]

const QUICK_START = `git clone ${REPO_URL}
cd frontiersql
cp .env.example .env           # set the two passwords and LLM_API_KEY
docker compose up -d           # PostgreSQL, read-only role, API on :8000
docker compose run --rm seed   # load the pinned OWID data
cd frontend && npm install && npm run dev   # http://localhost:5173`

const STACK = ['Python 3.11+, FastAPI, sqlglot', 'PostgreSQL 16', 'Any OpenAI-compatible LLM endpoint', 'React, TypeScript, Tailwind, Recharts']

const LIMITATIONS = [
  'PostgreSQL only; MySQL is not implemented.',
  'The rate limiter is in memory per process, so multi-instance deployments need a shared store.',
  'No hosted demo yet. The deployment guide has not been run end to end.',
  'Only one model has been evaluated; results depend on the model you choose.',
]

const PREVIEW_ROWS = 6

export function HomePage() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="min-h-dvh bg-surface">
      <TopBar />

      <main>
        <section className="mx-auto max-w-[72rem] px-4 pt-14 sm:px-6 sm:pt-20">
          <div className="mx-auto max-w-[46rem] text-center">
            <h1 className="text-[34px] leading-[1.12] font-semibold tracking-[-0.03em] text-balance sm:text-[50px]">
              Text-to-SQL that never trusts the model
            </h1>
            <p className="mx-auto mt-5 max-w-[38rem] text-[16.5px] leading-7 text-pretty text-ink-dim sm:text-[17.5px] sm:leading-8">
              Ask a PostgreSQL database a question in plain language. An LLM drafts the SQL; deterministic code validates
              it, runs it on a read-only account, checks the result and shows you every step.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <PrimaryLink href={CHAT_URL}>Try the demo</PrimaryLink>
              <OutlineLink href={REPO_URL}>
                <GithubIcon size={17} />
                View on GitHub
              </OutlineLink>
            </div>
            <p className="mt-5 text-[13px] text-ink-faint">
              MIT licensed ·{' '}
              <a href="#run" className="underline decoration-line underline-offset-4 hover:text-ink-dim">
                runs locally with Docker
              </a>
            </p>
          </div>

          <div className="mt-14 sm:mt-16">
            <Replay result={RECORDED_ANSWER} recordedAt={RECORDED_AT} />
          </div>
        </section>

        <Section id="how" title="Every answer shows its work">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
            <div>
              <Lead>
                The model only drafts. Everything that decides what reaches the database, and what reaches you, is plain
                code you can read and test.
              </Lead>
              <ol className="mt-9 flex flex-col gap-6">
                {STEPS.map((step, index) => (
                  <li key={step.name} className="flex gap-4">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-raised text-[12.5px] font-medium text-ink tabular-nums">
                      {index + 1}
                    </span>
                    <div>
                      <p className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-medium text-ink">
                        {step.name}
                        <span className="text-[13px] font-normal text-ink-faint">{step.kind}</span>
                      </p>
                      <p className="mt-1 text-[14.5px] leading-relaxed text-ink-dim">{step.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="lg:sticky lg:top-24 lg:self-start">
              <Verification result={RECORDED_ANSWER} defaultOpen />
              <p className="mt-3 px-1 text-[13px] leading-relaxed text-ink-faint">
                The same recorded answer with its verification line open, exactly as the chat shows it.
              </p>
            </div>
          </div>
        </Section>

        <Section id="safety" title="What the validator refuses">
          <Lead>
            Prompting a model to behave is not a security boundary. The offline safety suite sends hostile statements
            straight to the validator, with no LLM in the loop, and records what comes back.
          </Lead>
          <BlockedLedger />
          <dl className="mt-12 grid grid-cols-[minmax(0,1fr)] gap-x-10 gap-y-7 sm:grid-cols-2">
            {DEFENSES.map(({ term, text }) => (
              <div key={term} className="border-t border-line pt-4">
                <dt className="text-[15px] font-medium text-ink">{term}</dt>
                <dd className="mt-1 text-[14.5px] leading-relaxed text-ink-dim">{text}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <Section id="evaluation" title="Evaluation, as recorded">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
            <div>
              <Lead>
                78 questions across filtering, aggregation, ranking, time series, joins, follow-ups, ambiguous and unsafe
                requests. Ground truth is hand-written SQL on the pinned dataset, and scoring compares results, not SQL
                text.
              </Lead>
              <p className="mt-5 text-[14px] leading-relaxed text-ink-faint">
                One run of one model: <span className="font-mono text-[13px] text-ink-dim">{QUESTION_RUN.model}</span> on
                Groq, template answers, {QUESTION_RUN.date} (run{' '}
                <span className="font-mono text-[13px] text-ink-dim">{QUESTION_RUN.runId}</span>). It says nothing about
                other models.
              </p>
              <a
                href={repoFile('EVALUATION_PLAN.md')}
                className="mt-5 inline-flex text-[14px] font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink-faint"
              >
                Read the evaluation plan
              </a>
            </div>
            <div>
              <div className="overflow-hidden rounded-xl border border-line">
                <table className="w-full border-collapse text-[14px]">
                  <thead className="bg-code">
                    <tr>
                      <th scope="col" className="px-4 py-2.5 text-left text-[13px] font-medium text-ink-dim">
                        Metric
                      </th>
                      <th scope="col" className="px-4 py-2.5 text-right text-[13px] font-medium text-ink-dim">
                        Result
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {QUESTION_METRICS.map(({ label, value }) => (
                      <MetricRow key={label} label={label}>
                        <RatioCell value={value} />
                      </MetricRow>
                    ))}
                    <MetricRow label="Safety violations">
                      {SAFETY_VIOLATIONS} of {QUESTION_METRICS[0].value.total}
                    </MetricRow>
                    <MetricRow label="Median latency">{(LATENCY_MEDIAN_MS / 1000).toFixed(1)} s</MetricRow>
                  </tbody>
                </table>
              </div>
              <h3 className="mt-8 text-[14px] font-medium text-ink">The four misses</h3>
              <ul className="mt-2 flex flex-col gap-1.5 text-[14px] leading-relaxed text-ink-dim">
                {MISSES.map((miss) => (
                  <li key={miss.id} className="flex gap-3">
                    <span className="w-11 shrink-0 font-mono text-[12.5px] leading-[1.6rem] text-ink-faint">{miss.id}</span>
                    <span>{miss.what}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Section>

        <Section id="run" title="Run it yourself">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
            <div className="flex flex-col gap-5 text-[15px] leading-relaxed text-ink-dim">
              <p>
                You need Docker and an API key for any OpenAI-compatible endpoint; the example configuration uses the
                Gemini free tier.
              </p>
              <p>
                Point it at your own PostgreSQL database and it is profiled automatically. The account must be read-only:
                one that can write is refused, with the privileges that disqualified it.
              </p>
              <p>
                Deploying publicly?{' '}
                <a href={repoFile('docs/deployment.md')} className="text-ink underline decoration-line underline-offset-4 hover:decoration-ink-faint">
                  The deployment guide
                </a>{' '}
                covers Neon, Railway and Vercel.
              </p>
            </div>
            <div className="min-w-0 overflow-hidden rounded-xl border border-line bg-code">
              <div className="flex items-center justify-between border-b border-line py-1.5 pr-2 pl-4">
                <span className="text-[13px] text-ink-faint">Terminal</span>
                <CopyButton text={QUICK_START} label="Copy" />
              </div>
              <pre className="overflow-x-auto px-4 py-3.5 font-mono text-[13px] leading-[1.7] text-ink max-sm:whitespace-pre-wrap max-sm:[overflow-wrap:anywhere]">
                {QUICK_START.split('\n').map((line) => (
                  <CommandLine key={line} line={line} />
                ))}
              </pre>
            </div>
          </div>
        </Section>

        <Section id="status" title="Where it stands">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-10 sm:grid-cols-2 sm:gap-16">
            <div>
              <h3 className="text-[15px] font-medium text-ink">Built with</h3>
              <ul className="mt-3 flex flex-col gap-2 text-[14.5px] text-ink-dim">
                {STACK.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-[15px] font-medium text-ink">Known limitations</h3>
              <ul className="mt-3 flex flex-col gap-2 text-[14.5px] leading-relaxed text-ink-dim">
                {LIMITATIONS.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </Section>

        <section className="mt-24 border-t border-line sm:mt-32">
          <div className="mx-auto max-w-[46rem] px-4 py-24 text-center sm:px-6 sm:py-28">
            <h2 className="text-[28px] leading-tight font-semibold tracking-[-0.025em] text-balance sm:text-[34px]">
              Ask the demo database something
            </h2>
            <p className="mx-auto mt-4 max-w-[34rem] text-[16px] leading-7 text-pretty text-ink-dim">
              Our World in Data's CO₂ and greenhouse-gas emissions, by country and year from 1750 to 2024. Rankings,
              trends, per-capita comparisons, or a DELETE to watch it get refused.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <PrimaryLink href={CHAT_URL}>Try the demo</PrimaryLink>
              <OutlineLink href={REPO_URL}>
                <GithubIcon size={17} />
                View on GitHub
              </OutlineLink>
            </div>
          </div>
        </section>
      </main>

      <Footer preference={preference} onTheme={setPreference} />
    </div>
  )
}

function TopBar() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`sticky top-0 z-30 border-b bg-surface transition-colors ${scrolled ? 'border-line' : 'border-transparent'}`}>
      <div className="mx-auto flex h-14 max-w-[72rem] items-center gap-2 px-4 sm:px-6">
        <a href={import.meta.env.BASE_URL} className="mr-auto flex items-center gap-2.5 rounded-lg py-1 pr-2">
          <span className="text-[15px] font-semibold tracking-tight">FrontierSQL</span>
        </a>
        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          <NavLink href="#how">How it works</NavLink>
          <NavLink href="#safety">Safety</NavLink>
          <NavLink href="#evaluation">Evaluation</NavLink>
          <NavLink href="#run">Run it</NavLink>
        </nav>
        <a
          href={REPO_URL}
          aria-label="Source on GitHub"
          className="flex items-center gap-2 rounded-lg p-2 text-[14px] text-ink-dim transition-colors hover:bg-raised hover:text-ink sm:px-2.5"
        >
          <GithubIcon size={18} />
          <span className="hidden sm:inline">GitHub</span>
        </a>
        <a
          href={CHAT_URL}
          className="ml-1 rounded-full bg-ink px-4 py-1.5 text-[14px] font-medium text-surface transition-opacity hover:opacity-85"
        >
          Try the demo
        </a>
      </div>
    </header>
  )
}

function NavLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} className="rounded-lg px-2.5 py-1.5 text-[14px] text-ink-dim transition-colors hover:bg-raised hover:text-ink">
      {children}
    </a>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-14">
      <div className="mx-auto max-w-[72rem] px-4 pt-24 pb-4 sm:px-6 sm:pt-32">
        <h2 id={`${id}-title`} className="text-[26px] leading-tight font-semibold tracking-[-0.025em] text-balance sm:text-[32px]">
          {title}
        </h2>
        <div className="mt-5">{children}</div>
      </div>
    </section>
  )
}

function Lead({ children }: { children: ReactNode }) {
  return <p className="max-w-[38rem] text-[16px] leading-7 text-pretty text-ink-dim">{children}</p>
}

function PrimaryLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} className="rounded-full bg-ink px-5 py-2.5 text-[15px] font-medium text-surface transition-opacity hover:opacity-85">
      {children}
    </a>
  )
}

function OutlineLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="flex items-center gap-2 rounded-full border border-line px-5 py-2.5 text-[15px] font-medium text-ink transition-colors hover:bg-raised/60"
    >
      {children}
    </a>
  )
}

function BlockedLedger() {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? BLOCKED_STATEMENTS : BLOCKED_STATEMENTS.slice(0, PREVIEW_ROWS)
  const total = BLOCKED_STATEMENTS.length

  return (
    <div className="mt-9 overflow-hidden rounded-xl border border-line">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-code px-4 py-3">
        <ShieldCheckIcon size={17} className="text-ok" />
        <p className="text-[14px] font-medium text-ink">
          {total} of {total} statements blocked
        </p>
        <p className="text-[13px] text-ink-faint">
          run <span className="font-mono text-[12.5px]">{SAFETY_RUN.runId}</span> · {SAFETY_RUN.date} · no LLM involved
        </p>
      </div>
      <table className="w-full border-collapse text-left">
        <thead className="sr-only">
          <tr>
            <th scope="col">Statement</th>
            <th scope="col">Validator response</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((statement) => (
            <tr key={statement.id} className="border-b border-line last:border-b-0 max-md:flex max-md:flex-col max-md:gap-1 max-md:py-3">
              <td className="px-4 font-mono text-[13px] leading-relaxed break-words text-ink md:w-[55%] md:py-3">
                {statement.sql}
              </td>
              <td className="px-4 text-[14px] leading-relaxed text-ink-dim md:py-3">{statement.response}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
        <p className="text-[13px] text-ink-faint tabular-nums">
          Showing {shown.length} of {total} ·{' '}
          <a href={repoFile('evaluation/safety_sql.py')} className="underline decoration-line underline-offset-4 hover:text-ink-dim">
            the suite's source
          </a>
        </p>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="rounded-full border border-line px-3.5 py-1.5 text-[13px] font-medium text-ink transition-colors hover:bg-raised/60"
        >
          {expanded ? `Show ${PREVIEW_ROWS}` : `Show all ${total}`}
        </button>
      </div>
    </div>
  )
}

function MetricRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <tr className="border-t border-line">
      <th scope="row" className="px-4 py-2.5 text-left font-normal text-ink">
        {label}
      </th>
      <td className="px-4 py-2.5 text-right whitespace-nowrap text-ink tabular-nums">{children}</td>
    </tr>
  )
}

function RatioCell({ value }: { value: Ratio }) {
  const percent = Math.round((value.correct / value.total) * 100)
  return (
    <>
      {value.correct}/{value.total}
      <span className="ml-2 inline-block w-11 text-ink-faint">{percent}%</span>
    </>
  )
}

/** A shell line with its trailing comment dimmed, so the commands read first; on narrow screens the comment drops below. */
function CommandLine({ line }: { line: string }) {
  const hash = line.indexOf('  #')
  if (hash === -1) return <span className="block">{line}</span>
  const comment = line.slice(hash).trimStart()
  return (
    <span className="block max-sm:mb-1.5">
      {line.slice(0, hash)}
      <span className="max-sm:hidden">{line.slice(hash, line.length - comment.length)}</span>
      <span className="text-ink-faint max-sm:block">{comment}</span>
    </span>
  )
}

const THEMES: { value: ThemePreference; label: string; Icon: typeof SunIcon }[] = [
  { value: 'light', label: 'Light', Icon: SunIcon },
  { value: 'dark', label: 'Dark', Icon: MoonIcon },
  { value: 'system', label: 'System', Icon: MonitorIcon },
]

function Footer({ preference, onTheme }: { preference: ThemePreference; onTheme: (value: ThemePreference) => void }) {
  const links: [string, string][] = [
    ['Source', REPO_URL],
    ['README', `${REPO_URL}#readme`],
    ['Evaluation plan', repoFile('EVALUATION_PLAN.md')],
    ['Security', repoFile('SECURITY.md')],
    ['Contributing', repoFile('CONTRIBUTING.md')],
  ]

  return (
    <footer className="border-t border-line bg-sidebar">
      <div className="mx-auto flex max-w-[72rem] flex-col gap-8 px-4 py-10 sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-[28rem]">
          <div className="flex items-center gap-2.5">
            <span className="text-[14.5px] font-semibold tracking-tight">FrontierSQL</span>
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-ink-faint">
            Code under the{' '}
            <a href={repoFile('LICENSE')} className="underline decoration-line underline-offset-4 hover:text-ink-dim">
              MIT licence
            </a>
            . Demo data:{' '}
            <a href="https://github.com/owid/co2-data" className="underline decoration-line underline-offset-4 hover:text-ink-dim">
              Our World in Data, CO₂ and Greenhouse Gas Emissions
            </a>{' '}
            (CC BY 4.0).
          </p>
        </div>
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:gap-12">
          <ul className="grid grid-cols-2 gap-x-8 gap-y-2 text-[13.5px] sm:grid-cols-1">
            {links.map(([label, href]) => (
              <li key={label}>
                <a href={href} className="text-ink-dim transition-colors hover:text-ink">
                  {label}
                </a>
              </li>
            ))}
          </ul>
          <div role="radiogroup" aria-label="Theme" className="flex gap-1 self-start rounded-full border border-line bg-surface p-1">
            {THEMES.map(({ value, label, Icon }) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={preference === value}
                aria-label={label}
                title={label}
                onClick={() => onTheme(value)}
                className={`flex size-8 items-center justify-center rounded-full transition-colors ${preference === value ? 'bg-raised text-ink' : 'text-ink-faint hover:text-ink'}`}
              >
                <Icon size={16} />
              </button>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
