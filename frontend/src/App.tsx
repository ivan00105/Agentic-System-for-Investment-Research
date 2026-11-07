import { useEffect, useState } from 'react'
import type { CompanyMatch, View } from './api'
import { RunList } from './components/agent/RunList'
import { LevelPicker, LevelProvider } from './level'
import { ResearchPage } from './pages/ResearchPage'
import { SetupPage } from './pages/SetupPage'

// Baseline A, the old fixed pipeline, has no page: it is only the no-AI control in the evaluation (eval/baseline_a.py).
const VIEWS: View[] = ['research', 'history', 'setup']
const NAV: {view: View; label: string; icon: string}[] = [
  {view: 'research', label: 'Research', icon: '◧'}, {view: 'history', label: 'History', icon: '◷'},
  {view: 'setup', label: 'Setup & status', icon: '⇄'},
]
const HEADINGS: Record<View, [string, string]> = {
  research: ['Ask about any US-listed company.', 'The agents read its SEC filings, figures and prices, and cite every statement.'],
  history: ['Return to the evidence.', 'Original inputs. Saved evidence. A review trail you can reopen.'],
  setup: ['Setup & status', 'Which data each feature uses, which keys to add to .env, and whether each provider answers.'],
}

function route() {
  const params = new URLSearchParams(location.search)
  // ?view=connections is the Setup page's old name; any other unknown view opens Research.
  const asked = (params.get('view') === 'connections' ? 'setup' : params.get('view')) as View | null
  const view: View = asked && VIEWS.includes(asked) ? asked : 'research'
  // "Compare these" on a Discover shortlist hands its picks to the question box in the history entry.
  const compare = view === 'research' && Array.isArray(history.state?.compare) ? history.state.compare as CompanyMatch[] : null
  const compareFrom = compare && typeof history.state?.parent === 'string' ? history.state.parent as string : null // the Discover run
  return {view, agent: view === 'research' ? params.get('agent') : null, compare, compareFrom}
}

export default function App() {
  const [locationState, setLocationState] = useState(route)
  const {view, agent, compare, compareFrom} = locationState
  function navigate(nextView: View) {
    history.pushState({}, '', `?view=${nextView}`)
    setLocationState(route())
  }
  function openAgent(runId: string) {
    history.pushState({}, '', `?view=research&agent=${encodeURIComponent(runId)}`)
    setLocationState(route())
  }
  function openCompare(companies: CompanyMatch[], parent: string) {
    history.pushState({compare: companies, parent}, '', '?view=research')
    setLocationState(route())
  }
  useEffect(() => {const onPop = () => setLocationState(route()); addEventListener('popstate', onPop); return () => removeEventListener('popstate', onPop)}, [])
  const [title, lead] = HEADINGS[view]
  return <LevelProvider><div className="app-shell">
    <a className="skip-link" href="#main">{view === 'setup' ? 'Skip to setup' : 'Skip to research'}</a>
    <aside className="sidebar"><a className="brand" href="?view=research"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{NAV.map(item => <button key={item.view} aria-current={view === item.view ? 'page' : undefined} onClick={() => navigate(item.view)}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Research workspace<p>Evidence first.<br />Every revision in view.</p><small>Any SEC filer, with cited sources<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {(NAV.find(n => n.view === view)?.label ?? view).toUpperCase()}</span><LevelPicker /></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{title}</h1><p>{lead}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {view === 'setup' ? <SetupPage />
        : view === 'history' ? <RunList onOpen={openAgent} />
        : <ResearchPage agent={agent} compare={compare} compareFrom={compareFrom} openAgent={openAgent} onCompare={openCompare} onNew={() => navigate('research')} onHistory={() => navigate('history')} />}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div></LevelProvider>
}
