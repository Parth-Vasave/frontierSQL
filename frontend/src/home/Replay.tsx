import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import type { AgentResult } from '../api/types'
import { Prose, Working } from '../components/ChatTurn'
import { CopyButton } from '../components/CopyButton'
import { ArrowUpIcon, DatabaseIcon, NewChatIcon, RetryIcon, StopIcon } from '../components/icons'
import { ResultGrid } from '../components/ResultGrid'
import { Verification } from '../components/Verification'
import { chatTitle } from '../lib/chats'
import { totalMs } from '../lib/trace'

const ResultChart = lazy(() => import('../components/ResultChart').then((m) => ({ default: m.ResultChart })))

// Replay steps. Every answer part is laid out from the start and only revealed, so the window
// never changes height while it plays and the page below it never jumps.
const IDLE = 0
const TYPING = 1
const WAITING = 2
const ANSWERED = 3
const TABLE = 4
const DONE = 5

const TYPE_MS_PER_CHAR = 30
const PAUSE_BEFORE_SEND_MS = 450
const REVEAL_GAP_MS = 320

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * The chat app, replaying one recorded answer when it scrolls into view: the question is typed and
 * sent, the agent works for as long as the recorded steps took, and the answer appears. With
 * reduced motion, or without IntersectionObserver, it shows the finished answer straight away.
 */
export function Replay({ result, recordedAt }: { result: AgentResult; recordedAt: string }) {
  const question = result.question
  const [step, setStep] = useState(() => (typeof IntersectionObserver === 'undefined' || prefersReducedMotion() ? DONE : IDLE))
  const [typed, setTyped] = useState(0)
  const [run, setRun] = useState(0)
  const composerRow = useRef<HTMLDivElement>(null)

  // Start the first run once the composer is fully on screen, so the visitor sees the question typed.
  useEffect(() => {
    if (step !== IDLE || !composerRow.current) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setStep(TYPING)
          observer.disconnect()
        }
      },
      { threshold: 1 },
    )
    observer.observe(composerRow.current)
    return () => observer.disconnect()
  }, [step])

  useEffect(() => {
    if (step === TYPING) {
      if (typed < question.length) {
        const timer = setTimeout(() => setTyped((n) => n + 1), TYPE_MS_PER_CHAR)
        return () => clearTimeout(timer)
      }
      const timer = setTimeout(() => setStep(WAITING), PAUSE_BEFORE_SEND_MS)
      return () => clearTimeout(timer)
    }
    if (step === WAITING) {
      const timer = setTimeout(() => setStep(ANSWERED), totalMs(result.trace))
      return () => clearTimeout(timer)
    }
    if (step === ANSWERED || step === TABLE) {
      const timer = setTimeout(() => setStep((s) => s + 1), REVEAL_GAP_MS)
      return () => clearTimeout(timer)
    }
  }, [step, typed, question.length, result.trace, run])

  function replay() {
    setTyped(0)
    setStep(prefersReducedMotion() ? DONE : TYPING)
    setRun((n) => n + 1)
  }

  const sent = step >= WAITING
  const draft = step === TYPING ? question.slice(0, typed) : ''

  return (
    <figure className="flex flex-col gap-3">
      <div className="flex overflow-hidden rounded-2xl border border-line bg-surface text-left shadow-[var(--shadow-menu)]"
      >
        <aside inert className="hidden w-[15.5rem] shrink-0 flex-col border-r border-line bg-sidebar md:flex" aria-hidden="true">
          <div className="flex items-center gap-2.5 px-4.5 pt-4 pb-3">
            <span className="text-[14.5px] font-semibold tracking-tight">FrontierSQL</span>
          </div>
          <div className="px-3">
            <p className="flex items-center gap-3 rounded-xl px-2.5 py-2 text-[14px] font-medium">
              <NewChatIcon size={18} className="text-ink-dim" />
              New chat
            </p>
          </div>
          <div className="mt-3 flex-1 px-3">
            {sent ? (
              <>
                <p className="px-2.5 pb-1 text-[12px] font-medium text-ink-faint">Today</p>
                <p className="truncate rounded-xl bg-raised py-2 pr-3 pl-2.5 text-[14px]">
                  {step === WAITING && <span className="pulse-dot mr-2 inline-block size-1.5 rounded-full bg-ink-dim align-middle" />}
                  {chatTitle(question)}
                </p>
              </>
            ) : (
              <p className="px-2.5 py-2 text-[13.5px] leading-relaxed text-ink-faint">Your chats will appear here.</p>
            )}
          </div>
          <div className="flex items-center gap-3 border-t border-line px-4 py-3">
            <span className="relative flex size-8 shrink-0 items-center justify-center rounded-full bg-raised text-ink-dim">
              <DatabaseIcon size={17} />
              <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-sidebar bg-ok" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-[14px] font-medium">Default database</span>
              <span className="block text-[12.5px] text-ink-faint">postgresql · read-only</span>
            </span>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div inert aria-hidden="true" className="flex h-12 shrink-0 items-center px-5">
            {sent && <p className="truncate text-[14px] text-ink-dim">{chatTitle(question)}</p>}
          </div>

          <div className="relative mx-auto w-full max-w-3xl flex-1 px-4 pb-4 sm:px-8">
            {!sent && (
              <div inert aria-hidden="true" className="absolute inset-x-4 top-[22%] text-center sm:inset-x-8">
                <p className="text-[24px] leading-tight font-semibold tracking-tight sm:text-[28px]">What would you like to know?</p>
                <p className="mx-auto mt-3 max-w-[30rem] text-[15px] leading-relaxed text-pretty text-ink-dim">
                  Ask <span className="font-medium text-ink">Default database</span> a question in plain language. The SQL behind every
                  answer is checked as a single read-only query before it runs.
                </p>
              </div>
            )}
            <Reveal shown={sent} className="flex justify-end pt-2">
              <p className="max-w-[85%] rounded-3xl bg-raised px-4 py-2.5 text-[15px] leading-relaxed text-ink sm:max-w-[75%]">{question}</p>
            </Reveal>

            <div className="relative mt-5 flex flex-col gap-4">
              {step === WAITING && (
                <div className="absolute top-0 left-0">
                  <Working />
                </div>
              )}
              <Reveal shown={step >= ANSWERED} className="flex flex-col gap-4">
                <Verification key={run} result={result} />
                {result.answer && <Prose>{result.answer}</Prose>}
              </Reveal>
              <Reveal shown={step >= TABLE}>
                <ResultGrid
                  columns={result.columns}
                  rows={result.rows}
                  units={result.column_units}
                  executionTimeMs={result.metadata.execution_time_ms}
                  truncated={result.metadata.truncated}
                />
              </Reveal>
              {result.chart && result.chart.type !== 'none' && (
                <Reveal shown={step >= DONE}>
                  <Suspense fallback={<div className="h-72 rounded-xl border border-line" aria-hidden="true" />}>
                    <ResultChart chart={result.chart} columns={result.columns} rows={result.rows} units={result.column_units} />
                  </Suspense>
                </Reveal>
              )}
              {result.answer && (
                <Reveal shown={step >= DONE} className="-mt-1 -ml-2 flex">
                  <CopyButton text={result.answer} label="Copy answer" />
                </Reveal>
              )}
            </div>
          </div>

          <div ref={composerRow} inert aria-hidden="true" className="mx-auto w-full max-w-3xl px-3 pb-4 sm:px-8">
            <div className="flex items-center gap-2 rounded-[1.75rem] border border-line bg-surface py-2 pr-2 pl-5 shadow-[var(--shadow-composer)]">
              <p className={`min-w-0 flex-1 truncate py-1.5 text-[15.5px] leading-6 ${draft ? 'text-ink' : 'text-ink-faint'}`}>
                {draft || (sent ? 'Ask a follow-up' : 'Ask a question about your data')}
                {step === TYPING && <span className="ml-px inline-block h-[1.1em] w-px translate-y-[0.2em] bg-accent" />}
              </p>
              <span
                className={`flex size-9 shrink-0 items-center justify-center rounded-full bg-ink text-surface transition-opacity ${draft || step === WAITING ? '' : 'opacity-25'}`}
              >
                {step === WAITING ? <StopIcon size={18} /> : <ArrowUpIcon size={18} strokeWidth={2.25} />}
              </span>
            </div>
          </div>
        </div>
      </div>

      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-1 text-[13px] leading-relaxed text-ink-faint">
        <span className="max-w-[44rem] text-pretty">
          A real answer from the demo database, recorded {recordedAt} with {result.metadata.model} and replayed at its
          recorded speed. Open the line above the answer to see the plan, the SQL that ran and each step's timing.
        </span>
        <button
          type="button"
          onClick={replay}
          className="flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] text-ink-dim transition-colors hover:bg-raised hover:text-ink"
        >
          <RetryIcon size={15} />
          Replay
        </button>
      </figcaption>
    </figure>
  )
}

function Reveal({ shown, className = '', children }: { shown: boolean; className?: string; children: ReactNode }) {
  return (
    <div
      aria-hidden={!shown}
      className={`transition-[opacity,translate,visibility] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${shown ? 'visible translate-y-0 opacity-100' : 'invisible translate-y-1 opacity-0'} ${className}`}
    >
      {children}
    </div>
  )
}
