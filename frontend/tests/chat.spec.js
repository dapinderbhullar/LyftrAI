import { expect, test } from '@playwright/test'
import { join } from 'node:path'

const endpoint = 'http://localhost:8000/chat'
const metadata = {
  resolution_source: 'LIVE_INFERENCE',
  model: 'gemini/test-model',
  latency_ms: 316,
  input_tokens: 19,
  output_tokens: 7,
}

async function capture(page, name) {
  if (process.env.LYFTR_SCREENSHOTS) {
    await page.screenshot({ path: join(process.env.LYFTR_SCREENSHOTS, name), animations: 'disabled' })
  }
}

test('navigation and themes work across desktop, tablet and mobile widths', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible()
  await capture(page, 'lyftr-desktop-dark.png')
  await page.getByRole('button', { name: 'Switch to light mode' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  for (const width of [1440, 1024, 768, 390, 360]) {
    await page.setViewportSize({ width, height: 800 })
    const open = page.getByRole('button', { name: 'Open navigation' })
    await expect(page.getByTestId('chat-input')).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (width <= 800) {
      await open.click()
      await expect(page.getByRole('button', { name: 'Close navigation' })).toBeFocused()
      await page.keyboard.press('Escape')
      await expect(open).toBeFocused()
    } else {
      await expect(open).toBeHidden()
      await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()
    }
  }
  await page.setViewportSize({ width: 390, height: 800 })
  await page.getByRole('heading', { name: 'What’s on your mind?' }).click()
  await capture(page, 'lyftr-mobile-light.png')
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.setViewportSize({ width: 1024, height: 800 })
  await expect(page.getByTestId('chat-input')).toBeFocused()
})

test('copies replies and code, labels cached replies and starts a new chat', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 1440, height: 900 })
  const markdown = [
    '### A small Python example', '',
    'This loop prints each item from a list.', '',
    '- Put your values in the list.',
    '- Use `for` to visit each value.', '',
    '```python', 'for name in ["Ada", "Lin"]:', '    print(name)', '```', '',
    '| Step | Result |', '| --- | --- |', '| Loop | Visits both names |', '| Print | Writes one line per name |',
  ].join('\n')
  const requests = []
  await page.route(endpoint, route => {
    requests.push(route.request().postDataJSON())
    const cached = requests.length === 2
    return route.fulfill({ json: { reply: markdown, metadata: cached
      ? { ...metadata, resolution_source: 'LLM_CACHE', latency_ms: 1 } : metadata } })
  })
  await page.goto('/')
  const input = page.getByTestId('chat-input')
  await input.fill('Show me a small Python loop.')
  await input.press('Enter')
  const reply = page.getByTestId('assistant-message').first()
  await expect(reply.getByText('Live response')).toBeVisible()
  await capture(page, 'lyftr-desktop-conversation.png')
  const copyCode = reply.getByRole('button', { name: 'Copy code' })
  await copyCode.click()
  await expect(copyCode).toHaveText('Copied')
  expect((await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n')).toBe('for name in ["Ada", "Lin"]:\n    print(name)\n')
  const copyReply = reply.getByRole('button', { name: 'Copy response' })
  await copyReply.click()
  await expect(copyReply).toHaveText('Copied')
  expect((await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n')).toBe(markdown)

  await input.fill('Show me a small Python loop.')
  await input.press('Enter')
  await expect(page.getByTestId('assistant-message').last().getByText('Cached response')).toBeVisible()
  await expect(page.getByTestId('assistant-message').last().getByTestId('meta-latency')).toHaveText('1 ms')
  await capture(page, 'lyftr-cached-response.png')
  await page.getByRole('button', { name: 'New chat' }).click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(0)
  await input.fill('New session')
  await input.press('Enter')
  await expect(page.getByTestId('assistant-message')).toHaveCount(1)
  expect(requests[0].session_id).toBe(requests[1].session_id)
  expect(requests[2].session_id).not.toBe(requests[0].session_id)
})

test('retries a provider 503 in the same session without duplicating the turn', async ({ page }) => {
  const requests = []
  await page.route(endpoint, route => {
    requests.push(route.request().postDataJSON())
    if (requests.length === 1) {
      return route.fulfill({ status: 503, json: { detail: 'all providers unavailable' } })
    }
    return route.fulfill({ json: { reply: 'Ready now.', metadata } })
  })
  await page.goto('/')
  await page.getByTestId('chat-input').fill('Retry this prompt')
  await page.getByTestId('send-button').click()
  await expect(page.getByRole('alert')).toBeVisible()
  await capture(page, 'lyftr-error.png')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('Ready now.')).toBeVisible()
  await expect(page.getByText('Retry this prompt', { exact: true }).and(page.locator('.user'))).toHaveCount(1)
  expect(requests).toEqual([requests[0], requests[0]])
})

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

  await expect(page.getByRole('region', { name: 'Conversation' }).getByText('**Keep this literal**', { exact: true })).toBeVisible()
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
    await capture(page, 'lyftr-loading.png')
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
