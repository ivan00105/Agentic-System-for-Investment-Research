// The thin web path for agent runs (PROJECT_GUIDE Phase 7): question → run → progress → cited report → History.
import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { agentApi, agentRunning, stamp } from './api'
import type { AgentProgress, AgentReport, AgentRunSummary, Condition } from './api'

const CONDITIONS: Record<Condition, string> = {D: 'Analyst team with critic', C: 'Analyst team', B: 'Single agent'}
const STATUS: Record<string, string> = {
  running: 'Running', stopping: 'Stopping after the current step', finished: 'Finished',
  stopped_at_limit: 'Stopped at the step limit (partial report)', stopped: 'Cancelled (partial report)', failed: 'Failed',
  incomplete: 'No end recorded: still running elsewhere, or interrupted',
}
const tone = (status: string) => ['cited', 'finished'].includes(status) ? 'green' : ['abstained', 'running'].includes(status) ? '' : 'amber'
const clock = (at: string) => new Date(at).toISOString().slice(11, 19) + ' UTC'
// Only link to SEC pages; source URLs come from our own tools, but a saved trace is still a file on disk.
const secUrl = (url: string | null) => url && /^https:\/\/(www|data)\.sec\.gov\//.test(url) ? url : null

function Badge({children, tone = ''}: {children: ReactNode; tone?: string}) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function AgentQuestion({onStarted}: {onStarted: (id: string) => void}) {
  const [question, setQuestion] = useState('')
  const [condition, setCondition] = useState<Condition>('D')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !question.trim()) return
    setBusy(true); setError('')
    try { onStarted((await agentApi.start(question, condition)).run_id) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="request-panel agent-question" aria-label="Ask the research agents">
    <form onSubmit={submit}>
      <label>Research question<textarea rows={3} required value={question} onChange={e => setQuestion(e.target.value)} placeholder="e.g. Is NVIDIA's profitability sustainable? What are the main risks?" /></label>
      <details className="agent-options"><summary>Advanced options</summary>
        <label>Agents<select value={condition} onChange={e => setCondition(e.target.value as Condition)}>{(Object.keys(CONDITIONS) as Condition[]).map(c => <option key={c} value={c}>{c} · {CONDITIONS[c]}{c === 'D' ? ' (default)' : ''}</option>)}</select></label>
      </details>
      <button className="primary" disabled={busy || !question.trim()}>{busy ? 'Starting…' : 'Research this question →'}</button>
    </form>
    <p className="form-note">The agents read SEC filings, financial facts and prices, then write a report in which every statement cites its evidence. A run takes several minutes and keeps going if you leave this page.</p>
    {error && <div className="notice error" role="alert">{error}</div>}
  </section>
}

export function AgentRunView({id}: {id: string}) {
  const [run, setRun] = useState<AgentProgress | null>(null)
  const [report, setReport] = useState<AgentReport | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout> | undefined
    setRun(null); setReport(null); setError('')
    async function load() {
      try {
        const next = await agentApi.get(id)
        if (!alive) return
        setRun(next)
        if (agentRunning(next.status)) timer = setTimeout(load, 2000)
        else if (next.status !== 'incomplete') { const saved = await agentApi.report(id); if (alive) setReport(saved) }
      } catch (e) { if (alive) setError((e as Error).message) }
    }
    void load()
    return () => { alive = false; clearTimeout(timer) }
  }, [id, attempt])
  async function cancel() {
    try { const next = await agentApi.cancel(id); setRun(current => current && {...current, status: next.status}) }
    catch (e) { setError((e as Error).message) }
  }
  if (error) return <div className="notice error" role="alert"><p>{error}</p><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Retry</button></div>
  if (!run) return <div className="notice" role="status">Loading the agent run…</div>
  const running = agentRunning(run.status)
  return <section className="report-body agent-run">
    <div className="report-section">
      <div className="section-label">AGENT RUN · {run.condition ?? 'starting'}</div>
      <h2 className="agent-run-question">{run.question ?? 'Starting…'}</h2>
      <div className="run-state" aria-live="polite"><span className={running ? 'pulse-dot' : 'status-dot'} /><strong>{STATUS[run.status] ?? run.status}</strong>{run.started_at && <span>Started {stamp(run.started_at)}</span>}</div>
      {running && <><button className="secondary" disabled={run.status === 'stopping'} onClick={() => void cancel()}>{run.status === 'stopping' ? 'Stopping…' : 'Cancel run'}</button>
        <p className="muted">Cancelling keeps what the agents found so far as a partial report. It takes effect after the current model or tool call.</p></>}
      <details className="activity agent-progress" open={running}><summary>Progress <span>{run.progress.length} steps</span></summary>
        <ol>{run.progress.map((line, i) => <li key={i}>{line.at ? <time dateTime={line.at}>{clock(line.at)}</time> : <span />}<span>{line.text}</span></li>)}</ol>
      </details>
      <p className="mono muted">Run ID: {run.run_id}</p>
    </div>
    {report && <AgentReportView report={report} />}
  </section>
}

function AgentReportView({report}: {report: AgentReport}) {
  const totals = report.totals
  return <>
    <div className="report-section">
      <div className="section-heading"><h2>Report</h2><Badge tone={tone(report.status)}>{report.status_label}</Badge></div>
      {report.error && <p className="configuration-note">Error: {report.error}</p>}
      {totals && <p className="muted">{totals.model_calls} model calls · {totals.tool_calls} tool calls · {totals.total_tokens.toLocaleString('en-US')} tokens{totals.cost != null && ` · $${totals.cost.toFixed(2)}`}{report.model && ` · ${report.model}`}{report.cutoff && ` · cutoff ${stamp(report.cutoff)}`}</p>}
    </div>
    {report.sections.length === 0 ? <div className="report-section"><pre className="excerpt">{report.markdown}</pre></div> : report.sections.map(section => <section className="report-section" key={section.key}>
      <div className="section-heading"><h3>{section.heading}</h3><Badge tone={tone(section.status)}>{section.status}</Badge></div>
      {section.claims.length === 0 ? <p className="empty-inline">Abstained: nothing here is backed by evidence the agents found.</p> : <ul className="agent-claims">{section.claims.map((claim, i) => <li key={i}>
        {claim.text}{claim.citations.map(n => <a key={n} className="citation" href={`#source-${n}`} aria-label={`Source ${n}`}> [{n}]</a>)}
        {claim.status === 'qualified' && <> <Badge tone="amber">qualified</Badge><ul className="agent-flags">{claim.flags.map((flag, j) => <li key={j}>{flag}</li>)}</ul></>}
      </li>)}</ul>}
    </section>)}
    {report.objections.length > 0 && <section className="report-section"><h3>Critic review</h3><ul className="agent-claims">{report.objections.map((o, i) => <li key={i}>
      <Badge tone={o.outcome === 'unresolved' ? 'amber' : 'green'}>{o.outcome}</Badge> <strong>{o.issue}{o.material ? ', material' : ''}</strong> ({o.claim} v{o.version}): {o.problem}
      {o.explanation && <p className="muted">{o.explanation}</p>}
    </li>)}</ul></section>}
    {report.limitations.length > 0 && <section className="report-section limitations"><h3>Limitations</h3><ul>{report.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul></section>}
    {report.sources.length > 0 && <section className="report-section"><h3>Sources</h3><ol className="agent-sources">{report.sources.map(source => <li key={source.id} id={`source-${source.n}`}>
      {source.text} <span className="mono">{source.id}</span>{secUrl(source.url) && <> <a href={secUrl(source.url)!} target="_blank" rel="noopener noreferrer">Open filing ↗</a></>}
    </li>)}</ol></section>}
  </>
}

export function AgentHistory({onOpen}: {onOpen: (id: string) => void}) {
  const [items, setItems] = useState<AgentRunSummary[] | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true; setError('')
    agentApi.list().then(result => { if (alive) setItems(result.items) }).catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [attempt])
  return <section className="report-section history agent-history">
    <div className="section-heading"><h2>Agent runs</h2><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Refresh</button></div>
    <p className="muted">Every agent run saved in data/traces, including runs started from the command line. Opening one never starts new research.</p>
    {error && <div className="notice error" role="alert">{error}</div>}
    {items === null ? !error && <p role="status">Loading agent runs…</p> : items.length === 0 ? <p>No agent runs yet. Ask a question on the Research page.</p> : <div className="history-list">{items.map(run => <article className="history-entry" key={run.run_id}>
      <div className="history-row">
        <div className="history-info"><strong className="agent-history-question">{run.question ?? 'Question not recorded'}</strong><span>{run.condition ?? 'Condition not recorded'}</span></div>
        <div><Badge tone={tone(run.status)}>{run.status.replaceAll('_', ' ')}</Badge>{run.started_at && <small>{stamp(run.started_at)}</small>}</div>
        <button className="text-button history-open" onClick={() => onOpen(run.run_id)}>Open ↗</button>
      </div>
    </article>)}</div>}
  </section>
}
