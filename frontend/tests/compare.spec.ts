import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockRun, RUN } from './agent-fixtures'

const pick = (rank: number, cik: string, name: string, tickers: string[]) => ({rank, cik, name, tickers, outcome: 'picked', verdict: 'pass', run_id: null, lines: [], answer: `${name} fits the screen.`})
const SHORTLIST = {run_id: RUN, status: 'finished', status_label: 'finished', question: 'Find profitable tech companies.', condition: 'Discover (B (single agent))', error: null, sections: [], limitations: [], flags: [], objections: [], sources: [], markdown: '',
  discover: {spec: ['Universe: S&P 500'], counts: {screened: 500, eligible: 40, checked: 3, rejected: 0, researched: 3, returned: 3},
    candidates: [pick(1, '0000789019', 'MICROSOFT CORP', ['MSFT']), pick(2, '0001045810', 'NVIDIA CORP', ['NVDA']), pick(3, '0000320193', 'Apple Inc.', ['AAPL'])]}}

test('a Discover shortlist opens as a side-by-side comparison you can check first', async ({page}) => {
  await mockRun(page, {question: 'Find profitable tech companies.'}, SHORTLIST)
  await page.goto(`/?view=research&agent=${RUN}`)
  await page.getByRole('button', {name: 'Compare these →'}).click()
  await expect(page).toHaveURL(/\?view=research$/)
  await expect(page.getByRole('list', {name: 'Picked companies'}).getByRole('listitem')).toHaveCount(3)
  await expect(page.getByLabel('Your question')).toHaveValue('Compare Microsoft Corp (MSFT), Nvidia Corp (NVDA) and Apple Inc. (AAPL) on profitability, growth, valuation and risks.')
  await expect(page.getByRole('status').filter({hasText: 'side-by-side comparison'})).toContainText('You picked 3 companies')
  await expect(page.locator('.starter', {hasText: 'Compare a few'})).toHaveAttribute('aria-pressed', 'true')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.getByRole('button', {name: 'Remove Nvidia Corp'}).click()
  await page.getByRole('button', {name: 'Remove Apple Inc.'}).click()
  await expect(page.getByRole('status').filter({hasText: 'side-by-side comparison'})).toHaveCount(0) // one company: a check
  await expect(page.locator('.starter', {hasText: 'Check one company'})).toHaveAttribute('aria-pressed', 'true')
})

test('picking a second company says the question is now a comparison', async ({page}) => {
  const companies = {AAPL: {cik: '0000320193', name: 'Apple Inc.', tickers: ['AAPL'], exchanges: ['Nasdaq']}, MSFT: {cik: '0000789019', name: 'MICROSOFT CORP', tickers: ['MSFT'], exchanges: ['Nasdaq']}}
  await page.route('**/api/companies?*', route => { const q = new URL(route.request().url()).searchParams.get('q')!.toUpperCase() as 'AAPL' | 'MSFT'; return route.fulfill({json: {items: [companies[q]], total: 1}}) })
  await page.goto('/')
  const search = page.getByRole('combobox', {name: 'Companies'})
  for (const ticker of ['AAPL', 'MSFT']) {
    await search.fill(ticker)
    await page.getByRole('listbox', {name: 'Matching companies'}).getByRole('option').first().click()
  }
  await expect(page.getByRole('status').filter({hasText: 'side-by-side comparison'})).toContainText('You picked 2 companies')
  await expect(page.getByLabel('Your question')).toHaveValue(/^Compare Apple Inc\. \(AAPL\) and Microsoft Corp \(MSFT\)/)
})

test('Find offers the full S&P 500 and every SEC filer, which says why when SEC is not set up', async ({page}) => {
  await page.goto('/')
  await page.locator('.starter', {hasText: 'Find companies'}).click()
  const where = page.getByRole('group', {name: 'Where to look'})
  await expect(where.getByRole('radio', {name: /^S&P 500 500 companies/})).toBeChecked()
  await expect(where).toContainText('survivorship bias')
  const everyone = where.getByRole('radio', {name: /Every SEC filer with a ticker/})
  await expect(everyone).toBeDisabled() // the test server has no SEC_USER_AGENT
  await expect(where).toContainText('SEC_USER_AGENT')
})
