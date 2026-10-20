export type Mode = 'fresh' | 'frozen' | 'replay'
export type View = 'research' | 'discovery' | 'history'
export interface Screen { sector: string; min_operating_margin: string; limit: number }
export interface RunRequest { kind: 'research' | 'discovery'; mode: Mode; ticker: string | null; cutoff: string; source_run_id: string | null; screen: Screen | null }
export interface Metric { id: string; label: string; value: string | null; unit: 'USD' | 'ratio'; period: string; formula: string | null; inputs: string[]; evidence_ids: string[]; unavailable_reason: string | null }
export interface Claim { id: string; statement: string; kind: string; status: string; evidence_ids: string[]; version: number }
export interface Review { claim_id: string; original: string; objection: string; check: string; revised: string | null; disposition: string; evidence_ids: string[] }
export interface CompanyReport { ticker: string; company: string; support: string; summary: string; metrics: Metric[]; claims: Claim[]; reviews: Review[]; forecast: { status: string; probability: null; benchmark: string; horizon: string; model_version: string | null; reason: string }; limitations: string[] }
export interface Candidate { ticker: string; company: string; sector: string; eligibility: 'pass' | 'fail' | 'unknown'; reason: string; operating_margin: string | null; selected: boolean }
export interface Report { title: string; synthetic: boolean; companies: CompanyReport[]; candidates: Candidate[]; ranking: string | null; limitations: string[] }
export interface Action { sequence: number; at: string; role: string; message: string }
export interface Run { id: string; request: RunRequest; status: string; created_at: string; updated_at: string; stage: string; actions: Action[]; report: Report | null; error: string | null; synthetic: boolean }
export type HistoryItem = Omit<Run, 'actions' | 'report'>
export interface Evidence { id: string; ticker: string; title: string; excerpt: string; source_url: string | null; available_at: string; retrieved_at: string; period: string; locator: string; snapshot_hash: string; synthetic: boolean }
export interface Config { companies: {ticker: string; name: string; sector: string}[]; fixture_cutoff: string; sec_configured: boolean; model_configured: boolean; model: string | null; forecast_available: boolean }

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
  history: (offset = 0) => request<{items: HistoryItem[]; total: number}>(`/runs?limit=30&offset=${offset}`),
  evidence: (run: string, id: string) => request<Evidence>(`/runs/${encodeURIComponent(run)}/evidence/${encodeURIComponent(id)}`),
  submit: (body: RunRequest, key: string) => request<Run>('/runs', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}, body: JSON.stringify(body)}),
}
export const active = (run: Run | null) => !!run && ['queued', 'running'].includes(run.status)
export const modeLabel: Record<Mode, string> = {fresh: 'Fresh retrieval + inference', frozen: 'New inference · frozen evidence', replay: 'Saved replay · no new inference'}
export const percentage = (value: string | null) => value === null ? 'Unavailable' : new Intl.NumberFormat('en-US', {style: 'percent', maximumFractionDigits: 1}).format(Number(value))
export const metricValue = (metric: Metric) => metric.value === null ? 'Unavailable' : metric.unit === 'ratio' ? percentage(metric.value) : new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(Number(metric.value))
export const stamp = (value: string) => new Intl.DateTimeFormat('en-GB', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC'}).format(new Date(value)) + ' UTC'
