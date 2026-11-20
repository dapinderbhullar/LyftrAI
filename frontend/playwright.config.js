import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  use: {
    baseURL: 'http://localhost:3000',
    channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || undefined,
  },
  webServer: {
    command: 'npm run dev -- --strictPort',
    url: 'http://localhost:3000',
    env: { VITE_API_URL: 'http://localhost:8000' },
  },
})
