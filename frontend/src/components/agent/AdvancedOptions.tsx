// The question box's advanced options: agents, model, the Discover spec review and the cutoff. Open in the
// Professional view, folded away otherwise.
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { Condition, Config } from '../../api'
import { useLevel } from '../../level'
import { CONDITIONS } from './labels'

export interface Options { condition: Condition | ''; model: string; editSpec: boolean; cutoff: string }

export function AdvancedOptions({find, options, onChange}: {find: boolean; options: Options; onChange: (next: Partial<Options>) => void}) {
  const {level} = useLevel()
  const [config, setConfig] = useState<Config | null>(null)
  useEffect(() => { api.config().then(setConfig).catch(() => setConfig(null)) }, [])
  const defaultModel = config?.model ?? null
  // Not chosen yet: show the set-up the server will use for this mode, by name.
  const preset = config?.agents?.[find ? 'find' : 'research']
  return <details className="agent-options" open={level === 'professional'}><summary>Advanced options</summary>
    <label>Agents<select value={options.condition || preset || ''} onChange={e => onChange({condition: e.target.value as Condition | ''})}>{!options.condition && !preset && <option value="">Set by the server</option>}{(['D', 'C', 'B'] as Condition[]).map(c => <option key={c} value={c}>{CONDITIONS[c]}</option>)}</select></label>
    <p className="form-note">{find ? 'Find researches each pick in turn. Its default is one agent per pick, so a shortlist takes minutes rather than an hour.' : 'The default is the analyst team with critic: three analysts write the report and a critic checks it.'}</p>
    <label>Model<input value={options.model} onChange={e => onChange({model: e.target.value})} placeholder={defaultModel ?? 'the model set in .env'} spellCheck={false} /></label>
    <p className="form-note">Leave empty for {defaultModel ? <code>{defaultModel}</code> : 'the model set in .env'}. Another model ID of the same provider must support tool calling.</p>
    {find ? <>
      <label className="radio"><input type="checkbox" checked={options.editSpec} onChange={e => onChange({editSpec: e.target.checked})} /><span>Let me check and edit the screen spec before it runs<small>The run waits for you even when no word in the request is vague.</small></span></label>
      <p className="form-note">Find uses current data only, so it has no cutoff.</p>
    </> : <label>Research as of (end of day, UTC)<input type="date" value={options.cutoff} max={new Date().toISOString().slice(0, 10)} onChange={e => onChange({cutoff: e.target.value})} /></label>}
  </details>
}
