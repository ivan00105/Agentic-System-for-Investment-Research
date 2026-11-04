// Saved agent runs, newest first: the trace files in data/traces, including runs started from the command line.
import { useEffect, useState } from 'react'
import { agentApi, stamp } from '../../api'
import type { AgentRunSummary } from '../../api'
import { Badge } from '../Badge'
import { tone } from './labels'

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
    <p className="muted">{recent ? 'Reopen a saved run. Opening one never starts new research.' : 'Every agent run saved in data/traces, including runs started from the command line. Opening one never starts new research.'}</p>
    {error && <div className="notice error" role="alert">{error}</div>}
    {shown === null ? !error && <p role="status">Loading agent runs…</p> : shown.length === 0 ? <p>No agent runs yet. Ask a question above to start one.</p> : <div className="history-list">{shown.map(run => <article className="history-entry" key={run.run_id}>
      <div className="history-row">
        <div className="history-info"><strong className="agent-history-question">{run.question ?? 'Question not recorded'}</strong><span>{run.condition ?? 'Condition not recorded'}</span></div>
        <div><Badge tone={tone(run.status)}>{run.status.replaceAll('_', ' ')}</Badge>{run.started_at && <small>{stamp(run.started_at)}</small>}</div>
        <button className="text-button history-open" onClick={() => onOpen(run.run_id)}>Open ↗</button>
      </div>
    </article>)}</div>}
    {recent && items && items.length > recent && <p className="muted">Showing the {recent} newest of {items.length} runs. <button className="text-button" onClick={onSeeAll}>See all in History →</button></p>}
  </section>
}
