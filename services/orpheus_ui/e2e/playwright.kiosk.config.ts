import { defineConfig, devices } from '@playwright/test'

/**
 * Kiosk browser tests: frontend only, backend mocked inside the spec, so they
 * need no Python backend, database or station. Starts the Vite dev server.
 *
 *   make -C services/orpheus_ui test-kiosk-e2e
 *   KIOSK_BROWSER=webkit make ...   # Safari's engine, where Playwright has it
 */
const browser = process.env.KIOSK_BROWSER || 'chromium'
const device =
  browser === 'webkit' ? devices['Desktop Safari'] : browser === 'firefox' ? devices['Desktop Firefox'] : devices['Desktop Chrome']

export default defineConfig({
  testDir: '.',
  testMatch: 'kiosk.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 30000,
  outputDir: 'test-results/kiosk',
  use: {
    baseURL: 'http://127.0.0.1:5181',
    trace: 'retain-on-failure',
  },
  projects: [{ name: browser, use: { ...device } }],
  webServer: {
    command: 'npm --prefix ../frontend run dev -- --host 127.0.0.1 --port 5181 --strictPort',
    url: 'http://127.0.0.1:5181/kiosk?demo=1',
    reuseExistingServer: false,
    timeout: 120000,
  },
})
