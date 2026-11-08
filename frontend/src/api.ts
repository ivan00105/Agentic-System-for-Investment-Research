export type View = 'research' | 'history' | 'setup'
// /api/config: the configured model, which Advanced options shows as the default.
export interface Config { model: string | null; model_configured: boolean }

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
}
export const stamp = (value: string) => new Intl.DateTimeFormat('en-GB', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC'}).format(new Date(value)) + ' UTC'

// Agent runs (conditions B, C, D, and Discover), saved as trace files and served by /api/agent-runs.
export type Condition = 'B' | 'C' | 'D'
export interface AgentTotals { model_calls: number; tool_calls: number; total_tokens: number; cached_tokens: number | null; cost: number | null }
// title: the user's label, a pick's company, else the question. children: the runs it started (picks, a comparison).
export interface AgentRunSummary { run_id: string; status: string; title?: string | null; label?: string | null; kind?: 'pick' | 'comparison' | null; parent_run_id?: string | null; archived?: boolean; children?: AgentRunSummary[]; question?: string | null; preferences?: string | null; condition?: string | null; cutoff?: string | null; model?: string | null; started_at?: string | null; ended_at?: string | null; totals?: AgentTotals | null }
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
export interface StartAgentRun { question: string; condition?: Condition; cutoff?: string; discover?: {name: string} | {tickers: string[]}; top_k?: number; model?: string; edit_spec?: boolean; preferences?: string; parent_run_id?: string }
export interface CompanyMatch { cik: string; name: string; tickers: string[]; exchanges: string[] }
export interface UniverseInfo { id: string; name: string; companies: number | null; as_of: string; note: string; available?: boolean; problem?: string | null; dynamic?: boolean }
const post = (body: unknown): RequestInit => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
const run = (id: string) => `/agent-runs/${encodeURIComponent(id)}`
export const agentApi = {
  start: (body: StartAgentRun) => request<AgentRunSummary>('/agent-runs', post(body)),
  list: (archived = false) => request<{items: AgentRunSummary[]}>(`/agent-runs?archived=${archived}`),
  update: (id: string, change: {label?: string | null; archived?: boolean}) => request<AgentRunSummary>(run(id), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(change)}),
  remove: (id: string, children: boolean) => request<{deleted: string[]}>(`${run(id)}?children=${children}`, {method: 'DELETE'}),
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
