// The pieces of an agent report: citation chips, claim lists, the key-numbers table, the review's changes and sources.
import { useState } from 'react'
import { sourceLink } from '../../api'
import type { AgentClaim, AgentObjection, AgentSection, AgentSource, KeyNumber } from '../../api'
import { Badge } from '../Badge'

export type Open = (recordId: string) => void
const KINDS = ['fact', 'calc', 'prices', 'check', 'chunk', 'filing', 'insider', 'peers', 'calendar', 'company', 'claim']
const rank = (source?: AgentSource) => { const i = KINDS.indexOf(source?.kind ?? ''); return i < 0 ? KINDS.length : i }
const CHIPS_SHOWN = 4 // the rest sit behind "+N more", never dropped

export function SourceChips({citations, sources, onOpen}: {citations: number[]; sources: Map<number, AgentSource>; onOpen: Open}) {
  const [all, setAll] = useState(false)
  const sorted = [...citations].sort((a, b) => rank(sources.get(a)) - rank(sources.get(b)) || a - b)
  if (!sorted.length) return null
  return <span className="source-chips">
    {(all ? sorted : sorted.slice(0, CHIPS_SHOWN)).map(n => { const source = sources.get(n)
      return <button type="button" key={n} className="source-chip" disabled={!source} onClick={() => source && onOpen(source.id)} aria-label={`Open source ${n}: ${source?.label ?? 'not recorded'}`}>{source?.label ?? `Source ${n}`}</button> })}
    {sorted.length > CHIPS_SHOWN && <button type="button" className="source-chip more" aria-expanded={all} onClick={() => setAll(a => !a)}>{all ? 'Fewer' : `+${sorted.length - CHIPS_SHOWN} more`}</button>}
  </span>
}

export function Claim({claim, sources, onOpen}: {claim: AgentClaim; sources: Map<number, AgentSource>; onOpen: Open}) {
  return <li>{claim.text} <SourceChips citations={claim.citations} sources={sources} onOpen={onOpen} />
    {claim.status === 'qualified' && <> <Badge tone="amber">qualified</Badge><ul className="agent-flags">{claim.flags.map((flag, j) => <li key={j}>{flag}</li>)}</ul></>}
  </li>
}

export function Claims({section, sources, onOpen, empty}: {section?: AgentSection; sources: Map<number, AgentSource>; onOpen: Open; empty: string}) {
  if (!section?.claims.length) return <p className="empty-inline">{empty}</p>
  return <ul className="agent-claims">{section.claims.map((claim, i) => <Claim key={i} claim={claim} sources={sources} onOpen={onOpen} />)}</ul>
}

export function KeyNumbers({rows, onOpen}: {rows: KeyNumber[]; onOpen: Open}) {
  const many = new Set(rows.map(r => r.company)).size > 1
  return <div className="table-scroll key-numbers" tabIndex={0} aria-label="Key numbers table">
    <table><caption className="sr-only">Key numbers: each figure with its period and change</caption>
      <thead><tr>{many && <th scope="col">Company</th>}<th scope="col">Metric</th><th scope="col">Period</th><th scope="col" className="numeric">Value</th><th scope="col" className="numeric">Change</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        {many && <td>{row.company}</td>}<th scope="row">{row.metric}</th><td>{row.period}</td>
        <td className="numeric"><button type="button" className="text-button" onClick={() => onOpen(row.id)} aria-label={`${row.metric}, ${row.period}: ${row.value}. Open its source`}>{row.value}</button></td>
        <td className="numeric">{row.change && row.change_id ? <button type="button" className="text-button" onClick={() => onOpen(row.change_id!)} aria-label={`Change: ${row.change}. Open its calculation`}>{row.change}</button> : <span aria-label="no change calculated">–</span>}</td>
      </tr>)}</tbody>
    </table>
  </div>
}

const OUTCOME: Record<string, string> = {
  corrected: 'Fixed: the team changed the claim.', defended: 'Kept: the team showed evidence that answers it.',
  withdrawn: 'Removed: the claim was taken out of the report.', unresolved: 'Not fixed: read this claim with care.',
}
const WORD: Record<string, string> = {corrected: 'Fixed', defended: 'Kept', withdrawn: 'Removed', unresolved: 'Still open'}
const minor = (o: AgentObjection) => o.outcome === 'unresolved' && !o.material
// "key_numbers[0]" → "Key numbers, point 1"
function place(where: string | null | undefined, sections: AgentSection[]) {
  const match = where?.match(/^(\w+)\[(\d+)\]$/)
  const section = match && sections.find(s => s.key === match[1])
  return match && section ? `${section.heading}, point ${Number(match[2]) + 1}` : null
}

export function ReviewChanges({objections, sections}: {objections: AgentObjection[]; sections: AgentSection[]}) {
  const count = (outcome: string) => objections.filter(o => o.outcome === outcome && !minor(o)).length
  const summary = [[count('corrected'), 'fixed'], [count('defended'), 'kept'], [count('withdrawn'), 'removed'], [objections.filter(minor).length, 'minor and not sent back'], [count('unresolved'), 'still open']]
    .filter(([n]) => n).map(([n, what]) => `${n} ${what}`).join(', ')
  return <>
    <p className="muted">A separate critic agent checked the report against the evidence. It raised {objections.length} objection{objections.length === 1 ? '' : 's'}: {summary}. Material ones go back to the team to fix; minor ones are only listed here.</p>
    <ul className="review-changes">{objections.map((o, i) => <li key={i}>
      <div className="claim-meta"><Badge tone={o.outcome === 'unresolved' ? 'amber' : 'green'}>{minor(o) ? 'Minor' : WORD[o.outcome] ?? o.outcome}</Badge><strong>{o.issue}</strong>{place(o.where, sections) && <span>on {place(o.where, sections)}</span>}</div>
      <p>{o.problem}</p>
      <p><strong>{minor(o) ? 'Minor, so not sent back for fixing.' : OUTCOME[o.outcome] ?? o.outcome}</strong>{o.explanation && ` ${o.explanation}`}</p>
      {o.meaning && <p className="muted">"{o.issue}" means {o.meaning}.</p>}
      {!!o.notes?.length && <ul className="agent-flags">{o.notes.map((note, j) => <li key={j}>{note}</li>)}</ul>}
    </li>)}</ul>
  </>
}

const GROUPS = ['Reported figures', 'Calculations', 'Prices', 'Checks against the filing', 'Filing text', 'Filings', 'Insider trades', 'Peers and sector', 'Release dates', 'Companies', 'Analyst findings', 'Other']
const groupOf = (source: AgentSource) => GROUPS.includes(source.group ?? '') ? source.group! : 'Other' // a new group is never dropped
export function SourcesList({sources, onOpen}: {sources: AgentSource[]; onOpen: Open}) {
  const grouped = GROUPS.map(group => [group, sources.filter(s => groupOf(s) === group)] as const).filter(([, items]) => items.length)
  return <>{grouped.map(([group, items]) => <details key={group} className="source-group"><summary>{group} <span>{items.length}</span></summary>
    <ol className="agent-sources">{items.map(source => <li key={source.id} id={`source-${source.n}`} value={source.n}>
      <button type="button" className="text-button" onClick={() => onOpen(source.id)}>{source.label ?? source.id}</button> <span className="muted">{source.text}</span>
      {sourceLink(source.url) && <> <a href={sourceLink(source.url)!.href} target="_blank" rel="noopener noreferrer">{sourceLink(source.url)!.site} ↗</a></>}
    </li>)}</ol>
  </details>)}</>
}
