import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AgentResult } from '../api/types'
import { Verification } from './Verification'

const ASSUMPTIONS = [
  "Use the 'co2' column representing annual fossil and industry CO2 emissions (million tonnes).",
  "Only entities with entity_type='country' are considered.",
]

const RESULT: AgentResult = {
  status: 'success',
  question: 'Which 5 countries emitted the most CO2 in 2023?',
  resolved_question: null,
  answer: 'China emitted the most.',
  answer_source: 'llm',
  clarification_question: null,
  explanation: null,
  plan: {
    intent: 'ranking',
    tables: ['co2_emissions', 'countries'],
    metrics: ['co2'],
    filters: ['year = 2023', "entity_type = 'country'"],
    group_by: [],
    order_by: 'co2 desc',
    limit: 5,
    assumptions: ASSUMPTIONS,
  },
  sql: 'SELECT name, co2 FROM co2_emissions ORDER BY co2 DESC LIMIT 5',
  columns: ['name', 'co2'],
  rows: [['China', 11472.4]],
  column_units: {},
  chart_suggestion: null,
  chart: null,
  checks: [],
  error: null,
  trace: [],
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
    request_id: null,
  },
}

describe('Verification plan', () => {
  it('lists sentence-style assumptions one per line instead of joining them', () => {
    render(<Verification result={RESULT} defaultOpen />)

    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual(ASSUMPTIONS)
    expect(screen.queryByText(/\.;/)).toBeNull()
  })

  it('still joins short filter expressions on one line', () => {
    render(<Verification result={RESULT} defaultOpen />)

    expect(screen.getByText("year = 2023; entity_type = 'country'")).toBeTruthy()
  })
})
