// The agents' page: one question box and the recent runs, or one run with its timeline and report.
import { QuestionBox } from '../components/agent/QuestionBox'
import { RunList } from '../components/agent/RunList'
import { RunView } from '../components/agent/RunView'

const RECENT_RUNS = 5 // History lists every run

export function ResearchPage({agent, openAgent, onNew, onHistory}: {agent: string | null; openAgent: (id: string) => void; onNew: () => void; onHistory: () => void}) {
  if (agent) return <RunView key={agent} id={agent} onOpenRun={openAgent} onNew={onNew} />
  return <><QuestionBox onStarted={openAgent} /><RunList onOpen={openAgent} recent={RECENT_RUNS} onSeeAll={onHistory} /></>
}
