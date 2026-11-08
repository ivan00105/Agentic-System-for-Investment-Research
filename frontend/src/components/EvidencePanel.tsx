import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { agentApi, sourceLink, stamp } from '../api'
import type { AgentRecord } from '../api'
import { Badge } from './Badge'
import { ErrorBox } from './ErrorBox'

// The source desk beside an agent run's report: a frozen record opens here.
function EvidenceShell({focus, onClose, children}: {focus: string | null; onClose: () => void; children: ReactNode}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const open = focus !== null
  useEffect(() => { if (focus !== null) heading.current?.focus() }, [focus])
  return <aside className="evidence-panel" aria-labelledby="evidence-title"><div className="section-label">SOURCE DESK</div><div className="section-heading"><h2 id="evidence-title" ref={heading} tabIndex={-1}>Evidence inspector</h2>{open && <button onClick={onClose} className="text-button" aria-label="Close evidence inspector">Close</button>}</div>
    {!open ? <div className="evidence-empty"><div className="document-icon" aria-hidden="true">≡</div><h3>Keep the source beside the claim.</h3><p>Select an evidence link to inspect the saved excerpt, reporting period and provenance.</p><div className="evidence-principles"><span>01 &nbsp; Original excerpt</span><span>02 &nbsp; Period & availability</span><span>03 &nbsp; Saved source copy</span></div></div> : children}
  </aside>
}

function useLoad<T>(load: (() => Promise<T>) | null, key: string) {
  const [value, setValue] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true; setValue(null); setError('')
    load?.().then(v => {if (alive) setValue(v)}).catch(e => {if (alive) setError(e.message)})
    return () => {alive = false}
  }, [key, attempt])
  return {value, error, retry: () => setAttempt(a => a + 1)}
}

// An agent run's frozen record; a calculation links to its inputs and an analyst finding to what it cites.
export function RecordPanel({runId, trail, onOpen, onBack, onClose}: {runId: string; trail: string[]; onOpen: (id: string) => void; onBack: () => void; onClose: () => void}) {
  const recordId = trail[trail.length - 1] ?? null
  const {value: record, error, retry} = useLoad<AgentRecord>(recordId ? () => agentApi.record(runId, recordId) : null, `${runId}/${recordId}`)
  const link = sourceLink(record?.url ?? null)
  return <EvidenceShell focus={recordId} onClose={onClose}>
    {trail.length > 1 && <button className="text-button" onClick={onBack}>← Back</button>}
    {error ? <ErrorBox message={error} retry={retry} /> : !record ? <p role="status">Loading saved evidence…</p> : <>
      <Badge tone="green">{record.group}</Badge><h3 className="source-title">{record.title}</h3>
      {record.excerpt && <pre className="excerpt">{record.excerpt}</pre>}
      {record.rows.length > 0 && <dl className="source-meta">{record.rows.map((row, i) => <div key={i}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>}
      {record.available_at && <dl className="source-meta"><dt>Public from</dt><dd>{stamp(record.available_at)}</dd></dl>}
      {record.links.length > 0 && <><h3>Built from</h3><div className="source-chips">{record.links.map(link => <button type="button" key={link.id} className="source-chip" onClick={() => onOpen(link.id)}>{link.label}</button>)}</div></>}
      {link && <a className="source-link" href={link.href} target="_blank" rel="noopener noreferrer">Open on {link.site} ↗</a>}
      <p className="mono muted">{record.id}</p>
    </>}
  </EvidenceShell>
}
