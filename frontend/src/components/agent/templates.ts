// The question box's helpers write a question from the user's choices; the user can still edit the text.
import type { CompanyMatch } from '../../api'

export type Kind = 'check' | 'compare' | 'find'
export const TOPICS = ['profitability', 'growth', 'valuation', 'risks', 'recent events'] as const
export type Topic = typeof TOPICS[number]

const CHECK: Record<Topic, string> = {
  profitability: 'how profitable it is', growth: 'how fast it is growing', valuation: 'whether its valuation looks high or low',
  risks: 'its main risks', 'recent events': 'what its recent filings say has happened',
}
// Screens can't read events, so Find has no wording for them.
const FIND: Partial<Record<Topic, string>> = {profitability: 'high profit margins', growth: 'growing revenue', valuation: 'a reasonable valuation', risks: 'steady share prices'}

// SEC names are often upper case ("MICROSOFT CORP"); show those in title case.
export const companyName = (c: CompanyMatch) => c.name === c.name.toUpperCase() ? c.name.toLowerCase().replace(/\b\w/g, ch => ch.toUpperCase()) : c.name
const named = (c: CompanyMatch) => `${companyName(c)} (${c.tickers[0]})`
const list = (items: string[]) => items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`

export function buildQuestion(kind: Kind | null, companies: CompanyMatch[], topics: Topic[], find: {count: string; among: string}) {
  if (kind === 'find') {
    const what = list(topics.flatMap(t => FIND[t] ?? []))
    return `Find ${find.count ? `${find.count} ` : ''}companies ${find.among}${what ? ` with ${what}` : ''}.`
  }
  if (companies.length === 1) return `For ${named(companies[0])}, explain ${list(topics.length ? topics.map(t => CHECK[t]) : ['how its business is doing', 'its main risks'])}.`
  if (companies.length > 1) return `Compare ${list(companies.map(named))} on ${list(topics.length ? [...topics] : ['profitability', 'growth', 'valuation', 'risks'])}.`
  return ''
}
