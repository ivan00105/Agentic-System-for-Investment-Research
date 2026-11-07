// A mocked agent run for the browser tests: the test server has no model, so runs are served by page.route.
import type { Page } from '@playwright/test'

export const RUN = '20261105-090000-abc123'
export const summary = {run_id: RUN, status: 'finished', question: 'How profitable is Acme?', condition: 'D (analyst team with critic)', cutoff: '2026-11-05T09:00:00+00:00', model: 'test/model', started_at: '2026-11-05T09:00:00+00:00', totals: {model_calls: 3, tool_calls: 4, total_tokens: 1000, cached_tokens: 100, cost: 0.01}}
const claim = (text: string, citations = [1]) => ({text, status: 'cited', citations, flags: []})
const section = (key: string, heading: string, claims: unknown[]) => ({key, heading, status: claims.length ? 'cited' : 'abstained', claims})
export const REPORT = {...summary, status_label: 'finished', error: null, limitations: ['Figures are annual, from the 10-K.'], flags: [], objections: [], markdown: '# How profitable is Acme?\n',
  sections: [section('summary', 'Summary', [claim('Acme keeps a 25.0% operating margin, the share of revenue left after running costs.'), claim('Its P/E of 20.0x is below the market.')]),
    section('key_numbers', 'Key numbers', [claim('Operating margin 25.0%.', [2])]), section('bull_case', 'Bull case', [claim('Free cash flow is strong.')]),
    section('bear_case', 'Bear case', []), section('risks', 'Risks', []), section('what_would_change_view', 'What would change the view', [])],
  sources: [{n: 1, id: 'fact-rev', text: 'Revenue, FY2024', url: null, kind: 'fact', group: 'Reported figures', label: 'Revenue FY2024'}, {n: 2, id: 'calc-m', text: 'Operating margin', url: null, kind: 'calc', group: 'Calculations', label: 'Operating margin'}],
  figures: {table: [], charts: []},
  raw: [{id: 'calc-m', kind: 'calc', cik: '0000000001', company: 'Acme Corp', label: 'Operating margin', period: 'FY2024', value: '0.25', unit: 'ratio', shown: '25.0%', start: '2024-01-01', end: '2024-12-31', formula: 'ratio', inputs: {numerator: 'fact-oi', denominator: 'fact-rev'}, tag: null, form: null, accession: null, filed: null, url: null, notes: [], reason: null},
    {id: 'fact-rev', kind: 'fact', cik: '0000000001', company: 'Acme Corp', label: 'Revenue', period: 'FY2024', value: '100000000000', unit: 'USD', shown: '$100.0 billion', start: '2024-01-01', end: '2024-12-31', formula: null, inputs: {}, tag: 'us-gaap:Revenues', form: '10-K', accession: '0000000001-25-000001', filed: '2025-02-01', url: null, notes: [], reason: null}]}

export async function mockRun(page: Page, progress: object, report: object | null = REPORT) {
  await page.route(`**/api/agent-runs/${RUN}`, route => route.fulfill({json: {...summary, progress: [], questions: null, ...progress}}))
  if (report) await page.route(`**/api/agent-runs/${RUN}/report`, route => route.fulfill({json: report}))
}
