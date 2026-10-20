import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import path from 'node:path'
import fs from 'node:fs'

const evidenceDir = path.resolve('../verification')
fs.mkdirSync(evidenceDir, {recursive: true})

test('research, source, correction, keyboard and refresh retain the same saved run', async ({page}) => {
  const errors: string[] = []
  let submissions = 0
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) errors.push(message.text())})
  page.on('request', request => {if (request.method() === 'POST') submissions++})
  await page.goto('/?view=research&run=example-msft')
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await expect(page.getByText('SYNTHETIC TEACHING DATA', {exact: true})).toBeVisible()
  await expect(page.getByText('Annual operating margin is 3.0%.', {exact: true})).toBeVisible()
  await expect(page.getByText('Annual operating margin is 15.0% for 2024-01-01 – 2024-12-31.', {exact: true})).toHaveCount(2)
  const citation = page.getByRole('button', {name: 'Inspect evidence 1: fixture-MSFT-annual'}).first()
  await citation.click()
  await expect(page.getByRole('heading', {name: 'Evidence inspector', exact: true})).toBeFocused()
  await expect(page.locator('.excerpt')).toContainText('USD 15,000,000')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.keyboard.press('Control+Home')
  await page.screenshot({path: path.join(evidenceDir, 'desktop-research.png'), fullPage: true})
  await page.getByRole('button', {name: 'Close evidence inspector'}).click()
  await expect(citation).toBeFocused()
  await page.reload()
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', {name: 'Skip to research'})).toBeFocused()
  await page.keyboard.press('Enter')
  expect(submissions).toBe(0)
  expect(errors).toEqual([])
})

test('discovery includes exclusions and unknowns, sorts, opens candidate and history', async ({page}) => {
  await page.goto('/?view=discovery&run=example-discovery')
  await expect(page.getByRole('heading', {name: 'Find a candidate. Inspect the reason.'})).toBeVisible()
  const nvidia = page.getByRole('row').filter({hasText: 'NVDA'})
  await expect(nvidia).toContainText('unknown')
  await expect(nvidia).toContainText('Unavailable')
  await expect(page.getByRole('row').filter({hasText: 'AMZN'})).toContainText('below the required threshold')
  await page.getByRole('button', {name: 'Annual margin ↕'}).click()
  await expect(page.locator('tbody tr').first()).toContainText('GOOGL')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.screenshot({path: path.join(evidenceDir, 'desktop-discovery.png'), fullPage: true})
  await page.getByRole('button', {name: 'Inspect Microsoft research'}).click()
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await page.getByRole('button', {name: 'Back to screening results'}).click()
  await expect(page.getByRole('table')).toBeVisible()
  await page.getByRole('button', {name: 'History', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'Saved investigations'})).toBeVisible()
  await page.locator('.history-row').filter({hasText: 'MSFT'}).first().click()
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
})

test('mobile reflows source content and honours reduced motion', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844})
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.goto('/?view=research&run=example-msft')
  await page.getByRole('button', {name: 'Inspect evidence 1: fixture-MSFT-annual'}).first().click()
  await expect(page.locator('.excerpt')).toContainText('SYNTHETIC TEACHING DATA')
  const layout = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, sourcePosition: getComputedStyle(document.querySelector('.evidence-panel')!).position, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches}))
  expect(layout).toEqual({width: 390, scrollWidth: 390, sourcePosition: 'static', reduced: true})
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.keyboard.press('Control+Home')
  await page.screenshot({path: path.join(evidenceDir, 'mobile-research.png'), fullPage: true})
  await page.getByRole('button', {name: 'Close evidence inspector'}).click()
  await expect(page.getByRole('button', {name: 'Inspect evidence 1: fixture-MSFT-annual'}).first()).toBeFocused()
})

test('missing model produces a saved partial result and history reopens it', async ({page}) => {
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Run mode').selectOption('frozen')
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page).toHaveURL(/run=[0-9a-f-]{36}/)
  await expect(page.getByRole('alert')).toContainText('model review is unavailable', {timeout: 15000})
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await expect(page.locator('.metric').filter({hasText: 'Operating margin'})).toContainText('15%')
  await expect(page.getByText('No claim-specific review is recorded.')).toBeVisible()
  const url = page.url()
  await page.screenshot({path: path.join(evidenceDir, 'partial-result.png'), fullPage: true})
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('model review is unavailable')
  expect(page.url()).toBe(url)
  await page.getByRole('button', {name: 'History', exact: true}).click()
  await page.locator('.history-row').filter({hasText: 'failed'}).first().click()
  await expect(page.getByRole('alert')).toContainText('model review is unavailable')
})

test('fresh retrieval configuration failure is explicit; empty and invalid run states recover', async ({page}) => {
  await page.goto('/?view=research')
  await expect(page.getByRole('heading', {name: 'Start with a question and a source.'})).toBeVisible()
  await page.screenshot({path: path.join(evidenceDir, 'empty-state.png')})
  await page.getByLabel('Run mode').selectOption('fresh')
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page.getByRole('alert')).toContainText('SEC_USER_AGENT', {timeout: 15000})
  await page.goto('/?view=research&run=missing-run')
  await expect(page.getByRole('alert')).toContainText('Run not found')
  await page.screenshot({path: path.join(evidenceDir, 'error-state.png')})
  await page.getByRole('button', {name: 'Research', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'Start with a question and a source.'})).toBeVisible()
})

test('an accepted submission with a lost response retries with the same idempotency key after refresh', async ({page, request}) => {
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Run mode').selectOption('frozen')
  const keys: string[] = []
  let dropped = false
  await page.route('**/api/runs', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'])
    if (!dropped) {dropped = true; await route.fetch(); return route.abort('connectionfailed')}
    return route.continue()
  })
  const before = (await (await request.get('/api/runs')).json()).total
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page.getByRole('alert')).toContainText('Connection interrupted')
  await page.reload()
  await expect(page.getByRole('button', {name: 'Retry pending submission'})).toBeVisible()
  await page.getByRole('button', {name: 'Retry pending submission'}).click()
  await expect(page).toHaveURL(/run=[0-9a-f-]{36}/)
  expect(keys.length).toBe(2)
  expect(keys[0]).toBe(keys[1])
  expect((await (await request.get('/api/runs')).json()).total).toBe(before + 1)
})

test('loading, live progress and reconnect preserve run identity without submission', async ({page, request}) => {
  const run = await (await request.get('/api/runs/example-msft')).json()
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => {release = resolve})
  let polls = 0
  let posts = 0
  page.on('request', request => {if (request.method() === 'POST') posts++})
  await page.route('**/api/runs/example-msft', async route => {
    polls++
    // Initial report and saved-packet selector each read this run; fail the subsequent status poll.
    if (polls <= 2) {await gate; return route.fulfill({json: {...run, status: 'running', stage: 'Checking aligned annual periods'}})}
    if (polls === 3) return route.abort('connectionfailed')
    return route.fulfill({json: run})
  })
  await page.goto('/?view=research&run=example-msft')
  await expect(page.getByText('Loading the saved investigation…')).toBeVisible()
  await page.screenshot({path: path.join(evidenceDir, 'loading-state.png')})
  release!()
  await expect(page.getByText('Checking aligned annual periods', {exact: true})).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Connection interrupted', {timeout: 12000})
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await page.getByRole('button', {name: 'Retry connection'}).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  expect(posts).toBe(0)
})

test('untrusted evidence renders as text and long content stays inside viewport', async ({page, request}) => {
  const evidence = await (await request.get('/api/runs/example-msft/evidence/fixture-MSFT-annual')).json()
  await page.route('**/api/runs/example-msft/evidence/*', route => route.fulfill({json: {...evidence, excerpt: '<img src=x onerror="window.injected=true">' + 'LongSourceIdentifier'.repeat(40), source_url: 'javascript:alert(1)'}}))
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/?view=research&run=example-msft')
  await page.getByRole('button', {name: 'Inspect evidence 1: fixture-MSFT-annual'}).first().click()
  await expect(page.locator('.excerpt')).toContainText('<img src=x')
  await expect(page.locator('.excerpt img')).toHaveCount(0)
  await expect(page.getByRole('link', {name: 'Open original SEC endpoint'})).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})
