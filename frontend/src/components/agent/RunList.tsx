// Saved agent runs, newest first: the trace files in data/traces, including runs started from the command line.
// The runs a Discover run started (its picks, a comparison of them) sit under it, folded.
import { useEffect, useState } from 'react'
import { agentApi, stamp } from '../../api'
import type { AgentRunSummary } from '../../api'
import { Badge } from '../Badge'
import { tone } from './labels'

const count = (n: number, word: string) => n ? `${n} ${word}${n === 1 ? '' : 's'}` : ''
export const childCount = (children: AgentRunSummary[]) => {
  const picks = children.filter(c => c.kind === 'pick').length
  return [count(picks, 'pick'), count(children.length - picks, 'comparison')].filter(Boolean).join(' · ')
}

export function RunList({onOpen, recent, onSeeAll}: {onOpen: (id: string) => void; recent?: number; onSeeAll?: () => void}) {
  const [items, setItems] = useState<AgentRunSummary[] | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true; setError('')
    agentApi.list().then(result => { if (alive) setItems(result.items) }).catch(e => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [attempt])
  const shown = items && recent ? items.slice(0, recent) : items
  return <section className="report-section history agent-history">
    <div className="section-heading"><h2>{recent ? 'Recent runs' : 'Agent runs'}</h2><button className="secondary" onClick={() => setAttempt(a => a + 1)}>Refresh</button></div>
    <p className="muted">{recent ? 'Reopen a saved run. Opening one never starts new research.' : 'Every agent run saved in data/traces, including runs started from the command line. A Discover run keeps its picks under it. Opening a run never starts new research.'}</p>
    {error && <div className="notice error" role="alert">{error}</div>}
    {shown === null ? !error && <p role="status">Loading agent runs…</p> : shown.length === 0 ? <p>No agent runs yet. Ask a question above to start one.</p> : <div className="history-list">{shown.map(run => <article className="history-entry" key={run.run_id} data-run-id={run.run_id}>
      <RunRow run={run} onOpen={onOpen} />
      {run.children?.length ? <details className="run-children"><summary>{childCount(run.children)}</summary>
        <ul>{run.children.map(child => <li key={child.run_id} data-run-id={child.run_id}><RunRow run={child} onOpen={onOpen} /></li>)}</ul>
      </details> : null}
    </article>)}</div>}
    {recent && items && items.length > recent && <p className="muted">Showing the {recent} newest of {items.length} runs. <button className="text-button" onClick={onSeeAll}>See all in History →</button></p>}
  </section>
}

function RunRow({run, onOpen}: {run: AgentRunSummary; onOpen: (id: string) => void}) {
  return <div className="history-row">
    <div className="history-info"><strong className="agent-history-question">{run.title ?? run.question ?? 'Question not recorded'}</strong><span>{run.condition ?? 'Condition not recorded'}</span></div>
    <div><Badge tone={tone(run.status)}>{run.status.replaceAll('_', ' ')}</Badge>{run.started_at && <small>{stamp(run.started_at)}</small>}</div>
    <button className="text-button history-open" onClick={() => onOpen(run.run_id)}>Open ↗</button>
  </div>
}
