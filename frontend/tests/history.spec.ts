import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockRun, REPORT, RUN, summary } from './agent-fixtures'

const DISCOVER = '20261107-100000-aaaaaa'
const BRIEF = 'Explain whether Apple Inc. (AAPL, CIK 0000320193) fits this request, and where it doesn\'t: "Find large, profitable tech companies."\n\nIt is shortlist pick 1 of the 3 asked for.'
const LONG = 'Find large, profitable tech companies at a reasonable valuation, with revenue growing for three years, low debt, steady margins and a share price that has not swung much over the past year, among the S&P 500.'
const run = (run_id: string, title: string, more: object = {}) => ({...summary, run_id, title, question: title, archived: false, children: [], ...more})
const pick = (n: number, run_id: string, name: string) => run(run_id, `Pick ${n} of 3: ${name}`, {question: BRIEF, kind: 'pick', condition: 'B (single agent)'})
const TREE = [
  run(DISCOVER, LONG, {condition: 'Discover (B (single agent))', children: [pick(1, RUN, 'Apple Inc. (AAPL)'), pick(2, '20261107-100200-cccccc', 'NVIDIA CORP (NVDA)'), pick(3, '20261107-100300-dddddd', 'Alphabet Inc. (GOOGL)'),
    run('20261107-110000-eeeeee', 'Compare Apple and NVIDIA on growth.', {kind: 'comparison'})]}),
  run('20261106-090000-ffffff', 'Who is Apple?'),
]

async function mockHistory(page: Page, items: object[] = TREE, archived: object[] = []) {
  await page.route('**/api/agent-runs?archived=*', route => route.fulfill({json: {items: route.request().url().endsWith('archived=true') ? archived : items}}))
}

test('History nests a Discover run\'s picks and comparison under it, folded, with short titles', async ({page}) => {
  await mockHistory(page)
  await page.goto('/?view=history')
  const entries = page.locator('.agent-history .history-list > .history-entry')
  await expect(entries).toHaveCount(2) // the picks aren't listed at the top level
  const discover = entries.first()
  const title = discover.locator('.agent-history-question').first()
  await expect(title).toHaveText(LONG) // the whole text is there; CSS clamps it to two lines
  expect(await title.evaluate(el => getComputedStyle(el).webkitLineClamp)).toBe('2')
  const children = discover.locator('details.run-children')
  await expect(children.locator('summary')).toHaveText('3 picks · 1 comparison')
  await expect(children.getByText('Pick 2 of 3: NVIDIA CORP (NVDA)')).toBeHidden()
  await children.locator('summary').click()
  await expect(children.locator('li .agent-history-question')).toHaveText(['Pick 1 of 3: Apple Inc. (AAPL)', 'Pick 2 of 3: NVIDIA CORP (NVDA)', 'Pick 3 of 3: Alphabet Inc. (GOOGL)', 'Compare Apple and NVIDIA on growth.'])
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await mockRun(page, {title: 'Pick 1 of 3: Apple Inc. (AAPL)', question: BRIEF, kind: 'pick'}, {...REPORT, title: 'Pick 1 of 3: Apple Inc. (AAPL)', question: BRIEF, kind: 'pick'})
  await children.locator(`li[data-run-id="${RUN}"]`).getByRole('button', {name: 'Open ↗'}).click()
  await expect(page.getByRole('heading', {level: 2, name: 'Pick 1 of 3: Apple Inc. (AAPL)'})).toBeVisible()
  const brief = page.locator('details.run-brief')
  await expect(brief).not.toHaveAttribute('open') // a pick's brief is long, so it starts folded
  await brief.locator('summary').click()
  await expect(brief).toContainText('It is shortlist pick 1 of the 3 asked for.')
})

test('a labelled run shows its label as the heading and the full question under it', async ({page}) => {
  await mockRun(page, {title: 'My Acme check', label: 'My Acme check'})
  await page.goto(`/?view=research&agent=${RUN}`)
  await expect(page.getByRole('heading', {level: 2, name: 'My Acme check'})).toBeVisible()
  await expect(page.locator('p.run-brief')).toHaveText('How profitable is Acme?')
})

test('Compare these files the comparison under its Discover run', async ({page}) => {
  const picked = (rank: number, cik: string, name: string, ticker: string) => ({rank, cik, name, tickers: [ticker], outcome: 'picked', verdict: 'pass', run_id: null, lines: [], answer: null})
  const shortlist = {...REPORT, sections: [], question: 'Find tech.', discover: {spec: [], counts: {}, candidates: [picked(1, '0000320193', 'Apple Inc.', 'AAPL'), picked(2, '0001045810', 'NVIDIA CORP', 'NVDA')]}}
  await mockRun(page, {question: 'Find tech.'}, shortlist)
  let body: Record<string, unknown> = {}
  await page.route('**/api/agent-runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    body = route.request().postDataJSON()
    return route.fulfill({status: 202, json: {run_id: RUN, status: 'running'}})
  })
  await page.goto(`/?view=research&agent=${RUN}`)
  await page.getByRole('button', {name: 'Compare these →'}).click()
  await page.getByRole('button', {name: 'Research this question →'}).click()
  await expect.poll(() => body.parent_run_id).toBe(RUN)
})

// History's server for the manage tests: PATCH and DELETE change the list it serves next, as the real one does.
async function manageable(page: Page) {
  let items = structuredClone(TREE) as {run_id: string; title: string; label?: string | null; archived: boolean; children: {run_id: string}[]}[]
  const sent: {method: string; url: string; body: unknown}[] = []
  await page.route('**/api/agent-runs?archived=*', route => route.fulfill({json: {items: items.filter(i => i.archived === route.request().url().endsWith('true'))}}))
  await page.route('**/api/agent-runs/*', route => {
    const request = route.request(), url = new URL(request.url()), id = url.pathname.split('/').pop()!
    if (request.method() === 'GET') return route.continue()
    sent.push({method: request.method(), url: url.pathname + url.search, body: request.postDataJSON()})
    const found = items.find(i => i.run_id === id)!
    if (request.method() === 'PATCH') { Object.assign(found, request.postDataJSON()); if ('label' in request.postDataJSON()) found.title = found.label ?? LONG }
    else items = items.filter(i => i.run_id !== id)
    return route.fulfill({json: request.method() === 'PATCH' ? found : {deleted: [id]}})
  })
  return sent
}

test('a run can be renamed, archived and restored; the filter shows archived runs apart', async ({page}) => {
  const sent = await manageable(page)
  await page.goto('/?view=history')
  const discover = page.locator(`.history-entry[data-run-id="${DISCOVER}"]`)
  await discover.locator('.history-actions').first().getByRole('button', {name: 'Add label'}).click()
  await discover.getByLabel('Label').fill('Tech screen')
  await discover.getByRole('button', {name: 'Save'}).click()
  await expect(discover.locator('.agent-history-question').first()).toHaveText('Tech screen')
  expect(sent.at(-1)).toEqual({method: 'PATCH', url: `/api/agent-runs/${DISCOVER}`, body: {label: 'Tech screen'}})
  await expect(discover.locator('li').first().getByRole('button', {name: 'Archive'})).toHaveCount(0) // a pick goes with its parent
  await discover.locator('.history-actions').first().getByRole('button', {name: 'Archive'}).click()
  await expect(page.locator('.agent-history .history-list > .history-entry')).toHaveCount(1)
  await page.getByLabel('Show').selectOption('archived')
  const archived = page.locator(`.history-entry[data-run-id="${DISCOVER}"]`)
  await expect(archived.locator('.run-children summary')).toHaveText('3 picks · 1 comparison')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await archived.locator('.history-actions').first().getByRole('button', {name: 'Restore'}).click()
  await expect(page.getByText('No archived runs.', {exact: false})).toBeVisible()
  expect(sent.at(-1)).toEqual({method: 'PATCH', url: `/api/agent-runs/${DISCOVER}`, body: {archived: false}})
})

test('delete asks first, says it can\'t be undone, and offers to delete a parent\'s children too', async ({page}) => {
  const sent = await manageable(page)
  await page.goto('/?view=history')
  const other = page.locator('.history-entry[data-run-id="20261106-090000-ffffff"]')
  await other.getByRole('button', {name: 'Delete'}).click()
  await expect(other.getByRole('group', {name: 'Confirm delete'})).toContainText("This can't be undone")
  await other.getByRole('button', {name: 'Cancel'}).click()
  expect(sent).toEqual([])
  const discover = page.locator(`.history-entry[data-run-id="${DISCOVER}"]`)
  await discover.locator('.history-actions').first().getByRole('button', {name: 'Delete'}).click()
  const confirm = discover.getByRole('group', {name: 'Confirm delete'})
  await expect(confirm).toContainText('It started 3 picks · 1 comparison.')
  await expect(confirm.getByRole('button', {name: 'Delete only this run'})).toBeVisible()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await confirm.getByRole('button', {name: 'Delete it and its 4 runs'}).click()
  await expect(discover).toHaveCount(0)
  expect(sent).toEqual([{method: 'DELETE', url: `/api/agent-runs/${DISCOVER}?children=true`, body: null}])
})

test('a run still going cannot be deleted from History', async ({page}) => {
  await mockHistory(page, [run(RUN, 'How profitable is Acme?', {status: 'running'})])
  await page.goto('/?view=history')
  await expect(page.locator(`.history-entry[data-run-id="${RUN}"]`).getByRole('button', {name: 'Delete'})).toBeDisabled()
})
