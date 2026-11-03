// Discover in the page: the questions a run asks before it screens, and the shortlist it returns (REFERENCE §4).
import { useState } from 'react'
import type { FormEvent } from 'react'
import { agentApi } from '../../api'
import type { DiscoverResult, DiscoverTerm } from '../../api'
import { Badge } from '../Badge'
import { tone } from './labels'

const COUNTS: [string, string][] = [['screened', 'Screened'], ['eligible', 'Passed the screen'], ['checked', 'Checked on the latest 10-K'], ['rejected', 'Rejected by the check'], ['researched', 'Researched'], ['returned', 'Returned']]

export function DiscoverQuestions({runId, questions, onAnswered}: {runId: string; questions: {terms: DiscoverTerm[]; shown: string[]}; onAnswered: () => void}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true); setError('')
    try { await agentApi.answer(runId, Object.fromEntries(questions.terms.map(t => [t.term, (answers[t.term] ?? '').trim()]))); onAnswered() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="discover-questions" aria-labelledby="questions-title">
    <h3 id="questions-title">Check the screen before anything runs</h3>
    <p className="muted">The screener turned your request into the screen below. Some words could mean different things, so it proposes a meaning for each. Leave a box empty to accept the proposal, or write your own meaning. Nothing is screened or researched until you answer.</p>
    <ul className="spec-lines">{questions.shown.map((line, i) => <li key={i}>{line}</li>)}</ul>
    <form onSubmit={submit}>
      {questions.terms.map((term, i) => <fieldset key={term.term} className="term">
        <legend>"{term.term}"</legend>
        <p>{term.question}</p>
        <p className="muted">Proposed: {term.definition}</p>
        <label htmlFor={`term-${i}`}>Your meaning (leave empty to accept)</label>
        <input id={`term-${i}`} value={answers[term.term] ?? ''} onChange={e => setAnswers(a => ({...a, [term.term]: e.target.value}))} placeholder={term.definition} />
      </fieldset>)}
      <button className="primary" disabled={busy}>{busy ? 'Sending…' : 'Screen with these meanings →'}</button>
    </form>
    {error && <div className="notice error" role="alert">{error}</div>}
  </section>
}

export function DiscoverReport({result, onOpenRun}: {result: DiscoverResult; onOpenRun: (id: string) => void}) {
  const picks = result.candidates.filter(c => c.outcome === 'picked')
  const others = result.candidates.filter(c => c.outcome !== 'picked')
  return <div className="report-body">
    {result.spec && <section className="report-section"><div className="section-label">THE SCREEN</div><ul className="spec-lines">{result.spec.map((line, i) => <li key={i}>{line}</li>)}</ul></section>}
    {Object.keys(result.counts).length > 0 && <section className="report-section"><div className="screen-stats">{COUNTS.map(([key, label]) => <span key={key}><strong>{result.counts[key] ?? 0}</strong>{label}</span>)}</div></section>}
    <section className="report-section">
      <h2>Shortlist</h2>
      {picks.length === 0 ? <p className="empty-inline">No candidate made the shortlist. The candidates below say why.</p> : <ol className="shortlist">{picks.map(c => <li key={c.cik}>
        <div className="section-heading"><h3>{c.name ?? c.cik}</h3><span className="muted">screen rank {c.rank}</span></div>
        {c.answer && <p>{c.answer}</p>}
        <Checks lines={c.lines} />
        {c.run_id && <button className="secondary" onClick={() => onOpenRun(c.run_id!)}>Open its full report →</button>}
      </li>)}</ol>}
    </section>
    {others.length > 0 && <section className="report-section"><h2>Checked but not picked</h2><ul className="shortlist">{others.map(c => <li key={c.cik}>
      <div className="section-heading"><h3>{c.name ?? c.cik}</h3><Badge tone="amber">{c.outcome}</Badge></div>
      <Checks lines={c.lines} />
      {c.run_id && <button className="text-button" onClick={() => onOpenRun(c.run_id!)}>Open its research run ↗</button>}
    </li>)}</ul></section>}
  </div>
}

function Checks({lines}: {lines: DiscoverResult['candidates'][number]['lines']}) {
  if (!lines.length) return null
  return <details className="technical-details"><summary>Check on its latest 10-K and price ({lines.filter(l => l.state === 'pass').length} of {lines.length} passed)</summary>
    <ul className="check-lines">{lines.map((line, i) => <li key={i}><Badge tone={tone(line.state)}>{line.state}</Badge> {line.text}</li>)}</ul>
  </details>
}
