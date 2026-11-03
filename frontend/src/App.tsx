import { useEffect, useState } from 'react'
import type { View } from './api'
import { BaselinePage } from './pages/BaselinePage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { HistoryPage } from './pages/HistoryPage'
import { ResearchPage } from './pages/ResearchPage'

const VIEWS: View[] = ['research', 'baseline', 'discovery', 'history', 'connections']
const NAV: {view: View; label: string; icon: string}[] = [
  {view: 'research', label: 'Research', icon: '◧'}, {view: 'history', label: 'History', icon: '◷'},
  {view: 'connections', label: 'Connections', icon: '⇄'}, {view: 'baseline', label: 'Baseline A', icon: '⊞'},
]
const HEADINGS: Record<View, [string, string]> = {
  research: ['Ask about any US-listed company.', 'The agents read its SEC filings, figures and prices, and cite every statement.'],
  baseline: ['Read beyond the claim.', 'Baseline A, the fixed pipeline: investigate a company, inspect its sources, and follow what changed.'],
  discovery: ['A smaller, clearer shortlist.', 'Baseline A, the fixed pipeline: screen the declared universe and keep exclusions visible.'],
  history: ['Return to the evidence.', 'Original inputs. Saved evidence. A review trail you can reopen.'],
  connections: ['Connections', 'See what is configured and what has actually been tried.'],
}

function route() {
  const params = new URLSearchParams(location.search)
  const asked = params.get('view') as View | null
  const id = params.get('run')
  // ?view=research&run=… is a baseline A run (links saved before agent runs had their own page).
  const view: View = asked === 'research' && id ? 'baseline' : asked && VIEWS.includes(asked) ? asked : 'research'
  return {view, id: view === 'baseline' || view === 'discovery' ? id : null, ticker: params.get('company'), agent: view === 'research' ? params.get('agent') : null}
}

export default function App() {
  const [locationState, setLocationState] = useState(route)
  const {view, id, ticker, agent} = locationState
  function navigate(nextView: View, nextId: string | null = null, company: string | null = null) {
    const params = new URLSearchParams({view: nextView === 'baseline' && nextId ? 'research' : nextView})
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
  const current = view === 'discovery' ? 'baseline' : view
  const [title, lead] = view === 'discovery' && ticker ? ['Inside the candidate.', HEADINGS.discovery[1]] : HEADINGS[view]
  const openBaseline = (runId: string, kind: View) => navigate(kind === 'research' ? 'baseline' : kind, runId)
  return <div className="app-shell">
    <a className="skip-link" href="#main">{view === 'connections' ? 'Skip to connections' : 'Skip to research'}</a>
    <aside className="sidebar"><a className="brand" href="?view=research"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{NAV.map(item => <button key={item.view} aria-current={current === item.view ? 'page' : undefined} onClick={() => navigate(item.view)}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Research workspace<p>Evidence first.<br />Every revision in view.</p><small>Any SEC filer, with cited sources<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {(NAV.find(n => n.view === current)?.label ?? view).toUpperCase()}</span><span className="local-status">SOURCES · FIGURES · REVIEW</span></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{title}</h1><p>{lead}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {view === 'connections' ? <ConnectionsPage onOpen={openBaseline} />
        : view === 'history' ? <HistoryPage onOpenAgent={openAgent} onOpen={openBaseline} />
        : view === 'research' ? <ResearchPage agent={agent} openAgent={openAgent} onNew={() => navigate('research')} onHistory={() => navigate('history')} />
        : <>
          <div className="baseline-switch" role="group" aria-label="Baseline A form">{(['baseline', 'discovery'] as View[]).map(item => <button key={item} className="secondary" aria-pressed={view === item} onClick={() => navigate(item)}>{item === 'baseline' ? 'One company' : 'Five-company screen'}</button>)}</div>
          <BaselinePage key={view} view={view === 'baseline' ? 'research' : 'discovery'} id={id} ticker={ticker} navigate={(next, runId, company) => navigate(next === 'research' ? 'baseline' : next, runId, company)} />
        </>}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div>
}
