// Mirrors backend/app/api/schemas.py, backend/app/agent/controller.py, chart.py and
// result_checks.py field for field. Keep in sync by hand; there is no shared schema yet.

export type ConnectionStatus = 'ready' | 'rejected' | 'unavailable'
export type SamplingMode = 'off' | 'safe' | 'full'

export interface DatabaseInfo {
  id: string
  name: string
  dialect: string
  source: 'config' | 'ui'
  sampling: SamplingMode
  status: ConnectionStatus
  issues: string[]
  allowed_columns: string[]
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  databases: Record<string, ConnectionStatus>
}

/** One earlier turn of the conversation, sent back to the server (it keeps no state). */
export interface Turn {
  question: string
  sql: string | null
  answer: string | null
}

export type QueryIntent = 'lookup' | 'aggregate' | 'ranking' | 'trend' | 'comparison' | 'other'

export interface QueryPlan {
  intent: QueryIntent
  tables: string[]
  metrics: string[]
  filters: string[]
  group_by: string[]
  order_by: string | null
  limit: number | null
  assumptions: string[]
}

export type ChartType = 'stat' | 'bar' | 'line' | 'scatter' | 'none'

export interface ChartSpec {
  type: ChartType
  x: string | null
  y: string[]
  series: string | null
  label: string | null
  orientation: 'vertical' | 'horizontal' | null
  reason: string
}

export interface ResultCheck {
  code: string
  severity: 'info' | 'warning'
  message: string
  column: string | null
  repairable: boolean
}

export type TraceStatus = 'success' | 'failed' | 'skipped'

export interface TraceEvent {
  step: string
  status: TraceStatus
  duration_ms: number
  detail: Record<string, unknown>
}

export interface QueryError {
  category: string
  message: string
  code: string | null
  retry_after_seconds?: number | null
}

export interface QueryMetadata {
  database_id: string
  dialect: string
  model: string
  prompt_version: string
  tables_used: string[]
  execution_time_ms: number | null
  row_count: number | null
  truncated: boolean
  retry_count: number
  request_id: string | null
}

export type AgentStatus = 'success' | 'needs_clarification' | 'unanswerable' | 'error'
export type AnswerSource = 'llm' | 'template'

export interface AgentResult {
  status: AgentStatus
  question: string
  resolved_question: string | null
  answer: string | null
  answer_source: AnswerSource | null
  clarification_question: string | null
  explanation: string | null
  plan: QueryPlan | null
  sql: string | null
  columns: string[]
  rows: unknown[][]
  column_units: Record<string, string>
  chart_suggestion: string | null
  chart: ChartSpec | null
  checks: ResultCheck[]
  error: QueryError | null
  trace: TraceEvent[]
  metadata: QueryMetadata
}

export interface QueryRequest {
  question: string
  database_id?: string | null
  history?: Turn[]
}

export interface AddDatabaseRequest {
  name: string
  url: string
  sampling?: SamplingMode
  schemas?: string[] | null
}

export interface ValueHints {
  null_fraction: number | null
  min: unknown
  max: unknown
  categories: string[] | null
  examples: string[] | null
}

export interface ColumnProfile {
  name: string
  type: string
  nullable: boolean
  comment: string | null
  primary_key: boolean
  sensitive: boolean
  hints: ValueHints | null
}

export interface Relationship {
  from_table: string
  from_columns: string[]
  to_table: string
  to_columns: string[]
  inferred: boolean
}

export interface TableProfile {
  schema_name: string
  name: string
  kind: string
  comment: string | null
  estimated_rows: number | null
  columns: ColumnProfile[]
}

export interface DatabaseProfile {
  database_id: string
  dialect: string
  sampling: SamplingMode
  fingerprint: string
  tables: TableProfile[]
  relationships: Relationship[]
  notes: string[]
}

/** A transport-level failure: the request never reached the agent, or FastAPI itself rejected it
 *  (rate limit, no database ready, no LLM configured, unknown database). Distinct from
 *  AgentResult.status === 'error', which is a real agent run that ended in a reported failure. */
export class ApiError extends Error {
  httpStatus: number
  retryAfterSeconds: number | null
  requestId: string | null

  constructor(message: string, httpStatus: number, retryAfterSeconds: number | null = null, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.httpStatus = httpStatus
    this.retryAfterSeconds = retryAfterSeconds
    this.requestId = requestId
  }
}
