import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'

const RUN = '20261105-090000-abc123'
const summary = {run_id: RUN, status: 'finished', question: 'How profitable is Acme?', condition: 'D (analyst team with critic)', cutoff: '2026-11-05T09:00:00+00:00', model: 'test/model', started_at: '2026-11-05T09:00:00+00:00', totals: {model_calls: 3, tool_calls: 4, total_tokens: 1000, cached_tokens: 100, cost: 0.01}}
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

test('the detail level changes how runs are shown, never what they do', async ({page}) => {
  await page.goto('/')
  const level = page.getByLabel('Detail level')
  await expect(level).toHaveValue('standard')
  await expect(page.locator('.agent-options')).not.toHaveAttribute('open', '')
  await level.selectOption('professional')
  await expect(page.locator('.agent-options')).toHaveAttribute('open', '')
  await page.locator('.starter', {hasText: 'Find companies'}).click()
  await expect(page.getByRole('checkbox', {name: /check and edit the screen spec/})).toBeChecked()
  await expect(page.getByRole('textbox', {name: 'Model'})).toBeVisible()

  await mockRun(page, {})
  await page.goto(`/?view=research&agent=${RUN}`)
  await expect(level).toHaveValue('professional') // remembered
  const raw = page.locator('.raw-details')
  await expect(raw).toHaveAttribute('open', '')
  await expect(page.locator('.raw-figures')).toContainText('numerator=fact-oi')
  await expect(page.locator('.raw-figures')).toContainText('100000000000')
  const download = page.waitForEvent('download')
  await page.getByRole('button', {name: 'Figures (CSV)'}).click()
  const csv = await download
  expect(csv.suggestedFilename()).toBe(`${RUN}-figures.csv`)
  const text = fs.readFileSync(await csv.path(), 'utf-8')
  expect(text.split('\r\n')[0]).toContain('id,kind,company,cik,label,period,value,unit')
  expect(text).toContain('"{""numerator"":""fact-oi"",""denominator"":""fact-rev""}"')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])

  await level.selectOption('beginner')
  await expect(raw).not.toHaveAttribute('open', '')
  const glossary = page.getByRole('region', {name: 'Words used in this report'})
  await expect(glossary).toContainText('P/E (price to earnings)')
  await expect(glossary).toContainText('Free cash flow')
  await expect(glossary.locator('dt', {hasText: /^Free cash flow$/})).toHaveCount(1) // each term once
  await expect(page.getByRole('heading', {name: 'Reasons for'})).toBeVisible()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await level.selectOption('standard')
  await expect(glossary).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'Bull case: for'})).toBeVisible()
})

test('a professional can edit the screen spec directly before it runs', async ({page}) => {
  const spec = {rank_by: 'operating_margin', descending: true, filters: [], terms: []}
  await mockRun(page, {status: 'waiting', questions: {terms: [], shown: ['Universe: your list, 1 companies'], spec}}, null)
  let sent: unknown = null
  await page.route(`**/api/agent-runs/${RUN}/answers`, route => { sent = route.request().postDataJSON(); return route.fulfill({json: {...summary, status: 'running'}}) })
  await page.goto('/')
  await page.getByLabel('Detail level').selectOption('professional')
  await page.goto(`/?view=research&agent=${RUN}`)
  const editor = page.getByLabel('Screen spec (JSON)')
  await expect(editor).toBeVisible()
  await editor.fill('{"rank_by": "revenue"')
  await page.getByRole('button', {name: 'Screen with my edited spec →'}).click()
  await expect(page.getByRole('alert')).toContainText("isn't valid JSON")
  await editor.fill(JSON.stringify({...spec, rank_by: 'revenue'}))
  await page.getByRole('button', {name: 'Screen with my edited spec →'}).click()
  await expect.poll(() => sent).toEqual({answers: {}, spec: {...spec, rank_by: 'revenue'}})
})

test('help me start turns four choices into a Find question and a note the run keeps', async ({page}) => {
  await page.goto('/')
  await page.getByLabel('Detail level').selectOption('beginner')
  await page.reload()
  const guided = page.getByRole('form', {name: 'Help me start'})
  await expect(guided).toBeVisible() // opens by itself for beginners
  await expect(guided.getByRole('radio', {name: /Steady profits \(recommended\)/})).toBeChecked()
  await expect(guided.getByRole('radio', {name: /^Years/})).toBeChecked()
  await expect(guided.getByRole('radio', {name: /Not sure/})).toHaveCount(4)
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await guided.getByRole('radio', {name: /^Dividends/}).check()
  await guided.getByRole('radio', {name: /^Weeks/}).check()
  await guided.getByRole('radio', {name: /calm ride/}).check()
  await guided.getByRole('radio', {name: /^Health care/}).check()
  await guided.getByRole('button', {name: 'Build my question →'}).click()
  await expect(guided).toHaveCount(0)
  const question = page.getByLabel('Your question')
  await expect(question).toHaveValue(/^Find companies among .+ in health care with strong free cash flow and steady share prices\.$/)
  const note = page.getByLabel('Your preferences (the agents read this note)')
  await expect(note).toHaveValue(/What matters most: dividends \(the screen checks free cash flow instead\)\.\nTime horizon: weeks\.\nComfort with price swings: low\.\nSectors: health care\./)
  await expect(page.locator('.starter', {hasText: 'Find companies'})).toHaveAttribute('aria-pressed', 'true')
  let body: Record<string, unknown> = {}
  await page.route('**/api/agent-runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    body = route.request().postDataJSON()
    return route.fulfill({status: 202, json: {run_id: RUN, status: 'running'}})
  })
  await mockRun(page, {status: 'running', question: 'Find companies.', preferences: 'Time horizon: weeks.'}, null)
  await page.getByRole('button', {name: 'Find companies →'}).click()
  await expect(page.getByText('YOUR PREFERENCES')).toBeVisible()
  await expect(page.locator('.preferences-shown')).toContainText('Time horizon: weeks.')
  expect(body.preferences).toContain('Sectors: health care.')
  expect(body.discover).toMatchObject({name: expect.any(String)})
  expect(body.question).toMatch(/in health care/)
  // The answers are remembered for next time.
  await page.goto('/') // still Beginner, so the form is open
  await expect(page.getByRole('form', {name: 'Help me start'}).getByRole('radio', {name: /^Dividends/})).toBeChecked()
  await page.getByRole('button', {name: /Help me start/}).click()
  await expect(page.getByRole('form', {name: 'Help me start'})).toHaveCount(0)
})
