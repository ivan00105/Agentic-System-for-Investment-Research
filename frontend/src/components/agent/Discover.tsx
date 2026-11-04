// Discover in the page: the questions a run asks before it screens, and the shortlist it returns (REFERENCE §4).
import { useState } from 'react'
import type { FormEvent } from 'react'
import { agentApi } from '../../api'
import type { CompanyMatch, DiscoverQuestionSet, DiscoverResult, DiscoverTerm } from '../../api'
import { useLevel } from '../../level'
import { Badge } from '../Badge'
import { tone } from './labels'

const COUNTS: [string, string][] = [['screened', 'Screened'], ['eligible', 'Passed the screen'], ['checked', 'Checked on the latest 10-K'], ['rejected', 'Rejected by the check'], ['researched', 'Researched'], ['returned', 'Returned']]

export function DiscoverQuestions({runId, questions, onAnswered}: {runId: string; questions: DiscoverQuestionSet; onAnswered: () => void}) {
  const {level} = useLevel()
  const drafted = questions.spec ? JSON.stringify(questions.spec, null, 2) : ''
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [picked, setPicked] = useState<Record<string, string>>({}) // an option's index, or "other"
  const [specText, setSpecText] = useState(drafted)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const editing = !!drafted && specText.trim() !== drafted.trim()
  const choice = (t: DiscoverTerm) => picked[t.term] ?? String(Math.max(0, t.options?.findIndex(o => o.recommended) ?? 0))
  // The recommended option, or an empty Other box, accepts the proposal as before; another option or text sets the term.
  function answer(t: DiscoverTerm) {
    const option = t.options?.length && choice(t) !== 'other' ? t.options[Number(choice(t))] : null
    return option ? (option.recommended ? '' : option.definition) : (answers[t.term] ?? '').trim()
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    let spec: unknown
    if (editing) { try { spec = JSON.parse(specText) } catch (e) { setError(`The edited spec isn't valid JSON: ${(e as Error).message}`); return } }
    setBusy(true); setError('')
    try { await agentApi.answer(runId, editing ? {} : Object.fromEntries(questions.terms.map(t => [t.term, answer(t)])), spec); onAnswered() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="discover-questions" aria-labelledby="questions-title">
    <h3 id="questions-title">Check the screen before anything runs</h3>
    <p className="muted">{questions.terms.length ? 'The screener turned your request into the screen below. Some words could mean different things, so it offers a few meanings for each, with the one it recommends picked already. Pick another, or choose Other and write your own.' : 'The screener turned your request into the screen below. No word in it needed a choice.'} Nothing is screened or researched until you answer.</p>
    <ul className="spec-lines">{questions.shown.map((line, i) => <li key={i}>{line}</li>)}</ul>
    <form onSubmit={submit}>
      {questions.terms.map((term, i) => <fieldset key={term.term} className="term" disabled={editing}>
        <legend>"{term.term}"</legend>
        <p>{term.question}</p>
        {term.options?.length ? <>
          {[...term.options.map((o, j) => [String(j), o.definition, o.recommended] as const), ['other', 'Other', false] as const].map(([value, text, recommended]) => <label key={value} className="radio">
            <input type="radio" name={`term-${i}`} checked={choice(term) === value} onChange={() => setPicked(p => ({...p, [term.term]: value}))} />
            <span>{text}{recommended && <strong className="recommended"> (recommended)</strong>}</span></label>)}
          {choice(term) === 'other' && <><label htmlFor={`term-${i}-other`}>Your meaning (leave empty to keep the recommended one)</label>
            <input id={`term-${i}-other`} value={answers[term.term] ?? ''} onChange={e => setAnswers(a => ({...a, [term.term]: e.target.value}))} placeholder={term.definition} /></>}
        </> : <>
          <p className="muted">Proposed: {term.definition}</p>
          <label htmlFor={`term-${i}`}>Your meaning (leave empty to accept)</label>
          <input id={`term-${i}`} value={answers[term.term] ?? ''} onChange={e => setAnswers(a => ({...a, [term.term]: e.target.value}))} placeholder={term.definition} />
        </>}
      </fieldset>)}
      {drafted && <details className="spec-editor" open={level === 'professional'}><summary>Edit the screen spec directly</summary>
        <p className="muted">The spec as JSON: filters and price checks (metric, op, value), sic_prefixes, rank_by, descending, top_k, terms and not_covered. An edited spec is used exactly as written, with no model call{questions.terms.length ? ', and the boxes above are ignored' : ''}.</p>
        <label htmlFor="spec-json">Screen spec (JSON)</label>
        <textarea id="spec-json" className="mono" rows={14} spellCheck={false} value={specText} onChange={e => setSpecText(e.target.value)} />
        {editing && <button type="button" className="text-button" onClick={() => setSpecText(drafted)}>Undo my edits</button>}
      </details>}
      <button className="primary" disabled={busy}>{busy ? 'Sending…' : editing ? 'Screen with my edited spec →' : questions.terms.length ? 'Screen with these meanings →' : 'Screen with this spec →'}</button>
    </form>
    {error && <div className="notice error" role="alert">{error}</div>}
  </section>
}

const COMPARE_MAX = 4 // what a comparison takes (the question box's limit)

export function DiscoverReport({result, onOpenRun, onCompare}: {result: DiscoverResult; onOpenRun: (id: string) => void; onCompare: (companies: CompanyMatch[]) => void}) {
  const picks = result.candidates.filter(c => c.outcome === 'picked')
  const others = result.candidates.filter(c => c.outcome !== 'picked')
  const comparable = picks.filter(c => c.tickers?.length).map(c => ({cik: c.cik, name: c.name ?? c.cik, tickers: c.tickers!, exchanges: []}))
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
      {comparable.length >= 2 && <div className="compare-picks">
        <button className="primary" onClick={() => onCompare(comparable.slice(0, COMPARE_MAX))}>{comparable.length > COMPARE_MAX ? `Compare the first ${COMPARE_MAX} →` : 'Compare these →'}</button>
        <p className="muted">Opens a side-by-side comparison of {comparable.length > COMPARE_MAX ? `the top ${COMPARE_MAX} of these ${comparable.length} picks (a comparison takes up to ${COMPARE_MAX})` : 'these picks'} in the question box, so you can check it before it runs.{comparable.length < picks.length && ` ${picks.length - comparable.length} pick${picks.length - comparable.length === 1 ? ' has' : 's have'} no ticker and can't be added.`}</p>
      </div>}
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
