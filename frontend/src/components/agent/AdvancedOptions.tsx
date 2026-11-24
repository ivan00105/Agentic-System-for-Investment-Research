// The question box's advanced options: agents, model, the Discover spec review and the cutoff. Open in the
// Professional view, folded away otherwise.
import { useEffect, useState } from 'react'
import { api, setupApi } from '../../api'
import type { Condition, Config, ModelSource } from '../../api'
import { useLevel } from '../../level'
import { CONDITIONS } from './labels'

export interface Options { condition: Condition | ''; model: string; modelSource: string; agentModels: Record<string, string>; editSpec: boolean; cutoff: string }

export function AdvancedOptions({find, options, onChange, onDefaults}: {
  find: boolean; options: Options; onChange: (next: Partial<Options>) => void;
  onDefaults?: (defaults: {modelSource: string; agentModels: Record<string, string>}) => void
}) {
  const {level} = useLevel()
  const [defaultModel, setDefaultModel] = useState<string | null>(null)
  const [sources, setSources] = useState<ModelSource[]>([])
  const [agents, setAgents] = useState<Config['agents'] | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  useEffect(() => {
    api.config().then(c => {
      setDefaultModel(c.model)
      setSources(c.model_sources ?? [])
      setAgents(c.agents ?? null)
      const defaultSource = c.default_model_source ?? 'default'
      const agentModels = c.default_agent_models ?? {}
      onDefaults?.({modelSource: defaultSource, agentModels})
    }).catch(() => { setDefaultModel(null); setSources([]) })
  }, [])
  const configured = sources.filter(source => source.configured)
  const activeSource = configured.find(s => s.id === (options.modelSource || 'default')) ?? configured[0]
  const shownDefaultModel = activeSource?.model || defaultModel
  // Not chosen yet: show the set-up the server will use for this mode, by name.
  const preset = agents?.[find ? 'find' : 'research']
  const effectiveCondition = options.condition || preset || (find ? 'B' : 'D')
  const roles: {key: string; label: string}[] = [
    ...(effectiveCondition === 'B' ? [{key: 'single_agent', label: 'Single agent'}] : [
      {key: 'coordinator', label: 'Coordinator'},
      {key: 'fundamentals', label: 'Fundamentals analyst'},
      {key: 'filings', label: 'Filings & events analyst'},
      {key: 'market', label: 'Market & valuation analyst'},
      ...(effectiveCondition === 'D' ? [{key: 'critic', label: 'Critic'}] : []),
    ]),
    ...(find ? [{key: 'screener', label: 'Discover screener'}] : []),
  ]
  async function saveAsDefaults() {
    setSaving(true); setSavedMsg('')
    try {
      const res = await setupApi.saveModelPreferences({
        default_source: options.modelSource || 'default',
        agent_models: options.agentModels,
      })
      onDefaults?.({modelSource: res.default_model_source ?? 'default', agentModels: res.default_agent_models ?? {}})
      setSavedMsg('Saved as webapp defaults.')
    } catch (e) { setSavedMsg(`Save failed: ${(e as Error).message}`) }
    finally { setSaving(false) }
  }
  return <details className="agent-options" open={level === 'professional'}><summary>Advanced options</summary>
    <label>Agents<select value={options.condition || preset || ''} onChange={e => onChange({condition: e.target.value as Condition | ''})}>{!options.condition && !preset && <option value="">Set by the server</option>}{(['D', 'C', 'B'] as Condition[]).map(c => <option key={c} value={c}>{CONDITIONS[c]}</option>)}</select></label>
    <p className="form-note">{find ? 'Find researches each pick in turn. Its default is one agent per pick, so a shortlist takes minutes rather than an hour.' : 'The default is the analyst team with critic: three analysts write the report and a critic checks it.'}</p>
    {configured.length > 1 && <label>Default model source<select value={options.modelSource || configured[0].id} onChange={e => { setSavedMsg(''); onChange({modelSource: e.target.value}) }}>
      {configured.map(source => <option key={source.id} value={source.id}>{source.label}: {source.model}</option>)}
    </select></label>}
    <label>Model<input value={options.model} onChange={e => onChange({model: e.target.value})} placeholder={shownDefaultModel ?? 'the model set in .env'} spellCheck={false} /></label>
    <p className="form-note">Leave empty for {shownDefaultModel ? <code>{shownDefaultModel}</code> : 'the model set in .env'}. Another model ID of the same provider must support tool calling.</p>
    {configured.length > 1 && <fieldset className="agent-models"><legend>Choose a model source for each agent</legend>
      {roles.map(role => <label key={role.key}>{role.label}<select value={options.agentModels[role.key] ?? ''} onChange={e => { setSavedMsg(''); onChange({agentModels: {...options.agentModels, [role.key]: e.target.value}}) }}>
        <option value="">Use default{activeSource ? ` (${activeSource.label}: ${activeSource.model})` : ''}</option>
        {configured.map(source => <option key={source.id} value={source.id}>{source.label}: {source.model}</option>)}
      </select></label>)}
      <div className="agent-models-actions"><button type="button" className="secondary" disabled={saving} onClick={() => void saveAsDefaults()}>{saving ? 'Saving…' : 'Save as webapp defaults'}</button>{savedMsg && <span role="status" className="form-note">{savedMsg}</span>}</div>
    </fieldset>}
    {find ? <>
      <label className="radio"><input type="checkbox" checked={options.editSpec} onChange={e => onChange({editSpec: e.target.checked})} /><span>Let me check and edit the screen spec before it runs<small>The run waits for you even when no word in the request is vague.</small></span></label>
      <p className="form-note">Find uses current data only, so it has no cutoff.</p>
    </> : <label>Research as of (end of day, UTC)<input type="date" value={options.cutoff} max={new Date().toISOString().slice(0, 10)} onChange={e => onChange({cutoff: e.target.value})} /></label>}
  </details>
}
