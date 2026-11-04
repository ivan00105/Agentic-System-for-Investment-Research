// An agent run's checked report, answer first: the answer and takeaways, key numbers and charts, the cases for and
// against, risks, what the review changed, then limitations and sources folded away.
import { useMemo, useRef, useState } from 'react'
import { stamp } from '../../api'
import type { AgentReport as Report } from '../../api'
import { Badge } from '../Badge'
import { RecordPanel } from '../EvidencePanel'
import { CompanyCharts } from './Charts'
import { tone } from './labels'
import { Claim, Claims, KeyNumbers, ReviewChanges, SourcesList } from './ReportParts'

export function AgentReport({runId, report}: {runId: string; report: Report}) {
  const [trail, setTrail] = useState<string[]>([])
  const trigger = useRef<HTMLElement | null>(null)
  const sources = useMemo(() => new Map(report.sources.map(s => [s.n, s])), [report.sources])
  const section = (key: string) => report.sections.find(s => s.key === key)
  const open = (id: string) => { trigger.current = document.activeElement as HTMLElement; setTrail([id]) }
  const close = () => { setTrail([]); trigger.current?.focus() }
  const [answer, ...takeaways] = section('summary')?.claims ?? []
  const keyNumbers = section('key_numbers')
  const figures = report.figures
  const totals = report.totals
  const parts = {sources, onOpen: open}
  return <div className="report-layout"><div className="report-body agent-report">
    <section className="report-section summary-section">
      <div className="section-heading"><div className="section-label">THE ANSWER</div><Badge tone={tone(report.status)}>{report.status_label}</Badge></div>
      {report.error && <p className="configuration-note">The run failed: {report.error}</p>}
      {answer ? <ul className="agent-answer"><Claim claim={answer} {...parts} /></ul> : <p className="empty-inline">The agents could not answer from the evidence they found. The sections below say what they did find.</p>}
      {takeaways.length > 0 && <><h3>Takeaways</h3><ul className="agent-claims">{takeaways.map((claim, i) => <Claim key={i} claim={claim} {...parts} />)}</ul></>}
    </section>
    <section className="report-section">
      <div className="section-heading"><h2>Key numbers</h2><Badge tone={tone(keyNumbers?.status ?? 'abstained')}>{keyNumbers?.status ?? 'abstained'}</Badge></div>
      {figures?.table.length ? <KeyNumbers rows={figures.table} onOpen={open} /> : <Claims section={keyNumbers} {...parts} empty="No figure in this report is backed by a reported fact or calculation." />}
      {figures?.charts.map(chart => <CompanyCharts key={chart.cik} chart={chart} many={figures.charts.length > 1} />)}
      {!!figures?.charts.length && <p className="muted">Charts are drawn from the SEC figures and prices this run saved, with nothing fetched again. Years are fiscal years, labelled by the calendar year each one ends in.</p>}
      {!!figures?.table.length && !!keyNumbers?.claims.length && <details className="technical-details" open={keyNumbers.status === 'qualified'}><summary>Key numbers as the agents wrote them ({keyNumbers.claims.length})</summary><Claims section={keyNumbers} {...parts} empty="" /></details>}
    </section>
    <section className="report-section">
      <h2>The case for and against</h2>
      <div className="cases">
        <div><div className="section-heading"><h3>Bull case: for</h3><Badge tone={tone(section('bull_case')?.status ?? 'abstained')}>{section('bull_case')?.status ?? 'abstained'}</Badge></div><Claims section={section('bull_case')} {...parts} empty="No evidence-backed point for." /></div>
        <div><div className="section-heading"><h3>Bear case: against</h3><Badge tone={tone(section('bear_case')?.status ?? 'abstained')}>{section('bear_case')?.status ?? 'abstained'}</Badge></div><Claims section={section('bear_case')} {...parts} empty="No evidence-backed point against." /></div>
      </div>
    </section>
    {(['risks', 'what_would_change_view'] as const).map(key => <section className="report-section" key={key}>
      <div className="section-heading"><h2>{key === 'risks' ? 'Risks' : 'What would change the view'}</h2><Badge tone={tone(section(key)?.status ?? 'abstained')}>{section(key)?.status ?? 'abstained'}</Badge></div>
      <Claims section={section(key)} {...parts} empty="Nothing here is backed by evidence the agents found." />
    </section>)}
    {report.objections.length > 0 && <section className="report-section review-section"><h2>What the review changed</h2><ReviewChanges objections={report.objections} sections={report.sections} /></section>}
    <section className="report-section limitations">
      <details><summary><h2>Limitations</h2> <span className="muted">{report.limitations.length + report.flags.length} notes: what could not be checked, and how figures were found</span></summary>
        <ul>{report.limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>
        {report.flags.length > 0 && <><h3>Checker flags</h3><ul>{report.flags.map((text, i) => <li key={i}>{text}</li>)}</ul></>}
      </details>
    </section>
    {report.sources.length > 0 && <section className="report-section"><h2>Sources <span className="muted">{report.sources.length}</span></h2><SourcesList sources={report.sources} onOpen={open} /></section>}
    <section className="report-section"><details className="technical-details"><summary>Run details</summary>
      {totals && <p>{totals.model_calls} model calls · {totals.tool_calls} tool calls · {totals.total_tokens.toLocaleString('en-US')} tokens{totals.cached_tokens != null && ` (${totals.cached_tokens.toLocaleString('en-US')} cached)`}{totals.cost != null && ` · $${totals.cost.toFixed(2)}`}</p>}
      <p>{report.model && `Model ${report.model}`}{report.cutoff && ` · evidence cutoff ${stamp(report.cutoff)}`}</p>
      <p className="mono">Run ID: {runId}</p>
    </details></section>
  </div><RecordPanel runId={runId} trail={trail} onOpen={id => setTrail(t => [...t, id])} onBack={() => setTrail(t => t.slice(0, -1))} onClose={close} /></div>
}
