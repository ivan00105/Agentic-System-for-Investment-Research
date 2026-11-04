import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockRun, RUN, summary } from './agent-fixtures'

const CHEAP = {term: 'cheap', definition: 'P/E below 15', question: 'What P/E counts as cheap?', options: [
  {definition: 'P/E below 15', recommended: true}, {definition: 'P/E below 25', recommended: false}, {definition: 'P/S below 3', recommended: false}]}
const LARGE = {term: 'large', definition: 'market cap of at least $10 billion', question: 'What counts as large?', options: []}

async function waitingWith(page: import('@playwright/test').Page, terms: object[]) {
  await mockRun(page, {status: 'waiting', questions: {terms, shown: ['Universe: your list, 3 companies']}}, null)
  const sent: unknown[] = []
  await page.route(`**/api/agent-runs/${RUN}/answers`, route => { sent.push(route.request().postDataJSON()); return route.fulfill({json: {...summary, status: 'running'}}) })
  await page.goto(`/?view=research&agent=${RUN}`)
  return sent
}

test('a vague term offers concrete choices, the recommended one picked, plus Other', async ({page}) => {
  const sent = await waitingWith(page, [CHEAP, LARGE])
  const cheap = page.getByRole('group', {name: '"cheap"'})
  await expect(cheap.getByRole('radio', {name: 'P/E below 15 (recommended)'})).toBeChecked()
  await expect(cheap.getByRole('radio')).toHaveCount(4)
  await expect(page.getByRole('group', {name: '"large"'}).getByLabel('Your meaning (leave empty to accept)')).toBeVisible() // no options: a text box, as before
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await cheap.getByRole('radio', {name: 'P/E below 25'}).check()
  await page.getByRole('button', {name: 'Screen with these meanings →'}).click()
  await expect.poll(() => sent).toEqual([{answers: {cheap: 'P/E below 25', large: ''}}])
})

test('Other takes the user\'s own words, and left empty keeps the recommended one', async ({page}) => {
  const sent = await waitingWith(page, [CHEAP])
  const cheap = page.getByRole('group', {name: '"cheap"'})
  await cheap.getByRole('radio', {name: 'Other'}).check()
  await cheap.getByLabel('Your meaning (leave empty to keep the recommended one)').fill('P/E below 12')
  await page.getByRole('button', {name: 'Screen with these meanings →'}).click()
  await expect.poll(() => sent).toEqual([{answers: {cheap: 'P/E below 12'}}])
  await page.reload() // a fresh form: Other chosen, its box left empty
  await cheap.getByRole('radio', {name: 'Other'}).check()
  await page.getByRole('button', {name: 'Screen with these meanings →'}).click()
  await expect.poll(() => sent.length).toBe(2)
  expect(sent[1]).toEqual({answers: {cheap: ''}})
})
