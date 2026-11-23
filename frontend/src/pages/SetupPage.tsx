import { useEffect, useState } from 'react'
import { api, setupApi, stamp } from '../api'
import type { DataKind, ModelSource, ProviderStatus } from '../api'
import { Badge } from '../components/Badge'
import { ErrorBox } from '../components/ErrorBox'

const STATUS: Record<ProviderStatus['status'], {text: string; tone: string}> = {
  ready: {text: 'Ready (no key needed)', tone: 'green'},
  configured: {text: 'Configured', tone: 'green'},
  not_configured: {text: 'Not configured', tone: 'amber'},
  check_failed: {text: 'Last check failed', tone: 'amber'},
}
const TIERS = ['Tier 0 · free, no key', 'Tier 1 · free with a key', 'Tier 2 · paid']
const CATALOGUE = 'https://github.com/ivan00105/Agentic-System-for-Investment-Research/blob/main/docs/REFERENCE.md#data-providers-by-kind-options-and-order'
const AGENT_ROLES: {key: string; label: string}[] = [
  {key: 'coordinator', label: 'Coordinator'},
  {key: 'fundamentals', label: 'Fundamentals analyst'},
  {key: 'filings', label: 'Filings & events analyst'},
  {key: 'market', label: 'Market & valuation analyst'},
  {key: 'critic', label: 'Critic'},
  {key: 'single_agent', label: 'Single agent'},
  {key: 'screener', label: 'Discover screener'},
]

export function SetupPage() {
  const [kinds, setKinds] = useState<DataKind[] | null>(null)
  const [sources, setSources] = useState<ModelSource[]>([])
  const [agentModels, setAgentModels] = useState<Record<string, string>>({})
  const [savingModels, setSavingModels] = useState(false)
  const [savedNotice, setSavedNotice] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [testing, setTesting] = useState<string | null>(null)
  const [testError, setTestError] = useState('')
  useEffect(() => {
    let alive = true
    setKinds(null); setError(''); setTestError(''); setSavedNotice('')
    setupApi.status().then(result => {if (alive) setKinds(result.kinds)})
      .catch(() => {if (alive) setError('Setup status is unavailable. Check that the local server is running, then retry.')})
    api.config().then(c => {
      if (!alive) return
      setSources(c.model_sources ?? []); setAgentModels(c.default_agent_models ?? {})
    }).catch(() => { if (alive) { setSources([]); setAgentModels({}) } })
    return () => {alive = false}
  }, [attempt])
  async function test(name: string) {
    setTesting(name); setTestError('')
    try {setKinds((await setupApi.check(name)).kinds)}
    catch (err) {setTestError(`The test could not run: ${(err as Error).message}`)}
    finally {setTesting(null)}
  }
  async function setDefaultSource(sourceId: string) {
    setSavingModels(true); setTestError(''); setSavedNotice('')
    try {
      const res = await setupApi.saveModelPreferences({default_source: sourceId})
      setKinds(res.kinds); setSources(res.model_sources ?? []); setAgentModels(res.default_agent_models ?? {})
      setSavedNotice('Default model saved.')
    } catch (err) { setTestError(`Could not save model preference: ${(err as Error).message}`) }
    finally { setSavingModels(false) }
  }
  async function saveAgentDefaults() {
    setSavingModels(true); setTestError(''); setSavedNotice('')
    try {
      const payload = Object.fromEntries(AGENT_ROLES.map(r => [r.key, agentModels[r.key] ?? '']))
      const res = await setupApi.saveModelPreferences({agent_models: payload})
      setKinds(res.kinds); setSources(res.model_sources ?? []); setAgentModels(res.default_agent_models ?? {})
      setSavedNotice('Per-agent defaults saved.')
    } catch (err) { setTestError(`Could not save model preferences: ${(err as Error).message}`) }
    finally { setSavingModels(false) }
  }
  const notReady = kinds?.filter(kind => !kind.active) ?? []
  return <div className="connections">
    <div className="connections-toolbar"><p className="muted">Keys stay in <code>.env</code> on this computer. This page only shows whether each setting is set, never its value.</p><button className="secondary" disabled={!kinds && !error} onClick={() => setAttempt(value => value + 1)}>Refresh status</button></div>
    <p className="notice">Opening or refreshing this page calls no provider. A Test button sends one live request to that provider.</p>
    {error ? <ErrorBox message={error} retry={() => setAttempt(value => value + 1)} />
      : !kinds ? <p role="status">Loading setup status…</p>
      : <>
        <p className={notReady.length ? 'configuration-note setup-summary' : 'notice setup-summary'}>{notReady.length
          ? <>Not ready yet: {notReady.map(kind => kind.label).join(', ')}. Set the variables shown on {notReady.length === 1 ? 'that card' : 'those cards'} in <code>.env</code>, then restart the server.</>
          : 'Every kind of data has an active provider.'}</p>
        {testError && <div className="notice error" role="alert">{testError}</div>}
        <div className="connection-grid">{kinds.map(kind => <KindCard key={kind.kind} kind={kind} testing={testing} saving={savingModels} savedNotice={savedNotice} sources={sources} agentModels={agentModels} onAgentModelChange={(role, source) => { setSavedNotice(''); setAgentModels(m => ({...m, [role]: source})) }} onSaveAgents={() => void saveAgentDefaults()} onSetDefault={id => void setDefaultSource(id)} onTest={name => void test(name)} />)}</div>
      </>}
    <details className="technical-details connection-setup"><summary>Other sources we know about (not built)</summary><p>The cards above are every source the code can use. Other kinds of data we surveyed, such as earnings calendars, news and short interest, aren't built yet, so no run uses them. They are listed with their limits and keys in <a href={CATALOGUE} target="_blank" rel="noreferrer">REFERENCE §10, Data providers by kind</a>.</p></details>
    <details className="technical-details connection-setup"><summary>How to set a key</summary><p>Copy <code>.env.example</code> to <code>.env</code> in the project folder, then fill in the settings a card asks for. Each setting in <code>.env.example</code> says its tier and where to get a key. Restart the server after changes. Existing environment variables take precedence over <code>.env</code>.</p><p>The only required settings are <code>SEC_USER_AGENT</code> (a name and an email) and at least one model provider. Everything else is an optional upgrade.</p></details>
  </div>
}

function KindCard({kind, testing, saving, savedNotice, sources, agentModels, onAgentModelChange, onSaveAgents, onSetDefault, onTest}: {
  kind: DataKind; testing: string | null; saving: boolean; savedNotice: string; sources: ModelSource[];
  agentModels: Record<string, string>; onAgentModelChange: (role: string, source: string) => void;
  onSaveAgents: () => void; onSetDefault: (sourceId: string) => void; onTest: (name: string) => void
}) {
  const active = kind.providers.find(provider => provider.name === kind.active)
  const configuredCount = kind.providers.filter(p => p.configured).length
  const configuredSources = sources.filter(s => s.configured)
  return <section className="report-section connection-card" aria-label={kind.label}>
    <div className="section-heading"><h2>{kind.label}</h2><Badge tone={active ? 'green' : 'amber'}>{active ? `Active: ${active.label}` : 'Nothing active'}</Badge></div>
    <p className="muted">{kind.purpose}</p>
    {kind.providers.length > 1 && <p className="form-note">{kind.kind === 'llm'
      ? 'Configure one or more providers in .env. Choose the default here, or assign different models per agent below or under Research → Advanced options.'
      : 'Runs use the first configured provider. If it fails, the next one is used, and each result names its source.'}</p>}
    <ul className="provider-list">{kind.providers.map(provider => <ProviderRow key={provider.name} provider={provider} active={provider.name === kind.active} testing={testing} saving={saving} canSetDefault={kind.kind === 'llm' && configuredCount > 1 && provider.configured && provider.name !== kind.active && Boolean(provider.source_id)} onSetDefault={onSetDefault} onTest={onTest}
      testNote={kind.kind === 'llm' ? 'Sends one short message, as an agent run does. The provider may charge a fraction of a cent.' : null} />)}</ul>
    {kind.kind === 'llm' && configuredSources.length > 1 && <fieldset className="agent-model-defaults"><legend>Default model by agent</legend>
      <p className="form-note">Agents without a specific selection use the default provider above.</p>
      {AGENT_ROLES.map(role => <label key={role.key}>{role.label}<select value={agentModels[role.key] ?? ''} onChange={e => onAgentModelChange(role.key, e.target.value)}>
        <option value="">Use default{active?.model ? ` (${active.label}: ${active.model})` : ''}</option>
        {configuredSources.map(source => <option key={source.id} value={source.id}>{source.label}: {source.model}</option>)}
      </select></label>)}
      <div className="provider-test"><button className="secondary" disabled={saving} onClick={onSaveAgents}>{saving ? 'Saving…' : 'Save agent defaults'}</button>{savedNotice && <span role="status" className="form-note">{savedNotice}</span>}</div>
    </fieldset>}
  </section>
}

function ProviderRow({provider, active, testing, saving, canSetDefault, onSetDefault, onTest, testNote}: {provider: ProviderStatus; active: boolean; testing: string | null; saving: boolean; canSetDefault: boolean; onSetDefault: (sourceId: string) => void; onTest: (name: string) => void; testNote: string | null}) {
  const status = STATUS[provider.status]
  const check = provider.last_check
  return <li className="provider-row">
    <div className="provider-head"><strong>{provider.label}</strong>{active && <span className="active-tag">Default</span>}<Badge tone={status.tone}>{status.text}</Badge></div>
    <p className="provider-meta">{TIERS[provider.tier] ?? `Tier ${provider.tier}`}{provider.env.length ? <> · uses {provider.env.map((name, i) => <span key={name}>{i ? ', ' : ''}<code>{name}</code></span>)}</> : ''}{provider.configured && provider.model ? <> · model <code>{provider.model}</code></> : ''}</p>
    {provider.note && <p className="provider-meta">{provider.note}</p>}
    {provider.missing_env.length > 0 && <p className="provider-missing">To use it, set in <code>.env</code>: {provider.missing_env.map((name, i) => <span key={name}>{i ? ', ' : ''}<code>{name}</code></span>)}</p>}
    {provider.problem && <p className="configuration-note">{provider.problem}</p>}
    {check && <p className="provider-check">{check.ok ? 'Check passed' : 'Check failed'} · <time dateTime={check.checked_at}>{stamp(check.checked_at)}</time><br />{check.message}</p>}
    {(provider.can_check || canSetDefault) && <div className="provider-test">
      {provider.can_check && <button className="secondary" disabled={!provider.configured || testing !== null} onClick={() => onTest(provider.name)}>{testing === provider.name ? 'Testing…' : `Test ${provider.label}`}</button>}
      {canSetDefault && provider.source_id && <button className="secondary" disabled={saving || testing !== null} onClick={() => onSetDefault(provider.source_id!)}>Set as default</button>}
      {provider.name === testing && <span role="status" className="form-note">Waiting for {provider.label}…</span>}
      {provider.configured && testNote && <span className="form-note">{testNote}</span>}
    </div>}
  </li>
}
