// "Help me start", for someone with no company or criteria in mind: four multiple-choice questions, each with a
// recommended default and "Not sure", become a Find question plus a preferences note the run reads.
import { useState } from 'react'
import type { FormEvent } from 'react'

type Choice = {id: string; label: string; hint?: string; find?: string; note: string}
type Question = {id: string; legend: string; recommended: string; choices: Choice[]}

const QUESTIONS: Question[] = [
  {id: 'matters', legend: 'What matters most to you?', recommended: 'profits', choices: [
    {id: 'growth', label: 'Growth', hint: 'Sales rising fast.', find: 'growing revenue', note: 'growth'},
    {id: 'profits', label: 'Steady profits', hint: 'A good share of every sale kept as profit.', find: 'high profit margins', note: 'steady profits'},
    {id: 'dividends', label: 'Dividends', hint: 'The screen can\'t check dividends yet, so it looks for strong free cash flow, the cash that pays them.', find: 'strong free cash flow', note: 'dividends (the screen checks free cash flow instead)'},
    {id: 'value', label: 'Low valuation', hint: 'Shares that look cheap for what the company earns.', find: 'a low valuation', note: 'a low valuation'},
    {id: 'unsure', label: 'Not sure', hint: 'Start broad: profitable companies.', find: 'a profit', note: 'not sure'},
  ]},
  {id: 'horizon', legend: 'How long would you hold?', recommended: 'years', choices: [
    {id: 'weeks', label: 'Weeks', hint: 'Yearly filings say little about the next few weeks; short-term moves are close to a coin flip.', note: 'weeks'},
    {id: 'months', label: 'Months', note: 'months'},
    {id: 'years', label: 'Years', hint: 'What yearly filings speak to best.', note: 'years'},
    {id: 'unsure', label: 'Not sure', note: 'not sure'},
  ]},
  {id: 'swings', legend: 'How do you feel about price swings?', recommended: 'medium', choices: [
    {id: 'low', label: 'I want a calm ride', hint: 'Adds a check on how much the price has jumped around.', find: 'steady share prices', note: 'low'},
    {id: 'medium', label: 'Some ups and downs are fine', note: 'medium'},
    {id: 'high', label: 'Big swings don\'t bother me', note: 'high'},
    {id: 'unsure', label: 'Not sure', note: 'not sure'},
  ]},
  {id: 'sector', legend: 'Which part of the economy?', recommended: 'any', choices: [
    {id: 'any', label: 'Any sector', note: 'any'},
    {id: 'tech', label: 'Technology', find: 'in technology', note: 'technology'},
    {id: 'health', label: 'Health care', find: 'in health care', note: 'health care'},
    {id: 'financials', label: 'Banks and insurers', hint: 'They report no operating income, so the screen uses net income for them.', find: 'among banks and insurers', note: 'financials'},
    {id: 'consumer', label: 'Shops and consumer brands', find: 'in consumer goods and retail', note: 'consumer'},
    {id: 'industrial', label: 'Industry and energy', find: 'in industrials and energy', note: 'industrials and energy'},
    {id: 'unsure', label: 'Not sure', note: 'not sure'},
  ]},
]
const NOTE_LABELS: Record<string, string> = {matters: 'What matters most', horizon: 'Time horizon', swings: 'Comfort with price swings', sector: 'Sectors'}
const KEY = 'fieldnote-guided-answers'
function remembered(): Record<string, string> {
  let saved: Record<string, string> = {}
  try { saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') } catch { /* storage blocked or unreadable */ }
  return Object.fromEntries(QUESTIONS.map(q => [q.id, q.choices.some(c => c.id === saved?.[q.id]) ? saved[q.id] : q.recommended]))
}

export function buildGuided(answers: Record<string, string>, among: string) {
  const pick = (id: string) => QUESTIONS.find(q => q.id === id)!.choices.find(c => c.id === answers[id])!
  const [matters, horizon, swings, sector] = QUESTIONS.map(q => pick(q.id))
  const sectorText = sector.find ? ` ${sector.find}` : ''
  const qualities = [matters.find, swings.find].filter(Boolean).join(' and ')
  const question = `Find companies ${among}${sectorText} with ${qualities}.`
  const note = QUESTIONS.map((q, i) => `${NOTE_LABELS[q.id]}: ${[matters, horizon, swings, sector][i].note}.`).join('\n')
    + (horizon.id === 'weeks' ? '\nYearly filings say little about the next few weeks; short-term price moves are close to a coin flip.' : '')
  return {question, note}
}

export function GuidedStart({among, onBuilt, onClose}: {among: string; onBuilt: (built: {question: string; note: string}) => void; onClose: () => void}) {
  const [answers, setAnswers] = useState(remembered)
  function submit(event: FormEvent) {
    event.preventDefault()
    try { localStorage.setItem(KEY, JSON.stringify(answers)) } catch { /* not remembered */ }
    onBuilt(buildGuided(answers, among))
  }
  return <form className="guided-start" onSubmit={submit} aria-labelledby="guided-title">
    <h2 id="guided-title">Help me start</h2>
    <p className="muted">Four quick questions. Each has a recommended answer picked already, and "Not sure" is always fine. Your answers become a question to find companies, plus a note the agents read. You can edit both before anything runs. This is research support, not advice to buy or sell.</p>
    {QUESTIONS.map(q => <fieldset key={q.id} className="guided-question"><legend>{q.legend}</legend>
      {q.choices.map(c => <label key={c.id} className="radio"><input type="radio" name={`guided-${q.id}`} checked={answers[q.id] === c.id} onChange={() => setAnswers(a => ({...a, [q.id]: c.id}))} />
        <span>{c.label}{c.id === q.recommended && <strong className="recommended"> (recommended)</strong>}{c.hint && <small>{c.hint}</small>}</span></label>)}
    </fieldset>)}
    <div className="guided-actions"><button className="primary">Build my question →</button><button type="button" className="text-button" onClick={onClose}>Close</button></div>
  </form>
}
