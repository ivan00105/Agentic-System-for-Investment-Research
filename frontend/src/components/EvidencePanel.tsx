import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { agentApi, api, secUrl, stamp } from '../api'
import type { AgentRecord, Evidence } from '../api'
import { Badge } from './Badge'
import { ErrorBox } from './ErrorBox'

// The source desk beside a report: baseline A's evidence and an agent run's records open in the same panel.
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

export function EvidencePanel({runId, evidenceId, onClose}: {runId: string; evidenceId: string | null; onClose: () => void}) {
  const {value: evidence, error, retry} = useLoad<Evidence>(evidenceId ? () => api.evidence(runId, evidenceId) : null, `${runId}/${evidenceId}`)
  const safeUrl = evidence?.source_url && /^https:\/\/data\.sec\.gov\//.test(evidence.source_url) ? evidence.source_url : null
  return <EvidenceShell focus={evidenceId} onClose={onClose}>
    {error ? <ErrorBox message={error} retry={retry} /> : !evidence ? <p role="status">Loading saved evidence…</p> : <>
      <Badge tone={evidence.synthetic ? 'amber' : 'green'}>{evidence.synthetic ? 'Synthetic teaching source' : 'SEC company facts'}</Badge><h3 className="source-title">{evidence.title}</h3><pre className="excerpt">{evidence.excerpt}</pre><dl className="source-meta"><dt>Reporting period</dt><dd>{evidence.period}</dd><dt>Available by</dt><dd>{stamp(evidence.available_at)}</dd><dt>Saved on</dt><dd>{stamp(evidence.retrieved_at)}</dd></dl><details className="technical-details"><summary>Source details</summary><dl className="source-meta"><dt>Source locator</dt><dd>{evidence.locator}</dd><dt>Snapshot SHA-256</dt><dd className="mono hash">{evidence.snapshot_hash}</dd></dl></details>{safeUrl ? <a className="source-link" href={safeUrl} target="_blank" rel="noopener noreferrer">Open SEC source ↗</a> : <p className="muted">{evidence.synthetic ? 'This synthetic fixture has no original filing URL.' : 'No supported original source URL is recorded.'}</p>}
    </>}
  </EvidenceShell>
}

// An agent run's frozen record; a calculation links to its inputs and an analyst finding to what it cites.
export function RecordPanel({runId, trail, onOpen, onBack, onClose}: {runId: string; trail: string[]; onOpen: (id: string) => void; onBack: () => void; onClose: () => void}) {
  const recordId = trail[trail.length - 1] ?? null
  const {value: record, error, retry} = useLoad<AgentRecord>(recordId ? () => agentApi.record(runId, recordId) : null, `${runId}/${recordId}`)
  const url = secUrl(record?.url ?? null)
  return <EvidenceShell focus={recordId} onClose={onClose}>
    {trail.length > 1 && <button className="text-button" onClick={onBack}>← Back</button>}
    {error ? <ErrorBox message={error} retry={retry} /> : !record ? <p role="status">Loading saved evidence…</p> : <>
      <Badge tone="green">{record.group}</Badge><h3 className="source-title">{record.title}</h3>
      {record.excerpt && <pre className="excerpt">{record.excerpt}</pre>}
      {record.rows.length > 0 && <dl className="source-meta">{record.rows.map((row, i) => <div key={i}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>}
      {record.available_at && <dl className="source-meta"><dt>Public from</dt><dd>{stamp(record.available_at)}</dd></dl>}
      {record.links.length > 0 && <><h3>Built from</h3><div className="source-chips">{record.links.map(link => <button type="button" key={link.id} className="source-chip" onClick={() => onOpen(link.id)}>{link.label}</button>)}</div></>}
      {url && <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">Open on SEC.gov ↗</a>}
      <p className="mono muted">{record.id}</p>
    </>}
  </EvidenceShell>
}
