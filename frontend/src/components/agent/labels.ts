// Words the agent pages share: run statuses, roles and tool names in plain English.
import type { Condition } from '../../api'

export const CONDITIONS: Record<Condition, string> = {D: 'Analyst team with critic', C: 'Analyst team', B: 'Single agent'}
export const STATUS: Record<string, string> = {
  running: 'Running', stopping: 'Stopping after the current step', waiting: 'Waiting for your answers', finished: 'Finished',
  stopped_at_limit: 'Stopped at the step limit (partial report)', stopped: 'Cancelled (partial report)', failed: 'Failed',
  incomplete: 'No end recorded: still running elsewhere, or interrupted',
}
export const tone = (status: string) => ['cited', 'finished', 'pass', 'picked'].includes(status) ? 'green' : ['abstained', 'running', 'waiting'].includes(status) ? '' : 'amber'
export const clock = (at: string) => new Date(at).toISOString().slice(11, 19) + ' UTC'

export const ROLES: Record<string, string> = {
  single_agent: 'Research agent', coordinator: 'Coordinator', fundamentals: 'Fundamentals analyst', filings: 'Filings analyst',
  market: 'Market analyst', critic: 'Critic', screener: 'Screener', host: 'Host checks', research: 'Research',
}
export const ROLE_JOBS: Record<string, string> = {
  coordinator: 'plans the work, asks the analysts and writes the report', fundamentals: 'reported figures, margins and growth',
  filings: '10-K text and 8-K events', market: 'prices, returns and valuation', critic: 'checks the report against the evidence',
  screener: 'turns the request into a screen', host: 'screens and checks candidates without a model', single_agent: 'does all the research itself',
}
const TOOLS: Record<string, string> = {
  find_company: 'company lookup', get_financials: 'reported figures', calculate: 'a calculation', get_prices: 'prices',
  read_filing_section: 'filing text', list_filings: 'the filing list', verify_against_filing: 'a check against the filing',
  screen: 'the screen', ask_fundamentals: 'the fundamentals analyst', ask_filings: 'the filings analyst', ask_market: 'the market analyst',
  submit_report: 'handing in the report', submit_findings: 'handing in findings', submit_objections: 'handing in objections',
  submit_revision: 'handing in the revision', submit_screen_spec: 'handing in the screen spec',
}
const tool = (name: string) => TOOLS[name] ?? name
// "step 3: model asks for get_financials, calculate" → "step 3: model asks for reported figures, a calculation"
export const plain = (text: string) => text
  .replace(/^(step \d+: model asks for )(.+)$/m, (_, head: string, names: string) => head + names.split(', ').map(tool).join(', '))
  .replace(/^((?:step \d+: )?)(\w+) -> /, (_, head: string, name: string) => `${head}${tool(name)} -> `)
