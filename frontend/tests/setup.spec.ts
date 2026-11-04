import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import path from 'node:path'
import fs from 'node:fs'

const evidenceDir = path.resolve(process.env.FIELDNOTE_VERIFICATION_DIR ?? '../verification')
fs.mkdirSync(evidenceDir, {recursive: true})

const card = (page: Page, name: string) => page.getByRole('region', {name})
const row = (region: Locator, label: string) => region.getByRole('listitem').filter({has: region.page().locator('strong').getByText(label, {exact: true})})

// A small /api/status reply: Tiingo and OpenRouter configured, OpenRouter's last check failed.
function kinds(tiingoCheck: {ok: boolean; message: string; checked_at: string} | null = null) {
  const provider = (name: string, label: string, tier: number, env: string[], extra = {}) =>
    ({name, label, tier, env, configured: true, missing_env: [], problem: null, status: env.length ? 'configured' : 'ready', last_check: null, can_check: true, ...extra})
  return [
    {kind: 'prices', label: 'Daily prices', purpose: 'Closing prices for market cap, valuation ratios and risk.', active: 'tiingo', providers: [
      provider('tiingo', 'Tiingo', 1, ['TIINGO_API_KEY'], tiingoCheck ? {last_check: tiingoCheck, status: tiingoCheck.ok ? 'configured' : 'check_failed'} : {}),
      provider('yfinance', 'Yahoo Finance (yfinance)', 0, []),
    ]},
    {kind: 'llm', label: 'Model', purpose: 'The language model that writes the report.', active: 'openrouter', providers: [
      provider('openrouter', 'OpenRouter', 2, ['RESEARCH_MODEL_PROVIDER', 'RESEARCH_MODEL', 'OPENROUTER_API_KEY'], {status: 'check_failed',
        last_check: {ok: false, checked_at: '2026-11-04T09:30:00Z', message: '<img src=x onerror="window.injected=true"> Model authentication or access was rejected. (HTTP 401)'}}),
      provider('openai', 'OpenAI', 2, ['RESEARCH_MODEL', 'OPENAI_API_KEY'], {configured: false, status: 'not_configured', missing_env: ['RESEARCH_MODEL_PROVIDER=openai', 'OPENAI_API_KEY']}),
    ]},
  ]
}

test('with no keys, every kind of data has a card that names the variables to set', async ({page}) => {
  const errors: string[] = []
  let posts = 0
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {if (request.method() === 'POST') posts++})
  await page.goto('/?view=research')
  await page.getByRole('button', {name: 'Setup & status', exact: true}).click()
  await expect(page).toHaveURL(/view=setup/)
  await expect(page.getByRole('heading', {name: 'Setup & status', exact: true})).toBeVisible()
  for (const name of ['SEC filings', 'Fundamentals', 'Company lookup', 'Daily prices', 'Model']) await expect(card(page, name)).toBeVisible()
  await expect(page.locator('.setup-summary')).toContainText('Not ready yet: SEC filings, Fundamentals, Company lookup, Model.')

  const filings = card(page, 'SEC filings')
  await expect(filings.getByText('Nothing active', {exact: true})).toBeVisible()
  const edgar = row(filings, 'SEC EDGAR filings')
  await expect(edgar.getByText('Not configured', {exact: true})).toBeVisible()
  await expect(edgar.locator('.provider-missing code').getByText('SEC_USER_AGENT', {exact: true})).toBeVisible()
  await expect(edgar.getByRole('button', {name: 'Test SEC EDGAR filings'})).toBeDisabled()

  const prices = card(page, 'Daily prices')
  await expect(prices.getByText('Active: Yahoo Finance (yfinance)', {exact: true})).toBeVisible()
  await expect(row(prices, 'Yahoo Finance (yfinance)').getByText('Ready (no key needed)', {exact: true})).toBeVisible()
  await expect(row(prices, 'Tiingo').locator('.provider-missing')).toContainText('TIINGO_API_KEY')
  await expect(row(card(page, 'Model'), 'OpenRouter').locator('.provider-missing')).toContainText('RESEARCH_MODEL_PROVIDER=openrouter')

  // Keys are never typed into the browser, and there is no consent step.
  await expect(page.locator('input, textarea')).toHaveCount(0)
  expect(posts).toBe(0)
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.screenshot({path: path.join(evidenceDir, 'desktop-setup.png'), fullPage: true})

  await page.goto('/?view=connections')
  await expect(page.getByRole('heading', {name: 'Setup & status', exact: true})).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', {name: 'Skip to setup'})).toBeFocused()
  await page.setViewportSize({width: 390, height: 844})
  await expect(card(page, 'Model')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.screenshot({path: path.join(evidenceDir, 'mobile-setup.png'), fullPage: true})
  expect(posts).toBe(0)
  expect(errors).toEqual([])
})

test('statuses read in plain words, and a Test button checks one provider and shows its result', async ({page}) => {
  let reads = 0
  await page.route('**/api/status', route => {reads++; return route.fulfill({json: {kinds: kinds()}})})
  const checks: {url: string; body: unknown}[] = []
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => {release = resolve})
  await page.route('**/api/status/*/check', async route => {
    checks.push({url: route.request().url(), body: route.request().postDataJSON()})
    if (route.request().url().includes('/yfinance/')) return route.fulfill({status: 503, json: {error: {message: 'Yahoo is down.'}}})
    await gate
    return route.fulfill({json: {kinds: kinds({ok: true, message: 'Tiingo accepted the API key.', checked_at: '2026-11-04T10:00:00Z'})}})
  })
  await page.goto('/?view=setup')
  await expect(page.locator('.setup-summary')).toHaveText('Every kind of data has an active provider.')

  const model = card(page, 'Model')
  await expect(model.getByText('Active: OpenRouter', {exact: true})).toBeVisible()
  const openrouter = row(model, 'OpenRouter')
  await expect(openrouter.getByText('Last check failed', {exact: true})).toBeVisible()
  await expect(openrouter.locator('.provider-check')).toContainText('<img src=x')
  await expect(openrouter.locator('img')).toHaveCount(0)
  await expect(openrouter.locator('time')).toHaveText('4 Nov 2026, 09:30 UTC')
  await expect(openrouter).toContainText('may charge a fraction of a cent')
  await expect(openrouter.getByRole('button', {name: 'Test OpenRouter'})).toBeEnabled()
  const openai = row(model, 'OpenAI')
  await expect(openai.getByText('Not configured', {exact: true})).toBeVisible()
  await expect(openai.locator('.provider-missing')).toContainText('RESEARCH_MODEL_PROVIDER=openai, OPENAI_API_KEY')
  await expect(openai.getByRole('button', {name: 'Test OpenAI'})).toBeDisabled()
  await expect(page.getByRole('checkbox')).toHaveCount(0)

  const tiingo = row(card(page, 'Daily prices'), 'Tiingo')
  await expect(tiingo.getByText('Configured', {exact: true})).toBeVisible()
  await tiingo.getByRole('button', {name: 'Test Tiingo'}).click()
  await expect(tiingo.getByRole('button', {name: 'Testing…'})).toBeDisabled()
  await expect(tiingo.getByRole('status')).toHaveText('Waiting for Tiingo…')
  await expect(openrouter.getByRole('button', {name: 'Test OpenRouter'})).toBeDisabled()
  release!()
  await expect(tiingo.locator('.provider-check')).toContainText('Check passed')
  await expect(tiingo.locator('.provider-check')).toContainText('Tiingo accepted the API key.')
  await expect(openrouter.getByRole('button', {name: 'Test OpenRouter'})).toBeEnabled()
  expect(checks).toEqual([{url: expect.stringContaining('/api/status/tiingo/check'), body: {}}])

  await row(card(page, 'Daily prices'), 'Yahoo Finance (yfinance)').getByRole('button', {name: 'Test Yahoo Finance (yfinance)'}).click()
  await expect(page.getByRole('alert')).toHaveText('The test could not run: Yahoo is down.')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  const before = reads
  await page.getByRole('button', {name: 'Refresh status'}).click()
  await expect(page.locator('.setup-summary')).toBeVisible()
  expect(reads).toBe(before + 1)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('a status outage shows an error with a retry, never stale cards', async ({page}) => {
  let reads = 0
  await page.route('**/api/status', route => {
    reads++
    return reads === 1 ? route.fulfill({status: 503, json: {error: {message: 'Internal detail'}}}) : route.fulfill({json: {kinds: kinds()}})
  })
  await page.goto('/?view=setup')
  await expect(page.getByRole('alert')).toContainText('Setup status is unavailable')
  await expect(page.locator('main')).not.toContainText('Internal detail')
  await expect(page.getByRole('region', {name: 'Model'})).toHaveCount(0)
  await page.getByRole('button', {name: 'Retry connection'}).click()
  await expect(card(page, 'Model')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
