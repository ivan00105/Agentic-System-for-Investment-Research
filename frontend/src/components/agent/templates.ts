// The question box's helpers write a question from the user's choices; the user can still edit the text.
import type { CompanyMatch } from '../../api'

// "known": companies the user already has in mind (one is a check, two to four a comparison); "find": a screen.
export type Kind = 'known' | 'find'
export const TOPICS = ['profitability', 'growth', 'cash flow', 'debt', 'valuation', 'vs peers', 'risks', 'insider trades', 'recent events'] as const
export type Topic = typeof TOPICS[number]

const HINTS: Record<Topic, string> = {
  profitability: 'How much of each sale it keeps as profit.', growth: 'How fast its sales are rising.',
  'cash flow': 'Free cash flow: cash left after running and investing in the business.', debt: 'How much long-term debt it owes.',
  valuation: 'Whether the share price looks high or low for what it earns.', 'vs peers': 'How it measures up to similar companies.',
  risks: 'What could go wrong, from its annual report.', 'insider trades': 'Whether its directors and officers bought or sold shares.',
  'recent events': 'What its latest filings say has happened.',
}
const CHECK: Record<Topic, string> = {
  profitability: 'how profitable it is', growth: 'how fast it is growing', 'cash flow': 'how much free cash flow it makes',
  debt: 'how much long-term debt it carries', valuation: 'whether its valuation looks high or low', 'vs peers': 'how it compares with its peers',
  risks: 'its main risks', 'insider trades': 'whether its insiders have been buying or selling shares', 'recent events': 'what its recent filings say has happened',
}
// A comparison names the topic itself, except where the name doesn't read as a noun.
const COMPARE: Partial<Record<Topic, string>> = {'vs peers': 'how each ranks among its peers'}
// Only what the screen can check (SEC figures, P/E and price swings); Find greys out the other topics.
const FIND: Partial<Record<Topic, string>> = {profitability: 'high profit margins', growth: 'growing revenue', 'cash flow': 'strong free cash flow',
  valuation: 'a reasonable valuation', risks: 'steady share prices'}
const FIND_HINTS: Partial<Record<Topic, string>> = {risks: 'A share price that has not jumped around much.'}

export const findCanCheck = (topic: Topic) => Boolean(FIND[topic])
export const topicHint = (topic: Topic, kind: Kind | null) => kind !== 'find' ? HINTS[topic] : !FIND[topic] ? "Find can't check this yet." : FIND_HINTS[topic] ?? HINTS[topic]

// SEC names are often upper case ("MICROSOFT CORP"); show those in title case.
export const companyName = (c: CompanyMatch) => c.name === c.name.toUpperCase() ? c.name.toLowerCase().replace(/\b\w/g, ch => ch.toUpperCase()) : c.name
const named = (c: CompanyMatch) => `${companyName(c)} (${c.tickers[0]})`
const list = (items: string[]) => items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`

// find.sector is the sector Guide me chose, e.g. "in health care"; there is no chip for it.
export function buildQuestion(kind: Kind | null, companies: CompanyMatch[], topics: Topic[], find: {count: string; among: string; sector?: string}) {
  if (kind === 'find') {
    const what = list(topics.flatMap(t => FIND[t] ?? []))
    return `Find ${find.count ? `${find.count} ` : ''}companies ${find.among}${find.sector ? ` ${find.sector}` : ''}${what ? ` with ${what}` : ''}.`
  }
  if (companies.length === 1) return `For ${named(companies[0])}, explain ${list(topics.length ? topics.map(t => CHECK[t]) : ['how its business is doing', 'its main risks'])}.`
  if (companies.length > 1) return `Compare ${list(companies.map(named))} on ${list(topics.length ? topics.map(t => COMPARE[t] ?? t) : ['profitability', 'growth', 'valuation', 'risks'])}.`
  return ''
}
