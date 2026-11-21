import { expect, test } from '@playwright/test'

const endpoint = 'http://localhost:8000/chat'
const metadata = {
  resolution_source: 'LIVE_INFERENCE',
  model: 'gemini/test-model',
  latency_ms: 316,
  input_tokens: 19,
  output_tokens: 7,
}

test('renders assistant Markdown safely and leaves user text literal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 650 })
  const longCode = 'x'.repeat(200)
  const columns = Array.from({ length: 24 }, (_, index) => String(index + 1))
  const markdown = [
    '### What does REST mean?',
    '',
    '**REST** is an *architectural style*. Use `GET` to read.',
    'This starts on a new line.',
    '',
    '- One bullet',
    '- Another bullet',
    '',
    '1. First step',
    '2. Second step',
    '',
    '```text',
    longCode,
    '```',
    '',
    `| Method | Purpose | ${columns.join(' | ')} |`,
    `| --- | --- | ${columns.map(() => '---').join(' | ')} |`,
    `| GET | Read | ${columns.join(' | ')} |`,
    '',
    '[Documentation](https://example.com/docs)',
    '',
    '[Unsafe link](javascript:alert%281%29)',
    '',
    '<img src="https://example.com/raw.png" onerror="alert(1)">',
    '',
    '![Remote image](https://example.com/image.png)',
  ].join('\n')

  await page.route(endpoint, route => route.fulfill({ json: { reply: markdown, metadata } }))
  await page.goto('/')
  await page.getByTestId('chat-input').fill('**Keep this literal**')
  await page.getByTestId('send-button').click()

  await expect(page.getByText('**Keep this literal**', { exact: true })).toBeVisible()
  const reply = page.getByTestId('assistant-message')
  await expect(reply.getByRole('heading', { level: 3 })).toHaveText('What does REST mean?')
  await expect(reply.locator('p strong')).toHaveText('REST')
  await expect(reply.locator('em')).toHaveText('architectural style')
  await expect(reply.locator('p br')).toHaveCount(1)
  await expect(reply.locator('p code')).toHaveText('GET')
  await expect(reply.locator('ul li')).toHaveText(['One bullet', 'Another bullet'])
  await expect(reply.locator('ol li')).toHaveText(['First step', 'Second step'])
  await expect(reply.locator('pre code')).toHaveText(longCode)
  await expect(reply.getByRole('columnheader', { name: 'Method' })).toBeVisible()
  await expect(reply.getByRole('link', { name: 'Documentation' })).toHaveAttribute('href', 'https://example.com/docs')
  await expect(reply.locator('a[href^="javascript:"]')).toHaveCount(0)
  await expect(reply.locator('img')).toHaveCount(0)
  for (const selector of ['pre', '.reply-table']) {
    expect(await reply.locator(selector).evaluate(element => {
      element.scrollLeft = element.scrollWidth
      return element.scrollLeft
    })).toBeGreaterThan(0)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

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

test('shows validation errors and scrolls the latest turn into view on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 650 })
  let requests = 0
  await page.route(endpoint, route => {
    requests++
    if (requests === 1) {
      return route.fulfill({ json: { reply: 'Long answer.\n'.repeat(60), metadata } })
    }
    return route.fulfill({
      status: 422,
      json: { detail: [{ loc: ['body', 'message'], msg: 'Invalid message' }] },
    })
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible()
  const input = page.getByTestId('chat-input')
  await page.getByRole('button', { name: 'Explain how a rainbow forms' }).click()
  await expect(input).toHaveValue('Explain how a rainbow forms')
  await page.getByTestId('send-button').click()
  await expect(page.getByTestId('meta-output-tokens')).toBeInViewport()
  await input.fill('Rejected message')
  await page.getByTestId('send-button').click()
  const error = page.getByRole('alert')
  await expect(error).toContainText('Check your input and try again')
  await expect(error).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})
