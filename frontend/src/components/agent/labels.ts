// Words the agent pages share: run statuses and roles in plain English.
import type { AgentRunSummary, Condition } from '../../api'

export const CONDITIONS: Record<Condition, string> = {D: 'Analyst team with critic', C: 'Analyst team', B: 'Single agent'}
export const STATUS: Record<string, string> = {
  running: 'Running', stopping: 'Stopping after the current step', waiting: 'Waiting for your answers', finished: 'Finished',
  stopped_at_limit: 'Stopped at the step limit (partial report)', stopped: 'Cancelled (partial report)', failed: 'Failed',
  incomplete: 'No end recorded: still running elsewhere, or interrupted',
}
export const tone = (status: string) => ['cited', 'finished', 'pass', 'picked'].includes(status) ? 'green' : ['abstained', 'running', 'waiting'].includes(status) ? '' : 'amber'
const count = (n: number, word: string) => n ? `${n} ${word}${n === 1 ? '' : 's'}` : ''
// The runs a Discover run started, as History counts them: "3 picks · 1 comparison".
export const childCount = (children: AgentRunSummary[]) => {
  const picks = children.filter(c => c.kind === 'pick').length
  return [count(picks, 'pick'), count(children.length - picks, 'comparison')].filter(Boolean).join(' · ')
}
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
