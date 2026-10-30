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
  await page.goto('/?view=research')
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
  await page.getByRole('button', {name: 'Research', exact: true}).click()
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
  await page.goto('/?view=research')
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

test('Connections separates setup from attempts and navigation or refresh never submits research', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
  let reads = 0
  let posts = 0
  await page.route('**/api/config', route => {reads++; return route.fulfill({json: {...config, connections: {
    sec: {configured: true, provider: 'SEC', model: null, check: untested},
    model: {configured: false, provider: 'OpenAI', model: 'selected-model', check: untested},
  }}})})
  page.on('request', req => {if (req.method() === 'POST') posts++})
  await page.goto('/?view=research')
  await page.getByRole('button', {name: 'Connections', exact: true}).click()
  await expect(page).toHaveURL(/view=connections/)
  await expect(page.getByRole('heading', {name: 'Connections', exact: true})).toBeVisible()
  const sec = page.getByRole('region', {name: 'SEC financial data'})
  const model = page.getByRole('region', {name: 'Optional model analysis'})
  await expect(sec.getByText('Configured', {exact: true})).toBeVisible()
  await expect(sec.getByText('Not tested', {exact: true})).toBeVisible()
  await expect(model.getByText('Not configured', {exact: true})).toBeVisible()
  await expect(model.getByText('Not tested', {exact: true})).toBeVisible()
  await expect(model).toContainText('selected-model')
  await expect(page.getByRole('region', {name: 'Research controls'})).toHaveCount(0)
  await expect(page.getByLabel('Spending allowance (USD)')).toHaveValue('')
  await expect(model.getByRole('checkbox')).not.toBeChecked()
  await expect(model.getByRole('button', {name: 'Test model connection'})).toBeDisabled()
  await expect(page.getByText('Tests run only when you explicitly click a test button.', {exact: false})).toBeVisible()
  await expect(page.locator('.connection-setup')).not.toHaveAttribute('open', '')
  await expect(page.getByText('SEC_USER_AGENT', {exact: true})).toBeHidden()
  const before = reads
  await page.getByRole('button', {name: 'Refresh status'}).click()
  await expect(page.getByRole('button', {name: 'Refresh status'})).toBeEnabled()
  expect(reads).toBe(before + 1)
  await page.getByRole('button', {name: 'History', exact: true}).click()
  await page.getByRole('button', {name: 'Connections', exact: true}).click()
  await expect(sec.getByText('Not tested', {exact: true})).toBeVisible()
  expect(reads).toBeGreaterThan(before + 1)
  expect(posts).toBe(0)
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.screenshot({path: path.join(evidenceDir, 'desktop-connections.png'), fullPage: true})
  await page.reload()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', {name: 'Skip to connections'})).toBeFocused()
  await page.keyboard.press('Enter')
  await page.getByRole('button', {name: 'Refresh status'}).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', {name: 'Refresh status'})).toBeEnabled()
  expect(posts).toBe(0)
})

test('Connections shows recorded attempts and opens the correct saved investigation kind', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const checkedAt = '2026-10-27T09:30:00Z'
  await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
    sec: {configured: true, provider: 'SEC', model: null, check: {status: 'passed', checked_at: checkedAt, run_id: 'example-discovery', message: 'SEC data was retrieved.'}},
    model: {configured: true, provider: 'OpenAI', model: 'selected-model', check: {status: 'failed', checked_at: checkedAt, run_id: 'example-msft', message: '<img src=x onerror="window.injected=true"> The model attempt failed.'}},
  }}}))
  await page.goto('/?view=connections')
  const sec = page.getByRole('region', {name: 'SEC financial data'})
  const model = page.getByRole('region', {name: 'Optional model analysis'})
  await expect(sec.getByText('Check passed', {exact: true})).toBeVisible()
  await expect(model.getByText('Check failed', {exact: true})).toBeVisible()
  await expect(sec.locator('time')).toHaveAttribute('datetime', checkedAt)
  await expect(model.locator('time')).toContainText('27 Oct 2026, 09:30 UTC')
  await expect(model).toContainText('<img src=x')
  await expect(model.locator('img')).toHaveCount(0)
  await sec.getByRole('button', {name: 'Open saved investigation'}).click()
  await expect(page).toHaveURL(/view=discovery&run=example-discovery/)
  await expect(page.getByRole('heading', {name: 'Find a candidate. Inspect the reason.'})).toBeVisible()
  await page.getByRole('button', {name: 'Connections', exact: true}).click()
  await model.getByRole('button', {name: 'Open saved investigation'}).click()
  await expect(page).toHaveURL(/view=research&run=example-msft/)
  await expect(page.getByRole('heading', {name: 'Microsoft MSFT'})).toBeVisible()
})

test('Connections refresh clears old success while loading and after a configuration outage', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  let reads = 0
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => {release = resolve})
  await page.route('**/api/config', async route => {
    reads++
    if (reads === 2) {await gate; return route.fulfill({status: 503, json: {error: {message: 'Internal configuration detail'}}})}
    return route.fulfill({json: {...config, connections: {
      sec: {configured: true, provider: 'SEC', model: null, check: {status: 'passed', checked_at: '2026-10-27T09:30:00Z', run_id: null, message: 'SEC data was retrieved.'}},
      model: {configured: false, provider: 'OpenAI', model: null, check: {status: 'not_tested', checked_at: null, run_id: null, message: null}},
    }}})
  })
  await page.goto('/?view=connections')
  await expect(page.getByText('Check passed', {exact: true})).toBeVisible()
  await page.getByRole('button', {name: 'Refresh status'}).click()
  await expect(page.getByRole('status')).toContainText('Loading connection status')
  await expect(page.getByText('Check passed', {exact: true})).toHaveCount(0)
  release!()
  await expect(page.getByRole('alert')).toContainText('Connection status is unavailable')
  await expect(page.getByText('Check passed', {exact: true})).toHaveCount(0)
  await expect(page.locator('main')).not.toContainText('Internal configuration detail')
  await page.getByRole('button', {name: 'Retry connection'}).click()
  await expect(page.getByText('Check passed', {exact: true})).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('Connections supports legacy configuration, mobile keyboard access and collapsed setup details', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  delete config.connections
  await page.route('**/api/config', route => route.fulfill({json: {...config, sec_configured: false, model_configured: true, model: 'selected-model'}}))
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/?view=connections')
  const model = page.getByRole('region', {name: 'Optional model analysis'})
  await expect(model.getByText('Configured', {exact: true})).toBeVisible()
  await expect(model.getByText('Not tested', {exact: true})).toBeVisible()
  await expect(model).toContainText('Model service (not recorded)')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
  await page.screenshot({path: path.join(evidenceDir, 'mobile-connections.png'), fullPage: true})
  await page.locator('.connection-setup summary').focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('SEC_USER_AGENT', {exact: true})).toBeVisible()
  await expect(page.getByText('OPENAI_BASE_URL', {exact: true})).toBeVisible()
  await expect(page.locator('.connection-setup')).toContainText('Existing environment variables take precedence')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('model connection check requires source, allowance and fresh consent, then saves usage', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const source = await (await request.get('/api/runs/example-msft')).json()
  const real = {...source, id: 'real-saved-source', synthetic: false, request: {...source.request, ticker: 'AAPL'}, report: {...source.report, synthetic: false}}
  const empty = {...source, id: 'empty-source', report: null}
  const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
  await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
    sec: {configured: true, provider: 'SEC', model: null, check: untested},
    model: {configured: true, provider: 'OpenRouter', model: 'test/model', check: untested},
  }}}))
  await page.route('**/api/runs?*', route => route.fulfill({json: {items: [source, real, empty], total: 3}}))
  await page.route('**/api/runs/real-saved-source', route => route.fulfill({json: real}))
  await page.route('**/api/runs/empty-source', route => route.fulfill({json: empty}))
  const submissions: {payload: Record<string, unknown>; key: string}[] = []
  let saved: typeof source
  await page.route('**/api/runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    const payload = route.request().postDataJSON()
    submissions.push({payload, key: route.request().headers()['idempotency-key']})
    saved = {...real, id: 'mock-model-check', request: payload, report: {...real.report,
      model_run: {provider: 'openrouter', model: 'test/model', schema_version: 'test-v1', max_output_tokens: 2048},
      model_calls: [{role: 'interpretation', provider: 'openrouter', requested_model: 'test/model', returned_model: 'resolved/model', response_id: 'response-example', input_tokens: 100, output_tokens: 20, total_tokens: 120, cost_usd: null, status: 'completed', error_code: null}, {role: 'critic', provider: 'openrouter', requested_model: 'test/model', returned_model: null, response_id: null, input_tokens: null, output_tokens: null, total_tokens: null, cost_usd: '0', status: 'failed', error_code: 'provider_failure'}]}}
    return route.fulfill({json: saved})
  })
  await page.route('**/api/runs/mock-model-check', route => route.fulfill({json: saved}))
  await page.goto('/?view=connections')
  const model = page.getByRole('region', {name: 'Optional model analysis'})
  const button = model.getByRole('button', {name: 'Test model connection'})
  const consent = model.getByRole('checkbox')
  const amount = page.getByLabel('Spending allowance (USD)')
  const selector = page.getByLabel('Saved evidence for model check')
  await expect(model).toContainText('OpenRouter')
  await expect(model).toContainText('Synthetic teaching data: illustrative figures')
  await expect(amount).toHaveValue('')
  await expect(consent).not.toBeChecked()
  await expect(button).toBeDisabled()
  await amount.fill('0')
  await consent.check()
  await expect(button).toBeDisabled()
  await amount.fill('0.10')
  await expect(consent).not.toBeChecked()
  await expect(button).toBeDisabled()
  await consent.check()
  await expect(button).toBeEnabled()
  await selector.selectOption('empty-source')
  await expect(consent).not.toBeChecked()
  await expect(model).toContainText('no eligible company evidence')
  await consent.check()
  await expect(button).toBeDisabled()
  await selector.selectOption('real-saved-source')
  await expect(model).toContainText('Real saved research source')
  await expect(consent).not.toBeChecked()
  await consent.check()
  expect(submissions).toHaveLength(0)
  await button.click()
  await expect(page).toHaveURL(/view=research&run=mock-model-check/)
  expect(submissions).toHaveLength(1)
  expect(submissions[0].payload).toEqual({kind: 'research', mode: 'frozen', ticker: 'AAPL', cutoff: source.request.cutoff, source_run_id: real.id, screen: null, model_analysis: true, connection_check: 'model', spending_limit_usd: '0.10', provider_limit_confirmed: true})
  await expect(page.locator('.run-banner')).toContainText('Model connection check')
  await expect(page.getByText('Run completion and provider success are separate;', {exact: false})).toBeVisible()
  await expect(page.locator('.model-usage')).not.toHaveAttribute('open', '')
  await page.locator('.model-usage summary').click()
  await expect(page.locator('.model-usage')).toContainText('resolved/model')
  await expect(page.locator('.model-usage')).toContainText('Reported cost (USD)Unknown')
  await expect(page.locator('.model-usage')).toContainText('Reported cost (USD)0')
  await expect(page.locator('.model-usage')).toContainText('Unknown / Unknown / Unknown')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
})

test('SEC check requires configured setup and explicitly submits only the fixed fresh probe', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const source = await (await request.get('/api/runs/example-msft')).json()
  const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
  let configured = false
  let payload: Record<string, unknown> | undefined
  await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
    sec: {configured, provider: 'SEC', model: null, check: untested},
    model: {configured: false, provider: 'OpenRouter', model: null, configuration_error: 'Choose a model and configure its provider key.', check: untested},
  }}}))
  await page.route('**/api/runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    payload = route.request().postDataJSON()
    return route.fulfill({json: {...source, id: 'mock-sec-check', request: payload}})
  })
  await page.route('**/api/runs/mock-sec-check', route => route.fulfill({json: {...source, id: 'mock-sec-check', request: payload}}))
  await page.goto('/?view=connections')
  const button = page.getByRole('button', {name: 'Test SEC connection'})
  await expect(button).toBeDisabled()
  await expect(page.getByRole('button', {name: 'Test model connection'})).toBeDisabled()
  await expect(page.getByText('Choose a model and configure its provider key.')).toBeVisible()
  configured = true
  await page.getByRole('button', {name: 'Refresh status'}).click()
  await expect(button).toBeEnabled()
  expect(payload).toBeUndefined()
  const before = Date.now()
  await button.click()
  await expect(page).toHaveURL(/view=research&run=mock-sec-check/)
  expect(payload).toMatchObject({kind: 'research', mode: 'fresh', ticker: 'MSFT', source_run_id: null, screen: null, model_analysis: false, connection_check: 'sec'})
  expect(payload).not.toHaveProperty('spending_limit_usd')
  expect(payload).not.toHaveProperty('provider_limit_confirmed')
  expect(Date.parse(payload!.cutoff as string)).toBeGreaterThanOrEqual(before)
  await expect(page.locator('.run-banner')).toContainText('SEC connection check')
})

test('lost model check response locks controls and explicitly recovers the exact intent after reload', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const source = await (await request.get('/api/runs/example-msft')).json()
  const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
  await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
    sec: {configured: true, provider: 'SEC', model: null, check: untested},
    model: {configured: true, provider: 'OpenAI', model: 'test-model', check: untested},
  }}}))
  const requests: {payload: Record<string, unknown>; key: string}[] = []
  await page.route('**/api/runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    requests.push({payload: route.request().postDataJSON(), key: route.request().headers()['idempotency-key']})
    if (requests.length === 1) return route.abort('connectionfailed')
    return route.fulfill({json: {...source, id: 'recovered-check', request: requests[0].payload}})
  })
  await page.route('**/api/runs/recovered-check', route => route.fulfill({json: {...source, id: 'recovered-check', request: requests[0].payload}}))
  await page.goto('/?view=connections')
  await page.getByLabel('Spending allowance (USD)').fill('0.25')
  await expect(page.getByRole('region', {name: 'Optional model analysis'})).toContainText('Saved cutoff')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', {name: 'Test model connection'}).click()
  await expect(page.getByRole('alert')).toContainText('Connection interrupted')
  await expect(page.getByRole('button', {name: 'Test SEC connection'})).toBeDisabled()
  await expect(page.getByLabel('Saved evidence for model check')).toBeDisabled()
  await expect(page.getByLabel('Spending allowance (USD)')).toBeDisabled()
  await page.reload()
  await expect(page.getByRole('button', {name: 'Retry same submission'})).toBeVisible()
  await expect(page.getByRole('button', {name: 'Test model connection'})).toBeDisabled()
  expect(requests).toHaveLength(1)
  await page.getByRole('button', {name: 'Retry same submission'}).click()
  await expect(page).toHaveURL(/view=research&run=recovered-check/)
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
  expect(await page.evaluate(() => sessionStorage.getItem('fieldnote-pending-check'))).toBeNull()
})


for (const check of [true, false]) {
  for (const malformed of ['truncated JSON', 'empty object']) {
    test(`malformed accepted submission (${check ? 'model check' : 'research'}, ${malformed}) retains its exact key through reload`, async ({page, request}) => {
      const config = await (await request.get('/api/config')).json()
      const source = await (await request.get('/api/runs/example-msft')).json()
      const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
      await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
        sec: {configured: true, provider: 'SEC', model: null, check: untested},
        model: {configured: true, provider: 'OpenAI', model: 'test-model', check: untested},
      }}}))
      const submissions: {payload: Record<string, unknown>; key: string}[] = []
      await page.route('**/api/runs', route => {
        if (route.request().method() !== 'POST') return route.continue()
        submissions.push({payload: route.request().postDataJSON(), key: route.request().headers()['idempotency-key']})
        if (submissions.length === 1) return route.fulfill({status: 202, contentType: 'application/json', body: malformed === 'truncated JSON' ? '{"id":' : '{}'})
        return route.fulfill({status: 202, json: {...source, id: 'recovered-malformed-response', request: submissions[0].payload}})
      })
      await page.route('**/api/runs/recovered-malformed-response', route => route.fulfill({json: {...source, id: 'recovered-malformed-response', request: submissions[0].payload}}))
      await page.goto(check ? '/?view=connections' : '/?view=research&run=example-msft')
      const start = page.getByRole('button', {name: check ? 'Test model connection' : 'Start research →'})
      if (check) {
        await expect(page.getByRole('region', {name: 'Optional model analysis'})).toContainText('Saved cutoff')
        await page.getByLabel('Spending allowance (USD)').fill('0.25')
        await page.getByRole('checkbox').check()
      } else {
        await page.getByLabel('Research action').selectOption('frozen')
      }
      await expect(start).toBeEnabled()
      await start.click()
      await expect(page.getByRole('alert')).toContainText('The submission response was incomplete. Its outcome is unknown.')
      await expect(start).toBeDisabled()
      const storageKey = check ? 'fieldnote-pending-check' : 'fieldnote-pending'
      const stored = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key) ?? 'null'), storageKey)
      expect(stored).toEqual({request: submissions[0].payload, key: submissions[0].key})
      await page.reload()
      const recover = page.getByRole('button', {name: check ? 'Retry same submission' : 'Recover request'})
      await expect(recover).toBeVisible()
      await expect(check ? start : page.getByRole('button', {name: 'Open saved report ↗'})).toBeDisabled()
      expect(submissions).toHaveLength(1)
      await recover.click()
      await expect(page).toHaveURL(/view=research&run=recovered-malformed-response/)
      expect(submissions).toHaveLength(2)
      expect(submissions[1]).toEqual(submissions[0])
      expect(await page.evaluate(key => sessionStorage.getItem(key), storageKey)).toBeNull()
    })
  }
}


test('model check sends nothing and remains usable when recovery storage is unavailable', async ({page, request}) => {
  const config = await (await request.get('/api/config')).json()
  const untested = {status: 'not_tested', checked_at: null, run_id: null, message: null}
  await page.route('**/api/config', route => route.fulfill({json: {...config, connections: {
    sec: {configured: true, provider: 'SEC', model: null, check: untested},
    model: {configured: true, provider: 'OpenAI', model: 'test-model', check: untested},
  }}}))
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key === 'fieldnote-pending-check') throw new DOMException('Storage unavailable', 'SecurityError')
      return original.call(this, key, value)
    }
  })
  let posts = 0
  await page.route('**/api/runs', route => {
    if (route.request().method() !== 'POST') return route.continue()
    posts++
    return route.abort('blockedbyclient')
  })
  await page.goto('/?view=connections')
  await expect(page.getByRole('region', {name: 'Optional model analysis'})).toContainText('Saved cutoff')
  await page.getByLabel('Spending allowance (USD)').fill('0.25')
  await page.getByRole('checkbox').check()
  const button = page.getByRole('button', {name: 'Test model connection'})
  await button.click()
  await expect(page.getByRole('alert')).toContainText('No request was sent. Enable session storage')
  await expect(button).toBeEnabled()
  await expect(page.getByRole('button', {name: 'Test SEC connection'})).toBeEnabled()
  await expect(page.getByLabel('Spending allowance (USD)')).toBeEnabled()
  await expect(page.getByRole('button', {name: 'Retry same submission'})).toHaveCount(0)
  expect(posts).toBe(0)
  expect(await page.evaluate(() => sessionStorage.getItem('fieldnote-pending-check'))).toBeNull()
})
