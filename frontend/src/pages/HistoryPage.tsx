import { useEffect, useState } from 'react'
import { RunList } from '../components/agent/RunList'
import { api, investigationLabel, stamp } from '../api'
import type { HistoryItem, View } from '../api'
import { Badge } from '../components/Badge'
import { ErrorBox } from '../components/ErrorBox'

function BaselineHistory({onOpen}: {onOpen: (id: string, view: View) => void}) {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [archived, setArchived] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [labelDraft, setLabelDraft] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{id: string; message: string; retry: () => void} | null>(null)
  useEffect(() => {let alive = true; setLoading(true); setError(''); api.history(offset, archived).then(h => {if (alive) {setItems(h.items); setTotal(h.total)}}).catch(e => {if (alive) setError(e.message)}).finally(() => {if (alive) setLoading(false)}); return () => {alive = false}}, [offset, archived, attempt])
  async function organize(id: string, update: {label?: string | null; archived?: boolean}, retry: () => void) {
    setBusyId(id); setActionError(null)
    try {await api.updateRun(id, update); setEditingId(null); setOffset(0); setAttempt(a => a + 1)}
    catch (e) {setActionError({id, message: (e as Error).message, retry})}
    finally {setBusyId(null)}
  }
  const retryAction = () => actionError?.retry()
  return <section className="report-section history"><div className="section-heading"><h2>Saved investigations</h2><button className="secondary" disabled={loading || busyId !== null} onClick={() => setAttempt(a => a + 1)}>Refresh history</button></div><p className="muted">Reopen the original inputs, sources and review trail. Opening a saved report never starts new research. Archived reports stay available through their saved links, including source evidence.</p>
    <label className="history-filter">Show<select aria-label="Saved report status" disabled={loading || busyId !== null} value={archived ? 'archived' : 'active'} onChange={e => {setArchived(e.target.value === 'archived'); setOffset(0); setEditingId(null); setActionError(null)}}><option value="active">Active reports</option><option value="archived">Archived reports</option></select></label>
    {error && <ErrorBox message={error} retry={() => setAttempt(a => a + 1)} />}{actionError && <div className="notice error" role="alert"><strong>Could not update this saved report</strong><p>{actionError.message}</p><button className="secondary" disabled={busyId !== null || loading} onClick={retryAction}>Retry</button></div>}
    {loading ? <p role="status">Loading saved reports…</p> : items.length === 0 ? <p>{archived ? 'No archived reports.' : 'No active saved reports yet. Start an investigation from Research.'}</p> : <div className="history-list">{items.map(r => <article className="history-entry" key={r.id} data-run-id={r.id}>
      <div className="history-row"><div className="history-info"><strong>{r.label || r.request.ticker || 'Five-company discovery'}</strong><span>{r.label ? `${r.request.ticker ?? 'Five-company discovery'} · ` : ''}{investigationLabel(r.request)}{r.synthetic ? ' · Synthetic teaching data' : ''}</span></div><div><Badge tone={r.status === 'completed' ? 'green' : 'amber'}>{r.status.replaceAll('_', ' ')}</Badge><small>{stamp(r.created_at)}</small></div><button className="text-button history-open" disabled={loading || busyId === r.id} onClick={() => onOpen(r.id, r.request.kind)}>Open ↗</button></div>
      {editingId === r.id ? <form className="rename-form" onSubmit={event => {event.preventDefault(); const update = {label: labelDraft.trim() || null}; const retry = () => void organize(r.id, update, retry); void organize(r.id, update, retry)}}><label>Report label<input autoFocus maxLength={120} disabled={busyId === r.id} value={labelDraft} onChange={e => {setLabelDraft(e.target.value); setActionError(null)}} aria-describedby={`label-count-${r.id}`} /></label><span id={`label-count-${r.id}`} className="muted label-count">{labelDraft.length}/120</span><button className="primary" disabled={loading || busyId === r.id}>{busyId === r.id ? 'Saving…' : 'Save'}</button><button type="button" className="secondary" disabled={busyId === r.id} onClick={() => {setEditingId(null); setActionError(null)}}>Cancel</button></form> : <div className="history-actions"><button className="secondary" disabled={loading || busyId !== null} onClick={() => {setEditingId(r.id); setLabelDraft(r.label ?? ''); setActionError(null)}}>{r.label ? 'Rename' : 'Add label'}</button><button className="secondary" disabled={loading || busyId !== null} onClick={() => {const update = {archived: !archived}; const retry = () => void organize(r.id, update, retry); void organize(r.id, update, retry)}}>{busyId === r.id ? 'Updating…' : archived ? 'Restore' : 'Archive'}</button></div>}
    </article>)}</div>}
    <div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 30))}>Previous</button><span>{total ? `${offset + 1}–${Math.min(offset + 30, total)} of ${total}` : '0 reports'}</span><button className="secondary" disabled={offset + 30 >= total || loading} onClick={() => setOffset(offset + 30)}>Next</button></div></section>
}

export function HistoryPage({onOpen, onOpenAgent}: {onOpen: (id: string, view: View) => void; onOpenAgent: (id: string) => void}) {
  return <><RunList onOpen={onOpenAgent} /><BaselineHistory onOpen={onOpen} /></>
}
