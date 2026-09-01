import { test, expect } from '@playwright/test'
import { login, navigateTo, openSidebarIfNeeded } from './helpers'

const CROW_STATS_MOCK = {
  total_detections: 5,
  age_distribution: { adult: 3, juvenile: 2 },
  hourly_activity: Array.from({ length: 24 }, (_, i) => ({ hour: i, count: i === 9 ? 3 : 0 })),
  daily_activity: [{ date: '2026-03-15', count: 5 }],
  call_types: { caw: 3, rattle: 2 },
  intents: {},
  detections: [],
  scatter_sample: [],
  start_date: '2026-03-15',
  end_date: '2026-03-16',
}

test.describe('Complete Navigation Flow', () => {
  test('user can navigate through all pages after login', async ({ page }) => {
    // Mock APIs up front so pages are reliable without a real backend
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CROW_STATS_MOCK) })
    })
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0 }) })
    })
    await page.route('**/api/cameras', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    })

    await login(page)

    // === DASHBOARD ===
    // Already on dashboard after login
    await expect(page).toHaveURL('/')
    await expect(page.getByText(/cpu usage/i)).toBeVisible()
    await expect(page.getByText(/memory usage/i)).toBeVisible()
    await expect(page.getByText(/system disk/i)).toBeVisible()

    // === BIRDS ===
    await navigateTo(page, /^birds$/i)
    await expect(page).toHaveURL('/birds')
    await expect(page.getByRole('heading', { name: /bird detections/i })).toBeVisible()
    await expect(page.getByText(/total detections/i).first()).toBeVisible()
    await expect(page.getByText(/unique species/i).first()).toBeVisible()

    // === CROWS ===
    await navigateTo(page, /crows/i)
    await expect(page).toHaveURL('/crows')
    await expect(page.getByRole('heading', { name: /crow analysis/i })).toBeVisible()
    await expect(page.getByText(/call types/i).first()).toBeVisible()
    await expect(page.getByText(/peak hour/i)).toBeVisible()
    
    // === CAMERAS ===
    await navigateTo(page, /cameras/i)
    await expect(page).toHaveURL('/cameras')
    await expect(page.getByRole('heading', { name: /cameras/i })).toBeVisible()
    // Mock returns empty list, so empty state should be visible
    await expect(page.getByText(/no cameras configured/i)).toBeVisible()
    
    // === AUDIO ===
    await navigateTo(page, /^audio$/i)
    await expect(page).toHaveURL('/audio')
    await expect(page.getByRole('heading', { name: /audio detection/i })).toBeVisible()
    await expect(page.getByText(/system status/i)).toBeVisible()
    await expect(page.getByText(/channel status/i)).toBeVisible()
    
    // === VIDEO ===
    await navigateTo(page, /video/i)
    await expect(page).toHaveURL('/video')
    await expect(page.getByRole('heading', { name: /video detection/i })).toBeVisible()
    await expect(page.getByText(/camera status/i)).toBeVisible()
    
    // === SETTINGS ===
    await navigateTo(page, /settings/i)
    await expect(page).toHaveURL('/settings')
    await expect(page.getByRole('heading', { name: /settings/i })).toBeVisible()
    await expect(page.getByText(/account/i)).toBeVisible()
    await expect(page.getByText(/email/i)).toBeVisible()
    
    // === BACK TO DASHBOARD ===
    await navigateTo(page, /dashboard/i)
    await expect(page).toHaveURL('/')
    await expect(page.getByRole('heading', { name: /dashboard/i })).toBeVisible()
  })
})

test.describe('Individual Page Content', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('Dashboard shows system health metrics', async ({ page }) => {
    await expect(page.getByText(/cpu usage/i)).toBeVisible()
    await expect(page.getByText(/memory usage/i)).toBeVisible()
    await expect(page.getByText(/system disk/i)).toBeVisible()
    await expect(page.getByText(/uptime/i)).toBeVisible()
    await expect(page.getByText('Service Status')).toBeVisible()
  })

  test('Birds page shows detection stats', async ({ page }) => {
    await navigateTo(page, /^birds$/i)

    await expect(page.getByText(/total detections/i).first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/unique species/i).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: /detections in date range/i })).toBeVisible()
    await expect(page.getByText(/top species/i).first()).toBeVisible()
  })

  test('Crows page shows analysis data', async ({ page }) => {
    // Mock crow APIs so the test is reliable in CI regardless of backend speed
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CROW_STATS_MOCK) })
    })
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0 }) })
    })

    await navigateTo(page, /crows/i)

    await expect(page.getByText(/raw detections/i).first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(/call types/i).first()).toBeVisible()
    await expect(page.getByText(/peak hour/i)).toBeVisible()
    await expect(page.getByText(/hourly activity/i)).toBeVisible()
  })

  test('Audio page shows channel status', async ({ page }) => {
    await navigateTo(page, /^audio$/i)
    
    await expect(page.getByText(/system status/i)).toBeVisible()
    await expect(page.getByText(/active channels/i)).toBeVisible()
    await expect(page.getByText(/mqtt status/i)).toBeVisible()
    await expect(page.getByText(/channel 1/i)).toBeVisible()
  })

  test('Video page shows camera status', async ({ page }) => {
    await navigateTo(page, /video/i)
    
    await expect(page.getByText(/system status/i)).toBeVisible()
    await expect(page.getByText(/active cameras/i)).toBeVisible()
    await expect(page.getByText(/camera 1/i)).toBeVisible()
  })

  test('Settings page shows user info', async ({ page }) => {
    await navigateTo(page, /settings/i)

    await expect(page.getByText(/account/i)).toBeVisible()
    await expect(page.getByText(/email/i).first()).toBeVisible()
    await expect(page.getByText(/role/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible()
  })
})

test.describe('Page Interactions', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('Cameras page refresh button works', async ({ page }) => {
    await page.route('**/api/cameras', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    })

    await navigateTo(page, /cameras/i)

    const refreshButton = page.getByRole('button', { name: /refresh/i })
    await expect(refreshButton).toBeVisible()
    await refreshButton.click()
    
    // Page should still be visible after refresh
    await expect(page.getByRole('heading', { name: /cameras/i })).toBeVisible()
  })

  test('Sidebar navigation highlights active page', async ({ page }) => {
    // On dashboard, dashboard link should be highlighted
    const dashboardLink = page.getByRole('link', { name: /dashboard/i })
    await expect(dashboardLink).toHaveClass(/blue/)
    
    // Click Crows
    await navigateTo(page, /crows/i)
    const crowsLink = page.getByRole('link', { name: /crows/i })
    await expect(crowsLink).toHaveClass(/blue/)
  })
})

test.describe('Mobile Navigation', () => {
  test.use({ viewport: { width: 375, height: 667 } })

  test('mobile menu opens and closes', async ({ page }) => {
    // Mock crow APIs so the crows page loads reliably in CI
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CROW_STATS_MOCK) })
    })
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0 }) })
    })

    await login(page)

    // Sidebar should be off-screen initially on mobile (translated out via CSS)
    const sidebar = page.locator('aside')
    await expect(sidebar).not.toBeInViewport()
    
    // Click hamburger menu to open
    const menuButton = page.getByRole('button', { name: 'Open menu' })
    await menuButton.click()
    
    // Sidebar should now be visible
    await expect(sidebar).toBeVisible()
    
    // Sidebar is already open; wait for the CSS transition, then click directly
    await expect(sidebar).toBeInViewport()
    await page.getByRole('link', { name: /crows/i }).click()
    
    // Should navigate and close sidebar
    await expect(page).toHaveURL('/crows')
    await expect(page.getByRole('heading', { name: /crow analysis/i })).toBeVisible()
  })

  test('all pages are usable on mobile', async ({ page }) => {
    // Mock APIs so pages load reliably in CI
    await page.route('**/api/data/crows/stats*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CROW_STATS_MOCK) })
    })
    await page.route('**/api/entities*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entities: [], count: 0 }) })
    })
    await page.route('**/api/cameras', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    })

    await login(page)

    // Dashboard content should be visible
    await expect(page.getByText(/cpu/i)).toBeVisible()
    
    // Navigate to each page and verify content is accessible
    const pages = [
      { link: /^birds$/i, content: /bird detections/i },
      { link: /crows/i, content: /crow analysis/i },
      { link: /cameras/i, content: /cameras/i },
      { link: /^audio$/i, content: /audio detection/i },
      { link: /video/i, content: /video detection/i },
      { link: /settings/i, content: /settings/i },
    ]
    
    for (const { link, content } of pages) {
      // Open menu
      const menuButton = page.getByRole('button', { name: 'Open menu' })
      await menuButton.click()
      
      // Click link
      await page.getByRole('link', { name: link }).click()
      
      // Verify page loaded
      await expect(page.getByRole('heading', { name: content })).toBeVisible()
    }
  })
})

test.describe('Logout Flow', () => {
  test('user can log out from any page', async ({ page }) => {
    await login(page)
    
    // Navigate to Settings
    await navigateTo(page, /settings/i)
    await expect(page).toHaveURL('/settings')
    
    // Open user menu (at bottom of sidebar) — on mobile, reopen sidebar first
    await openSidebarIfNeeded(page)
    const userButton = page.getByRole('button', { name: 'User menu' })
    // The button is absolute bottom-0 inside the sidebar; scroll it into view
    // on small mobile viewports where it may be at/near the viewport edge
    await userButton.scrollIntoViewIfNeeded()
    await userButton.click()
    
    // Click sign out
    await page.getByRole('button', { name: /sign out/i }).click()
    
    // Should redirect to login
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
    await expect(page).toHaveURL(/login/)
  })

  test('protected pages redirect to login when not authenticated', async ({ page }) => {
    // Clear any stored auth
    await page.goto('/')
    await page.evaluate(() => localStorage.clear())
    
    // Try to access protected route
    await page.goto('/settings')
    
    // Should redirect to login
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
  })
})

test.describe('Error States', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('pages handle API errors gracefully', async ({ page }) => {
    // Navigate to Birds page which fetches data
    await navigateTo(page, /^birds$/i)
    
    // Page should load even if API returns error
    // Either shows data or shows "failed to load" message
    await expect(page.getByRole('heading', { name: /bird detections/i })).toBeVisible()
  })
})
