// History's rename, archive and delete for one saved agent run. A label and the archived flag sit in labels.json
// beside the traces; the traces themselves are frozen evidence and never edited. Delete removes the trace file.
import { useState } from 'react'
import { agentApi, agentRunning } from '../../api'
import type { AgentRunSummary } from '../../api'
import { childCount } from './labels'

const LABEL_MAX = 120 // the server's config.RUN_LABEL_MAX

export function RunActions({run, top, onChanged}: {run: AgentRunSummary; top: boolean; onChanged: () => void}) {
  const [mode, setMode] = useState<'buttons' | 'rename' | 'delete'>('buttons')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const children = run.children ?? []
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError('')
    try { await action(); setMode('buttons'); onChanged() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const remove = (withChildren: boolean) => void act(() => agentApi.remove(run.run_id, withChildren))
  const close = () => { setMode('buttons'); setError('') }
  return <>
    {mode === 'rename' ? <form className="rename-form" onSubmit={e => { e.preventDefault(); void act(() => agentApi.update(run.run_id, {label: draft.trim() || null})) }}>
      <label>Label<input autoFocus maxLength={LABEL_MAX} disabled={busy} value={draft} onChange={e => setDraft(e.target.value)} aria-describedby={`label-note-${run.run_id}`} /></label>
      <span className="muted label-count">{draft.length}/{LABEL_MAX}</span>
      <button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      <button type="button" className="secondary" disabled={busy} onClick={close}>Cancel</button>
      <p className="form-note" id={`label-note-${run.run_id}`}>Shown as the run's title. Leave it empty to use the question again.</p>
    </form>
    : mode === 'delete' ? <div className="delete-confirm" role="group" aria-label="Confirm delete">
      <p><strong>Delete this run for good?</strong> This can't be undone: its saved trace and evidence are removed.{children.length > 0 && ` It started ${childCount(children)}.`}</p>
      <div className="history-actions">
        {children.length > 0 && <button className="primary danger" disabled={busy} onClick={() => remove(true)}>Delete it and its {children.length} run{children.length === 1 ? '' : 's'}</button>}
        <button className={children.length ? 'secondary' : 'primary danger'} disabled={busy} onClick={() => remove(false)}>{children.length ? 'Delete only this run' : 'Delete'}</button>
        <button className="secondary" disabled={busy} onClick={close}>Cancel</button>
      </div>
      {children.length > 0 && <p className="form-note">Kept runs move to the top of the list on their own.</p>}
    </div>
    : <div className="history-actions">
      <button className="secondary" onClick={() => { setDraft(run.label ?? ''); setMode('rename') }}>{run.label ? 'Rename' : 'Add label'}</button>
      {top && <button className="secondary" disabled={busy} onClick={() => void act(() => agentApi.update(run.run_id, {archived: !run.archived}))}>{busy ? 'Updating…' : run.archived ? 'Restore' : 'Archive'}</button>}
      <button className="secondary" disabled={agentRunning(run.status)} title={agentRunning(run.status) ? 'Cancel the run before deleting it.' : undefined} onClick={() => setMode('delete')}>Delete</button>
    </div>}
    {error && <div className="notice error" role="alert">{error}</div>}
  </>
}
