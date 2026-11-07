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
  await expect(page.locator('.starter', {hasText: 'Companies I already know'})).toHaveAttribute('aria-pressed', 'true')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.getByRole('button', {name: 'Remove Nvidia Corp'}).click()
  await page.getByRole('button', {name: 'Remove Apple Inc.'}).click()
  await expect(page.getByRole('status').filter({hasText: 'side-by-side comparison'})).toHaveCount(0) // one company: a check
  await expect(page.getByLabel('Your question')).toHaveValue(/^For Microsoft Corp \(MSFT\), explain/)
  await expect(page.locator('.starter', {hasText: 'Companies I already know'})).toHaveAttribute('aria-pressed', 'true')
})

test('a comparison is filed under its Discover run only while its question comes from the shortlist', async ({page}) => {
  const sent: Record<string, unknown>[] = []
  await page.route('**/api/agent-runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    sent.push(route.request().postDataJSON())
    return route.fulfill({status: 202, json: {run_id: RUN, status: 'running'}})
  })
  await mockRun(page, {question: 'Find profitable tech companies.'}, SHORTLIST)
  const research = page.getByRole('button', {name: 'Research this question →'})
  async function compareThen(change: () => Promise<unknown>) {
    await page.goto(`/?view=research&agent=${RUN}`)
    await page.getByRole('button', {name: 'Compare these →'}).click()
    await change()
    await research.click()
    await expect(page).toHaveURL(/agent=/)
  }
  await compareThen(async () => {})
  await compareThen(() => page.getByRole('button', {name: 'Remove Apple Inc.'}).click())
  await compareThen(() => page.getByRole('button', {name: 'Compare NVIDIA and AMD on growth and valuation.'}).click())
  await compareThen(async () => {
    await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
    await page.locator('.starter', {hasText: 'Companies I already know'}).click()
  })
  expect(sent.map(body => body.parent_run_id)).toEqual([RUN, undefined, undefined, undefined])
})

const COMPANIES = {AAPL: {cik: '0000320193', name: 'Apple Inc.', tickers: ['AAPL'], exchanges: ['Nasdaq']}, MSFT: {cik: '0000789019', name: 'MICROSOFT CORP', tickers: ['MSFT'], exchanges: ['Nasdaq']}}
async function pickCompanies(page: import('@playwright/test').Page, tickers: (keyof typeof COMPANIES)[]) {
  await page.route('**/api/companies?*', route => { const q = new URL(route.request().url()).searchParams.get('q')!.toUpperCase() as keyof typeof COMPANIES; return route.fulfill({json: {items: [COMPANIES[q]], total: 1}}) })
  const search = page.getByRole('combobox', {name: 'Companies'})
  for (const ticker of tickers) {
    await search.fill(ticker)
    await page.getByRole('listbox', {name: 'Matching companies'}).getByRole('option').first().click()
  }
}

test('picking a second company says the question is now a comparison', async ({page}) => {
  await page.goto('/')
  await pickCompanies(page, ['AAPL', 'MSFT'])
  await expect(page.getByRole('status').filter({hasText: 'side-by-side comparison'})).toContainText('You picked 2 companies')
  await expect(page.getByLabel('Your question')).toHaveValue(/^Compare Apple Inc\. \(AAPL\) and Microsoft Corp \(MSFT\)/)
  await page.getByRole('group', {name: 'Topics to cover'}).getByRole('button', {name: /^vs peers/}).click()
  await expect(page.getByLabel('Your question')).toHaveValue(/ on how each ranks among its peers\.$/)
})

test('three starter cards, and topic chips that say what each covers', async ({page}) => {
  await page.goto('/')
  await expect(page.locator('.starter')).toHaveText([/^Companies I already know/, /^Find companies by my criteria/, /^Not sure\? Guide me/])
  const topics = page.getByRole('group', {name: 'Topics to cover'})
  await expect(topics.getByRole('button')).toHaveText([/^profitability/, /^growth/, /^cash flow/, /^debt/, /^valuation/, /^vs peers/, /^risks/, /^insider trades/, /^recent events/])
  await expect(topics.getByRole('button', {name: /^insider trades/})).toContainText('directors and officers bought or sold shares')
  await pickCompanies(page, ['AAPL'])
  await expect(page.locator('.starter', {hasText: 'Companies I already know'})).toHaveAttribute('aria-pressed', 'true')
  for (const name of [/^debt/, /^vs peers/]) await topics.getByRole('button', {name}).click()
  const question = page.getByLabel('Your question')
  await expect(question).toHaveValue('For Apple Inc. (AAPL), explain how much long-term debt it carries and how it compares with its peers.')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  // Find keeps every chip in place but greys out what the screen can't check, and says so.
  await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
  await expect(topics.getByRole('button')).toHaveCount(9)
  const off = topics.locator('button:disabled')
  await expect(off).toHaveText([/^debt/, /^vs peers/, /^insider trades/, /^recent events/])
  for (const chip of await off.all()) await expect(chip).toContainText("Find can't check this yet.")
  await expect(topics.getByRole('button', {name: /^debt/})).toHaveAttribute('aria-pressed', 'false') // picked before, not used by Find
  await expect(topics.getByRole('button', {name: /^risks/})).toContainText('has not jumped around much')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await topics.getByRole('button', {name: /^cash flow/}).click()
  await expect(question).toHaveValue('Find companies among S&P 500 with strong free cash flow.')
})

test('Find offers the full S&P 500 and every SEC filer, which says why when SEC is not set up', async ({page}) => {
  await page.goto('/')
  await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
  const where = page.getByRole('group', {name: 'Where to look'})
  await expect(where.getByRole('radio', {name: /^S&P 500 500 companies/})).toBeChecked()
  await expect(where).toContainText('survivorship bias')
  const everyone = where.getByRole('radio', {name: /Every SEC filer with a ticker/})
  await expect(everyone).toBeDisabled() // the test server has no SEC_USER_AGENT
  await expect(where).toContainText('SEC_USER_AGENT')
})

test('an edited Find question shows the list and count that will run, and the count is sent', async ({page}) => {
  let body: Record<string, unknown> = {}
  await page.route('**/api/agent-runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    body = route.request().postDataJSON()
    return route.fulfill({status: 202, json: {run_id: RUN, status: 'running'}})
  })
  await mockRun(page, {status: 'running', question: 'Find cheap companies.'}, null)
  await page.goto('/')
  await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
  await page.getByLabel('How many to return (optional)').fill('7')
  const question = page.getByLabel('Your question')
  await expect(question).toHaveValue('Find 7 companies among S&P 500.')
  await expect(page.locator('.will-screen')).toHaveCount(0) // the built question already says it
  await question.fill('Find cheap companies.')
  await expect(page.locator('.will-screen')).toHaveText('Will screen: S&P 500, return 7.')
  await page.getByRole('button', {name: 'Find companies →'}).click()
  await expect.poll(() => body.top_k).toBe(7)
  expect(body.discover).toEqual({name: 'sp500'})
  expect(body.question).toBe('Find cheap companies.')
})

test('a shortlist shows a pick\'s warnings and citations, and why the search ended', async ({page}) => {
  const flagged = {...pick(1, '0000789019', 'MICROSOFT CORP', ['MSFT']), answer: 'Microsoft made 280 billion dollars.', citations: ['fact-rev'],
    warnings: ["'280' is typed, not a {fact:ID}/{calc:ID} placeholder"], run_status: 'finished'}
  const discover = {...SHORTLIST.discover, candidates: [flagged], notes: ['Stopped at the research limit: 3 research runs.']}
  await mockRun(page, {question: 'Find profitable tech companies.'}, {...SHORTLIST, discover})
  await page.goto(`/?view=research&agent=${RUN}`)
  const shortlist = page.locator('.shortlist').first()
  await expect(shortlist.getByRole('note')).toContainText("'280' is typed")
  await expect(shortlist).toContainText('Its answer cites fact-rev.')
  await expect(page.getByRole('heading', {name: 'How the search ended'})).toBeVisible()
  await expect(page.getByText('Stopped at the research limit: 3 research runs.')).toBeVisible()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
})
