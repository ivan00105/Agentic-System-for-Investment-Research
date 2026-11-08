// The live trace, grouped by the role that did each step: plan, analysts' work, draft, the critic's review, revisions.
// Each model step is one line with its time; what its tool calls did folds under it.
import type { ProgressLine } from '../../api'
import { clock, ROLE_JOBS, ROLES } from './labels'

const OPENERS = ['plan', 'analyst_start', 'critic_start', 'revision_start', 'questions', 'screen_spec', 'research_start']

function groups(lines: ProgressLine[]) {
  const out: {role: string | null; lines: ProgressLine[]}[] = []
  for (const line of lines) {
    const last = out[out.length - 1]
    if (last && last.role === (line.role ?? null) && !(line.kind && OPENERS.includes(line.kind) && last.lines.length)) last.lines.push(line)
    else out.push({role: line.role ?? null, lines: [line]})
  }
  return out
}

function Line({line, live}: {line: ProgressLine; live: boolean}) {
  const time = line.at ? <time dateTime={line.at}>{clock(line.at)}</time> : <span />
  if (!line.details?.length) return <li>{time}<span>{line.text}</span></li>
  return <li>{time}<details open={live}><summary>{line.text}</summary>
    <ol>{line.details.map((detail, i) => <li key={detail.seq ?? i} className={detail.status && detail.status !== 'ok' ? 'timeline-problem' : undefined}>{detail.text}</li>)}</ol>
  </details></li>
}

export function RunTimeline({lines, running}: {lines: ProgressLine[]; running: boolean}) {
  const all = groups(lines)
  if (!all.length) return <p className="muted" role="status">{running ? 'Starting: the first step appears here in a moment.' : 'No steps were recorded.'}</p>
  return <ol className="timeline">{all.map((group, i) => {
    const role = group.role ?? ''
    const first = group.lines[0], last = group.lines[group.lines.length - 1]
    const live = running && i === all.length - 1
    const steps = group.lines.filter(line => line.kind === 'model_call').length || group.lines.length
    return <li key={`${i}-${first.seq}`} className={live ? 'live' : ''}>
      <details open={live}>
        <summary><strong>{ROLES[role] ?? 'Run'}</strong>{ROLE_JOBS[role] && <span className="muted"> · {ROLE_JOBS[role]}</span>}
          <span className="timeline-lead">{first.text.split('\n')[0]}</span>
          <small>{steps} step{steps === 1 ? '' : 's'}{first.at && last.at && ` · ${clock(first.at)}–${clock(last.at)}`}</small>
        </summary>
        <ol>{group.lines.map((line, j) => <Line key={line.seq ?? j} line={line} live={live && j === group.lines.length - 1} />)}</ol>
      </details>
    </li>
  })}</ol>
}
