import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import path from 'node:path'
import fs from 'node:fs'

const evidenceDir = path.resolve(process.env.FIELDNOTE_VERIFICATION_DIR ?? '../verification')
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
  const citation = page.getByRole('button', {name: 'Inspect evidence 1'}).first()
  await citation.click()
  await expect(page.getByRole('heading', {name: 'Evidence inspector', exact: true})).toBeFocused()
  await expect(page.locator('.excerpt')).toContainText('USD 15,000,000')
  await expect(page.getByLabel('Research action')).toHaveValue('replay')
  await expect(page.getByRole('checkbox', {name: 'Include model analysis (optional)'})).toHaveCount(0)
  await expect(page.getByRole('option', {name: 'Review saved sources again'})).toHaveCount(1)
  await expect(page.locator('.claim-meta').filter({hasText: 'version'})).toHaveCount(0)
  await expect(page.locator('.hash')).toBeHidden()
  await page.getByText('Source details', {exact: true}).click()
  await expect(page.locator('.hash')).toBeVisible()
  await page.getByText('Source details', {exact: true}).click()
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
  await page.locator('.history-row').filter({hasText: 'MSFT'}).first().getByRole('button', {name: 'Open'}).click()
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
})

test('mobile reflows source content and honours reduced motion', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844})
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.goto('/?view=research&run=example-msft')
  await page.getByRole('button', {name: 'Inspect evidence 1'}).first().click()
  await expect(page.locator('.excerpt')).toContainText('SYNTHETIC TEACHING DATA')
  const layout = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, sourcePosition: getComputedStyle(document.querySelector('.evidence-panel')!).position, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches}))
  expect(layout).toEqual({width: 390, scrollWidth: 390, sourcePosition: 'static', reduced: true})
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.keyboard.press('Control+Home')
  await page.screenshot({path: path.join(evidenceDir, 'mobile-research.png'), fullPage: true})
  await page.getByRole('button', {name: 'Close evidence inspector'}).click()
  await expect(page.getByRole('button', {name: 'Inspect evidence 1'}).first()).toBeFocused()
})

test('model analysis defaults off, financial results complete and history reopens them', async ({page}) => {
  const submissions: unknown[] = []
  page.on('request', request => {if (request.method() === 'POST') submissions.push(request.postDataJSON())})
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Research action').selectOption('frozen')
  await expect(page.getByRole('checkbox', {name: 'Include model analysis (optional)'})).not.toBeChecked()
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page).toHaveURL(/run=[0-9a-f-]{36}/)
  await expect(page.locator('.run-state strong')).toHaveText('completed', {timeout: 15000})
  expect(submissions).toHaveLength(1)
  expect(submissions[0]).toMatchObject({model_analysis: false})
  await expect(page.locator('.report-availability')).toContainText('Financial figuresAvailable')
  await expect(page.locator('.report-availability')).toContainText('Model analysisNot requested')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await expect(page.locator('.metric').filter({hasText: 'Operating margin'})).toContainText('15%')
  await expect(page.getByText('SYNTHETIC TEACHING DATA', {exact: true})).toBeVisible()
  await expect(page.getByText('Real source evidence', {exact: true})).toHaveCount(0)
  const url = page.url()
  await page.reload()
  await expect(page.locator('.report-availability')).toContainText('Model analysisNot requested')
  expect(page.url()).toBe(url)
  await page.getByRole('button', {name: 'History', exact: true}).click()
  await page.locator('.history-row').first().getByRole('button', {name: 'Open'}).click()
  expect(page.url()).toBe(url)
  await expect(page.locator('.report-availability')).toContainText('Model analysisNot requested')
})

test('saved reports can be renamed, archived, reopened by link and restored', async ({page, request}) => {
  const source = await (await request.get('/api/runs/example-msft')).json()
  const createdResponse = await request.post('/api/runs', {headers: {'Idempotency-Key': `saved-report-ui-${crypto.randomUUID()}`}, data: {kind: 'research', mode: 'frozen', ticker: 'MSFT', cutoff: source.request.cutoff, source_run_id: source.id, screen: null, model_analysis: false}})
  expect(createdResponse.ok()).toBeTruthy()
  const created = await createdResponse.json()
  const runId = created.id as string
  await expect.poll(async () => (await (await request.get(`/api/runs/${runId}`)).json()).status, {timeout: 20000}).toBe('completed')
  const saved = await (await request.get(`/api/runs/${runId}`)).json()
  expect(saved.report.companies[0].metrics.some((metric: {evidence_ids: string[]}) => metric.evidence_ids.length > 0)).toBeTruthy()
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/?view=history')
  const row = page.locator(`.history-entry[data-run-id="${runId}"]`)
  await expect(row).toBeVisible()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.screenshot({path: path.join(evidenceDir, 'mobile-saved-reports.png'), fullPage: true})
  await row.getByRole('button', {name: 'Add label'}).click()
  await page.getByLabel('Report label').fill('Quarterly evidence review')
  await page.getByRole('button', {name: 'Save', exact: true}).click()
  await expect(row).toContainText('Quarterly evidence review')
  await page.reload()
  await expect(row).toContainText('Quarterly evidence review')
  await row.getByRole('button', {name: 'Archive'}).click()
  await expect(row).toHaveCount(0)
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Research action').selectOption('frozen')
  await expect(page.locator('.source-select option[value="example-msft"]')).toHaveCount(1)
  await expect(page.locator(`.source-select option[value="${runId}"]`)).toHaveCount(0)
  await page.goto(`/?view=research&run=${runId}`)
  await expect(page.locator('.run-banner')).toContainText('Quarterly evidence review')
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
  await page.getByRole('button', {name: 'Inspect evidence 1'}).first().click()
  await expect(page.locator('.excerpt')).toContainText('USD 15,000,000')
  await expect(page).toHaveURL(new RegExp(`view=research&run=${runId}`))
  await page.goto('/?view=history')
  await page.getByLabel('Saved report status').selectOption('archived')
  const archivedRow = page.locator(`.history-entry[data-run-id="${runId}"]`)
  await expect(archivedRow).toBeVisible()
  await archivedRow.getByRole('button', {name: 'Restore'}).click()
  await expect(archivedRow).toHaveCount(0)
  await page.getByLabel('Saved report status').selectOption('active')
  await expect(row).toContainText('Quarterly evidence review')
  await row.getByRole('button', {name: 'Rename'}).click()
  await page.getByLabel('Report label').fill('X'.repeat(120))
  await page.getByRole('button', {name: 'Save', exact: true}).click()
  await expect(row).toContainText('X'.repeat(120))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.goto(`/?view=research&run=${runId}`)
  await expect(page.locator('.run-banner')).toContainText('X'.repeat(120))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.goto('/?view=history')
  await row.getByRole('button', {name: 'Rename'}).click()
  await page.getByLabel('Report label').fill('')
  await page.getByRole('button', {name: 'Save', exact: true}).click()
  await expect(row.getByRole('button', {name: 'Add label'})).toBeVisible()
  expect((await (await request.get(`/api/runs/${runId}`)).json()).label).toBeNull()
})

test('failed saved-report rename preserves the label for retry', async ({page, request}) => {
  const source = await (await request.get('/api/runs/example-msft')).json()
  let patchCount = 0
  let serverLabel: string | null = null
  await page.route('**/api/runs?*', route => route.fulfill({json: {items: [{...source, actions: undefined, report: undefined, label: serverLabel, archived: false}], total: 1}}))
  await page.route('**/api/runs/example-msft', route => {
    if (route.request().method() !== 'PATCH') return route.fulfill({json: source})
    patchCount++
    if (patchCount === 1) return route.fulfill({status: 503, json: {error: {message: 'Temporary save failure'}}})
    serverLabel = route.request().postDataJSON().label
    return route.fulfill({json: {...source, label: serverLabel, archived: false}})
  })
  await page.goto('/?view=history')
  await page.locator('.history-entry').getByRole('button', {name: 'Add label'}).click()
  const input = page.getByLabel('Report label')
  await input.fill('Keep this draft')
  await page.getByRole('button', {name: 'Save', exact: true}).click()
  await expect(page.getByRole('alert')).toContainText('Temporary save failure')
  await expect(input).toHaveValue('Keep this draft')
  await page.getByRole('button', {name: 'Retry'}).click()
  await expect(page.locator('.history-entry')).toContainText('Keep this draft')
  expect(patchCount).toBe(2)
  expect(serverLabel).toBe('Keep this draft')
})

test('opting into unavailable model analysis still completes and saves financial results', async ({page}) => {
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Research action').selectOption('frozen')
  await page.getByRole('checkbox', {name: 'Include model analysis (optional)'}).check()
  await expect(page.locator('.configuration-note')).toContainText('Model analysis is unavailable in this setup')
  const submitted = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/runs'))
  await page.getByRole('button', {name: 'Start research →'}).click()
  expect((await submitted).postDataJSON()).toMatchObject({model_analysis: true})
  await expect(page.locator('.run-state strong')).toHaveText('completed', {timeout: 15000})
  await expect(page.locator('.report-availability')).toContainText('Financial figuresAvailable')
  await expect(page.locator('.report-availability')).toContainText('Model analysisUnavailable')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('.metric').filter({hasText: 'Operating margin'})).toContainText('15%')
  const url = page.url()
  await page.screenshot({path: path.join(evidenceDir, 'model-unavailable.png'), fullPage: true})
  await page.reload()
  await expect(page.locator('.report-availability')).toContainText('Model analysisUnavailable')
  expect(page.url()).toBe(url)
  await page.getByRole('button', {name: 'History', exact: true}).click()
  await page.locator('.history-row').first().getByRole('button', {name: 'Open'}).click()
  expect(page.url()).toBe(url)
  await expect(page.locator('.report-availability')).toContainText('Model analysisUnavailable')
})

test('fresh retrieval configuration failure is explicit; empty and invalid run states recover', async ({page}) => {
  await page.goto('/?view=baseline')
  await expect(page.getByRole('heading', {name: 'Start with a question and a source.'})).toBeVisible()
  await page.screenshot({path: path.join(evidenceDir, 'empty-state.png')})
  await page.getByLabel('Research action').selectOption('fresh')
  await expect(page.getByRole('checkbox', {name: 'Include model analysis (optional)'})).not.toBeChecked()
  await expect(page.locator('.configuration-note')).toContainText('SEC source access is required')
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page.getByRole('alert')).toContainText('SEC source access', {timeout: 15000})
  await expect(page.getByText('SYNTHETIC TEACHING DATA', {exact: true})).toHaveCount(0)
  await expect(page.getByText('Real source evidence', {exact: true})).toHaveCount(0)
  await page.goto('/?view=research&run=missing-run')
  await expect(page.getByRole('alert')).toContainText('Run not found')
  await page.screenshot({path: path.join(evidenceDir, 'error-state.png')})
  await page.getByRole('button', {name: 'Baseline A', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'Start with a question and a source.'})).toBeVisible()
})

test('an accepted submission with a lost response retries with the same idempotency key after refresh', async ({page, request}) => {
  await page.goto('/?view=research&run=example-msft')
  await page.getByLabel('Research action').selectOption('frozen')
  const keys: string[] = []
  const payloads: unknown[] = []
  let dropped = false
  await page.route('**/api/runs', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'])
    payloads.push(route.request().postDataJSON())
    if (!dropped) {dropped = true; await route.fetch(); return route.abort('connectionfailed')}
    return route.continue()
  })
  const before = (await (await request.get('/api/runs')).json()).total
  await page.getByRole('button', {name: 'Start research →'}).click()
  await expect(page.getByRole('alert')).toContainText('Connection interrupted')
  await page.reload()
  await expect(page.getByRole('button', {name: 'Recover request'})).toBeVisible()
  await page.getByRole('button', {name: 'Recover request'}).click()
  await expect(page).toHaveURL(/run=[0-9a-f-]{36}/)
  expect(keys.length).toBe(2)
  expect(keys[0]).toBe(keys[1])
  expect(payloads[0]).toEqual(payloads[1])
  expect(payloads[0]).toMatchObject({model_analysis: false})
  expect((await (await request.get('/api/runs')).json()).total).toBe(before + 1)
})

test('legacy pending submissions retain their original payload and key', async ({page, request}) => {
  const source = await (await request.get('/api/runs/example-msft')).json()
  const legacy = {request: {kind: 'research', mode: 'frozen', ticker: 'MSFT', cutoff: source.request.cutoff, source_run_id: source.id, screen: null}, key: 'legacy-pending-recovery'}
  await page.goto('/?view=baseline')
  await page.evaluate(intent => sessionStorage.setItem('fieldnote-pending', JSON.stringify(intent)), legacy)
  await page.reload()
  const submitted = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/runs'))
  await page.getByRole('button', {name: 'Recover request'}).click()
  const recovered = await submitted
  expect(recovered.postDataJSON()).toEqual(legacy.request)
  expect(recovered.headers()['idempotency-key']).toBe(legacy.key)
  await expect(page).toHaveURL(/run=[0-9a-f-]{36}/)
})

test('report labels distinguish real evidence, missing evidence and legacy or incomplete model analysis', async ({page, request}) => {
  const source = await (await request.get('/api/runs/example-msft')).json()
  const company = source.report.companies[0]
  const cases = [
    {review_status: 'completed', financial: 'Available', model: 'Completed', evidence: true, values: 'all'},
    {review_status: 'pending', financial: 'Available', model: 'Pending', evidence: true, values: 'all', status: 'running'},
    {review_status: 'pending', financial: 'Available', model: 'Not finished', evidence: true, values: 'all', status: 'interrupted'},
    {review_status: 'failed', financial: 'Partly available', model: 'Failed', evidence: true, values: 'some'},
    {review_status: 'unavailable', financial: 'Unavailable', model: 'Unavailable', evidence: false, values: 'none'},
    {review_status: undefined, financial: 'Available', model: 'Not recorded', evidence: true, values: 'all'},
  ]
  for (const item of cases) {
    await page.route('**/api/runs/example-msft', route => route.fulfill({json: {
      ...source, status: item.status ?? source.status, synthetic: false, report: {...source.report, synthetic: false, companies: [{...company,
        review_status: item.review_status, review_error: 'SDK developer-model-id details',
        metrics: company.metrics.map((metric: {value: string | null; evidence_ids: string[]}, index: number) => ({...metric,
          value: item.values === 'none' || (item.values === 'some' && index > 0) ? null : metric.value,
          evidence_ids: item.evidence ? metric.evidence_ids : [],
        })),
      }]},
    }}))
    await page.goto('/?view=research&run=example-msft')
    const availability = page.locator('.report-availability')
    await expect(availability).toContainText(`Financial figures${item.financial}`)
    await expect(availability).toContainText(`Model analysis${item.model}`)
    await expect(page.locator('.run-banner')).toContainText(item.evidence ? 'Real source evidence' : 'No source evidence recorded')
    await expect(page.locator('.report-body')).not.toContainText('SDK developer-model-id')
    await page.unroute('**/api/runs/example-msft')
  }
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
    if (polls <= 2) {await gate; return route.fulfill({json: {...run, status: 'running', stage: 'Using developer-model-id with structured output', actions: [{sequence: 1, at: run.created_at, role: 'Filings interpretation', message: 'Using developer-model-id with structured output'}]}})}
    if (polls === 3) return route.abort('connectionfailed')
    return route.fulfill({json: run})
  })
  await page.goto('/?view=research&run=example-msft')
  await expect(page.getByText('Loading the saved investigation…')).toBeVisible()
  await page.screenshot({path: path.join(evidenceDir, 'loading-state.png')})
  release!()
  await expect(page.getByText('Reviewing the company evidence', {exact: true})).toBeVisible()
  await expect(page.locator('.run-state')).not.toContainText('developer-model-id')
  await expect(page.getByText('Research continues if you leave or refresh. Progress updates automatically.')).toBeVisible()
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
  await page.getByRole('button', {name: 'Inspect evidence 1'}).first().click()
  await expect(page.locator('.excerpt')).toContainText('<img src=x')
  await expect(page.locator('.excerpt img')).toHaveCount(0)
  await expect(page.getByRole('link', {name: 'Open SEC source'})).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('a saved model connection check shows its banner and model usage', async ({page, request}) => {
  const source = await (await request.get('/api/runs/example-msft')).json()
  const real = {...source, id: 'real-saved-source', synthetic: false, request: {...source.request, ticker: 'AAPL'}, report: {...source.report, synthetic: false}}
  const payload = {kind: 'research', mode: 'frozen', ticker: 'AAPL', cutoff: source.request.cutoff, source_run_id: real.id, screen: null, model_analysis: true, connection_check: 'model'}
  let saved = {...real, id: 'mock-model-check', request: payload, report: {...real.report,
    model_run: {provider: 'openrouter', model: 'test/model', schema_version: 'financial-review-v2', max_output_tokens: null},
    model_calls: [{role: 'interpretation', provider: 'openrouter', requested_model: 'test/model', returned_model: 'resolved/model', response_id: 'response-example', input_tokens: 100, output_tokens: 20, total_tokens: 120, cost_usd: null, status: 'completed', error_code: null}, {role: 'critic', provider: 'openrouter', requested_model: 'test/model', returned_model: null, response_id: null, input_tokens: null, output_tokens: 2000, total_tokens: null, reasoning_tokens: 1900, provider_status: 'incomplete', incomplete_reason: 'max_output_tokens', cost_usd: '0', status: 'incomplete', error_code: 'model_output_limit', error_message: 'The provider output limit stopped this response; financial results are preserved.'}]}}
  await page.route('**/api/runs/real-saved-source', route => route.fulfill({json: real}))
  await page.route('**/api/runs/mock-model-check', route => route.fulfill({json: saved}))
  await page.goto('/?view=research&run=mock-model-check')
  await expect(page.locator('.run-banner')).toContainText('Model connection check')
  await expect(page.getByText('Run completion and provider success are separate;', {exact: false})).toBeVisible()
  await expect(page.locator('.model-usage')).not.toHaveAttribute('open', '')
  await page.locator('.model-usage summary').click()
  await expect(page.locator('.model-usage')).toContainText('resolved/model')
  await expect(page.locator('.model-usage')).toContainText('Reported cost (USD)Unknown')
  await expect(page.locator('.model-usage')).toContainText('Reported cost (USD)0')
  await expect(page.locator('.model-usage')).toContainText('Unknown / 2000 / Unknown')
  await expect(page.locator('.model-usage')).toContainText('Provider/model default (no app cap)')
  await expect(page.locator('.model-usage')).toContainText('Output-token limit reached')
  await expect(page.locator('.model-usage')).toContainText('Reasoning tokens (included in output)1900')
  await expect(page.locator('.model-usage')).toContainText('Failure reasonThe provider output limit stopped this response; financial results are preserved.')
  const finished = saved
  saved = {...saved, status: 'running', report: {...saved.report, model_calls: [
    saved.report.model_calls[0], {...saved.report.model_calls[1], status: 'running', provider_status: null, incomplete_reason: null, error_code: null},
  ]}}
  await page.reload()
  await page.locator('.model-usage summary').click()
  await expect(page.locator('.model-usage')).toContainText('critic · Running')
  await expect(page.locator('.model-usage')).not.toContainText('Output-token limit reached')
  saved = finished
  await expect(page.locator('.model-usage')).toContainText('Output-token limit reached')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
})

for (const malformed of ['truncated JSON', 'empty object']) {
  test(`malformed accepted submission (research, ${malformed}) retains its exact key through reload`, async ({page, request}) => {
    const source = await (await request.get('/api/runs/example-msft')).json()
    const submissions: {payload: Record<string, unknown>; key: string}[] = []
    await page.route('**/api/runs', route => {
      if (route.request().method() !== 'POST') return route.continue()
      submissions.push({payload: route.request().postDataJSON(), key: route.request().headers()['idempotency-key']})
      if (submissions.length === 1) return route.fulfill({status: 202, contentType: 'application/json', body: malformed === 'truncated JSON' ? '{"id":' : '{}'})
      return route.fulfill({status: 202, json: {...source, id: 'recovered-malformed-response', request: submissions[0].payload}})
    })
    await page.route('**/api/runs/recovered-malformed-response', route => route.fulfill({json: {...source, id: 'recovered-malformed-response', request: submissions[0].payload}}))
    await page.goto('/?view=research&run=example-msft')
    const start = page.getByRole('button', {name: 'Start research →'})
    await page.getByLabel('Research action').selectOption('frozen')
    await expect(start).toBeEnabled()
    await start.click()
    await expect(page.getByRole('alert')).toContainText('The submission response was incomplete. Its outcome is unknown.')
    await expect(start).toBeDisabled()
    const stored = await page.evaluate(() => JSON.parse(sessionStorage.getItem('fieldnote-pending') ?? 'null'))
    expect(stored).toEqual({request: submissions[0].payload, key: submissions[0].key})
    await page.reload()
    const recover = page.getByRole('button', {name: 'Recover request'})
    await expect(recover).toBeVisible()
    await expect(page.getByRole('button', {name: 'Open saved report ↗'})).toBeDisabled()
    expect(submissions).toHaveLength(1)
    await recover.click()
    await expect(page).toHaveURL(/view=research&run=recovered-malformed-response/)
    expect(submissions).toHaveLength(2)
    expect(submissions[1]).toEqual(submissions[0])
    expect(await page.evaluate(() => sessionStorage.getItem('fieldnote-pending'))).toBeNull()
  })
}

test('the agent page opens on an empty question box whose helpers only fill the text', async ({page}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', {name: 'Ask about any US-listed company.'})).toBeVisible()
  await expect(page.getByText('SYNTHETIC TEACHING DATA', {exact: true})).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'Recent runs'})).toBeVisible()
  await expect(page.getByLabel('Your question')).toHaveValue('')
  await page.getByRole('button', {name: 'Compare NVIDIA and AMD on growth and valuation.'}).click()
  await expect(page.getByLabel('Your question')).toHaveValue('Compare NVIDIA and AMD on growth and valuation.')
  await page.locator('.starter', {hasText: 'Find companies'}).click()
  await expect(page.getByRole('group', {name: 'Where to look'})).toBeVisible()
  await expect(page.getByRole('button', {name: 'Find companies →'})).toBeEnabled()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.getByRole('button', {name: 'Baseline A', exact: true}).click()
  await expect(page.getByRole('heading', {name: 'Start with a question and a source.'})).toBeVisible()
})
