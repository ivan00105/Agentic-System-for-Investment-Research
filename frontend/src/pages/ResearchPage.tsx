// The agents' page: one question box and the recent runs, or one run with its timeline and report.
import type { CompanyMatch } from '../api'
import { QuestionBox } from '../components/agent/QuestionBox'
import { RunList } from '../components/agent/RunList'
import { RunView } from '../components/agent/RunView'

const RECENT_RUNS = 5 // History lists every run

export function ResearchPage({agent, compare, openAgent, onCompare, onNew, onHistory}: {agent: string | null; compare: CompanyMatch[] | null; openAgent: (id: string) => void; onCompare: (companies: CompanyMatch[]) => void; onNew: () => void; onHistory: () => void}) {
  if (agent) return <RunView key={agent} id={agent} onOpenRun={openAgent} onNew={onNew} onCompare={onCompare} />
  return <><QuestionBox onStarted={openAgent} initial={compare} /><RunList onOpen={openAgent} recent={RECENT_RUNS} onSeeAll={onHistory} /></>
}
