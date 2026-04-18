import { test, expect } from '@playwright/test'
import { navigateTo } from './helpers'

/**
 * E2E tests for V2 Detection context and lineage data.
 *
 * Verifies that:
 * 1. The Birds page renders GPS coordinates (Location column) from mocked context data.
 * 2. Clicking a detection row opens a Detail Drawer showing the Source Event ID.
 */

test.describe('Context & Lineage Verification', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')

    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('Birds page shows location and lineage from V2 context', async ({ page }) => {
    // Defensive: if anything in the Birds flow ever queries /api/entities, return empty.
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ entities: [], count: 0, scatter_sample: [], stats: { total_count: 0, unique_species_count: 0, hourly_activity: [], daily_activity: [], species_distribution: {} } }),
      })
    })

    // Mock bird history API with V2 context & lineage fields
    await page.route('**/api/data/birds/history*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          detections: [
            {
              timestamp: '2026-01-18T10:00:00Z',
              species_code: 'amecro',
              species_common: 'American Crow',
              confidence: 0.92,
              channel: '1',
              audio_clip_path: null,
              context: {
                lat: 40.7128,
                lon: -74.006,
                sensor_id: 'mic-1',
                timestamp: '2026-01-18T10:00:00Z',
              },
              source_event_id: 'abc-123-def-456-source',
            },
          ],
          scatter_sample: [{ timestamp: '2026-01-18T10:00:00Z', species_code: 'amecro', species_common: 'American Crow', confidence: 0.92 }],
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

    // Verify Location column header exists
    await expect(page.getByRole('columnheader', { name: /location/i })).toBeVisible()

    // Verify the location badge renders with sensor_id
    const locationBadge = page.getByTestId('location-badge')
    await expect(locationBadge).toBeVisible()
    await expect(locationBadge).toContainText('mic-1')

    // Click the detection row to open the detail drawer (use table row to avoid ambiguity)
    await page.locator('tbody tr').first().click()

    // Verify the drawer shows the Source Event ID
    const sourceEventId = page.getByTestId('source-event-id')
    await expect(sourceEventId).toBeVisible()
    await expect(sourceEventId).toContainText('abc-123-def-456-source')

    // Verify the Context section is visible
    await expect(page.getByText('40.712800, -74.006000')).toBeVisible()

    // Verify Raw JSON toggle is present
    await expect(page.getByText(/show raw json/i)).toBeVisible()
  })
})
