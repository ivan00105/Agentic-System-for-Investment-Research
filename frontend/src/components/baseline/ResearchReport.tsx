import { metricValue } from '../../api'
import type { CompanyReport } from '../../api'
import { Badge } from '../Badge'

function Citations({ids, onEvidence}: {ids: string[]; onEvidence: (id: string) => void}) {
  return <div className="citations">{ids.map((id, i) => <button key={id} className="text-button citation" aria-label={`Inspect evidence ${i + 1}`} onClick={() => onEvidence(id)}>↗ Evidence {i + 1}</button>)}</div>
}

export function ResearchReport({company, ongoing, onEvidence}: {company: CompanyReport; ongoing: boolean; onEvidence: (id: string) => void}) {
  const available = company.metrics.filter(metric => metric.value !== null).length
  const financialStatus = available === 0 ? 'Unavailable' : available === company.metrics.length ? 'Available' : 'Partly available'
  const reviewStatus = company.review_status ?? 'not_recorded'
  const unfinished = reviewStatus === 'pending' && !ongoing
  const reviewLabel = unfinished ? 'Not finished' : {not_requested: 'Not requested', pending: 'Pending', completed: 'Completed', unavailable: 'Unavailable', failed: 'Failed', not_recorded: 'Not recorded'}[reviewStatus]
  const reviewNote = unfinished ? 'Model analysis did not finish before this investigation stopped. Any available financial figures have been saved.' : {
    not_requested: 'Model analysis was not requested. Inspect any available figures and calculation claims below.',
    pending: 'Model analysis is pending. Available financial figures are shown below.',
    completed: 'Model analysis is complete. Inspect its findings and supporting evidence below.',
    unavailable: 'Model analysis could not run with the available setup or evidence. Any available financial figures have been saved.',
    failed: 'Model analysis did not finish. Any available financial figures have been saved.',
    not_recorded: 'This saved report does not record model analysis status. Its review trail does not establish whether analysis completed.',
  }[reviewStatus]
  return <>
    <section className="report-section summary-section">
      <div className="section-label">01 / RESEARCH BRIEF</div>
      <div className="section-heading"><h2>{company.company} <span className="ticker">{company.ticker}</span></h2><Badge tone="amber">{company.support}</Badge></div>
      <dl className="report-availability" aria-label="Report availability"><div><dt>Financial figures</dt><dd><Badge tone={financialStatus === 'Available' ? 'green' : 'amber'}>{financialStatus}</Badge></dd></div><div><dt>Model analysis</dt><dd><Badge tone={reviewStatus === 'completed' ? 'green' : ''}>{reviewLabel}</Badge></dd></div></dl>
      <p className="muted model-status-note">{reviewNote}</p>
      <p className="summary">{company.summary}</p>
      <div className="metric-grid">{company.metrics.map(metric => <div className="metric" key={metric.id}><span>{metric.label}</span><strong className={metric.value === null ? 'missing-value' : ''}>{metricValue(metric)}</strong><small>{metric.period}</small><details><summary>Inputs & source</summary>{metric.formula && <p className="mono">{metric.formula}</p>}{metric.inputs.map(id => {const input = company.metrics.find(m => m.id === id); return <p key={id}>{input?.label}: {input ? metricValue(input) : 'Unavailable'}</p>})}{metric.unavailable_reason && <p>{metric.unavailable_reason}</p>}<Citations ids={metric.evidence_ids} onEvidence={onEvidence} /></details></div>)}</div>
    </section>
    <section className="report-section">
      <div className="section-label">02 / CLAIMS & SUPPORT</div>
      <h2>What the evidence supports</h2>
      <div className="claims">{company.claims.map(claim => <article className="claim" key={claim.id}><div className="claim-meta"><Badge tone={claim.status === 'unresolved' ? 'amber' : 'green'}>{claim.status}</Badge>{claim.kind === 'interpretation' && <span>Interpretation</span>}</div><p>{claim.statement}</p><Citations ids={claim.evidence_ids} onEvidence={onEvidence} /></article>)}</div>
    </section>
    <section className="report-section review-section">
      <div className="section-label">03 / REVIEW TRAIL</div><div className="section-heading"><h2>Review findings</h2><span className="muted">{company.reviews.length} recorded review{company.reviews.length === 1 ? '' : 's'}</span></div>
      {company.reviews.length === 0 ? <p className="empty-inline">No review findings are recorded. This does not establish that the claims are correct.</p> : company.reviews.map((review, i) => <article className="review" key={`${review.claim_id}-${i}`}><ol className="review-steps"><li><span className="step-number">1</span><div><h3>Original claim</h3><p>{review.original}</p></div></li><li><span className="step-number">2</span><div><h3>Objection</h3><p>{review.objection}</p></div></li><li><span className="step-number">3</span><div><h3>Evidence check</h3><p>{review.check}</p><Citations ids={review.evidence_ids} onEvidence={onEvidence} /></div></li><li className={review.revised ? 'corrected-step' : ''}><span className="step-number">4</span><div><h3>{review.revised ? 'Revised result' : 'Unresolved'} <Badge tone={review.revised ? 'green' : 'amber'}>{review.disposition}</Badge></h3><p>{review.revised ?? 'This concern remains unresolved; the claim has not been verified.'}</p></div></li></ol></article>)}
    </section>
    <section className="report-section forecast"><div className="section-heading"><h2>Return forecast</h2><Badge>Unavailable</Badge></div><p>No validated return forecast is available. Evidence support does not indicate the chance of beating the market.</p></section>
    <section className="report-section limitations"><div className="section-label">05 / LIMITATIONS</div><h2>Keep in view</h2><ul>{company.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
  </>
}
