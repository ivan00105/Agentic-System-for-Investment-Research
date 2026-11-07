export type Mode = 'fresh' | 'frozen' | 'replay'
export type View = 'research' | 'baseline' | 'discovery' | 'history' | 'setup'
export interface Screen { sector: string; min_operating_margin: string; limit: number }
// Legacy spending fields remain readable for saved requests and exact-key recovery; new checks omit them.
export interface RunRequest { kind: 'research' | 'discovery'; mode: Mode; ticker: string | null; cutoff: string; source_run_id: string | null; screen: Screen | null; model_analysis?: boolean; connection_check?: 'sec' | 'model' | null; spending_limit_usd?: string | null; provider_limit_confirmed?: boolean }
export interface Metric { id: string; label: string; value: string | null; unit: 'USD' | 'ratio'; period: string; formula: string | null; inputs: string[]; evidence_ids: string[]; unavailable_reason: string | null }
export interface Claim { id: string; statement: string; kind: string; status: string; evidence_ids: string[]; version: number }
export interface Review { claim_id: string; original: string; objection: string; check: string; revised: string | null; disposition: string; evidence_ids: string[] }
export type ReviewStatus = 'not_requested' | 'pending' | 'completed' | 'unavailable' | 'failed' | 'not_recorded'
export interface CompanyReport { ticker: string; company: string; support: string; summary: string; metrics: Metric[]; claims: Claim[]; reviews: Review[]; review_status?: ReviewStatus; review_error?: string | null; forecast: { status: string; probability: null; benchmark: string; horizon: string; model_version: string | null; reason: string }; limitations: string[]; source_limitations?: string[] | null }
export interface Candidate { ticker: string; company: string; sector: string; eligibility: 'pass' | 'fail' | 'unknown'; reason: string; operating_margin: string | null; selected: boolean }
export interface ModelCall { role: string; provider: string; requested_model: string; returned_model: string | null; response_id: string | null; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; cost_usd: string | null; reasoning_tokens?: number | null; provider_status?: string | null; incomplete_reason?: 'max_output_tokens' | 'content_filter' | 'other' | null; status: 'running' | 'completed' | 'failed' | 'incomplete'; error_code: string | null; error_message?: string | null; output_snapshot_hash?: string | null }
export interface ModelRun { provider: string; model: string | null; schema_version: string; max_output_tokens: number | null }
export interface Report { model_run?: ModelRun | null; model_calls?: ModelCall[];  title: string; synthetic: boolean; companies: CompanyReport[]; candidates: Candidate[]; ranking: string | null; limitations: string[] }
export interface Action { sequence: number; at: string; role: string; message: string }
export interface Run { id: string; request: RunRequest; status: string; created_at: string; updated_at: string; stage: string; actions: Action[]; report: Report | null; error: string | null; synthetic: boolean; label?: string | null; archived?: boolean }
export type HistoryItem = Omit<Run, 'actions' | 'report'>
export interface Evidence { id: string; ticker: string; title: string; excerpt: string; source_url: string | null; available_at: string; retrieved_at: string; period: string; locator: string; snapshot_hash: string; synthetic: boolean }
export interface ConnectionInfo { configuration_error?: string | null; configured: boolean; provider: string; model: string | null; check: {status: 'not_tested' | 'passed' | 'failed'; checked_at: string | null; run_id: string | null; message: string | null} }
export interface Config { companies: {ticker: string; name: string; sector: string}[]; fixture_cutoff: string; sec_configured: boolean; model_configured: boolean; model: string | null; forecast_available: boolean; connections?: {sec: ConnectionInfo; model: ConnectionInfo} }

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`/api${path}`, { ...options, signal: options?.signal ?? AbortSignal.timeout(15000) }) }
  catch { throw new ApiError('Connection interrupted. Check that the local server is running, then retry. Your saved run will not restart.', 0) }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(body?.error?.message ?? `Request failed (${response.status}). Please retry.`, response.status)
  return body as T
}
export const api = {
  config: () => request<Config>('/config'),
  run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
  history: (offset = 0, archived = false) => request<{items: HistoryItem[]; total: number}>(`/runs?archived=${archived}&limit=30&offset=${offset}`),
  updateRun: (id: string, update: {label?: string | null; archived?: boolean}) => request<Run>(`/runs/${encodeURIComponent(id)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(update)}),
  evidence: (run: string, id: string) => request<Evidence>(`/runs/${encodeURIComponent(run)}/evidence/${encodeURIComponent(id)}`),
  submit: async (body: RunRequest, key: string): Promise<Run> => {
    const result = await request<unknown>('/runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}, body: JSON.stringify(body)})
    // A successful HTTP status alone does not identify an accepted run. Keep the
    // original request/key recoverable when a proxy or interrupted body loses it.
    const run = result as Partial<Run> | null
    if (!run || typeof run !== 'object' || typeof run.id !== 'string' || !run.id.trim() || run.request?.kind !== body.kind) {
      throw new ApiError('The submission response was incomplete. Its outcome is unknown. Recover the same submission to find its saved result.', 0)
    }
    return run as Run
  },
}
export const active = (run: Run | null) => !!run && ['queued', 'running'].includes(run.status)
export const modeLabel: Record<Mode, string> = {fresh: 'Research with latest available sources', frozen: 'Review saved sources again', replay: 'Open saved report'}
export function progressLabel(run: Run) {
  if (run.status === 'queued') return 'Waiting to begin'
  if (run.status === 'completed') return 'Saved report ready'
  if (run.status === 'failed') return 'Available results have been saved'
  if (run.status === 'budget_exhausted') return 'Research limit reached; available results have been saved'
  if (run.status === 'interrupted') return 'Stopped before research finished; available results have been saved'
  const role = [...run.actions].reverse().find(action => action.role !== 'Usage')?.role
  if (role === 'Filings') return 'Gathering company evidence'
  if (role === 'Quantitative' || role === 'Calculation') return 'Checking the financial figures'
  if (role === 'Filings interpretation') return 'Reviewing the company evidence'
  if (role?.startsWith('Critic:')) return 'Checking claims against the evidence'
  if (role === 'Tool check') return 'Checking a review concern'
  if (role === 'Coordinator' || role === 'Screen') return 'Checking company selection'
  if (role === 'Review') return 'Saving review results'
  return 'Research in progress'
}
export const percentage = (value: string | null) => value === null ? 'Unavailable' : new Intl.NumberFormat('en-US', {style: 'percent', maximumFractionDigits: 1}).format(Number(value))
export const metricValue = (metric: Metric) => metric.value === null ? 'Unavailable' : metric.unit === 'ratio' ? percentage(metric.value) : new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(Number(metric.value))
export const stamp = (value: string) => new Intl.DateTimeFormat('en-GB', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC'}).format(new Date(value)) + ' UTC'

export const investigationLabel = (request: RunRequest) => request.connection_check === 'sec' ? 'SEC connection check' : request.connection_check === 'model' ? 'Model connection check' : modeLabel[request.mode]

// Agent runs (conditions B, C, D, and Discover), saved as trace files and served by /api/agent-runs.
export type Condition = 'B' | 'C' | 'D'
export interface AgentTotals { model_calls: number; tool_calls: number; total_tokens: number; cached_tokens: number | null; cost: number | null }
export interface AgentRunSummary { run_id: string; status: string; question?: string | null; preferences?: string | null; condition?: string | null; cutoff?: string | null; model?: string | null; started_at?: string | null; ended_at?: string | null; totals?: AgentTotals | null }
// A model step is one line ("Step 4 · 10 calculations · all OK"); its tool calls fold under it as `details`.
export interface ProgressDetail { seq: number | null; text: string; status: string | null }
export interface ProgressLine { seq: number | null; at: string | null; kind?: string | null; role?: string | null; text: string; step?: number | null; details?: ProgressDetail[] }
export interface DiscoverTerm { term: string; definition: string; question: string; options?: {definition: string; recommended: boolean}[] }
export interface DiscoverQuestionSet { terms: DiscoverTerm[]; shown: string[]; spec?: Record<string, unknown> | null }
export interface AgentProgress extends AgentRunSummary { progress: ProgressLine[]; questions?: DiscoverQuestionSet | null }
export interface AgentClaim { text: string; status: 'cited' | 'qualified'; citations: number[]; flags: string[] }
export interface AgentSection { key: string; heading: string; status: 'cited' | 'qualified' | 'abstained'; claims: AgentClaim[] }
export interface AgentObjection { claim: string; version: number; where?: string | null; issue: string; meaning?: string | null; material: boolean; problem: string; outcome: string; explanation: string | null; notes?: string[] }
export interface AgentSource { n: number; id: string; text: string; url: string | null; kind?: string | null; group?: string; label?: string }
export interface KeyNumber { id: string; company: string | null; metric: string; period: string; value: string; change: string | null; change_id: string | null }
export interface ChartPoint { end: string; value: number; label: string; ids: string[] }
export interface CompanyChart { cik: string; company: string; revenue: ChartPoint[]; margin: {label: string | null; points: ChartPoint[]}; price: {id: string; ticker: string | null; source: string | null; points: [string, number][]} | null }
export interface DiscoverCandidate { rank: number; cik: string; name: string | null; tickers?: string[]; outcome: string; verdict: string | null; run_id: string | null; lines: {state: string; text: string; ids: string[]}[]; answer: string | null; citations?: string[]; warnings?: string[]; run_status?: string | null }
export interface DiscoverResult { spec: string[] | null; counts: Record<string, number>; candidates: DiscoverCandidate[]; notes?: string[] }
export interface RawFigure { id: string; kind: 'fact' | 'calc'; cik: string | null; company: string | null; label: string; period: string; value: string | null; unit: string | null; shown: string; start: string | null; end: string | null; formula: string | null; inputs: Record<string, string>; tag: string | null; form: string | null; accession: string | null; filed: string | null; url: string | null; notes: string[]; reason: string | null }
export interface AgentReport extends AgentRunSummary { status_label: string; error: string | null; sections: AgentSection[]; limitations: string[]; flags: string[]; objections: AgentObjection[]; sources: AgentSource[]; figures?: {table: KeyNumber[]; charts: CompanyChart[]} | null; raw?: RawFigure[]; discover?: DiscoverResult | null; markdown: string }
export interface AgentRecord { id: string; kind: string | null; group: string; title: string; excerpt: string; available_at: string | null; url: string | null; rows: {label: string; value: string}[]; links: {id: string; label: string}[] }
export interface StartAgentRun { question: string; condition?: Condition; cutoff?: string; discover?: {name: string} | {tickers: string[]}; top_k?: number; model?: string; edit_spec?: boolean; preferences?: string }
export interface CompanyMatch { cik: string; name: string; tickers: string[]; exchanges: string[] }
export interface UniverseInfo { id: string; name: string; companies: number | null; as_of: string; note: string; available?: boolean; problem?: string | null; dynamic?: boolean }
const post = (body: unknown): RequestInit => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
const run = (id: string) => `/agent-runs/${encodeURIComponent(id)}`
export const agentApi = {
  start: (body: StartAgentRun) => request<AgentRunSummary>('/agent-runs', post(body)),
  list: () => request<{items: AgentRunSummary[]}>('/agent-runs'),
  get: (id: string) => request<AgentProgress>(run(id)),
  cancel: (id: string) => request<AgentRunSummary>(`${run(id)}/cancel`, post({})),
  answer: (id: string, answers: Record<string, string>, spec?: unknown) => request<AgentRunSummary>(`${run(id)}/answers`, post({answers, ...(spec !== undefined && {spec})})),
  report: (id: string) => request<AgentReport>(`${run(id)}/report`),
  record: (id: string, record: string) => request<AgentRecord>(`${run(id)}/records/${encodeURIComponent(record)}`),
  companies: (q: string, signal?: AbortSignal) => request<{items: CompanyMatch[]; total: number}>(`/companies?q=${encodeURIComponent(q)}`, {signal}),
  universes: () => request<{items: UniverseInfo[]}>('/universes'),
}
// Setup & status (/api/status): every data provider by kind. Only whether a setting is set, never its value.
export interface ProviderCheck { ok: boolean; message: string; checked_at: string }
export interface ProviderStatus { name: string; label: string; tier: number; env: string[]; configured: boolean; missing_env: string[]; problem: string | null; status: 'ready' | 'configured' | 'not_configured' | 'check_failed'; last_check: ProviderCheck | null; can_check: boolean; note?: string | null }
export interface DataKind { kind: string; label: string; purpose: string; active: string | null; providers: ProviderStatus[] }
export const setupApi = {
  status: () => request<{kinds: DataKind[]}>('/status'),
  // No browser timeout: a model check can take a while, and the provider's own timeout ends it.
  check: (name: string) => request<{kinds: DataKind[]}>(`/status/${encodeURIComponent(name)}/check`, {...post({}), signal: new AbortController().signal}),
}
export const agentRunning = (status: string) => status === 'running' || status === 'stopping' || status === 'waiting'
// Only link to SEC pages; source URLs come from our own tools, but a saved trace is still a file on disk.
// A record's link opens only on a host our data providers use; any other URL stays unlinked.
const SITES: [RegExp, string][] = [[/^https:\/\/(www|data)\.sec\.gov\//, 'SEC.gov'], [/^https:\/\/fred\.stlouisfed\.org\//, 'FRED'], [/^https:\/\/home\.treasury\.gov\//, 'Treasury.gov']]
export const sourceLink = (url: string | null) => { const site = url ? SITES.find(([pattern]) => pattern.test(url)) : undefined; return url && site ? {href: url, site: site[1]} : null }
