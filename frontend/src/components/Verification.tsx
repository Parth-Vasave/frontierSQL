import { useId, useState, type ReactNode } from 'react'
import type { AgentResult, QueryPlan, ResultCheck } from '../api/types'
import { formatMs } from '../lib/format'
import { CopyButton } from './CopyButton'
import { AlertIcon, CheckIcon, ChevronIcon, ShieldCheckIcon } from './icons'
import { totalMs } from '../lib/trace'
import { TraceStrip } from './TraceStrip'

/**
 * The answer's provenance as one line — validated, checks, repairs, time — that opens into the
 * plan, the exact SQL that ran, the step timings and every check. Closed by default; never empty.
 */
export function Verification({ result, defaultOpen = false }: { result: AgentResult; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = useId()
  const validated = result.trace.some((e) => e.step === 'sql_validation' && e.status === 'success')
  const warnings = result.checks.filter((c) => c.severity === 'warning').length
  const elapsed = totalMs(result.trace)
  const failed = result.status === 'error'

  const parts: string[] = []
  const time = elapsed > 0 ? formatMs(elapsed) : null
  if (result.checks.length > 0) {
    parts.push(warnings > 0 ? `${warnings} warning${warnings === 1 ? '' : 's'}` : `${result.checks.length} check${result.checks.length === 1 ? '' : 's'} passed`)
  }
  if (result.metadata.retry_count > 0) parts.push(`repaired ${result.metadata.retry_count}×`)

  const headline = failed ? 'What was attempted' : validated ? 'Validated read-only SQL' : 'How this was answered'
  const Icon = failed || warnings > 0 ? AlertIcon : ShieldCheckIcon
  const iconColor = failed || warnings > 0 ? 'text-accent' : validated ? 'text-ok' : 'text-ink-faint'

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        className="-ml-2 flex max-w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-[13.5px] text-ink-dim transition-colors hover:bg-raised hover:text-ink"
      >
        <Icon size={16} className={`shrink-0 ${iconColor}`} />
        <span className="truncate">
          <span className="font-medium text-ink">{headline}</span>
          {parts.length > 0 && <span className="text-ink-faint"> · {parts.join(' · ')}</span>}
          {time && <span className="font-mono text-[12.5px] text-ink-faint tabular-nums"> · {time}</span>}
        </span>
        <ChevronIcon size={15} className={`shrink-0 text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {open && (
        <div id={panelId} className="rise-in mt-2 flex flex-col gap-5 rounded-xl border border-line px-4 py-4">
          {result.plan && (
            <Section title="Plan">
              <PlanList plan={result.plan} />
            </Section>
          )}
          {result.sql && (
            <Section title="SQL that ran" action={<CopyButton text={result.sql} label="Copy SQL" />}>
              <pre className="overflow-x-auto rounded-lg bg-code px-3 py-2.5 font-mono text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
                {result.sql}
              </pre>
            </Section>
          )}
          {result.trace.length > 0 && (
            <Section title="Steps">
              <TraceStrip trace={result.trace} retryCount={result.metadata.retry_count} />
            </Section>
          )}
          {result.checks.length > 0 && (
            <Section title="Result checks">
              <ChecksList checks={result.checks} />
            </Section>
          )}
          <p className="text-[12.5px] text-ink-faint">
            {result.metadata.model && <>Model {result.metadata.model} · </>}
            {result.metadata.prompt_version} · answer written by {result.answer_source === 'template' ? 'template (no LLM)' : 'LLM, numbers checked against the rows'}
            {result.metadata.request_id && <> · request {result.metadata.request_id}</>}
          </p>
        </div>
      )}
    </div>
  )
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex min-h-7 items-center justify-between gap-2">
        <h4 className="text-[13px] font-medium text-ink-dim">{title}</h4>
        {action}
      </div>
      {children}
    </section>
  )
}

function PlanList({ plan }: { plan: QueryPlan }) {
  const rows: [string, ReactNode][] = [['Intent', plan.intent]]
  if (plan.tables.length) rows.push(['Tables', plan.tables.join(', ')])
  if (plan.metrics.length) rows.push(['Metrics', plan.metrics.join(', ')])
  if (plan.filters.length) rows.push(['Filters', plan.filters.join('; ')])
  if (plan.group_by.length) rows.push(['Grouped by', plan.group_by.join(', ')])
  if (plan.order_by) rows.push(['Ordered by', plan.order_by])
  if (plan.limit) rows.push(['Limit', String(plan.limit)])
  // Assumptions are usually whole sentences: one per line, since joining them would print ".;".
  if (plan.assumptions.length) {
    rows.push([
      'Assumptions',
      <ul key="assumptions" className="flex flex-col gap-1">
        {plan.assumptions.map((assumption, index) => (
          <li key={index}>{assumption}</li>
        ))}
      </ul>,
    ])
  }

  return (
    <dl className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-4 gap-y-1 text-[13.5px]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-ink-faint">{label}</dt>
          <dd className="text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function ChecksList({ checks }: { checks: ResultCheck[] }) {
  return (
    <ul className="flex flex-col gap-1.5 text-[13.5px]">
      {checks.map((check, index) => (
        <li key={index} className="flex items-start gap-2">
          {check.severity === 'warning' ? (
            <AlertIcon size={15} className="mt-0.5 shrink-0 text-accent" />
          ) : (
            <CheckIcon size={15} className="mt-0.5 shrink-0 text-ok" />
          )}
          <span>
            <span className="font-mono text-[12.5px] text-ink">{check.code}</span>{' '}
            <span className="text-ink-dim">{check.message}</span>
            {check.column && <span className="text-ink-faint"> (column {check.column})</span>}
            {check.repairable && <span className="text-ink-faint"> — fed back for one repair attempt</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Warning-severity checks stay visible beside the answer; they never hide behind the summary. */
export function CheckWarnings({ checks }: { checks: ResultCheck[] }) {
  const warnings = checks.filter((c) => c.severity === 'warning')
  if (warnings.length === 0) return null
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-accent/40 bg-accent-soft px-3.5 py-2.5 text-[14px]" role="note">
      {warnings.map((check, index) => (
        <p key={index} className="flex items-start gap-2 text-ink">
          <AlertIcon size={16} className="mt-0.5 shrink-0 text-accent" />
          <span>
            {check.message}
            {check.column && <span className="text-ink-dim"> (column {check.column})</span>}
          </span>
        </p>
      ))}
    </div>
  )
}
