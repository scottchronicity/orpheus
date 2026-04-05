import { test, expect } from '@playwright/test'
import { navigateTo } from './helpers'

/**
 * Media Playback Tests
 * 
 * Tests verify:
 * 1. Media Authentication - Audio/video requests include Authorization header
 * 2. Timezone Formatting - Timestamps display in local time with proper format
 */

test.describe('Media Playback Authentication', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('audio clip requests include Authorization header', async ({ page }) => {
    // Track API requests to audio clips endpoint
    const audioRequests: { url: string; hasAuthHeader: boolean }[] = []
    
    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/api/audio/clips/')) {
        const authHeader = request.headers()['authorization'] || request.headers()['Authorization']
        audioRequests.push({ 
          url, 
          hasAuthHeader: !!authHeader && authHeader.startsWith('Bearer ')
        })
      }
    })

    // Mock entity section (CrowEntitySection fetches this; return empty so page renders)
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ entities: [], count: 0 }),
      })
    })

    // Mock crow stats API with audio clips
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_detections: 1,
          age_distribution: { adult: 1 },
          hourly_activity: Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0 })),
          call_types: { caw: 1 },
          intents: {},
          daily_activity: [{ date: '2026-01-18', count: 1 }],
          scatter_sample: [{ timestamp: '2026-01-18T10:00:00Z', call_type: 'caw', confidence: 0.95 }],
          detections: [
            {
              timestamp: '2026-01-18T10:00:00Z',
              confidence: 0.95,
              call_type: 'caw',
              audio_clip_path: '/data/orpheus/audio/1/test_clip.flac',
              channel: 1,
            },
          ],
          start_date: '2026-01-11',
          end_date: '2026-01-18',
        }),
      })
    })

    // Mock audio clip endpoint to return a blob
    await page.route('**/api/audio/clips/**', async (route) => {
      // Return a mock audio file
      const mockAudioBlob = Buffer.from([0xff, 0xf8, 0x00, 0x00]) // Minimal audio header
      await route.fulfill({
        status: 200,
        contentType: 'audio/flac',
        body: mockAudioBlob,
      })
    })

    // Navigate to Crows page
    await navigateTo(page, /crows/i)
    await expect(page.getByText(/crow analysis/i)).toBeVisible({ timeout: 10000 })

    // Wait for the table to render
    await expect(page.getByText(/raw detections in date range/i)).toBeVisible()

    // Click play button to trigger audio fetch
    const playButton = page.getByRole('button', { name: /play/i }).first()
    await expect(playButton).toBeVisible()
    await playButton.click()

    // Wait for the audio request to be made
    await page.waitForTimeout(1000)

    // Verify that at least one audio request was made with auth header
    expect(audioRequests.length).toBeGreaterThan(0)
    
    const audioRequest = audioRequests.find(req => req.url.includes('/api/audio/clips/'))
    expect(audioRequest).toBeDefined()
    expect(audioRequest?.hasAuthHeader).toBe(true)
  })
})

test.describe('Timezone Formatting', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('timestamps display in local time format', async ({ page }) => {
    // Mock entity section (CrowEntitySection fetches this; return empty so page renders)
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ entities: [], count: 0 }),
      })
    })

    // Mock crow stats API with a known UTC timestamp
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_detections: 1,
          age_distribution: { adult: 1 },
          hourly_activity: Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0 })),
          call_types: { caw: 1 },
          intents: {},
          daily_activity: [{ date: '2026-01-18', count: 1 }],
          scatter_sample: [{ timestamp: '2026-01-18T14:30:45Z', call_type: 'caw', confidence: 0.95 }],
          detections: [
            {
              timestamp: '2026-01-18T14:30:45Z', // 2:30:45 PM UTC
              confidence: 0.95,
              call_type: 'caw',
              audio_clip_path: null,
              channel: 1,
            },
          ],
          start_date: '2026-01-11',
          end_date: '2026-01-18',
        }),
      })
    })

    // Navigate to Crows page
    await navigateTo(page, /crows/i)
    await expect(page.getByText(/crow analysis/i)).toBeVisible({ timeout: 10000 })

    // Wait for the table to render
    await expect(page.getByText(/raw detections in date range/i)).toBeVisible()

    // Get the table content
    const tableContent = await page.locator('table').textContent()
    
    // Verify that the timestamp is formatted with:
    // - Month abbreviation (Jan)
    // - Day (18)
    // - Year (2026)
    // - Time with AM/PM
    expect(tableContent).toMatch(/Jan/i)
    expect(tableContent).toContain('18')
    expect(tableContent).toContain('2026')
    expect(tableContent).toMatch(/AM|PM/i)
    
    // Verify the time component includes colon-separated minutes/seconds
    expect(tableContent).toMatch(/\d+:\d+:\d+/)
  })

  test('bird detections show formatted timestamps', async ({ page }) => {
    // Mock bird history API
    await page.route('**/api/data/birds/history*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          detections: [
            {
              timestamp: '2026-01-18T09:15:30Z',
              species_code: 'amecro',
              species_common: 'American Crow',
              confidence: 0.92,
              channel: '1',
            },
          ],
          scatter_sample: [{ timestamp: '2026-01-18T09:15:30Z', species_code: 'amecro', species_common: 'American Crow', confidence: 0.92 }],
          count: 1,
          filtered_count: 0,
          start_date: '2026-01-11',
          end_date: '2026-01-18',
          stats: {
            total_count: 1,
            unique_species_count: 1,
            hourly_activity: [],
            daily_activity: [{ date: '2026-01-18', count: 1 }],
            species_distribution: { 'American Crow': 1 },
          },
        }),
      })
    })

    // Navigate to Birds page
    await navigateTo(page, /^birds$/i)
    await expect(page.getByRole('heading', { name: 'Bird Detections' })).toBeVisible({ timeout: 10000 })

    // Get the table content
    const tableContent = await page.locator('table').textContent()
    
    // Verify formatted timestamp components
    expect(tableContent).toMatch(/Jan/i)
    expect(tableContent).toContain('18')
    expect(tableContent).toContain('2026')
    expect(tableContent).toMatch(/AM|PM/i)
  })
})
