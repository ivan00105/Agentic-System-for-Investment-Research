import { useEffect, useState } from 'react'
import type { CompanyMatch, View } from './api'
import { LevelPicker, LevelProvider } from './level'
import { BaselinePage } from './pages/BaselinePage'
import { HistoryPage } from './pages/HistoryPage'
import { ResearchPage } from './pages/ResearchPage'
import { SetupPage } from './pages/SetupPage'

const VIEWS: View[] = ['research', 'baseline', 'discovery', 'history', 'setup']
const NAV: {view: View; label: string; icon: string}[] = [
  {view: 'research', label: 'Research', icon: '◧'}, {view: 'history', label: 'History', icon: '◷'},
  {view: 'setup', label: 'Setup & status', icon: '⇄'}, {view: 'baseline', label: 'Baseline A', icon: '⊞'},
]
const HEADINGS: Record<View, [string, string]> = {
  research: ['Ask about any US-listed company.', 'The agents read its SEC filings, figures and prices, and cite every statement.'],
  baseline: ['Read beyond the claim.', 'Baseline A, the fixed pipeline: investigate a company, inspect its sources, and follow what changed.'],
  discovery: ['A smaller, clearer shortlist.', 'Baseline A, the fixed pipeline: screen the declared universe and keep exclusions visible.'],
  history: ['Return to the evidence.', 'Original inputs. Saved evidence. A review trail you can reopen.'],
  setup: ['Setup & status', 'Which data each feature uses, which keys to add to .env, and whether each provider answers.'],
}

function route() {
  const params = new URLSearchParams(location.search)
  // ?view=connections is the Setup page's old name.
  const asked = (params.get('view') === 'connections' ? 'setup' : params.get('view')) as View | null
  const id = params.get('run')
  // ?view=research&run=… is a baseline A run (links saved before agent runs had their own page).
  const view: View = asked === 'research' && id ? 'baseline' : asked && VIEWS.includes(asked) ? asked : 'research'
  // "Compare these" on a Discover shortlist hands its picks to the question box in the history entry.
  const compare = view === 'research' && Array.isArray(history.state?.compare) ? history.state.compare as CompanyMatch[] : null
  const compareFrom = compare && typeof history.state?.parent === 'string' ? history.state.parent as string : null // the Discover run
  return {view, id: view === 'baseline' || view === 'discovery' ? id : null, ticker: params.get('company'), agent: view === 'research' ? params.get('agent') : null, compare, compareFrom}
}

export default function App() {
  const [locationState, setLocationState] = useState(route)
  const {view, id, ticker, agent, compare, compareFrom} = locationState
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
  function openCompare(companies: CompanyMatch[], parent: string) {
    history.pushState({compare: companies, parent}, '', '?view=research')
    setLocationState(route())
  }
  useEffect(() => {const onPop = () => setLocationState(route()); addEventListener('popstate', onPop); return () => removeEventListener('popstate', onPop)}, [])
  const current = view === 'discovery' ? 'baseline' : view
  const [title, lead] = view === 'discovery' && ticker ? ['Inside the candidate.', HEADINGS.discovery[1]] : HEADINGS[view]
  const openBaseline = (runId: string, kind: View) => navigate(kind === 'research' ? 'baseline' : kind, runId)
  return <LevelProvider><div className="app-shell">
    <a className="skip-link" href="#main">{view === 'setup' ? 'Skip to setup' : 'Skip to research'}</a>
    <aside className="sidebar"><a className="brand" href="?view=research"><span className="brand-mark" aria-hidden="true">f.</span><span>fieldnote<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{NAV.map(item => <button key={item.view} aria-current={current === item.view ? 'page' : undefined} onClick={() => navigate(item.view)}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav><div className="sidebar-footer"><span className="local-dot" /> Research workspace<p>Evidence first.<br />Every revision in view.</p><small>Any SEC filer, with cited sources<br />No trade execution</small></div></aside>
    <div className="workspace"><header className="topbar"><span>WORKSPACE <span className="separator">/</span> {(NAV.find(n => n.view === current)?.label ?? view).toUpperCase()}</span><LevelPicker /></header><main id="main">
      <div className="page-heading"><div><div className="eyebrow">EVIDENCE-GROUNDED RESEARCH</div><h1>{title}</h1><p>{lead}</p></div><span className="edition">FIELDNOTES / 01</span></div>
      {view === 'setup' ? <SetupPage />
        : view === 'history' ? <HistoryPage onOpenAgent={openAgent} onOpen={openBaseline} />
        : view === 'research' ? <ResearchPage agent={agent} compare={compare} compareFrom={compareFrom} openAgent={openAgent} onCompare={openCompare} onNew={() => navigate('research')} onHistory={() => navigate('history')} />
        : <>
          <div className="baseline-switch" role="group" aria-label="Baseline A form">{(['baseline', 'discovery'] as View[]).map(item => <button key={item} className="secondary" aria-pressed={view === item} onClick={() => navigate(item)}>{item === 'baseline' ? 'One company' : 'Five-company screen'}</button>)}</div>
          <BaselinePage key={view} view={view === 'baseline' ? 'research' : 'discovery'} id={id} ticker={ticker} navigate={(next, runId, company) => navigate(next === 'research' ? 'baseline' : next, runId, company)} />
        </>}
      <footer className="page-footer"><span>FIELDNOTE</span><p>Research support, with provenance and limitations kept visible.</p></footer>
    </main></div>
  </div></LevelProvider>
}
