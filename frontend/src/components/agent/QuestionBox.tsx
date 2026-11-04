// One question box. Starter cards, the company picker, topics and examples only fill it; the user can edit the text.
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { agentApi } from '../../api'
import type { CompanyMatch, StartAgentRun, UniverseInfo } from '../../api'
import { useLevel } from '../../level'
import { AdvancedOptions } from './AdvancedOptions'
import type { Options } from './AdvancedOptions'
import { CompanyPicker } from './CompanyPicker'
import { GuidedStart } from './GuidedStart'
import { buildQuestion, TOPICS } from './templates'
import type { Kind, Topic } from './templates'

// One company means Check and two to four mean Compare (PROJECT_GUIDE Phase 7); more is a Find over your own list.
const COMPARE_MAX = 4
const STARTERS: {kind: Kind; title: string; text: string}[] = [
  {kind: 'check', title: 'Check one company', text: 'How it is doing: figures, risks, and the case for and against.'},
  {kind: 'compare', title: 'Compare a few', text: 'Two to four companies side by side.'},
  {kind: 'find', title: 'Find companies', text: 'Screen a list of companies for the ones that fit.'},
]
const EXAMPLES: {kind: Kind | null; text: string}[] = [
  {kind: 'check', text: 'How profitable is Microsoft, and is its operating margin rising?'},
  {kind: 'compare', text: 'Compare NVIDIA and AMD on growth and valuation.'},
  {kind: 'check', text: "What are the main risks in Apple's latest 10-K?"},
  {kind: 'find', text: 'Find large, profitable tech companies at a reasonable valuation.'},
]

export function QuestionBox({onStarted, initial}: {onStarted: (id: string) => void; initial?: CompanyMatch[] | null}) {
  const [kind, setKind] = useState<Kind | null>(initial?.length ? 'compare' : null)
  const [companies, setCompanies] = useState<CompanyMatch[]>(initial ?? [])
  const [topics, setTopics] = useState<Topic[]>([])
  const [universes, setUniverses] = useState<UniverseInfo[]>([])
  const [among, setAmong] = useState('mine') // a bundled universe's id, or the user's own list
  const [count, setCount] = useState('')
  const [question, setQuestion] = useState('')
  const [edited, setEdited] = useState(false)
  const {level} = useLevel()
  const [guided, setGuided] = useState(level === 'beginner' && !initial?.length)
  const [note, setNote] = useState('') // the preferences note "Help me start" wrote; the user can edit it
  const [options, setOptions] = useState<Options>({condition: '', model: '', editSpec: level === 'professional', cutoff: ''})
  useEffect(() => setOptions(o => ({...o, editSpec: level === 'professional'})), [level])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { agentApi.universes().then(r => { setUniverses(r.items); if (r.items.length) setAmong(r.items[0].id) }).catch(() => setUniverses([])) }, [])
  const find = kind === 'find'
  const universe = universes.find(u => u.id === among)
  const built = buildQuestion(kind, companies, topics, {count, among: universe ? `among ${universe.name}` : 'from my list'})
  useEffect(() => { if (!edited && built) setQuestion(built) }, [built, edited])

  // Help me start searches the biggest bundled list, never every SEC filer (thousands of small companies and shells).
  const widest = universes.filter(u => !u.dynamic).sort((a, b) => (b.companies ?? 0) - (a.companies ?? 0))[0]
  function guide({question: text, note: written}: {question: string; note: string}) {
    setKind('find'); setCompanies([]); setTopics([]); setQuestion(text); setEdited(true); setNote(written); setGuided(false); setError('')
    if (widest) setAmong(widest.id)
  }
  function choose(next: Kind) {
    setKind(next); setEdited(false); setError(''); setGuided(false)
    if (next === 'check') setCompanies(c => c.slice(0, 1))
    if (next === 'compare') setCompanies(c => c.slice(0, COMPARE_MAX))
    if (next === 'find' && companies.length && !universe) setAmong('mine')
  }
  function pickCompanies(next: CompanyMatch[]) {
    setCompanies(next)
    if (!find) setKind(next.length > 1 ? 'compare' : next.length === 1 ? 'check' : kind)
  }
  function example(next: {kind: Kind | null; text: string}) {
    setKind(next.kind); setCompanies([]); setTopics([]); setQuestion(next.text); setEdited(true); setError(''); setNote(''); setGuided(false)
    if (next.kind === 'find' && universes.length) setAmong(universes[0].id)
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !question.trim()) return
    if (find && among === 'mine' && !companies.length) { setError('Pick at least one company for your own list, or choose a bundled list.'); return }
    const {condition, model, editSpec, cutoff} = options
    const body: StartAgentRun = {question, ...(condition && {condition}), ...(model.trim() && {model: model.trim()}), ...(note.trim() && {preferences: note.trim()}),
      ...(find ? {discover: among === 'mine' ? {tickers: companies.map(c => c.tickers[0])} : {name: among}, ...(editSpec && {edit_spec: true})} : cutoff ? {cutoff} : {})}
    setBusy(true); setError('')
    try { onStarted((await agentApi.start(body)).run_id) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="request-panel agent-question" aria-label="Ask the research agents">
    <div className="starter-cards" role="group" aria-label="What do you want to do?">{STARTERS.map(s => <button type="button" key={s.kind} className="starter" aria-pressed={!guided && kind === s.kind} onClick={() => choose(s.kind)}><strong>{s.title}</strong><span>{s.text}</span></button>)}
      <button type="button" className="starter guided" aria-pressed={guided} onClick={() => setGuided(g => !g)}><strong>Help me start</strong><span>No company or criteria in mind? Answer four quick questions.</span></button></div>
    {guided && <GuidedStart among={widest ? `among ${widest.name}` : 'from SEC filers'} onBuilt={guide} onClose={() => setGuided(false)} />}
    <form onSubmit={submit}>
      <CompanyPicker picked={companies} onChange={pickCompanies} label={find ? 'Your own list of companies' : 'Companies'} max={find ? undefined : COMPARE_MAX}
        hint={find ? 'Pick any number, then choose "My own list" below.' : companies.length >= COMPARE_MAX ? 'A comparison takes up to four companies. To screen more, use Find companies with your own list.' : 'One company checks it; two to four compare them. Any SEC filer works.'} />
      {!find && companies.length > 1 && <p className="mode-note" role="status">You picked {companies.length} companies, so this is now a side-by-side comparison. Remove all but one to check a single company{companies.length >= COMPARE_MAX ? ', or use Find companies to screen a longer list' : ''}.</p>}
      {find && <fieldset className="find-options"><legend>Where to look</legend>
        {universes.map(u => <label className="radio" key={u.id}><input type="radio" name="among" checked={among === u.id} disabled={u.available === false} onChange={() => setAmong(u.id)} /><span>{u.name}<small>{u.companies != null ? `${u.companies.toLocaleString('en-US')} companies` : 'Size unknown'}, as of {u.as_of}. {u.note}{u.problem && ` ${u.problem}`}</small></span></label>)}
        <label className="radio"><input type="radio" name="among" checked={among === 'mine'} onChange={() => setAmong('mine')} /><span>My own list<small>The {companies.length} compan{companies.length === 1 ? 'y' : 'ies'} picked above.</small></span></label>
        <label className="count">How many to return (optional)<input type="number" min={1} step={1} value={count} onChange={e => setCount(e.target.value)} /></label>
      </fieldset>}
      <div className="topic-chips" role="group" aria-label="Topics to cover">{TOPICS.filter(t => !find || t !== 'recent events').map(t => <button type="button" key={t} className="topic" aria-pressed={topics.includes(t)} onClick={() => setTopics(ts => ts.includes(t) ? ts.filter(x => x !== t) : [...ts, t])}>{t}</button>)}</div>
      <label>Your question<textarea rows={3} required value={question} onChange={e => { setQuestion(e.target.value); setEdited(true) }} placeholder="Pick a starter or a company above, or type any question about US-listed companies." /></label>
      {note && <div className="preferences-note"><label>Your preferences (the agents read this note)<textarea rows={4} value={note} onChange={e => setNote(e.target.value)} /></label>
        <button type="button" className="text-button" onClick={() => setNote('')}>Remove the note</button></div>}
      {edited && built && built !== question && !note && <button type="button" className="text-button" onClick={() => { setQuestion(built); setEdited(false) }}>Use the question built from your choices</button>}
      <AdvancedOptions find={find} options={options} onChange={next => setOptions(o => ({...o, ...next}))} />
      <button className="primary" disabled={busy || !question.trim()}>{busy ? 'Starting…' : find ? 'Find companies →' : 'Research this question →'}</button>
    </form>
    <div className="examples"><span className="section-label">OR TRY AN EXAMPLE</span><ul>{EXAMPLES.map(ex => <li key={ex.text}><button type="button" className="text-button" onClick={() => example(ex)}>{ex.text}</button></li>)}</ul></div>
    <p className="form-note">The agents read SEC filings, reported figures and prices, then write a report in which every statement cites its evidence. A run takes several minutes and keeps going if you leave this page.</p>
    {error && <div className="notice error" role="alert">{error}</div>}
  </section>
}
