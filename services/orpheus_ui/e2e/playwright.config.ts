import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright configuration for orpheus_ui end-to-end tests.
 * 
 * Located at: services/orpheus_ui/e2e/
 * 
 * These tests verify the full user experience including:
 * - Login flow
 * - Dashboard rendering
 * - Navigation
 * - Responsive design
 * 
 * Run with: make test-e2e (from orpheus_ui root)
 * 
 * In CI: Tests run against the backend (port 8082) which serves built static files.
 * Locally: Tests run against frontend dev server (port 5173) + backend.
 */

const isCI = !!process.env.CI

export default defineConfig({
  // Tests are in the same directory as this config
  testDir: '.',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: isCI ? 1 : undefined,
  reporter: isCI ? 'list' : 'html',
  
  // Global timeout for the entire test run (5 minutes in CI)
  globalTimeout: isCI ? 5 * 60 * 1000 : undefined,
  // Per-test timeout (30 seconds)
  timeout: 30000,
  
  use: {
    // In CI, test against backend which serves static files
    // Locally, test against frontend dev server
    baseURL: isCI ? 'http://localhost:8082' : 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Only run mobile tests locally (too slow for CI)
    ...(isCI ? [] : [
      {
        name: 'mobile',
        use: { ...devices['iPhone 12'], browserName: 'chromium' },
      },
    ]),
  ],

  // Web server configuration
  webServer: isCI
    ? [
        {
          // In CI: Only backend (serves built static files)
          command: 'cd ../backend && make run',
          url: 'http://localhost:8082/api/health',
          reuseExistingServer: true,
          timeout: 60000,
        },
      ]
    : [
        {
          // Locally: Backend (Python FastAPI)
          command: 'cd ../backend && make run',
          url: 'http://localhost:8082/api/health',
          reuseExistingServer: true,
          timeout: 60000,
        },
        {
          // Locally: Frontend (Vite dev server)
          command: 'cd ../frontend && npm run dev',
          url: 'http://localhost:5173',
          reuseExistingServer: true,
          timeout: 30000,
        },
      ],
})
