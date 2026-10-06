import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as client from './api/client'
import { ApiError, type AgentResult, type DatabaseInfo } from './api/types'

vi.mock('./api/client')

const DATABASE: DatabaseInfo = {
  id: 'owid',
  name: 'owid_co2',
  dialect: 'postgresql',
  source: 'config',
  sampling: 'safe',
  status: 'ready',
  issues: [],
  allowed_columns: [],
}

function successResult(overrides: Partial<AgentResult> = {}): AgentResult {
  return {
    status: 'success',
    question: 'Which country emitted the most CO2 in 2023?',
    resolved_question: null,
    answer: 'China emitted the most CO2 in 2023, at 11,472 Mt.',
    answer_source: 'llm',
    clarification_question: null,
    explanation: null,
    plan: {
      intent: 'ranking',
      tables: ['co2_emissions'],
      metrics: ['co2'],
      filters: ['year = 2023'],
      group_by: [],
      order_by: 'co2 desc',
      limit: 1,
      assumptions: ['latest available year'],
    },
    sql: "SELECT country, co2 FROM co2_emissions WHERE year = 2023 ORDER BY co2 DESC LIMIT 1;",
    columns: ['country', 'co2'],
    rows: [['China', 11472.4]],
    column_units: { co2: 'Mt' },
    chart_suggestion: 'bar',
    chart: null,
    checks: [],
    error: null,
    trace: [
      { step: 'sql_generation', status: 'success', duration_ms: 340, detail: {} },
      { step: 'sql_validation', status: 'success', duration_ms: 2, detail: {} },
      { step: 'query_execution', status: 'success', duration_ms: 41, detail: {} },
    ],
    metadata: {
      database_id: 'owid',
      dialect: 'postgresql',
      model: 'gemini-3.6-flash',
      prompt_version: 'sql-generator/3',
      tables_used: ['co2_emissions'],
      execution_time_ms: 41,
      row_count: 1,
      truncated: false,
      retry_count: 0,
      request_id: 'req-1',
    },
    ...overrides,
  }
}

const PROFILE = {
  database_id: 'owid',
  dialect: 'postgresql',
  sampling: 'safe' as const,
  fingerprint: 'x',
  tables: [],
  relationships: [],
  notes: [],
}

beforeEach(() => {
  vi.mocked(client.fetchDatabases).mockResolvedValue([DATABASE])
  vi.mocked(client.fetchProfile).mockResolvedValue(PROFILE)
  sessionStorage.clear()
  localStorage.clear()
})

async function ask(question: string) {
  await userEvent.type(await screen.findByLabelText(/ask a question/i), `${question}{Enter}`)
}

async function openSettings() {
  await userEvent.click(await screen.findByRole('button', { name: /settings and database/i }))
}

describe('App', () => {
  it('shows the safety promise and the connected database before any question is asked', async () => {
    render(<App />)
    expect(await screen.findByText(/checked as a single read-only query before it runs/i)).toBeInTheDocument()
    expect(await screen.findAllByText('owid_co2')).not.toHaveLength(0)
  })

  it('offers example questions only on the demo database, and runs one when clicked', async () => {
    vi.mocked(client.fetchProfile).mockResolvedValue({
      ...PROFILE,
      tables: [{ schema_name: 'public', name: 'co2_emissions', kind: 'table', comment: null, estimated_rows: null, columns: [] }],
    })
    vi.mocked(client.runQuery).mockResolvedValue(successResult())
    render(<App />)

    await userEvent.click(await screen.findByRole('button', { name: /which 5 countries emitted the most co2 in 2023/i }))

    await waitFor(() =>
      expect(client.runQuery).toHaveBeenCalledWith(expect.objectContaining({ question: 'Which 5 countries emitted the most CO2 in 2023?' }), expect.any(AbortSignal)),
    )
  })

  it('does not offer demo examples on another database', async () => {
    render(<App />)
    expect(await screen.findByText(/what would you like to know/i)).toBeInTheDocument()
    await waitFor(() => expect(client.fetchProfile).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /which 5 countries/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /see what's in this database/i })).toBeInTheDocument()
  })

  it('asks a question and renders the answer, result, and the SQL and trace behind it', async () => {
    vi.mocked(client.runQuery).mockResolvedValue(successResult())
    render(<App />)

    await ask('Which country emitted the most CO2 in 2023?')

    expect(await screen.findByText(/China emitted the most CO2 in 2023/)).toBeInTheDocument()
    expect(screen.getByText('China')).toBeInTheDocument()
    expect(screen.getByText(/Assumed: latest available year/)).toBeInTheDocument()
    expect(screen.queryByText(/SELECT country, co2 FROM co2_emissions/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /validated read-only sql/i }))
    expect(screen.getByText(/SELECT country, co2 FROM co2_emissions/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /execution trace: sql_generation 340ms success/ })).toBeInTheDocument()
    expect(client.runQuery).toHaveBeenCalledWith(
      expect.objectContaining({ question: 'Which country emitted the most CO2 in 2023?', database_id: 'owid' }),
      expect.any(AbortSignal),
    )
  })

  it('shows a clarification question without SQL or a result grid', async () => {
    vi.mocked(client.runQuery).mockResolvedValue(
      successResult({
        status: 'needs_clarification',
        clarification_question: 'Which year do you mean?',
        sql: null,
        answer: null,
        columns: [],
        rows: [],
        trace: [],
      }),
    )
    render(<App />)
    await ask('Who emits the most?')

    expect(await screen.findByText('Which year do you mean?')).toBeInTheDocument()
  })

  it('shows a rate-limit error with a retry affordance', async () => {
    vi.mocked(client.runQuery).mockRejectedValue(new ApiError('Too many questions. Try again in 30 s.', 429, 30, 'req-2'))
    render(<App />)
    await ask('Another question')

    expect(await screen.findByText(/rate limited/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry in 30s/i })).toBeDisabled()
  })

  it('lets the user switch databases when more than one is configured', async () => {
    const second: DatabaseInfo = { ...DATABASE, id: 'other', name: 'other_db' }
    vi.mocked(client.fetchDatabases).mockResolvedValue([DATABASE, second])
    vi.mocked(client.runQuery).mockResolvedValue(successResult())
    render(<App />)

    await openSettings()
    await userEvent.click(await screen.findByRole('menuitemradio', { name: /other_db/ }))
    await ask('A question')

    await waitFor(() => expect(client.runQuery).toHaveBeenCalledWith(expect.objectContaining({ database_id: 'other' }), expect.any(AbortSignal)))
  })

  it('opens the connect, schema and help dialogs from the settings menu', async () => {
    render(<App />)

    await openSettings()
    await userEvent.click(screen.getByRole('menuitem', { name: /connect a database/i }))
    expect(await screen.findByLabelText(/connection url/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByLabelText(/connection url/i)).not.toBeInTheDocument()

    await openSettings()
    await userEvent.click(screen.getByRole('menuitem', { name: /how it works/i }))
    expect(await screen.findByText(/asking questions/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^close$/i }))

    vi.mocked(client.fetchProfile).mockResolvedValue({
      database_id: 'owid',
      dialect: 'postgresql',
      sampling: 'safe',
      fingerprint: 'x',
      tables: [],
      relationships: [],
      notes: [],
    })
    await openSettings()
    await userEvent.click(screen.getByRole('menuitem', { name: /browse schema/i }))
    expect(await screen.findByText(/0 tables, sampling: safe/)).toBeInTheDocument()
  })

  it('lists saved chats in the sidebar and reopens one without re-running it', async () => {
    const result = successResult()
    const now = Date.now()
    localStorage.setItem(
      'ai-sql-analyst:chats',
      JSON.stringify([{ id: 'c1', title: result.question, createdAt: now, updatedAt: now, turns: [{ id: 't1', question: result.question, result }] }]),
    )
    render(<App />)

    await userEvent.click(await screen.findByRole('button', { name: result.question }))

    expect(await screen.findByText(/China emitted the most CO2 in 2023/)).toBeInTheDocument()
    expect(client.runQuery).not.toHaveBeenCalled()
  })

  it('keeps each question in its own chat, sends follow-up history, and starts fresh on New chat', async () => {
    vi.mocked(client.runQuery).mockResolvedValue(successResult())
    render(<App />)

    await ask('First question')
    await screen.findByText(/China emitted the most CO2 in 2023/)
    await ask('And in 2020?')
    await waitFor(() => expect(client.runQuery).toHaveBeenCalledTimes(2))
    expect(vi.mocked(client.runQuery).mock.calls[1][0].history).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: /^new chat$/i }))
    expect(await screen.findByText(/what would you like to know/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'First question' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /delete chat: first question/i }))
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    expect(screen.queryByRole('button', { name: 'First question' })).not.toBeInTheDocument()
  })

  it('stops waiting for an answer and offers to ask again', async () => {
    vi.mocked(client.runQuery).mockImplementation(
      (_body, signal) => new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new ApiError('aborted', 0)))),
    )
    render(<App />)
    await ask('A slow question')

    await userEvent.click(await screen.findByRole('button', { name: /stop waiting for the answer/i }))

    expect(await screen.findByText(/stopped before an answer came back/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ask again/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send question/i })).toBeInTheDocument()
  })

  it('names a provider rate limit in plain language with its recovery', async () => {
    vi.mocked(client.runQuery).mockResolvedValue(
      successResult({ status: 'error', error: { category: 'provider', message: 'LLM provider returned HTTP 429', code: null }, answer: null, columns: [], rows: [] }),
    )
    render(<App />)
    await ask('Anything')

    expect(await screen.findByText(/model provider is rate-limiting requests/i)).toBeInTheDocument()
    expect(screen.getByText(/wait a minute, then retry/i)).toBeInTheDocument()
  })
})
