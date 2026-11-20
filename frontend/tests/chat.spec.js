import { expect, test } from '@playwright/test'

const endpoint = 'http://localhost:8000/chat'
const metadata = {
  resolution_source: 'LIVE_INFERENCE',
  model: 'openai/test-model',
  latency_ms: 316,
  input_tokens: 19,
  output_tokens: 7,
}

test('submits once, clears the composer and renders the reply metadata', async ({ page }) => {
  let finish
  const waiting = new Promise(resolve => { finish = resolve })
  const requests = []
  await page.route(endpoint, async route => {
    const payload = route.request().postDataJSON()
    requests.push(payload)
    await waiting
    await route.fulfill({ json: { session_id: payload.session_id, reply: 'Hello there!', metadata } })
  })
  await page.goto('/')
  const input = page.getByTestId('chat-input')
  await input.fill('Hello')
  await input.press('Shift+Enter')
  await expect(input).toHaveValue('Hello\n')
  await input.press('Enter')
  try {
    await expect(input).toHaveValue('')
    await expect(page.getByRole('status')).toHaveText('Waiting for a reply…')
    await input.fill('Second message')
    await expect(page.getByTestId('send-button')).toBeDisabled()
    await input.press('Enter')
  } finally {
    finish()
  }
  const reply = page.getByTestId('assistant-message')
  await expect(reply).toContainText('Hello there!')
  await expect(reply.getByTestId('meta-source')).toHaveText(metadata.resolution_source)
  await expect(reply.getByTestId('meta-model')).toHaveText(metadata.model)
  await expect(reply.getByTestId('meta-latency')).toHaveText('316 ms')
  await expect(reply.getByTestId('meta-input-tokens')).toHaveText('19')
  await expect(reply.getByTestId('meta-output-tokens')).toHaveText('7')
  expect(requests).toEqual([{ session_id: expect.any(String), message: 'Hello' }])
})

test('shows a readable error, restores the message and starts a fresh session on reload', async ({ page }) => {
  const sessions = []
  await page.route(endpoint, async route => {
    sessions.push(route.request().postDataJSON().session_id)
    await route.fulfill({
      status: 503,
      json: { detail: 'all providers unavailable' },
    })
  })
  await page.goto('/')
  const input = page.getByTestId('chat-input')
  await input.fill('Hello')
  await page.getByTestId('send-button').click()
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable')
  await page.getByRole('button', { name: 'Restore message' }).click()
  await expect(input).toHaveValue('Hello')
  await page.reload()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(input).toHaveValue('')
  await input.fill('Hello')
  await page.getByTestId('send-button').click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(sessions).toHaveLength(2)
  expect(sessions[0]).not.toBe(sessions[1])
})
