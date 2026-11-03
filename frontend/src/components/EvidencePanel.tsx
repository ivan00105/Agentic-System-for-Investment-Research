import { useEffect, useRef, useState } from 'react'
import { api, stamp } from '../api'
import type { Evidence } from '../api'
import { Badge } from './Badge'
import { ErrorBox } from './ErrorBox'

export function EvidencePanel({runId, evidenceId, onClose}: {runId: string; evidenceId: string | null; onClose: () => void}) {
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
