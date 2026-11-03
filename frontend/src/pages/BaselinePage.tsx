// Baseline A, the old fixed pipeline: its request form, a saved run and its report (PROJECT_GUIDE §3).
import { useEffect, useRef, useState } from 'react'
import { active, api, investigationLabel, progressLabel, stamp } from '../api'
import type { Config, Run, View } from '../api'
import { Badge } from '../components/Badge'
import { ErrorBox } from '../components/ErrorBox'
import { EvidencePanel } from '../components/EvidencePanel'
import { Discovery } from '../components/baseline/Discovery'
import { RequestForm } from '../components/baseline/RequestForm'
import { ResearchReport } from '../components/baseline/ResearchReport'

export function BaselinePage({view, id, ticker, navigate}: {view: 'research' | 'discovery'; id: string | null; ticker: string | null; navigate: (view: View, id?: string | null, company?: string | null) => void}) {
  const [config, setConfig] = useState<Config | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [configError, setConfigError] = useState('')
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const evidenceTrigger = useRef<HTMLElement | null>(null)
  useEffect(() => {let alive = true; api.config().then(c => {if (alive) {setConfig(c); setConfigError('')}}).catch(e => {if (alive) setConfigError(e.message)}); return () => {alive = false}}, [attempt])
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout> | undefined
    setRun(null); setError(''); setEvidenceId(null); setLoading(!!id)
    async function load() {
      if (!id) return
      try {const result = await api.run(id); if (!alive) return; setRun(result); setError(''); if (active(result)) timer = setTimeout(load, 2000)}
      catch (e) {if (!alive) return; setError((e as Error).message)}
      finally {if (alive) setLoading(false)}
    }
    void load()
    return () => {alive = false; clearTimeout(timer)}
  }, [id, attempt])
  useEffect(() => setEvidenceId(null), [ticker])
  function showEvidence(next: string) {evidenceTrigger.current = document.activeElement as HTMLElement; setEvidenceId(next); document.getElementById('evidence-title')?.focus()}
  const company = run?.report?.companies.find(c => c.ticker === ticker) ?? run?.report?.companies[0]
  const synthetic = !!(run?.synthetic || run?.report?.synthetic)
  const hasEvidence = !!run?.report?.companies.some(c => c.metrics.some(metric => metric.evidence_ids.length > 0))
  const showDiscovery = view === 'discovery' && !ticker
  return <>
    {configError && <ErrorBox message={configError} retry={() => setAttempt(a => a + 1)} />}
    {config && <RequestForm key={view} view={view} config={config} current={run} onOpen={(runId, kind) => navigate(kind, runId)} />}
    {error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}
    {loading && <div className="notice" role="status">Loading the saved investigation…</div>}
    {!id && !loading && <section className="empty-state"><span className="section-label">READY WHEN YOU ARE</span><h2>{view === 'research' ? 'Start with a question and a source.' : 'Make the selection criteria explicit.'}</h2><p>Open a teaching example to explore the evidence trail, or research a company using available sources.</p><button className="secondary" onClick={() => navigate(view, view === 'research' ? 'example-msft' : 'example-discovery')}>Explore the teaching example ↗</button></section>}
    {run && <>
      <div className={`run-banner ${synthetic ? 'synthetic' : ''}`}><div><Badge tone={synthetic ? 'amber' : ''}>{synthetic ? 'SYNTHETIC TEACHING DATA' : hasEvidence ? 'Real source evidence' : 'No source evidence recorded'}</Badge><strong>{run.label || investigationLabel(run.request)}</strong></div><span>Cutoff {stamp(run.request.cutoff)}</span></div>
      {synthetic && <p className="synthetic-caption">Illustrative figures and teaching sources. These are not actual company financials. {run.request.mode === 'replay' && 'The correction is a saved teaching example, not a live AI result.'}</p>}
      <div className="run-state" aria-live="polite"><span className={active(run) ? 'pulse-dot' : 'status-dot'} /><strong>{run.status.replaceAll('_', ' ')}</strong><span>{progressLabel(run)}</span></div>
      {run.request.connection_check && <p className="notice">This saved investigation is a {run.request.connection_check === 'sec' ? 'SEC' : 'model'} connection check. Run completion and provider success are separate; <a href="?view=setup">see Setup &amp; status for provider status</a>.</p>}
      {run.error && <ErrorBox message={run.error} />}
      {active(run) && <p className="muted">Research continues if you leave or refresh. Progress updates automatically.</p>}
      {run.report && (showDiscovery ? <Discovery run={run} onCompany={selected => navigate('discovery', run.id, selected)} /> : company ? <>{ticker && <button className="text-button back-button" onClick={() => navigate('discovery', run.id)}>← Back to screening results</button>}<div className="report-layout"><div className="report-body"><ResearchReport company={company} ongoing={active(run)} onEvidence={showEvidence} /></div><EvidencePanel runId={run.id} evidenceId={evidenceId} onClose={() => {setEvidenceId(null); evidenceTrigger.current?.focus()}} /></div></> : <div className="notice">No company results are available yet. Check the research status and activity log.</div>)}
      {run.report && (run.report.model_run || !!run.report.model_calls?.length) && <details className="technical-details model-usage"><summary>Model usage</summary>{run.report.model_run && <p>Provider: {run.report.model_run.provider} · Model: {run.report.model_run.model ?? 'Not recorded'} · Schema: {run.report.model_run.schema_version} · Output-token limit: {run.report.model_run.max_output_tokens ?? 'Provider/model default (no app cap)'}</p>}{run.report.model_calls?.map((call, index) => <div key={index}><h3>{call.role} · {call.status === 'running' ? 'Running' : call.status}</h3><dl className="source-meta"><dt>Provider / requested model</dt><dd>{call.provider} / {call.requested_model}</dd><dt>Returned model</dt><dd>{call.returned_model ?? 'Unknown'}</dd><dt>Response ID</dt><dd>{call.response_id ?? 'Unknown'}</dd><dt>Input / output / total tokens</dt><dd>{call.input_tokens ?? 'Unknown'} / {call.output_tokens ?? 'Unknown'} / {call.total_tokens ?? 'Unknown'}</dd>{call.reasoning_tokens != null && <><dt>Reasoning tokens (included in output)</dt><dd>{call.reasoning_tokens}</dd></>}{call.provider_status && <><dt>Provider response status</dt><dd>{call.provider_status}</dd></>}{call.incomplete_reason && <><dt>Response stop reason</dt><dd>{call.incomplete_reason === 'max_output_tokens' ? 'Output-token limit reached' : call.incomplete_reason === 'content_filter' ? 'Content filtered by provider' : 'Other provider reason'}</dd></>}<dt>Reported cost (USD)</dt><dd>{call.cost_usd == null ? 'Unknown' : call.cost_usd}</dd>{call.error_code && <><dt>Error code</dt><dd>{call.error_code}</dd></>}{call.error_message && <><dt>Failure reason</dt><dd>{call.error_message}</dd></>}</dl></div>)}<p>Usage and cost reflect what the provider returned. Unknown cost does not mean zero.</p></details>}
      <details className="activity"><summary>Activity log <span>{run.actions.length} recorded actions</span></summary><ol>{run.actions.map(a => <li key={a.sequence}><time>{stamp(a.at)}</time><strong>{a.role}</strong><span>{a.message}</span></li>)}</ol><p>Latest detail: {run.stage}</p><p className="mono">Run ID: {run.id}</p></details>
    </>}
  </>
}
