import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { active, api, ApiError, metricValue, modeLabel, investigationLabel, percentage, progressLabel, stamp } from './api'
import type { Candidate, CompanyReport, Config, ConnectionInfo, Evidence, HistoryItem, Mode, Run, RunRequest, View } from './api'

function route() {
  const params = new URLSearchParams(location.search)
  const view = params.get('view')
  return {view: (view === 'discovery' || view === 'history' || view === 'connections' ? view : 'research') as View, id: view === 'connections' ? null : params.get('run') ?? (location.search ? null : 'example-msft'), ticker: params.get('company')}
}
function Badge({children, tone = ''}: {children: React.ReactNode; tone?: string}) {
  return <span className={`badge ${tone}`}>{children}</span>
}
function ErrorBox({message, retry}: {message: string; retry?: () => void}) {
  return <div className="notice error" role="alert"><strong>Something needs attention</strong><p>{message}</p>{retry && <button onClick={retry} className="secondary">Retry connection</button>}</div>
}

function RequestForm({view, config, current, onOpen}: {view: 'research' | 'discovery'; config: Config; current: Run | null; onOpen: (id: string, view: View) => void}) {
  const [mode, setMode] = useState<Mode>('replay')
  const [ticker, setTicker] = useState('MSFT')
  const [cutoff, setCutoff] = useState(new Date(Date.now() - 86400000).toISOString().slice(0, 16))
  const [sector, setSector] = useState('All')
  const [threshold, setThreshold] = useState('10')
  const [limit, setLimit] = useState(3)
  const [modelAnalysis, setModelAnalysis] = useState(false)
  const [sourceId, setSourceId] = useState(current?.request.kind === view ? current.id : view === 'research' ? 'example-msft' : 'example-discovery')
  const [sources, setSources] = useState<HistoryItem[]>([])
  const [source, setSource] = useState<Run | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const submitting = useRef(false)
  const [pending, setPending] = useState<{request: RunRequest; key: string} | null>(() => {
    try { return JSON.parse(sessionStorage.getItem('fieldnote-pending') ?? 'null') } catch { return null }
  })
  useEffect(() => { let alive = true; api.history().then(h => {if (alive) setSources(h.items.filter(r => r.request.kind === view && !['queued', 'running'].includes(r.status)))}).catch(e => {if (alive) setError(e.message)}); return () => {alive = false} }, [view, current?.id, retry])
  useEffect(() => { let alive = true; setSource(null); if (mode !== 'fresh') api.run(sourceId).then(r => {if (alive) setSource(r)}).catch(e => {if (alive) setError(e.message)}); return () => {alive = false} }, [sourceId, mode, retry])

  async function send(intent: {request: RunRequest; key: string}) {
    if (submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    try {sessionStorage.setItem('fieldnote-pending', JSON.stringify(intent))}
    catch {
      setError('The browser could not save submission recovery details. No request was sent. Enable session storage before trying again.')
      submitting.current = false; setBusy(false)
      return
    }
    setPending(intent)
    try {
      const result = await api.submit(intent.request, intent.key)
      sessionStorage.removeItem('fieldnote-pending'); setPending(null)
      onOpen(result.id, result.request.kind)
    } catch (e) {
      setError((e as Error).message)
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) { sessionStorage.removeItem('fieldnote-pending'); setPending(null) }
    } finally {submitting.current = false; setBusy(false)}
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (mode === 'replay') { if (source) onOpen(source.id, source.request.kind); return }
    if (pending) return
    const request: RunRequest = {kind: view, mode, ticker: view === 'research' ? mode === 'frozen' ? source!.request.ticker : ticker : null, cutoff: mode === 'frozen' ? source!.request.cutoff : `${cutoff}:00Z`, source_run_id: mode === 'frozen' ? sourceId : null, screen: view === 'discovery' ? {sector, min_operating_margin: String(Number(threshold) / 100), limit} : null, model_analysis: modelAnalysis}
    void send({request, key: crypto.randomUUID()})
  }
  return <section className="request-panel" aria-label="Research controls">
    <form onSubmit={submit}>
      <div className="form-grid">
        <label>Research action<select value={mode} onChange={e => {setMode(e.target.value as Mode); setError('')}}><option value="replay">{modeLabel.replay}</option><option value="frozen">{modeLabel.frozen}</option><option value="fresh">{modeLabel.fresh}</option></select></label>
        {mode === 'fresh' ? <>
          {view === 'research' && <label>Company<select value={ticker} onChange={e => setTicker(e.target.value)}>{config.companies.map(c => <option key={c.ticker} value={c.ticker}>{c.ticker} · {c.name}</option>)}</select></label>}
          <label>Evidence cutoff · UTC<input type="datetime-local" required max={new Date().toISOString().slice(0, 16)} value={cutoff} onChange={e => setCutoff(e.target.value)} /></label>
        </> : <label className="source-select">Saved report<select value={sourceId} onChange={e => setSourceId(e.target.value)}>
          {!sources.some(s => s.id === sourceId) && <option value={sourceId}>Loading saved report…</option>}
          {sources.map(s => <option key={s.id} value={s.id}>{s.request.ticker ?? 'Five-company screen'} · {s.synthetic ? 'teaching example · ' : ''}{stamp(s.created_at)}</option>)}
        </select></label>}
        <button className="primary submit" disabled={busy || !!pending || (mode !== 'fresh' && !source) || (mode !== 'replay' && active(current))}>{busy ? 'Submitting…' : mode === 'replay' ? 'Open saved report ↗' : view === 'research' ? 'Start research →' : 'Screen companies →'}</button>
      </div>
      {view === 'discovery' && mode !== 'replay' && <div className="form-grid screen-controls"><label>Sector<select value={sector} onChange={e => setSector(e.target.value)}>{['All', 'Technology', 'Consumer discretionary', 'Communication services'].map(s => <option key={s}>{s}</option>)}</select></label><label>Minimum annual margin (%)<input type="number" min="-1000" max="1000" step="0.1" required value={threshold} onChange={e => setThreshold(e.target.value)} /></label><label>Maximum selected companies<select value={limit} onChange={e => setLimit(Number(e.target.value))}>{[1, 2, 3, 4, 5].map(n => <option key={n}>{n}</option>)}</select></label></div>}
      {mode !== 'replay' && <><label className="model-choice"><input type="checkbox" checked={modelAnalysis} onChange={e => setModelAnalysis(e.target.checked)} aria-describedby="model-choice-note" />Include model analysis (optional)</label><p className="form-note" id="model-choice-note">Financial figures are prepared without model analysis by default. Opt in to add an evidence review.</p></>}
      <p className="form-note">{mode === 'replay' ? 'Reopen the saved result without starting new research.' : mode === 'frozen' ? `Use the same saved sources again, with their original cutoff${source ? ` (${stamp(source.request.cutoff)})` : ''}.` : 'Find the latest available annual SEC facts before your cutoff and calculate the figures.'}</p>
      {mode !== 'replay' && modelAnalysis && !config.model_configured && <p className="configuration-note">Model analysis is unavailable in this setup. Financial figures can still be prepared and saved. <a href="?view=connections">View Connections for setup details.</a></p>}
      {mode === 'fresh' && !config.sec_configured && <p className="configuration-note">SEC source access is required for fresh research. <a href="?view=connections">View Connections for setup details.</a> Missing access causes a source error; teaching data will not be substituted.</p>}
    </form>
    {pending && <div className="notice" role="status"><strong>Recover your research request</strong><p>Your request may already have been received. Check for its saved result without starting another investigation.</p><button className="secondary" disabled={busy} onClick={() => void send(pending)}>Recover request</button></div>}
    {error && <ErrorBox message={error} retry={pending ? undefined : () => {setError(''); setRetry(r => r + 1)}} />}
  </section>
}

function Citations({ids, onEvidence}: {ids: string[]; onEvidence: (id: string) => void}) {
  return <div className="citations">{ids.map((id, i) => <button key={id} className="text-button citation" aria-label={`Inspect evidence ${i + 1}`} onClick={() => onEvidence(id)}>↗ Evidence {i + 1}</button>)}</div>
}

function ResearchReport({company, ongoing, onEvidence}: {company: CompanyReport; ongoing: boolean; onEvidence: (id: string) => void}) {
  const available = company.metrics.filter(metric => metric.value !== null).length
  const financialStatus = available === 0 ? 'Unavailable' : available === company.metrics.length ? 'Available' : 'Partly available'
  const reviewStatus = company.review_status ?? 'not_recorded'
  const unfinished = reviewStatus === 'pending' && !ongoing
  const reviewLabel = unfinished ? 'Not finished' : {not_requested: 'Not requested', pending: 'Pending', completed: 'Completed', unavailable: 'Unavailable', failed: 'Failed', not_recorded: 'Not recorded'}[reviewStatus]
  const reviewNote = unfinished ? 'Model analysis did not finish before this investigation stopped. Any available financial figures have been saved.' : {
    not_requested: 'Model analysis was not requested. Inspect any available figures and calculation claims below.',
    pending: 'Model analysis is pending. Available financial figures are shown below.',
    completed: 'Model analysis is complete. Inspect its findings and supporting evidence below.',
    unavailable: 'Model analysis could not run with the available setup or evidence. Any available financial figures have been saved.',
    failed: 'Model analysis did not finish. Any available financial figures have been saved.',
    not_recorded: 'This saved report does not record model analysis status. Its review trail does not establish whether analysis completed.',
  }[reviewStatus]
  return <>
    <section className="report-section summary-section">
      <div className="section-label">01 / RESEARCH BRIEF</div>
      <div className="section-heading"><h2>{company.company} <span className="ticker">{company.ticker}</span></h2><Badge tone="amber">{company.support}</Badge></div>
      <dl className="report-availability" aria-label="Report availability"><div><dt>Financial figures</dt><dd><Badge tone={financialStatus === 'Available' ? 'green' : 'amber'}>{financialStatus}</Badge></dd></div><div><dt>Model analysis</dt><dd><Badge tone={reviewStatus === 'completed' ? 'green' : ''}>{reviewLabel}</Badge></dd></div></dl>
      <p className="muted model-status-note">{reviewNote}</p>
      <p className="summary">{company.summary}</p>
      <div className="metric-grid">{company.metrics.map(metric => <div className="metric" key={metric.id}><span>{metric.label}</span><strong className={metric.value === null ? 'missing-value' : ''}>{metricValue(metric)}</strong><small>{metric.period}</small><details><summary>Inputs & source</summary>{metric.formula && <p className="mono">{metric.formula}</p>}{metric.inputs.map(id => {const input = company.metrics.find(m => m.id === id); return <p key={id}>{input?.label}: {input ? metricValue(input) : 'Unavailable'}</p>})}{metric.unavailable_reason && <p>{metric.unavailable_reason}</p>}<Citations ids={metric.evidence_ids} onEvidence={onEvidence} /></details></div>)}</div>
    </section>
    <section className="report-section">
      <div className="section-label">02 / CLAIMS & SUPPORT</div>
      <h2>What the evidence supports</h2>
      <div className="claims">{company.claims.map(claim => <article className="claim" key={claim.id}><div className="claim-meta"><Badge tone={claim.status === 'unresolved' ? 'amber' : 'green'}>{claim.status}</Badge>{claim.kind === 'interpretation' && <span>Interpretation</span>}</div><p>{claim.statement}</p><Citations ids={claim.evidence_ids} onEvidence={onEvidence} /></article>)}</div>
    </section>
    <section className="report-section review-section">
      <div className="section-label">03 / REVIEW TRAIL</div><div className="section-heading"><h2>Review findings</h2><span className="muted">{company.reviews.length} recorded review{company.reviews.length === 1 ? '' : 's'}</span></div>
      {company.reviews.length === 0 ? <p className="empty-inline">No review findings are recorded. This does not establish that the claims are correct.</p> : company.reviews.map((review, i) => <article className="review" key={`${review.claim_id}-${i}`}><ol className="review-steps"><li><span className="step-number">1</span><div><h3>Original claim</h3><p>{review.original}</p></div></li><li><span className="step-number">2</span><div><h3>Objection</h3><p>{review.objection}</p></div></li><li><span className="step-number">3</span><div><h3>Evidence check</h3><p>{review.check}</p><Citations ids={review.evidence_ids} onEvidence={onEvidence} /></div></li><li className={review.revised ? 'corrected-step' : ''}><span className="step-number">4</span><div><h3>{review.revised ? 'Revised result' : 'Unresolved'} <Badge tone={review.revised ? 'green' : 'amber'}>{review.disposition}</Badge></h3><p>{review.revised ?? 'This concern remains unresolved; the claim has not been verified.'}</p></div></li></ol></article>)}
    </section>
    <section className="report-section forecast"><div className="section-heading"><h2>Return forecast</h2><Badge>Unavailable</Badge></div><p>No validated return forecast is available. Evidence support does not indicate the chance of beating the market.</p></section>
    <section className="report-section limitations"><div className="section-label">05 / LIMITATIONS</div><h2>Keep in view</h2><ul>{company.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
  </>
}

function EvidencePanel({runId, evidenceId, onClose}: {runId: string; evidenceId: string | null; onClose: () => void}) {
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    let alive = true; setEvidence(null); setError('')
    if (evidenceId) { heading.current?.focus(); api.evidence(runId, evidenceId).then(e => {if (alive) setEvidence(e)}).catch(e => {if (alive) setError(e.message)}) }
    return () => {alive = false}
  }, [runId, evidenceId, attempt])
  const safeUrl = evidence?.source_url && /^https:\/\/data\.sec\.gov\//.test(evidence.source_url) ? evidence.source_url : null
  return <aside className="evidence-panel" aria-labelledby="evidence-title"><div className="section-label">SOURCE DESK</div><div className="section-heading"><h2 id="evidence-title" ref={heading} tabIndex={-1}>Evidence inspector</h2>{evidenceId && <button onClick={onClose} className="text-button" aria-label="Close evidence inspector">Close</button>}</div>
    {!evidenceId ? <div className="evidence-empty"><div className="document-icon" aria-hidden="true">≡</div><h3>Keep the source beside the claim.</h3><p>Select an evidence link to inspect the saved excerpt, reporting period and provenance.</p><div className="evidence-principles"><span>01 &nbsp; Original excerpt</span><span>02 &nbsp; Period & availability</span><span>03 &nbsp; Saved source copy</span></div></div> : error ? <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} /> : !evidence ? <p role="status">Loading saved evidence…</p> : <>
      <Badge tone={evidence.synthetic ? 'amber' : 'green'}>{evidence.synthetic ? 'Synthetic teaching source' : 'SEC company facts'}</Badge><h3 className="source-title">{evidence.title}</h3><pre className="excerpt">{evidence.excerpt}</pre><dl className="source-meta"><dt>Reporting period</dt><dd>{evidence.period}</dd><dt>Available by</dt><dd>{stamp(evidence.available_at)}</dd><dt>Saved on</dt><dd>{stamp(evidence.retrieved_at)}</dd></dl><details className="technical-details"><summary>Source details</summary><dl className="source-meta"><dt>Source locator</dt><dd>{evidence.locator}</dd><dt>Snapshot SHA-256</dt><dd className="mono hash">{evidence.snapshot_hash}</dd></dl></details>{safeUrl ? <a className="source-link" href={safeUrl} target="_blank" rel="noopener noreferrer">Open SEC source ↗</a> : <p className="muted">{evidence.synthetic ? 'This synthetic fixture has no original filing URL.' : 'No supported original source URL is recorded.'}</p>}
    </>}
  </aside>
}

function Discovery({run, onCompany}: {run: Run; onCompany: (ticker: string) => void}) {
  const [sort, setSort] = useState<'ticker' | 'operating_margin'>('ticker')
  const candidates = [...(run.report?.candidates ?? [])].sort((a, b) => sort === 'ticker' ? a.ticker.localeCompare(b.ticker) : a.operating_margin === null ? 1 : b.operating_margin === null ? -1 : Number(b.operating_margin) - Number(a.operating_margin) || a.ticker.localeCompare(b.ticker))
  const count = (status: Candidate['eligibility']) => candidates.filter(c => c.eligibility === status).length
  return <section className="report-section discovery-report"><div className="section-label">UNIVERSE / FIVE US OPERATING COMPANIES</div><h2>Find a candidate. Inspect the reason.</h2><p className="summary">Annual operating margin ≥ {percentage(run.request.screen?.min_operating_margin ?? null)} · Sector: {run.request.screen?.sector ?? 'All'} · Up to {run.request.screen?.limit} selected</p><div className="screen-stats"><span><strong>{candidates.length}</strong> screened</span><span><strong>{count('pass')}</strong> pass</span><span><strong>{count('fail')}</strong> fail</span><span><strong>{count('unknown')}</strong> unknown</span></div><p className="muted">{run.report?.ranking} Table sorting changes presentation only.</p>
    <div className="table-scroll" tabIndex={0} aria-label="Scrollable candidate results"><table><caption className="sr-only">Candidate screening results and exclusion reasons</caption><thead><tr><th aria-sort={sort === 'ticker' ? 'ascending' : 'none'}><button className="table-sort" onClick={() => setSort('ticker')}>Company ↕</button></th><th aria-sort={sort === 'operating_margin' ? 'descending' : 'none'}><button className="table-sort" onClick={() => setSort('operating_margin')}>Annual margin ↕</button></th><th>Eligibility</th><th>Reason</th><th><span className="sr-only">Open report</span></th></tr></thead><tbody>{candidates.map(c => <tr key={c.ticker}><th scope="row">{c.ticker}<small>{c.company}</small></th><td className="numeric">{percentage(c.operating_margin)}</td><td><Badge tone={c.eligibility === 'pass' ? 'green' : 'amber'}>{c.eligibility}</Badge>{c.selected && <small>Selected</small>}</td><td>{c.reason}</td><td><button className="text-button" onClick={() => onCompany(c.ticker)} aria-label={`Inspect ${c.company} research`}>Inspect ↗</button></td></tr>)}</tbody></table></div>{run.report?.limitations.map(l => <p className="muted" key={l}>{l}</p>)}</section>
}

function History({onOpen}: {onOpen: (id: string, view: View) => void}) {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {let alive = true; setLoading(true); setError(''); api.history(offset).then(h => {if (alive) {setItems(h.items); setTotal(h.total)}}).catch(e => {if (alive) setError(e.message)}).finally(() => {if (alive) setLoading(false)}); return () => {alive = false}}, [offset, attempt])
  return <section className="report-section history"><div className="section-heading"><h2>Saved investigations</h2><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Refresh history</button></div><p className="muted">Reopen the original inputs, sources and review trail. Opening a saved report never starts new research.</p>{error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}{loading ? <p role="status">Loading saved reports…</p> : items.length === 0 ? <p>No saved reports yet. Start an investigation from Research.</p> : <div className="history-list">{items.map(r => <button className="history-row" key={r.id} onClick={() => onOpen(r.id, r.request.kind)}><div><strong>{r.request.ticker ?? 'Five-company discovery'}</strong><span>{investigationLabel(r.request)}{r.synthetic ? ' · Synthetic teaching data' : ''}</span></div><div><Badge tone={r.status === 'completed' ? 'green' : 'amber'}>{r.status.replaceAll('_', ' ')}</Badge><small>{stamp(r.created_at)}</small></div><span aria-hidden="true">↗</span></button>)}</div>}<div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</button><span>{total ? `${offset + 1}–${Math.min(offset + 30, total)} of ${total}` : '0 runs'}</span><button className="secondary" disabled={offset + 30 >= total || loading} onClick={() => setOffset(offset + 30)}>Next</button></div></section>
}

function Connections({onOpen}: {onOpen: (id: string, view: View) => void}) {
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
  const [spending, setSpending] = useState('')
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
  const positiveSpending = /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(spending) && Number.isFinite(Number(spending)) && Number(spending) > 0
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
    if (kind === 'model' && (!connections?.model.configured || !connections.model.model || !sourceEligible || !positiveSpending || !consent)) return
    const request: RunRequest = kind === 'sec'
      ? {kind: 'research', mode: 'fresh', ticker: 'MSFT', cutoff: new Date().toISOString(), source_run_id: null, screen: null, model_analysis: false, connection_check: 'sec'}
      : {kind: 'research', mode: 'frozen', ticker: source!.request.ticker, cutoff: source!.request.cutoff, source_run_id: source!.id, screen: null, model_analysis: true, connection_check: 'model', spending_limit_usd: spending, provider_limit_confirmed: true}
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
          <label>Saved evidence for model check<select value={sourceId} onChange={event => {setSourceId(event.target.value); setConsent(false)}}>{!sources.some(item => item.id === sourceId) && <option value={sourceId}>{sourceId === 'example-msft' ? 'MSFT · Synthetic teaching data' : 'Selected saved source'}</option>}{sources.map(item => <option key={item.id} value={item.id}>{item.request.ticker} · {item.synthetic ? 'Synthetic teaching data' : 'Real saved research'} · {stamp(item.created_at)}</option>)}</select></label>
          {source ? <p className="form-note">{source.synthetic || source.report?.synthetic ? 'Synthetic teaching data: illustrative figures, not actual company financials.' : 'Real saved research source.'} Saved cutoff: {stamp(source.request.cutoff)}.</p> : !sourceError && <p role="status">Loading saved source…</p>}
          {source && !sourceEligible && <p className="configuration-note">This saved investigation has no eligible company evidence. Choose a finished research report with saved evidence.</p>}
          {sourceError && <p className="configuration-note">{sourceError}</p>}
          <label>Spending allowance (USD)<input type="text" inputMode="decimal" required pattern="(?:0|[1-9][0-9]*)(?:[.][0-9]+)?" value={spending} onChange={event => {setSpending(event.target.value); setConsent(false)}} aria-describedby="check-spending-note" /></label>
          <p id="check-spending-note" className="form-note">Enter a positive amount. This allowance is not a guaranteed application dollar cap. Set a provider or key spending cap before continuing; reported cost may be unknown.</p>
          <label className="model-choice"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />I agree to send this saved evidence to the model provider, understand charges may apply, and confirm a provider or key spending cap is set.</label>
          <button className="primary" type="submit" disabled={!info.configured || !info.model || !sourceEligible || !positiveSpending || !consent}>Test model connection</button>
        </fieldset>
      </form>}
    </section>
  }
  return <div className="connections">
    <div className="connections-toolbar"><p className="muted">Setup and the latest provider attempt are shown separately. Status lasts for the current server session.</p><button className="secondary" disabled={loading} onClick={refresh}>Refresh status</button></div>
    <p className="notice">Tests run only when you explicitly click a test button. Opening this page or refreshing status makes no provider calls.</p>
    {loading ? <p role="status">Loading connection status…</p> : error ? <ErrorBox message={error} retry={refresh} /> : connections && <div className="connection-grid">{card('SEC financial data', connections.sec, 'Annual USD financial facts for the five companies in the current research universe.')}{card('Optional model analysis', connections.model, 'Adds an evidence review when requested. Financial figures can be prepared without model analysis.')}</div>}
    {pending && <div className="notice" role="status"><strong>Recover your connection check</strong><p>The {pending.request.connection_check === 'model' ? 'model' : 'SEC'} check may already have been received. Retry the exact submission to recover its saved result. New tests and edits are disabled while its outcome is unknown.</p>{pending.request.connection_check === 'model' && <p>Saved source: {pending.request.source_run_id} · Spending allowance: USD {pending.request.spending_limit_usd}</p>}<button className="secondary" disabled={busy} onClick={() => void sendCheck(pending)}>{busy ? 'Submitting…' : 'Retry same submission'}</button></div>}
    {submissionError && <div className="notice error" role="alert">{submissionError}</div>}
    {runError && <div className="notice error" role="alert">{runError}</div>}
    <p className="muted connection-limits">A passed check means a provider attempt succeeded. It does not prove financial correctness. Model costs may be unknown; the spending allowance and research limits are not a guaranteed dollar spending cap.</p>
    <details className="technical-details connection-setup"><summary>Setup details</summary><p>Set <code>SEC_USER_AGENT</code> for SEC access. For optional model analysis, OpenAI is the default: set <code>OPENAI_API_KEY</code> and choose a model with <code>RESEARCH_MODEL</code>. For OpenRouter, set <code>RESEARCH_MODEL_PROVIDER</code> to <code>openrouter</code>, set <code>OPENROUTER_API_KEY</code> and choose <code>RESEARCH_MODEL</code>.</p><p>Use <code>OPENAI_BASE_URL</code> only for a trusted compatible endpoint. Restart the server after changing environment variables. A <code>.env</code> file is not automatically loaded.</p><p>Credentials and server settings cannot be entered or saved here. Test allowances and consent apply only to an explicit model check.</p></details>
  </div>
}

export default function App() {
  const [locationState, setLocationState] = useState(route)
  const [config, setConfig] = useState<Config | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [configError, setConfigError] = useState('')
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const evidenceTrigger = useRef<HTMLElement | null>(null)
  const {view, id, ticker} = locationState
  function navigate(nextView: View, nextId: string | null = null, company: string | null = null) {
    const params = new URLSearchParams({view: nextView})
    if (nextId) params.set('run', nextId)
    if (company) params.set('company', company)
    history.pushState({}, '', `?${params}`)
    setLocationState(route()); setEvidenceId(null)
  }
  useEffect(() => {const onPop = () => {setLocationState(route()); setEvidenceId(null)}; addEventListener('popstate', onPop); return () => removeEventListener('popstate', onPop)}, [])
  useEffect(() => {if (view === 'connections') return; let alive = true; api.config().then(c => {if (alive) {setConfig(c); setConfigError('')}}).catch(e => {if (alive) setConfigError(e.message)}); return () => {alive = false}}, [attempt, view])
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
  function showEvidence(next: string) {evidenceTrigger.current = document.activeElement as HTMLElement; setEvidenceId(next); document.getElementById('evidence-title')?.focus()}
  const company = run?.report?.companies.find(c => c.ticker === ticker) ?? run?.report?.companies[0]
  const synthetic = !!(run?.synthetic || run?.report?.synthetic)
  const hasEvidence = !!run?.report?.companies.some(c => c.metrics.some(metric => metric.evidence_ids.length > 0))
  const showDiscovery = view === 'discovery' && !ticker
  return <div className="app-shell">
    <a className="skip-link" href="#main">{view === 'connections' ? 'Skip to connections' : 'Skip to research'}</a>
    <aside className="sidebar"><a className="brand" href="?view=research&run=example-msft"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{(['research', 'discovery', 'history', 'connections'] as View[]).map((item, i) => <button key={item} aria-current={view === item ? 'page' : undefined} onClick={() => navigate(item)}><span aria-hidden="true">{['◧', '⊞', '◷', '⇄'][i]}</span>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Research workspace<p>Evidence first.<br />Every revision in view.</p><small>Five-company research universe<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {view.toUpperCase()}</span><span className="local-status">SOURCES · FIGURES · REVIEW</span></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{view === 'research' ? 'Read beyond the claim.' : view === 'discovery' ? ticker ? 'Inside the candidate.' : 'A smaller, clearer shortlist.' : view === 'connections' ? 'Connections' : 'Return to the evidence.'}</h1><p>{view === 'research' ? 'Investigate a company, inspect its sources, and follow what changed.' : view === 'discovery' ? 'Screen the declared universe. Keep exclusions and missing evidence visible.' : view === 'connections' ? 'See what is configured and what has actually been tried.' : 'Original inputs. Saved evidence. A review trail you can reopen.'}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {view !== 'connections' && configError && <ErrorBox message={configError} retry={() => setAttempt(a => a + 1)} />}
      {view === 'connections' ? <Connections onOpen={(runId, kind) => navigate(kind, runId)} /> : view === 'history' ? <History onOpen={(runId, kind) => navigate(kind, runId)} /> : <>
        {config && <RequestForm key={view} view={view} config={config} current={run} onOpen={(runId, kind) => navigate(kind, runId)} />}
        {error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}
        {loading && <div className="notice" role="status">Loading the saved investigation…</div>}
        {!id && !loading && <section className="empty-state"><span className="section-label">READY WHEN YOU ARE</span><h2>{view === 'research' ? 'Start with a question and a source.' : 'Make the selection criteria explicit.'}</h2><p>Open a teaching example to explore the evidence trail, or research a company using available sources.</p><button className="secondary" onClick={() => navigate(view, view === 'research' ? 'example-msft' : 'example-discovery')}>Explore the teaching example ↗</button></section>}
        {run && <>
          <div className={`run-banner ${synthetic ? 'synthetic' : ''}`}><div><Badge tone={synthetic ? 'amber' : ''}>{synthetic ? 'SYNTHETIC TEACHING DATA' : hasEvidence ? 'Real source evidence' : 'No source evidence recorded'}</Badge><strong>{investigationLabel(run.request)}</strong></div><span>Cutoff {stamp(run.request.cutoff)}</span></div>
          {synthetic && <p className="synthetic-caption">Illustrative figures and teaching sources. These are not actual company financials. {run.request.mode === 'replay' && 'The correction is a saved teaching example, not a live AI result.'}</p>}
          <div className="run-state" aria-live="polite"><span className={active(run) ? 'pulse-dot' : 'status-dot'} /><strong>{run.status.replaceAll('_', ' ')}</strong><span>{progressLabel(run)}</span></div>
          {run.request.connection_check && <p className="notice">This saved investigation is a {run.request.connection_check === 'sec' ? 'SEC' : 'model'} connection check. Run completion and provider success are separate; <a href="?view=connections">view Connections for provider status</a>.</p>}
          {run.error && <ErrorBox message={run.error} />}
          {active(run) && <p className="muted">Research continues if you leave or refresh. Progress updates automatically.</p>}
          {run.report && (showDiscovery ? <Discovery run={run} onCompany={selected => navigate('discovery', run.id, selected)} /> : company ? <>{ticker && <button className="text-button back-button" onClick={() => navigate('discovery', run.id)}>← Back to screening results</button>}<div className="report-layout"><div className="report-body"><ResearchReport company={company} ongoing={active(run)} onEvidence={showEvidence} /></div><EvidencePanel runId={run.id} evidenceId={evidenceId} onClose={() => {setEvidenceId(null); evidenceTrigger.current?.focus()}} /></div></> : <div className="notice">No company results are available yet. Check the research status and activity log.</div>)}
          {run.report && (run.report.model_run || !!run.report.model_calls?.length) && <details className="technical-details model-usage"><summary>Model usage</summary>{run.report.model_run && <p>Provider: {run.report.model_run.provider} · Model: {run.report.model_run.model ?? 'Not recorded'} · Schema: {run.report.model_run.schema_version} · Maximum output tokens per call: {run.report.model_run.max_output_tokens}</p>}{run.report.model_calls?.map((call, index) => <div key={index}><h3>{call.role} · {call.status}</h3><dl className="source-meta"><dt>Provider / requested model</dt><dd>{call.provider} / {call.requested_model}</dd><dt>Returned model</dt><dd>{call.returned_model ?? 'Unknown'}</dd><dt>Response ID</dt><dd>{call.response_id ?? 'Unknown'}</dd><dt>Input / output / total tokens</dt><dd>{call.input_tokens ?? 'Unknown'} / {call.output_tokens ?? 'Unknown'} / {call.total_tokens ?? 'Unknown'}</dd><dt>Reported cost (USD)</dt><dd>{call.cost_usd == null ? 'Unknown' : call.cost_usd}</dd>{call.error_code && <><dt>Error code</dt><dd>{call.error_code}</dd></>}</dl></div>)}<p>Usage and cost reflect what the provider returned. Unknown cost does not mean zero.</p></details>}
          <details className="activity"><summary>Activity log <span>{run.actions.length} recorded actions</span></summary><ol>{run.actions.map(a => <li key={a.sequence}><time>{stamp(a.at)}</time><strong>{a.role}</strong><span>{a.message}</span></li>)}</ol><p>Latest detail: {run.stage}</p><p className="mono">Run ID: {run.id}</p></details>
        </>}
      </>}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div>
}
