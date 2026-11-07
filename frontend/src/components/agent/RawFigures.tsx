// Professional view: every cited figure with its formula and inputs, unformatted, and exports of figures and sources.
import type { AgentReport, RawFigure } from '../../api'
import type { Open } from './ReportParts'

const COLUMNS: (keyof RawFigure)[] = ['id', 'kind', 'company', 'cik', 'label', 'period', 'value', 'unit', 'shown', 'formula', 'inputs', 'start', 'end', 'tag', 'form', 'accession', 'filed', 'url', 'reason', 'notes']
const cell = (value: unknown) => {
  const text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}
export const toCsv = (rows: Record<string, unknown>[], columns: string[]) => [columns.join(','), ...rows.map(r => columns.map(c => cell(r[c])).join(','))].join('\r\n') + '\r\n'

function download(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], {type}))
  const link = Object.assign(document.createElement('a'), {href: url, download: name})
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function Exports({runId, report}: {runId: string; report: AgentReport}) {
  const figures = report.raw ?? []
  const sources = report.sources.map(s => ({n: s.n, id: s.id, kind: s.kind, group: s.group, label: s.label, text: s.text, url: s.url}))
  return <div className="export-buttons" role="group" aria-label="Export this report">
    <button type="button" className="secondary" onClick={() => download(`${runId}-figures.csv`, 'text/csv', toCsv(figures as unknown as Record<string, unknown>[], COLUMNS))}>Figures (CSV)</button>
    <button type="button" className="secondary" onClick={() => download(`${runId}-sources.csv`, 'text/csv', toCsv(sources, ['n', 'id', 'kind', 'group', 'label', 'text', 'url']))}>Sources (CSV)</button>
    <button type="button" className="secondary" onClick={() => download(`${runId}.json`, 'application/json', JSON.stringify({run_id: runId, question: report.question, preferences: report.preferences ?? null, model: report.model, cutoff: report.cutoff, status: report.status, figures, sources}, null, 2))}>Figures and sources (JSON)</button>
    {report.markdown && <button type="button" className="secondary" onClick={() => download(`${runId}.md`, 'text/markdown', report.markdown)}>Report (Markdown)</button>}
  </div>
}

export function RawFigures({rows, onOpen}: {rows: RawFigure[]; onOpen: Open}) {
  if (!rows.length) return <p className="empty-inline">This report cites no reported figure or calculation.</p>
  return <div className="table-scroll raw-figures" tabIndex={0} aria-label="Raw figures table">
    <table><caption className="sr-only">Every cited figure, unformatted, with its formula, inputs and filing</caption>
      <thead><tr><th scope="col">Figure</th><th scope="col">Period</th><th scope="col" className="numeric">Value</th><th scope="col">Unit</th><th scope="col">Formula and inputs</th><th scope="col">Filing</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <th scope="row"><button type="button" className="text-button" onClick={() => onOpen(row.id)}>{row.label}</button>{row.company && <small className="muted">{row.company}</small>}</th>
        <td>{row.period}</td>
        <td className="numeric mono">{row.value ?? `unavailable: ${row.reason ?? 'no value'}`}</td>
        <td>{row.unit}</td>
        <td>{row.formula ? <><code>{row.formula}</code>({Object.entries(row.inputs).map(([role, id], i) => <span key={role}>{i > 0 && ', '}{role}=<button type="button" className="text-button mono" onClick={() => onOpen(id)}>{id}</button></span>)})</> : <span className="muted">reported{row.tag && <> as <code>{row.tag}</code></>}</span>}</td>
        <td className="mono">{row.form ? `${row.form} ${row.accession ?? ''}, filed ${row.filed ?? '?'}` : '–'}</td>
      </tr>)}</tbody>
    </table>
  </div>
}
