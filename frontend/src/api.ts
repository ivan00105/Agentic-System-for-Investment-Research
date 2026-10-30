export type Mode = 'fresh' | 'frozen' | 'replay'
export type View = 'research' | 'discovery' | 'history' | 'connections'
export interface Screen { sector: string; min_operating_margin: string; limit: number }
export interface RunRequest { kind: 'research' | 'discovery'; mode: Mode; ticker: string | null; cutoff: string; source_run_id: string | null; screen: Screen | null; model_analysis?: boolean; connection_check?: 'sec' | 'model' | null; spending_limit_usd?: string | null; provider_limit_confirmed?: boolean }
export interface Metric { id: string; label: string; value: string | null; unit: 'USD' | 'ratio'; period: string; formula: string | null; inputs: string[]; evidence_ids: string[]; unavailable_reason: string | null }
export interface Claim { id: string; statement: string; kind: string; status: string; evidence_ids: string[]; version: number }
export interface Review { claim_id: string; original: string; objection: string; check: string; revised: string | null; disposition: string; evidence_ids: string[] }
export type ReviewStatus = 'not_requested' | 'pending' | 'completed' | 'unavailable' | 'failed' | 'not_recorded'
export interface CompanyReport { ticker: string; company: string; support: string; summary: string; metrics: Metric[]; claims: Claim[]; reviews: Review[]; review_status?: ReviewStatus; review_error?: string | null; forecast: { status: string; probability: null; benchmark: string; horizon: string; model_version: string | null; reason: string }; limitations: string[]; source_limitations?: string[] | null }
export interface Candidate { ticker: string; company: string; sector: string; eligibility: 'pass' | 'fail' | 'unknown'; reason: string; operating_margin: string | null; selected: boolean }
export interface ModelCall { role: string; provider: string; requested_model: string; returned_model: string | null; response_id: string | null; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; cost_usd: string | null; status: 'completed' | 'failed' | 'incomplete'; error_code: string | null }
export interface ModelRun { provider: string; model: string | null; schema_version: string; max_output_tokens: number }
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
