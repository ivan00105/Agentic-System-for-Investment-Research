import { useEffect, useState } from 'react'
import { AgentQuestion, AgentRunView } from './AgentRun'
import type { View } from './api'
import { BaselinePage } from './pages/BaselinePage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { HistoryPage } from './pages/HistoryPage'

function route() {
  const params = new URLSearchParams(location.search)
  const view = params.get('view')
  return {view: (view === 'discovery' || view === 'history' || view === 'connections' ? view : 'research') as View, id: view === 'connections' ? null : params.get('run') ?? (location.search ? null : 'example-msft'), ticker: params.get('company'), agent: view === 'research' ? params.get('agent') : null}
}

export default function App() {
  const [locationState, setLocationState] = useState(route)
  const {view, id, ticker, agent} = locationState
  function navigate(nextView: View, nextId: string | null = null, company: string | null = null) {
    const params = new URLSearchParams({view: nextView})
    if (nextId) params.set('run', nextId)
    if (company) params.set('company', company)
    history.pushState({}, '', `?${params}`)
    setLocationState(route())
  }
  function openAgent(runId: string) {
    history.pushState({}, '', `?view=research&agent=${encodeURIComponent(runId)}`)
    setLocationState(route())
  }
  useEffect(() => {const onPop = () => setLocationState(route()); addEventListener('popstate', onPop); return () => removeEventListener('popstate', onPop)}, [])
  return <div className="app-shell">
    <a className="skip-link" href="#main">{view === 'connections' ? 'Skip to connections' : 'Skip to research'}</a>
    <aside className="sidebar"><a className="brand" href="?view=research&run=example-msft"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{(['research', 'discovery', 'history', 'connections'] as View[]).map((item, i) => <button key={item} aria-current={view === item ? 'page' : undefined} onClick={() => navigate(item)}><span aria-hidden="true">{['◧', '⊞', '◷', '⇄'][i]}</span>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Research workspace<p>Evidence first.<br />Every revision in view.</p><small>Five-company research universe<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {view.toUpperCase()}</span><span className="local-status">SOURCES · FIGURES · REVIEW</span></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{view === 'research' ? 'Read beyond the claim.' : view === 'discovery' ? ticker ? 'Inside the candidate.' : 'A smaller, clearer shortlist.' : view === 'connections' ? 'Connections' : 'Return to the evidence.'}</h1><p>{view === 'research' ? 'Investigate a company, inspect its sources, and follow what changed.' : view === 'discovery' ? 'Screen the declared universe. Keep exclusions and missing evidence visible.' : view === 'connections' ? 'See what is configured and what has actually been tried.' : 'Original inputs. Saved evidence. A review trail you can reopen.'}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {view === 'connections' ? <ConnectionsPage onOpen={(runId, kind) => navigate(kind, runId)} /> : view === 'history' ? <HistoryPage onOpenAgent={openAgent} onOpen={(runId, kind) => navigate(kind, runId)} /> : <>
        {view === 'research' && <AgentQuestion onStarted={openAgent} />}
        {agent ? <AgentRunView id={agent} /> : <BaselinePage key={view} view={view} id={id} ticker={ticker} navigate={navigate} />}
      </>}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div>
}
