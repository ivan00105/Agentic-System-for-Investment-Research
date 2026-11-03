import { useEffect, useRef, useState } from 'react'
import { active, api, ApiError, stamp } from '../api'
import type { Config, ConnectionInfo, HistoryItem, Run, RunRequest, View } from '../api'
import { Badge } from '../components/Badge'
import { ErrorBox } from '../components/ErrorBox'

export function ConnectionsPage({onOpen}: {onOpen: (id: string, view: View) => void}) {
  const [config, setConfig] = useState<Config | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [opening, setOpening] = useState<string | null>(null)
  const [runError, setRunError] = useState('')
  const [sources, setSources] = useState<HistoryItem[]>([])
  const [sourceId, setSourceId] = useState('example-msft')
  const [source, setSource] = useState<Run | null>(null)
  const [sourceError, setSourceError] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [submissionError, setSubmissionError] = useState('')
  const submitting = useRef(false)
  const [pending, setPending] = useState<{request: RunRequest; key: string} | null>(() => {
    try { return JSON.parse(sessionStorage.getItem('fieldnote-pending-check') ?? 'null') } catch { return null }
  })
  useEffect(() => {
    let alive = true
    async function loadSources() {
      try {
        const saved: HistoryItem[] = []
        let offset = 0
        while (true) {
          const page = await api.history(offset)
          saved.push(...page.items.filter(item => item.request.kind === 'research' && !['queued', 'running'].includes(item.status)))
          offset += page.items.length
          if (offset >= page.total || !page.items.length) break
        }
        if (alive) setSources(saved)
      } catch {if (alive) setSourceError('Saved sources could not be listed. Refresh status to try again.')}
    }
    void loadSources()
    return () => {alive = false}
  }, [attempt])
  useEffect(() => {
    let alive = true
    setSource(null); setSourceError(''); setConsent(false)
    api.run(sourceId).then(result => {if (alive) setSource(result)}).catch(() => {if (alive) setSourceError('The selected saved source could not be loaded. Choose another source or refresh status.')})
    return () => {alive = false}
  }, [sourceId, attempt])
  const sourceEligible = !!source && source.request.kind === 'research' && !active(source) && !!source.request.ticker && !!source.report?.companies.some(company => company.metrics.some(metric => metric.evidence_ids.length > 0) || company.claims.some(claim => claim.evidence_ids.length > 0))
  async function sendCheck(intent: {request: RunRequest; key: string}) {
    if (submitting.current) return
    submitting.current = true; setBusy(true); setSubmissionError('')
    try {sessionStorage.setItem('fieldnote-pending-check', JSON.stringify(intent))}
    catch {
      setSubmissionError('The browser could not save submission recovery details. No request was sent. Enable session storage before trying again.')
      submitting.current = false; setBusy(false)
      return
    }
    setPending(intent)
    try {
      const result = await api.submit(intent.request, intent.key)
      sessionStorage.removeItem('fieldnote-pending-check'); setPending(null)
      onOpen(result.id, result.request.kind)
    } catch (err) {
      setSubmissionError((err as Error).message)
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {sessionStorage.removeItem('fieldnote-pending-check'); setPending(null); setConsent(false)}
    } finally {submitting.current = false; setBusy(false)}
  }
  function startCheck(kind: 'sec' | 'model') {
    if (pending || busy) return
    if (kind === 'sec' && !connections?.sec.configured) return
    if (kind === 'model' && (!connections?.model.configured || !connections.model.model || !sourceEligible || !consent)) return
    const request: RunRequest = kind === 'sec'
      ? {kind: 'research', mode: 'fresh', ticker: 'MSFT', cutoff: new Date().toISOString(), source_run_id: null, screen: null, model_analysis: false, connection_check: 'sec'}
      : {kind: 'research', mode: 'frozen', ticker: source!.request.ticker, cutoff: source!.request.cutoff, source_run_id: source!.id, screen: null, model_analysis: true, connection_check: 'model'}
    void sendCheck({request, key: crypto.randomUUID()})
  }
  useEffect(() => {
    let alive = true
    api.config().then(result => {if (alive) setConfig(result)}).catch(() => {if (alive) setError('Connection status is unavailable. Check that the local server is running, then retry. Previous status is not shown.')}).finally(() => {if (alive) setLoading(false)})
    return () => {alive = false}
  }, [attempt])
  function refresh() {setConfig(null); setError(''); setRunError(''); setLoading(true); setAttempt(value => value + 1)}
  async function openRun(id: string) {
    setOpening(id); setRunError('')
    try {const run = await api.run(id); onOpen(run.id, run.request.kind)}
    catch {setRunError('The saved investigation could not be opened. Retry its link or find the investigation in History.')}
    finally {setOpening(null)}
  }
  const untested = {status: 'not_tested' as const, checked_at: null, run_id: null, message: null}
  const connections = config?.connections ?? (config ? {
    sec: {configured: config.sec_configured, provider: 'SEC', model: null, check: untested},
    model: {configured: config.model_configured, provider: 'Model service (not recorded)', model: config.model, check: untested},
  } : null)
  function card(title: string, info: ConnectionInfo, description: string) {
    const checkLabel = {not_tested: 'Not tested', passed: 'Check passed', failed: 'Check failed'}[info.check.status]
    return <section className="report-section connection-card" aria-label={title}>
      <div className="section-heading"><h2>{title}</h2><Badge tone={info.configured ? '' : 'amber'}>{info.configured ? 'Configured' : 'Not configured'}</Badge></div>
      <p className="muted">{description}</p>
      <dl className="connection-meta"><div><dt>Provider</dt><dd>{info.provider}</dd></div>{title === 'Optional model analysis' && <div><dt>Selected model</dt><dd>{info.model ?? 'Not selected'}</dd></div>}</dl>
      <div className="connection-check"><h3>Latest provider attempt</h3><Badge tone={info.check.status === 'passed' ? 'green' : info.check.status === 'failed' ? 'amber' : ''}>{checkLabel}</Badge>{info.check.checked_at && <p><time dateTime={info.check.checked_at}>{stamp(info.check.checked_at)}</time></p>}
        {info.check.message && <p>{info.check.message}</p>}
        {info.configuration_error && <p className="configuration-note">{info.configuration_error}</p>}
        {info.check.status === 'not_tested' && <p>No finished provider attempt is recorded during this server session.</p>}
        {info.check.run_id && <button className="text-button" disabled={opening !== null} onClick={() => void openRun(info.check.run_id!)}>{opening === info.check.run_id ? 'Opening saved investigation…' : 'Open saved investigation ↗'}</button>}
      </div>
      {title === 'SEC financial data' ? <div className="connection-test"><p>Check SEC access using MSFT annual facts. This is a fixed connection probe for the existing research universe.</p><button className="primary" disabled={!info.configured || busy || !!pending} onClick={() => startCheck('sec')}>Test SEC connection</button></div> : <form className="connection-test" onSubmit={event => {event.preventDefault(); startCheck('model')}}>
        <p>Run at most one interpretation and one critic call using saved evidence. This may incur provider charges.</p>
        <fieldset disabled={busy || !!pending}><legend className="sr-only">Model connection check</legend>
          <label>Saved evidence for model check<select value={sourceId} onChange={event => {setSourceId(event.target.value); setConsent(false)}}>{!sources.some(item => item.id === sourceId) && <option value={sourceId}>{sourceId === 'example-msft' ? 'MSFT · Synthetic teaching data' : 'Selected saved source'}</option>}{sources.map(item => <option key={item.id} value={item.id}>{item.label ? `${item.label} · ` : ''}{item.request.ticker} · {item.synthetic ? 'Synthetic teaching data' : 'Real saved research'} · {stamp(item.created_at)}</option>)}</select></label>
          {source ? <p className="form-note">{source.synthetic || source.report?.synthetic ? 'Synthetic teaching data: illustrative figures, not actual company financials.' : 'Real saved research source.'} Saved cutoff: {stamp(source.request.cutoff)}.</p> : !sourceError && <p role="status">Loading saved source…</p>}
          {source && !sourceEligible && <p className="configuration-note">This saved investigation has no eligible company evidence. Choose a finished research report with saved evidence.</p>}
          {sourceError && <p className="configuration-note">{sourceError}</p>}
          <p className="form-note">Manage spending limits with your model provider. Reported usage and cost are saved when available.</p>
          <label className="model-choice"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />I agree to send this saved evidence to the model provider and understand charges may apply.</label>
          <button className="primary" type="submit" disabled={!info.configured || !info.model || !sourceEligible || !consent}>Test model connection</button>
        </fieldset>
      </form>}
    </section>
  }
  return <div className="connections">
    <div className="connections-toolbar"><p className="muted">Setup and the latest provider attempt are shown separately. Status lasts for the current server session.</p><button className="secondary" disabled={loading} onClick={refresh}>Refresh status</button></div>
    <p className="notice">Tests run only when you explicitly click a test button. Opening this page or refreshing status makes no provider calls.</p>
    {loading ? <p role="status">Loading connection status…</p> : error ? <ErrorBox message={error} retry={refresh} /> : connections && <div className="connection-grid">{card('SEC financial data', connections.sec, 'Annual USD financial facts for the five companies in the current research universe.')}{card('Optional model analysis', connections.model, 'Adds an evidence review when requested. Financial figures can be prepared without model analysis.')}</div>}
    {pending && <div className="notice" role="status"><strong>Recover your connection check</strong><p>The {pending.request.connection_check === 'model' ? 'model' : 'SEC'} check may already have been received. Retry the exact submission to recover its saved result. New tests and edits are disabled while its outcome is unknown.</p>{pending.request.connection_check === 'model' && <p>Saved source: {pending.request.source_run_id}</p>}<button className="secondary" disabled={busy} onClick={() => void sendCheck(pending)}>{busy ? 'Submitting…' : 'Retry same submission'}</button></div>}
    {submissionError && <div className="notice error" role="alert">{submissionError}</div>}
    {runError && <div className="notice error" role="alert">{runError}</div>}
    <p className="muted connection-limits">A passed check means a provider attempt succeeded. It does not prove financial correctness. Spending limits are managed with your provider; reported model costs may be unknown.</p>
    <details className="technical-details connection-setup"><summary>Setup details</summary><p>Copy <code>.env.example</code> to <code>.env</code> in the project folder, then add your settings. Set <code>SEC_USER_AGENT</code> for SEC access. For optional model analysis, OpenAI is the default: set <code>OPENAI_API_KEY</code> and <code>RESEARCH_MODEL</code>. For OpenRouter, set <code>RESEARCH_MODEL_PROVIDER</code> to <code>openrouter</code>, set <code>OPENROUTER_API_KEY</code> and choose <code>RESEARCH_MODEL</code>.</p><p>Use <code>OPENAI_BASE_URL</code> only for a trusted compatible endpoint. Existing environment variables take precedence over <code>.env</code>. Restart the server after changes.</p><p>Credentials, server settings and provider spending limits are managed outside this page. Consent applies only to the selected model check.</p></details>
  </div>
}
