import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockRun, RUN } from './agent-fixtures'

const at = (second: number) => `2026-11-05T09:00:${String(second).padStart(2, '0')}+00:00`
const margins = Array.from({length: 9}, (_, i) => ({seq: 3 + i, text: `Calculation: Gross margin, ACME, year ended ${2016 + i}-12-31 → OK, 25.0%`, status: 'ok'}))
const progress = [
  {seq: 1, at: at(1), kind: 'plan', role: 'single_agent', text: 'plan ready'},
  {seq: 2, at: at(5), kind: 'model_call', role: 'single_agent', step: 4, text: 'Step 4 · 10 calculations · 9 OK, 1 unsupported',
    details: [...margins, {seq: 12, text: 'Calculation: P/E, ACME, at 2026-11-03 → unsupported: Earnings are negative, so no P/E.', status: 'unsupported'}]},
  {seq: 13, at: at(9), kind: 'model_call', role: 'single_agent', step: 5, text: 'Step 5 · handing in the report · OK', details: [{seq: 14, text: 'Handing in the answer → OK', status: 'ok'}]},
]

test('each model step is one line with its time, and its tool calls fold under it', async ({page}) => {
  await mockRun(page, {progress})
  await page.goto(`/?view=research&agent=${RUN}`)
  await page.getByText('How the agents worked').click()
  const group = page.locator('.timeline > li').first()
  await expect(group.locator('summary').first()).toContainText('Research agent')
  await expect(group.locator('summary').first()).toContainText('2 steps · 09:00:01 UTC–09:00:09 UTC')
  await group.locator('summary').first().click()
  const step = group.locator('details details').first()
  await expect(step.locator('summary')).toHaveText('Step 4 · 10 calculations · 9 OK, 1 unsupported')
  await expect(group.locator('time')).toHaveCount(3) // once per line, never per tool call
  await expect(group.getByText('09:00:05 UTC')).toHaveCount(1)
  const first = step.getByText('Calculation: Gross margin, ACME, year ended 2016-12-31 → OK, 25.0%')
  await expect(first).toBeHidden()
  await step.locator('summary').click()
  await expect(first).toBeVisible()
  await expect(step.locator('li')).toHaveCount(10)
  await expect(step.locator('.timeline-problem')).toHaveText('Calculation: P/E, ACME, at 2026-11-03 → unsupported: Earnings are negative, so no P/E.')
  await expect(page.locator('.agent-progress')).not.toContainText('model asks for')
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
})

test('while a run is going its latest step stays open', async ({page}) => {
  await mockRun(page, {status: 'running', progress}, null)
  await page.goto(`/?view=research&agent=${RUN}`)
  const steps = page.locator('.timeline details details')
  await expect(steps.last()).toHaveAttribute('open', '')
  await expect(steps.first()).not.toHaveAttribute('open', '')
  await expect(page.getByText('Handing in the answer → OK')).toBeVisible()
})
