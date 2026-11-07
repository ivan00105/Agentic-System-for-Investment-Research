import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('the agent page opens on an empty question box whose helpers only fill the text', async ({page}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', {name: 'Ask about any US-listed company.'})).toBeVisible()
  await expect(page.getByText('SYNTHETIC TEACHING DATA', {exact: true})).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'Recent runs'})).toBeVisible()
  await expect(page.getByLabel('Your question')).toHaveValue('')
  await page.getByRole('button', {name: 'Compare NVIDIA and AMD on growth and valuation.'}).click()
  await expect(page.getByLabel('Your question')).toHaveValue('Compare NVIDIA and AMD on growth and valuation.')
  await page.locator('.starter', {hasText: 'Find companies by my criteria'}).click()
  await expect(page.getByRole('group', {name: 'Where to look'})).toBeVisible()
  await expect(page.getByRole('button', {name: 'Find companies →'})).toBeEnabled()
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([])
})

test('with no model key, asking a question starts nothing and says what to set in .env', async ({page}) => {
  await page.goto('/')
  await page.getByRole('button', {name: 'How profitable is Microsoft, and is its operating margin rising?'}).click()
  await page.getByRole('button', {name: 'Research this question →'}).click()
  await expect(page.getByRole('alert')).toContainText('.env')
  await expect(page.getByLabel('Your question')).toHaveValue('How profitable is Microsoft, and is its operating margin rising?')
})

test('baseline A has no page: the menu has three items and its old links open Research', async ({page}) => {
  await page.goto('/')
  await expect(page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button')).toHaveText([/Research/, /History/, /Setup & status/])
  for (const link of ['/?view=baseline', '/?view=discovery&run=example-discovery', '/?view=research&run=example-msft']) {
    await page.goto(link)
    await expect(page.getByRole('heading', {name: 'Ask about any US-listed company.'})).toBeVisible()
  }
  await page.goto('/?view=history')
  await expect(page.getByRole('heading', {name: 'Agent runs'})).toBeVisible()
  await expect(page.getByRole('heading', {name: 'Saved investigations'})).toHaveCount(0)
})
