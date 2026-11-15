import { test, expect, type Page, type Route } from '@playwright/test'

/**
 * Kiosk display in a real browser, with the backend mocked at the network
 * layer (page.route). Exercises the live code path (guest sign-in, polling,
 * blob-loaded snapshots, layout at kiosk screen sizes) without a station.
 *
 * Run: make -C services/orpheus_ui test-kiosk-e2e
 * (playwright.kiosk.config.ts starts only the Vite dev server.)
 */

const TINY_JPEG = Buffer.from(
  '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==',
  'base64',
)

interface Calls {
  guestLogins: number
  paths: string[]
  auth: string[]
}

async function mockStation(page: Page, opts: { guest?: boolean; servicesDown?: boolean } = {}): Promise<Calls> {
  const calls: Calls = { guestLogins: 0, paths: [], auth: [] }
  const now = Date.now()
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

  await page.route('**/auth/guest-login', (route) => {
    calls.guestLogins++
    return opts.guest === false
      ? json(route, { detail: 'Guest sign-in is disabled' }, 403)
      : json(route, { access_token: 'guest-token', token_type: 'bearer' })
  })
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    calls.paths.push(url.pathname)
    calls.auth.push(route.request().headers()['authorization'] ?? '')
    if (url.pathname === '/api/config') return json(route, { poll_interval: 5000, guest_quick_login: opts.guest !== false })
    if (route.request().headers()['authorization'] !== 'Bearer guest-token') return json(route, { detail: 'Unauthorized' }, 401)
    switch (url.pathname) {
      case '/api/health':
        return json(route, { status: 'healthy', cpu_percent: 41, memory_percent: 66, disk_percent: 52, uptime_seconds: 200000 })
      case '/api/services/status':
        return json(route, {
          services: [
            { name: 'orpheus-ui', status: 'active' },
            { name: 'orpheus-agent-audio-motion', status: opts.servicesDown ? 'failed' : 'active' },
          ],
        })
      case '/api/diagnostics/audio':
        return json(route, {
          running: true,
          channels: [1, 2, 3, 4].map((i) => ({ id: String(i), level_db: -50 + i * 8, peak_db: -40, has_signal: i > 1, level_color: 'green' })),
        })
      case '/api/entities':
        return json(route, {
          entities: [
            { entity_id: 'e1', timestamp: new Date(now - 120_000).toISOString(), species_code: 'amecro', common_name: 'American Crow', confidence: 0.93, entity_type: 'Animal.Bird.Crow', evidence: [{ sensor_id: 'channel_2' }] },
            { entity_id: 'e2', timestamp: new Date(now - 600_000).toISOString(), species_code: 'norcar', common_name: 'Northern Cardinal', confidence: 0.81, entity_type: 'Animal.Bird' },
            { entity_id: 'e3', timestamp: new Date(now - 700_000).toISOString(), species_code: 'own', common_name: 'Played By Orpheus', confidence: 0.99, is_self_generated: true },
          ],
          count: 3,
          stats: {
            total_count: 57,
            unique_species_count: 9,
            hourly_activity: [{ hour: 6, count: 12 }, { hour: 7, count: 20 }],
            species_distribution: { 'American Crow': 21, 'Northern Cardinal': 14 },
          },
        })
      case '/api/cameras':
        return json(route, [{ name: 'orpheus-eye-1', status: 'online' }])
      case '/api/media/snapshots/orpheus-eye-1':
        return json(route, {
          snapshots: [{ filename: 'x.orpheus-eye-1.jpg', timestamp_iso: new Date(now - 30_000).toISOString(), download_url: '/api/media/snapshots/orpheus-eye-1/2026.11.14/x.orpheus-eye-1.jpg' }],
        })
      case '/api/weather/latest':
        return json(route, { available: true, temperature_c: 9.6, humidity_pct: 70 })
      default:
        if (url.pathname.startsWith('/api/media/snapshots/orpheus-eye-1/')) {
          return route.fulfill({ status: 200, contentType: 'image/jpeg', body: TINY_JPEG })
        }
        return json(route, { detail: 'not mocked' }, 404)
    }
  })
  return calls
}

test.describe('kiosk display', () => {
  test('signs in as the guest and shows live station data', async ({ page }) => {
    const calls = await mockStation(page)
    await page.goto('/kiosk')
    await expect(page.getByTestId('kiosk-latest')).toContainText('American Crow')
    await expect(page.getByTestId('kiosk-latest')).toContainText('Mic 2')
    await expect(page.getByTestId('kiosk-total')).toHaveText('57')
    await expect(page.getByTestId('kiosk-species')).toHaveText('9')
    await expect(page.getByRole('meter')).toHaveCount(4)
    await expect(page.getByTestId('kiosk-services')).toContainText('2 of 2 services running')
    await expect(page.getByTestId('kiosk-weather')).toContainText('10°C')
    await expect(page.getByTestId('kiosk-status')).toHaveText('All systems normal')
    // Orpheus's own sound is not presented as wildlife.
    await expect(page.getByText('Played By Orpheus')).toHaveCount(0)
    // The snapshot is a saved file, loaded with the guest token as a blob.
    const img = page.getByAltText('Latest snapshot from orpheus-eye-1')
    await expect(img).toBeVisible()
    expect(await img.evaluate((el: HTMLImageElement) => el.src.startsWith('blob:') && el.naturalWidth > 0)).toBe(true)
    // One guest sign-in, and it never touched the live camera endpoint.
    expect(calls.guestLogins).toBe(1)
    expect(calls.paths.some((p) => /\/api\/cameras\/[^/]+\/snapshot/.test(p))).toBe(false)
    await expect(page).toHaveTitle('Orpheus · Kiosk')
  })

  test('keeps a signed-in operator session and its token separate', async ({ page }) => {
    await mockStation(page)
    await page.goto('/kiosk')
    await expect(page.getByTestId('kiosk-total')).toHaveText('57')
    const storage = await page.evaluate(() => ({
      operator: localStorage.getItem('orpheus_token'),
      kiosk: localStorage.getItem('orpheus_kiosk_token'),
    }))
    expect(storage).toEqual({ operator: null, kiosk: 'guest-token' })
  })

  test('asks for a viewer sign-in when guest viewing is off', async ({ page }) => {
    await mockStation(page, { guest: false })
    await page.goto('/kiosk')
    await expect(page.getByRole('heading', { name: 'This display needs a viewer sign-in' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login?next=%2Fkiosk')
  })

  test('flags services that are not running', async ({ page }) => {
    await mockStation(page, { servicesDown: true })
    await page.goto('/kiosk')
    await expect(page.getByTestId('kiosk-status')).toHaveText('1 service need attention')
    await expect(page.getByTestId('kiosk-system')).toContainText('Not running: orpheus-agent-audio-motion')
  })

  test('respects the panel selection', async ({ page }) => {
    await mockStation(page)
    await page.goto('/kiosk?panels=sightings,cameras')
    await expect(page.getByTestId('kiosk-sightings')).toBeVisible()
    await expect(page.getByTestId('kiosk-camera')).toBeVisible()
    await expect(page.getByTestId('kiosk-audio')).toHaveCount(0)
    await expect(page.getByTestId('kiosk-system')).toHaveCount(0)
  })

  for (const size of [
    { width: 800, height: 480, name: '7-inch 800x480' },
    { width: 1920, height: 1080, name: '1080p' },
  ]) {
    test(`fits a ${size.name} screen without scrolling`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height })
      await mockStation(page)
      await page.goto('/kiosk')
      await expect(page.getByTestId('kiosk-total')).toHaveText('57')
      const overflow = await page.evaluate(() => ({
        x: document.documentElement.scrollWidth - window.innerWidth,
        y: document.documentElement.scrollHeight - window.innerHeight,
      }))
      expect(overflow.x).toBeLessThanOrEqual(0)
      expect(overflow.y).toBeLessThanOrEqual(0)
      // Panels stay inside the screen and never overlap one another.
      const boxes = await page.locator('[data-testid="kiosk"] section').evaluateAll((els) =>
        els.map((el) => {
          const r = el.getBoundingClientRect()
          return { id: el.getAttribute('data-testid'), l: r.left, t: r.top, r: r.right, b: r.bottom }
        }),
      )
      expect(boxes.length).toBeGreaterThanOrEqual(4)
      for (const b of boxes) {
        expect(b.l).toBeGreaterThanOrEqual(0)
        expect(b.t).toBeGreaterThanOrEqual(0)
        expect(b.r).toBeLessThanOrEqual(size.width)
        expect(b.b).toBeLessThanOrEqual(size.height)
      }
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          const [a, c] = [boxes[i], boxes[j]]
          const overlap = a.l < c.r - 1 && c.l < a.r - 1 && a.t < c.b - 1 && c.t < a.b - 1
          expect(overlap, `${a.id} overlaps ${c.id}`).toBe(false)
        }
      }
      await expect(page.locator('[data-layout]')).toHaveAttribute('data-layout', size.width < 900 ? 'compact' : 'full')
      await page.screenshot({ path: `test-results/kiosk-${size.width}x${size.height}.png` })
    })
  }

  test('demo mode works with no backend at all', async ({ page }) => {
    let apiCalls = 0
    await page.route('**/api/**', (route) => {
      apiCalls++
      return route.abort()
    })
    await page.route('**/auth/**', (route) => route.abort())
    await page.goto('/kiosk?demo=1')
    await expect(page.getByTestId('kiosk-latest')).toBeVisible()
    await expect(page.getByText('Demo data — not from a station')).toBeVisible()
    // /api/config (the poll-interval bootstrap) may be tried; nothing else is.
    expect(apiCalls).toBeLessThanOrEqual(1)
  })
})
