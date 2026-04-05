import { test, expect } from '@playwright/test'
import { navigateTo } from './helpers'

/**
 * Regression tests for dashboard functionality.
 * 
 * Tests verify the restored features:
 * 1. Time Range Filtering - Date range controls update API calls
 * 2. Crow Table Rendering - Detections table shows crow events
 * 3. System Stats - Dashboard shows two disk usage cards
 * 
 * Uses Playwright network interception to simulate backend responses.
 */

test.describe('Dashboard Regressions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('displays two disk usage cards (System vs Data)', async ({ page }) => {
    // Intercept health API and return mock data with both disk types
    await page.route('**/api/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          cpu_percent: 25.5,
          memory_percent: 60.0,
          disk_percent: 45.0,
          uptime_seconds: 86400,
          disk_system: {
            path: '/',
            percent: 45.0,
            total: 500000000000,
            used: 225000000000,
            free: 275000000000,
            ok: true,
          },
          disk_data: {
            path: '/data/orpheus',
            percent: 30.0,
            total: 2000000000000,
            used: 600000000000,
            free: 1400000000000,
            ok: true,
          },
        }),
      })
    })

    // Reload to trigger the mocked health API (already logged in from beforeEach)
    await page.reload()

    // Wait for dashboard to load
    await expect(page.getByRole('heading', { name: /dashboard/i })).toBeVisible({ timeout: 10000 })

    // Verify two disk cards are displayed
    await expect(page.getByText(/system disk/i)).toBeVisible()
    await expect(page.getByText(/data drive/i)).toBeVisible()
  })
})

test.describe('Crow Page Regressions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('crow table renders detection rows', async ({ page }) => {
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0 }) })
    })

    // Intercept crow stats API with mock detections
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_detections: 3,
          age_distribution: { adult: 2, juvenile: 1 },
          hourly_activity: Array.from({ length: 24 }, (_, i) => ({ hour: i, count: i === 8 ? 2 : 0 })),
          daily_activity: [
            { date: '2026-01-17', count: 1 },
            { date: '2026-01-18', count: 2 },
          ],
          call_types: { caw: 2, rattle: 1 },
          intents: {},
          detections: [
            {
              timestamp: '2026-01-18T10:00:00Z',
              confidence: 0.95,
              call_type: 'caw',
              audio_clip_path: '/data/orpheus/audio/1/clip1.flac',
              channel: 1,
            },
            {
              timestamp: '2026-01-18T11:00:00Z',
              confidence: 0.88,
              call_type: 'rattle',
              audio_clip_path: '/data/orpheus/audio/2/clip2.flac',
              channel: 2,
            },
            {
              timestamp: '2026-01-18T12:00:00Z',
              confidence: 0.72,
              call_type: 'caw',
              audio_clip_path: null,
              channel: 1,
            },
          ],
          scatter_sample: [
            { timestamp: '2026-01-17T08:00:00Z', call_type: 'caw', confidence: 0.95 },
            { timestamp: '2026-01-18T10:00:00Z', call_type: 'rattle', confidence: 0.88 },
          ],
          start_date: '2026-01-11',
          end_date: '2026-01-18',
        }),
      })
    })

    // Navigate to Crows page
    await navigateTo(page, /crows/i)

    // Wait for page to load
    await expect(page.getByText(/crow analysis/i)).toBeVisible({ timeout: 10000 })

    // Verify the detections table shows (or at least the detection data)
    await expect(page.getByText(/raw detections in date range/i)).toBeVisible()
    
    // Verify detection data is displayed
    await expect(page.getByText(/caw/i).first()).toBeVisible()
    await expect(page.getByText(/rattle/i).first()).toBeVisible()
  })
})

test.describe('Birds Page Time Range Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('date filter updates API request parameters', async ({ page }) => {
    // Track API calls
    const apiCalls: string[] = []
    
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0, scatter_sample: [], stats: { total_count: 0, unique_species_count: 0, hourly_activity: [], daily_activity: [], species_distribution: {} } }) })
    })

    await page.route('**/api/data/birds/history*', async (route) => {
      apiCalls.push(route.request().url())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          detections: [],
          scatter_sample: [],
          count: 0,
          filtered_count: 0,
          start_date: '2026-01-11',
          end_date: '2026-01-18',
          stats: {
            total_count: 0,
            unique_species_count: 0,
            hourly_activity: [],
            daily_activity: [],
            species_distribution: {},
          },
        }),
      })
    })

    // Navigate to Birds page
    await navigateTo(page, /^birds$/i)

    // Wait for page to load
    await expect(page.getByRole('heading', { name: 'Bird Detections' })).toBeVisible({ timeout: 10000 })

    // Verify initial API call was made
    expect(apiCalls.length).toBeGreaterThan(0)

    // Click 30 days preset button
    await page.getByRole('button', { name: /30 days/i }).click()

    // Wait for new API call
    await page.waitForTimeout(500)

    // Verify a new API call was made (total should be > 1)
    expect(apiCalls.length).toBeGreaterThan(1)
    
    // The last call should have updated date parameters
    const lastCall = apiCalls[apiCalls.length - 1]
    expect(lastCall).toContain('start_date=')
    expect(lastCall).toContain('end_date=')
  })
})
