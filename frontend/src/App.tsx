import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { active, api, ApiError, metricValue, modeLabel, percentage, stamp } from './api'
import type { Candidate, CompanyReport, Config, Evidence, HistoryItem, Mode, Run, RunRequest, View } from './api'

function route() {
  const params = new URLSearchParams(location.search)
  const view = params.get('view')
  return {view: (view === 'discovery' || view === 'history' ? view : 'research') as View, id: params.get('run') ?? (location.search ? null : 'example-msft'), ticker: params.get('company')}
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
    setPending(intent)
    sessionStorage.setItem('fieldnote-pending', JSON.stringify(intent))
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
    const request: RunRequest = {kind: view, mode, ticker: view === 'research' ? mode === 'frozen' ? source!.request.ticker : ticker : null, cutoff: mode === 'frozen' ? source!.request.cutoff : `${cutoff}:00Z`, source_run_id: mode === 'frozen' ? sourceId : null, screen: view === 'discovery' ? {sector, min_operating_margin: String(Number(threshold) / 100), limit} : null}
    void send({request, key: crypto.randomUUID()})
  }
  return <section className="request-panel" aria-label="Research controls">
    <form onSubmit={submit}>
      <div className="form-grid">
        <label>Run mode<select value={mode} onChange={e => {setMode(e.target.value as Mode); setError('')}}><option value="replay">Saved replay</option><option value="frozen">New inference · frozen evidence</option><option value="fresh">Fresh retrieval + inference</option></select></label>
        {mode === 'fresh' ? <>
          {view === 'research' && <label>Company<select value={ticker} onChange={e => setTicker(e.target.value)}>{config.companies.map(c => <option key={c.ticker} value={c.ticker}>{c.ticker} · {c.name}</option>)}</select></label>}
          <label>Evidence cutoff · UTC<input type="datetime-local" required max={new Date().toISOString().slice(0, 16)} value={cutoff} onChange={e => setCutoff(e.target.value)} /></label>
        </> : <label className="source-select">Saved evidence packet<select value={sourceId} onChange={e => setSourceId(e.target.value)}>
          {!sources.some(s => s.id === sourceId) && <option value={sourceId}>{sourceId}</option>}
          {sources.map(s => <option key={s.id} value={s.id}>{s.request.ticker ?? 'Five-company screen'} · {s.synthetic ? 'synthetic example' : stamp(s.created_at)} · {s.id.slice(0, 14)}</option>)}
        </select></label>}
        <button className="primary submit" disabled={busy || !!pending || (mode !== 'fresh' && !source) || (mode !== 'replay' && active(current))}>{busy ? 'Submitting…' : mode === 'replay' ? 'Open saved replay ↗' : view === 'research' ? 'Start research →' : 'Screen companies →'}</button>
      </div>
      {view === 'discovery' && mode !== 'replay' && <div className="form-grid screen-controls"><label>Sector<select value={sector} onChange={e => setSector(e.target.value)}>{['All', 'Technology', 'Consumer discretionary', 'Communication services'].map(s => <option key={s}>{s}</option>)}</select></label><label>Minimum annual margin (%)<input type="number" min="-1000" max="1000" step="0.1" required value={threshold} onChange={e => setThreshold(e.target.value)} /></label><label>Maximum selected companies<select value={limit} onChange={e => setLimit(Number(e.target.value))}>{[1, 2, 3, 4, 5].map(n => <option key={n}>{n}</option>)}</select></label></div>}
      <p className="form-note">{mode === 'replay' ? 'Open a stored result. No retrieval, model calls or new inference.' : mode === 'frozen' ? `Run new model interpretation and review using the original evidence and cutoff${source ? ` (${stamp(source.request.cutoff)})` : ''}.` : 'Retrieve annual SEC facts, calculate aligned metrics, then request model review. One active run at a time.'}</p>
      {mode !== 'replay' && (!config.model_configured || (mode === 'fresh' && !config.sec_configured)) && <p className="configuration-note">Setup required: {!config.model_configured && 'model credentials and model name'}{!config.model_configured && mode === 'fresh' && !config.sec_configured && '; '}{mode === 'fresh' && !config.sec_configured && 'SEC contact identity'}. Unavailable steps will stop explicitly and preserve partial results. See the local setup guide.</p>}
    </form>
    {pending && <div className="notice" role="status"><strong>A submission needs confirmation</strong><p>Its result may already exist. Retry with the same key to recover it without starting another run.</p><button className="secondary" disabled={busy} onClick={() => void send(pending)}>Retry pending submission</button></div>}
    {error && <ErrorBox message={error} retry={pending ? undefined : () => {setError(''); setRetry(r => r + 1)}} />}
  </section>
}

function Citations({ids, onEvidence}: {ids: string[]; onEvidence: (id: string) => void}) {
  return <div className="citations">{ids.map((id, i) => <button key={id} className="text-button citation" aria-label={`Inspect evidence ${i + 1}: ${id}`} onClick={() => onEvidence(id)}>↗ Evidence {i + 1}</button>)}</div>
}

function ResearchReport({company, onEvidence}: {company: CompanyReport; onEvidence: (id: string) => void}) {
  return <>
    <section className="report-section summary-section">
      <div className="section-label">01 / RESEARCH BRIEF</div>
      <div className="section-heading"><h2>{company.company} <span className="ticker">{company.ticker}</span></h2><Badge tone="amber">{company.support}</Badge></div>
      <p className="summary">{company.summary}</p>
      <div className="metric-grid">{company.metrics.map(metric => <div className="metric" key={metric.id}><span>{metric.label}</span><strong className={metric.value === null ? 'missing-value' : ''}>{metricValue(metric)}</strong><small>{metric.period}</small><details><summary>Inputs & source</summary>{metric.formula && <p className="mono">{metric.formula}</p>}{metric.inputs.map(id => {const input = company.metrics.find(m => m.id === id); return <p key={id}>{input?.label}: {input ? metricValue(input) : 'Unavailable'}</p>})}{metric.unavailable_reason && <p>{metric.unavailable_reason}</p>}<Citations ids={metric.evidence_ids} onEvidence={onEvidence} /></details></div>)}</div>
    </section>
    <section className="report-section">
      <div className="section-label">02 / CLAIMS & SUPPORT</div>
      <h2>What the evidence supports</h2>
      <div className="claims">{company.claims.map(claim => <article className="claim" key={claim.id}><div className="claim-meta"><Badge tone={claim.status === 'unresolved' ? 'amber' : 'green'}>{claim.status}</Badge><span>{claim.kind} · version {claim.version}</span></div><p>{claim.statement}</p><Citations ids={claim.evidence_ids} onEvidence={onEvidence} /></article>)}</div>
    </section>
    <section className="report-section review-section">
      <div className="section-label">03 / REVIEW TRAIL</div><div className="section-heading"><h2>Follow the correction</h2><span className="muted">{company.reviews.length} recorded review{company.reviews.length === 1 ? '' : 's'}</span></div>
      {company.reviews.length === 0 ? <p className="empty-inline">No claim-specific review is recorded. This does not establish that the claims are correct.</p> : company.reviews.map((review, i) => <article className="review" key={`${review.claim_id}-${i}`}><ol className="review-steps"><li><span className="step-number">1</span><div><h3>Original claim</h3><p>{review.original}</p></div></li><li><span className="step-number">2</span><div><h3>Objection</h3><p>{review.objection}</p></div></li><li><span className="step-number">3</span><div><h3>Evidence check</h3><p>{review.check}</p><Citations ids={review.evidence_ids} onEvidence={onEvidence} /></div></li><li className={review.revised ? 'corrected-step' : ''}><span className="step-number">4</span><div><h3>{review.revised ? 'Revised result' : 'Unresolved'} <Badge tone={review.revised ? 'green' : 'amber'}>{review.disposition}</Badge></h3><p>{review.revised ?? 'The objection remains attached to the claim. No correction or verification is being implied.'}</p></div></li></ol></article>)}
    </section>
    <section className="report-section forecast"><div className="section-label">04 / SEPARATE STATISTICAL FORECAST</div><div className="section-heading"><h2>Outperformance probability</h2><Badge>Unavailable</Badge></div><p>{company.forecast.reason}</p><dl className="forecast-details"><div><dt>Benchmark</dt><dd>{company.forecast.benchmark}</dd></div><div><dt>Horizon</dt><dd>{company.forecast.horizon}</dd></div><div><dt>Model version</dt><dd>{company.forecast.model_version ?? 'Not installed'}</dd></div></dl><p className="muted">Evidence support is not a return probability. Narrative review never changes the forecast.</p></section>
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
    {!evidenceId ? <div className="evidence-empty"><div className="document-icon" aria-hidden="true">≡</div><h3>Keep the source beside the claim.</h3><p>Select an evidence link to inspect the saved excerpt, reporting period and provenance.</p><div className="evidence-principles"><span>01 &nbsp; Original excerpt</span><span>02 &nbsp; Period & availability</span><span>03 &nbsp; Immutable snapshot</span></div></div> : error ? <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} /> : !evidence ? <p role="status">Loading saved evidence…</p> : <>
      <Badge tone={evidence.synthetic ? 'amber' : 'green'}>{evidence.synthetic ? 'Synthetic teaching source' : 'SEC company facts'}</Badge><h3 className="source-title">{evidence.title}</h3><pre className="excerpt">{evidence.excerpt}</pre><dl className="source-meta"><dt>Reporting period</dt><dd>{evidence.period}</dd><dt>Available by</dt><dd>{stamp(evidence.available_at)}</dd><dt>Retrieved / fixture captured</dt><dd>{stamp(evidence.retrieved_at)}</dd><dt>Source locator</dt><dd>{evidence.locator}</dd><dt>Snapshot SHA-256</dt><dd className="mono hash">{evidence.snapshot_hash}</dd></dl>{safeUrl ? <a className="source-link" href={safeUrl} target="_blank" rel="noopener noreferrer">Open original SEC endpoint ↗</a> : <p className="muted">This synthetic fixture has no original filing URL.</p>}
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
  return <section className="report-section history"><div className="section-heading"><h2>Saved investigations</h2><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Refresh history</button></div><p className="muted">Reopen the original inputs, sources and review trail. Opening a run never starts new inference.</p>{error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}{loading ? <p role="status">Loading saved runs…</p> : items.length === 0 ? <p>No saved runs yet. Start an investigation from Research.</p> : <div className="history-list">{items.map(r => <button className="history-row" key={r.id} onClick={() => onOpen(r.id, r.request.kind)}><div><strong>{r.request.ticker ?? 'Five-company discovery'}</strong><span>{r.synthetic ? 'Synthetic teaching example' : modeLabel[r.request.mode]}</span></div><div><Badge tone={r.status === 'completed' ? 'green' : 'amber'}>{r.status.replaceAll('_', ' ')}</Badge><small>{stamp(r.created_at)}</small></div><span aria-hidden="true">↗</span></button>)}</div>}<div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</button><span>{total ? `${offset + 1}–${Math.min(offset + 30, total)} of ${total}` : '0 runs'}</span><button className="secondary" disabled={offset + 30 >= total || loading} onClick={() => setOffset(offset + 30)}>Next</button></div></section>
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
  function showEvidence(next: string) {evidenceTrigger.current = document.activeElement as HTMLElement; setEvidenceId(next); document.getElementById('evidence-title')?.focus()}
  const company = run?.report?.companies.find(c => c.ticker === ticker) ?? run?.report?.companies[0]
  const showDiscovery = view === 'discovery' && !ticker
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to research</a>
    <aside className="sidebar"><a className="brand" href="?view=research&run=example-msft"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{(['research', 'discovery', 'history'] as View[]).map((item, i) => <button key={item} aria-current={view === item ? 'page' : undefined} onClick={() => navigate(item)}><span aria-hidden="true">{['◧', '⊞', '◷'][i]}</span>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Local workspace<p>Evidence first.<br />Every revision in view.</p><small>Five-company research universe<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {view.toUpperCase()}</span><span className="local-status">LOCAL · SINGLE USER</span></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{view === 'research' ? 'Read beyond the claim.' : view === 'discovery' ? ticker ? 'Inside the candidate.' : 'A smaller, clearer shortlist.' : 'Return to the evidence.'}</h1><p>{view === 'research' ? 'Investigate a company, inspect its sources, and follow what changed.' : view === 'discovery' ? 'Screen the declared universe. Keep exclusions and missing evidence visible.' : 'Original inputs. Saved evidence. A review trail you can reopen.'}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {configError && <ErrorBox message={configError} retry={() => setAttempt(a => a + 1)} />}
      {view === 'history' ? <History onOpen={(runId, kind) => navigate(kind, runId)} /> : <>
        {config && <RequestForm key={view} view={view} config={config} current={run} onOpen={(runId, kind) => navigate(kind, runId)} />}
        {error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}
        {loading && <div className="notice" role="status">Loading the saved investigation…</div>}
        {!id && !loading && <section className="empty-state"><span className="section-label">READY WHEN YOU ARE</span><h2>{view === 'research' ? 'Start with a question and a source.' : 'Make the selection criteria explicit.'}</h2><p>Open a labelled teaching replay to explore the full evidence trail, or configure live retrieval and inference for a new investigation.</p><button className="secondary" onClick={() => navigate(view, view === 'research' ? 'example-msft' : 'example-discovery')}>Explore the teaching example ↗</button></section>}
        {run && <>
          <div className={`run-banner ${run.synthetic ? 'synthetic' : ''}`}><div><Badge tone={run.synthetic ? 'amber' : ''}>{run.synthetic ? 'SYNTHETIC TEACHING DATA' : 'RESEARCH RUN'}</Badge><strong>{modeLabel[run.request.mode]}</strong></div><span>Cutoff {stamp(run.request.cutoff)}</span></div>
          {run.synthetic && <p className="synthetic-caption">Illustrative figures and teaching sources. These are not actual company financials. {run.request.mode === 'replay' && 'The correction is a recorded fixture, not a live model result.'}</p>}
          <div className="run-state" aria-live="polite"><span className={active(run) ? 'pulse-dot' : 'status-dot'} /><strong>{run.status.replaceAll('_', ' ')}</strong><span>{run.stage}</span></div>
          {run.error && <ErrorBox message={run.error} />}
          {active(run) && <p className="muted">This run continues on the server if you leave or refresh. Updates are checked every two seconds.</p>}
          {run.report && (showDiscovery ? <Discovery run={run} onCompany={selected => navigate('discovery', run.id, selected)} /> : company ? <>{ticker && <button className="text-button back-button" onClick={() => navigate('discovery', run.id)}>← Back to screening results</button>}<div className="report-layout"><div className="report-body"><ResearchReport company={company} onEvidence={showEvidence} /></div><EvidencePanel runId={run.id} evidenceId={evidenceId} onClose={() => {setEvidenceId(null); evidenceTrigger.current?.focus()}} /></div></> : <div className="notice">No company results are available yet. Check the run status and recorded actions.</div>)}
          <details className="activity"><summary>Activity log <span>{run.actions.length} recorded actions</span></summary><ol>{run.actions.map(a => <li key={a.sequence}><time>{stamp(a.at)}</time><strong>{a.role}</strong><span>{a.message}</span></li>)}</ol><p className="mono">Run ID: {run.id}</p></details>
        </>}
      </>}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div>
}
