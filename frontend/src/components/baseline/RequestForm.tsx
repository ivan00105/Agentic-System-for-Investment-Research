import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { active, api, ApiError, modeLabel, stamp } from '../../api'
import type { Config, HistoryItem, Mode, Run, RunRequest, View } from '../../api'
import { ErrorBox } from '../ErrorBox'

export function RequestForm({view, config, current, onOpen}: {view: 'research' | 'discovery'; config: Config; current: Run | null; onOpen: (id: string, view: View) => void}) {
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
          {sources.map(s => <option key={s.id} value={s.id}>{s.label ? `${s.label} · ` : ''}{s.request.ticker ?? 'Five-company screen'} · {s.synthetic ? 'teaching example · ' : ''}{stamp(s.created_at)}</option>)}
        </select></label>}
        <button className="primary submit" disabled={busy || !!pending || (mode !== 'fresh' && !source) || (mode !== 'replay' && active(current))}>{busy ? 'Submitting…' : mode === 'replay' ? 'Open saved report ↗' : view === 'research' ? 'Start research →' : 'Screen companies →'}</button>
      </div>
      {view === 'discovery' && mode !== 'replay' && <div className="form-grid screen-controls"><label>Sector<select value={sector} onChange={e => setSector(e.target.value)}>{['All', 'Technology', 'Consumer discretionary', 'Communication services'].map(s => <option key={s}>{s}</option>)}</select></label><label>Minimum annual margin (%)<input type="number" min="-1000" max="1000" step="0.1" required value={threshold} onChange={e => setThreshold(e.target.value)} /></label><label>Maximum selected companies<select value={limit} onChange={e => setLimit(Number(e.target.value))}>{[1, 2, 3, 4, 5].map(n => <option key={n}>{n}</option>)}</select></label></div>}
      {mode !== 'replay' && <><label className="model-choice"><input type="checkbox" checked={modelAnalysis} onChange={e => setModelAnalysis(e.target.checked)} aria-describedby="model-choice-note" />Include model analysis (optional)</label><p className="form-note" id="model-choice-note">Financial figures are prepared without model analysis by default. Opt in to add an evidence review.</p></>}
      <p className="form-note">{mode === 'replay' ? 'Reopen the saved result without starting new research.' : mode === 'frozen' ? `Use the same saved sources again, with their original cutoff${source ? ` (${stamp(source.request.cutoff)})` : ''}.` : 'Find the latest available annual SEC facts before your cutoff and calculate the figures.'}</p>
      {mode !== 'replay' && modelAnalysis && !config.model_configured && <p className="configuration-note">Model analysis is unavailable in this setup. Financial figures can still be prepared and saved. <a href="?view=setup">See Setup &amp; status for what to set.</a></p>}
      {mode === 'fresh' && !config.sec_configured && <p className="configuration-note">SEC source access is required for fresh research. <a href="?view=setup">See Setup &amp; status for what to set.</a> Missing access causes a source error; teaching data will not be substituted.</p>}
    </form>
    {pending && <div className="notice" role="status"><strong>Recover your research request</strong><p>Your request may already have been received. Check for its saved result without starting another investigation.</p><button className="secondary" disabled={busy} onClick={() => void send(pending)}>Recover request</button></div>}
    {error && <ErrorBox message={error} retry={pending ? undefined : () => {setError(''); setRetry(r => r + 1)}} />}
  </section>
}
