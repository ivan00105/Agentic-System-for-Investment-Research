// One agent run: its question and state, Discover's questions while it waits, the live timeline, then the report.
import { useEffect, useState } from 'react'
import { agentApi, agentRunning, stamp } from '../../api'
import type { AgentProgress, AgentReport as Report, CompanyMatch } from '../../api'
import { AgentReport } from './AgentReport'
import { DiscoverQuestions, DiscoverReport } from './Discover'
import { useLevel } from '../../level'
import { STATUS } from './labels'
import { RunTimeline } from './RunTimeline'

export function RunView({id, onOpenRun, onNew, onCompare}: {id: string; onOpenRun: (id: string) => void; onNew: () => void; onCompare: (companies: CompanyMatch[], parent: string) => void}) {
  const [run, setRun] = useState<AgentProgress | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const {level} = useLevel()
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
  const back = <button className="text-button back-button" onClick={onNew}>← Ask another question</button>
  if (error) return <>{back}<div className="notice error" role="alert"><p>{error}</p><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Retry</button></div></>
  if (!run) return <div className="notice" role="status">Loading the agent run…</div>
  const running = agentRunning(run.status)
  const title = run.title ?? run.question ?? 'Starting…'
  return <>
    {back}
    <section className="report-body agent-run">
      <div className="report-section">
        <div className="section-label">AGENT RUN · {run.condition ?? 'starting'}</div>
        <h2 className="agent-run-question">{title}</h2>
        {run.question && (run.kind === 'pick' ? <details className="run-brief"><summary>The brief its research agents got</summary><p>{run.question}</p></details>
          : run.question !== title && <p className="run-brief">{run.question}</p>)}
        {run.preferences && <div className="preferences-shown"><div className="section-label">YOUR PREFERENCES</div><p>{run.preferences}</p><p className="muted">From Help me start. The agents read this note with the question; it shapes what they stress, not the evidence rules.</p></div>}
        <div className="run-state" aria-live="polite"><span className={running ? 'pulse-dot' : 'status-dot'} /><strong>{STATUS[run.status] ?? run.status}</strong>{run.started_at && <span>Started {stamp(run.started_at)}</span>}</div>
        {running && <div className="run-actions"><button className="secondary" disabled={run.status === 'stopping'} onClick={() => void cancel()}>{run.status === 'stopping' ? 'Stopping…' : 'Cancel run'}</button>
          <p className="muted">Cancelling keeps what the agents found so far as a partial report. It takes effect after the current model or tool call. The run keeps going if you leave this page.</p></div>}
        {run.status === 'waiting' && run.questions && <DiscoverQuestions runId={id} questions={run.questions} onAnswered={() => setAttempt(a => a + 1)} />}
        <details className="activity agent-progress" open={running || level === 'professional'}><summary>How the agents worked <span>{run.progress.length} steps</span></summary>
          <RunTimeline lines={run.progress} running={running} />
        </details>
      </div>
    </section>
    {report?.discover && report.error && <div className="notice error" role="alert">The run failed: {report.error}</div>}
    {report && (report.discover ? <DiscoverReport result={report.discover} onOpenRun={onOpenRun} onCompare={companies => onCompare(companies, id)} /> : <AgentReport runId={id} report={report} />)}
  </>
}
