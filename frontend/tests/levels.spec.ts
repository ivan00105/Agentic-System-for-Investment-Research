import { expect, test } from '@playwright/test'
import { mockRun, REPORT, RUN, summary } from './agent-fixtures'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'

test('the detail level changes how runs are shown, never what they do', async ({page}) => {
  await page.goto('/')
  const level = page.getByLabel('Detail level')
  await expect(level).toHaveValue('standard')
  await expect(page.locator('.agent-options')).not.toHaveAttribute('open', '')
  await level.selectOption('professional')
  await expect(page.locator('.agent-options')).toHaveAttribute('open', '')
  await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
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

test('guide me turns four choices into a Find question and a note the run keeps', async ({page}) => {
  await page.goto('/')
  await page.getByLabel('Detail level').selectOption('beginner')
  await page.reload()
  const guided = page.getByRole('form', {name: 'Guide me'})
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
  await expect(page.locator('.starter', {hasText: 'Find companies by my criteria'})).toHaveAttribute('aria-pressed', 'true')
  // The answers turned on chips, so changing a chip changes the question.
  const topics = page.getByRole('group', {name: 'Topics to cover'})
  await expect(topics.locator('[aria-pressed=true]')).toHaveText([/^cash flow/, /^risks/])
  await topics.getByRole('button', {name: /^growth/}).click()
  await expect(question).toHaveValue(/ in health care with strong free cash flow, steady share prices and growing revenue\.$/)
  // Your own words win; the built question is one click away.
  const built = await question.inputValue()
  await question.fill('Find steady health care companies.')
  await page.getByRole('button', {name: 'Use the question built from your choices'}).click()
  await expect(question).toHaveValue(built)
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
  await expect(page.getByRole('form', {name: 'Guide me'}).getByRole('radio', {name: /^Dividends/})).toBeChecked()
  await page.getByRole('button', {name: /^Not sure\? Guide me/}).click()
  await expect(page.getByRole('form', {name: 'Guide me'})).toHaveCount(0)
})

test('sources from the newer data tools get their own groups, and only known sites are linked', async ({page}) => {
  const sources = [...REPORT.sources,
    {n: 3, id: 'insider-1', text: 'Doe Jane (director): purchase of 1000 shares', url: 'https://www.sec.gov/Archives/edgar/data/1/1/form4.xml', kind: 'insider', group: 'Insider trades', label: 'Form 4 purchase 2026-09-30'},
    {n: 4, id: 'fact-rate', text: 'tbill_3m = 4.0%', url: 'https://fred.stlouisfed.org/series/DTB3', kind: 'fact', group: 'Reported figures', label: '3-month T-bill rate 2026'},
    {n: 5, id: 'mystery-1', text: 'A kind this page has never seen', url: 'https://example.com/x', kind: 'mystery', group: 'Something new', label: 'Mystery record'}]
  await mockRun(page, {}, {...REPORT, sources})
  await page.goto(`/?view=research&agent=${RUN}`)
  const group = (name: string) => page.locator('.source-group').filter({has: page.locator('summary', {hasText: name})})
  for (const name of ['Reported figures', 'Insider trades', 'Other']) await group(name).locator('summary').click()
  await expect(group('Insider trades').getByRole('link', {name: 'SEC.gov ↗'})).toBeVisible()
  await expect(group('Reported figures').getByRole('link', {name: 'FRED ↗'})).toHaveAttribute('href', 'https://fred.stlouisfed.org/series/DTB3')
  // An unknown group is listed under Other, never dropped, and a link to an unknown site stays text.
  await expect(group('Other')).toContainText('Mystery record')
  await expect(group('Other').getByRole('link')).toHaveCount(0)
})
