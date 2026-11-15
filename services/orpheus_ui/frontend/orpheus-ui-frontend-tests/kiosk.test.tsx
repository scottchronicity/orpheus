/**
 * Kiosk display (/kiosk): settings, formatting, the kiosk's own fetch/session
 * handling, and rendering against controllable APIs. Network calls are mocked
 * (global fetch, or a fake KioskApi); the real-browser checks live in
 * e2e/kiosk.spec.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { DEFAULT_KIOSK_SETTINGS, isNightHour, parseKioskSettings } from '../src/kiosk/settings'
import { channelLabel, entityKind, meterFraction, timeAgo, uptime } from '../src/kiosk/format'
import {
  KIOSK_TOKEN_KEY,
  KioskAuthError,
  demoApi,
  kioskFetch,
  liveApi,
  resetKioskSessionForTests,
  utcFolderDate,
  type KioskApi,
} from '../src/kiosk/kioskApi'
import { KioskView } from '../src/kiosk/KioskPage'
import KioskPage from '../src/kiosk/KioskPage'

// ---------------------------------------------------------------------------
// settings
// ---------------------------------------------------------------------------
describe('parseKioskSettings', () => {
  it('defaults to every panel and safe values', () => {
    expect(parseKioskSettings('')).toEqual(DEFAULT_KIOSK_SETTINGS)
  })

  it('keeps only known panels, in the given order, without duplicates', () => {
    expect(parseKioskSettings('?panels=cameras,bogus,sightings,cameras').panels).toEqual([
      'cameras',
      'sightings',
    ])
    expect(parseKioskSettings('?panels=bogus').panels).toEqual(DEFAULT_KIOSK_SETTINGS.panels)
  })

  it('clamps numbers and ignores garbage', () => {
    const s = parseKioskSettings('?rotate=1&hours=9999&scale=abc')
    expect(s.rotateSeconds).toBe(5)
    expect(s.windowHours).toBe(168)
    expect(s.scale).toBe(1)
  })

  it('accepts only path-safe camera names', () => {
    expect(parseKioskSettings('?cameras=orpheus-eye-1,../etc,eye_2').cameras).toEqual([
      'orpheus-eye-1',
      'eye_2',
    ])
    expect(parseKioskSettings('?cameras=').cameras).toBeNull()
  })

  it('parses flags and the night window', () => {
    const s = parseKioskSettings('?self=1&shift=0&demo=yes&night=22-6')
    expect(s.includeSelfGenerated).toBe(true)
    expect(s.burnInShift).toBe(false)
    expect(s.demo).toBe(true)
    expect(s.night).toEqual({ startHour: 22, endHour: 6 })
    expect(parseKioskSettings('?night=25-3').night).toBeNull()
    expect(parseKioskSettings('?night=5-5').night).toBeNull()
  })

  it('handles night windows that wrap midnight and ones that do not', () => {
    const wrap = { startHour: 22, endHour: 6 }
    expect([21, 22, 23, 0, 5, 6].map((h) => isNightHour(wrap, h))).toEqual([false, true, true, true, true, false])
    const day = { startHour: 1, endHour: 4 }
    expect([0, 1, 3, 4].map((h) => isNightHour(day, h))).toEqual([false, true, true, false])
    expect(isNightHour(null, 2)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// format
// ---------------------------------------------------------------------------
describe('kiosk formatting', () => {
  const now = Date.parse('2026-11-14T12:00:00Z')
  it('describes ages briefly', () => {
    expect(timeAgo('2026-11-14T11:59:40Z', now)).toBe('just now')
    expect(timeAgo('2026-11-14T11:50:00Z', now)).toBe('10 min ago')
    expect(timeAgo('2026-11-14T09:00:00Z', now)).toBe('3 h ago')
    expect(timeAgo('2026-11-12T12:00:00Z', now)).toBe('2 d ago')
    expect(timeAgo('garbage', now)).toBe('')
  })
  it('maps dBFS onto a meter and labels channels', () => {
    expect(meterFraction(-80)).toBe(0)
    expect(meterFraction(-30)).toBeCloseTo(0.5)
    expect(meterFraction(3)).toBe(1)
    expect(channelLabel('channel_3')).toBe('Mic 3')
    expect(channelLabel('2')).toBe('Mic 2')
  })
  it('classifies entity types and formats uptime', () => {
    expect(entityKind('Animal.Bird.Crow')).toBe('bird')
    expect(entityKind('Animal.Mammal')).toBe('animal')
    expect(entityKind(null)).toBe('sound')
    expect(uptime(90061)).toBe('1 d 1 h')
    expect(uptime(3700)).toBe('1 h 1 min')
  })
})

// ---------------------------------------------------------------------------
// kioskFetch: guest session handling
// ---------------------------------------------------------------------------
function jsonResponse(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('kioskFetch', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    localStorage.clear()
    resetKioskSessionForTests()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  const authOf = (call: unknown[]) =>
    ((call[1] as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.Authorization

  it("uses an operator's session when one exists", async () => {
    localStorage.setItem('orpheus_token', 'operator')
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }))
    await kioskFetch('/api/health')
    expect(authOf(fetchMock.mock.calls[0])).toBe('Bearer operator')
  })

  it('signs in as the guest on 401 and retries once, never redirecting', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'guest-1' }))
      .mockResolvedValueOnce(jsonResponse(200, { status: 'healthy' }))
    const res = await kioskFetch('/api/health')
    expect(res.status).toBe(200)
    expect(fetchMock.mock.calls[1][0]).toBe('/auth/guest-login')
    expect(authOf(fetchMock.mock.calls[2])).toBe('Bearer guest-1')
    expect(localStorage.getItem(KIOSK_TOKEN_KEY)).toBe('guest-1')
    expect(window.location.pathname).not.toBe('/login')
  })

  it("never deletes an operator's expired token, and stops sending it", async () => {
    localStorage.setItem('orpheus_token', 'expired-operator')
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'guest-2' }))
      .mockResolvedValueOnce(jsonResponse(200))
      .mockResolvedValueOnce(jsonResponse(200))
    await kioskFetch('/api/health')
    await kioskFetch('/api/health')
    expect(localStorage.getItem('orpheus_token')).toBe('expired-operator')
    expect(authOf(fetchMock.mock.calls[2])).toBe('Bearer guest-2')
    expect(authOf(fetchMock.mock.calls[3])).toBe('Bearer guest-2')
  })

  it('reports KioskAuthError when guest viewing is off', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(403))
    await expect(kioskFetch('/api/health')).rejects.toBeInstanceOf(KioskAuthError)
  })

  it('shares one guest sign-in between concurrent requests', async () => {
    let guestCalls = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/auth/guest-login') {
        guestCalls++
        return jsonResponse(200, { access_token: 'guest-3' })
      }
      const auth = (init?.headers as Record<string, string>)?.Authorization
      return auth === 'Bearer guest-3' ? jsonResponse(200) : jsonResponse(401)
    })
    await Promise.all([kioskFetch('/api/a'), kioskFetch('/api/b'), kioskFetch('/api/c')])
    expect(guestCalls).toBe(1)
  })

  it("falls back to yesterday's snapshot folder just after UTC midnight", async () => {
    localStorage.setItem('orpheus_token', 'operator')
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { snapshots: [] }))
      .mockResolvedValueOnce(
        jsonResponse(200, { snapshots: [{ filename: 'a.cam.jpg', timestamp_iso: 'x', download_url: '/u' }] }),
      )
    const snap = await liveApi.latestSnapshot('cam')
    expect(snap?.filename).toBe('a.cam.jpg')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/media/snapshots/cam?limit=1')
    expect(fetchMock.mock.calls[1][0]).toMatch(/^\/api\/media\/snapshots\/cam\?limit=1&date=\d{4}\.\d{2}\.\d{2}$/)
  })

  it('names snapshot folders by UTC date', () => {
    expect(utcFolderDate(new Date('2026-11-14T23:30:00-05:00'))).toBe('2026.11.15')
  })

  it('asks the entities endpoint for a bounded, local-time window', async () => {
    localStorage.setItem('orpheus_token', 'operator')
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { entities: [], count: 0, stats: {} }))
    await liveApi.entities(24, 12)
    const url = new URL(fetchMock.mock.calls[0][0] as string, 'http://x')
    expect(url.pathname).toBe('/api/entities')
    expect(url.searchParams.get('page')).toBe('1')
    expect(url.searchParams.get('page_size')).toBe('12')
    expect(Date.now() - Date.parse(url.searchParams.get('start_date') as string)).toBeGreaterThan(23.9 * 3600_000)
  })
})

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------
function renderView(api: KioskApi, search = '') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/kiosk${search}`]}>
        <KioskView api={api} settings={parseKioskSettings(search)} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('KioskView', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { revokeObjectURL: vi.fn() }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows sightings, counts, microphones, a camera and the station', async () => {
    renderView(demoApi, '?demo=1')
    const latest = await screen.findByTestId('kiosk-latest')
    expect(latest.textContent).toMatch(/confident/)
    expect(await screen.findByTestId('kiosk-total')).not.toHaveTextContent('—')
    expect(screen.getByTestId('kiosk-species')).not.toHaveTextContent('—')
    expect(await screen.findAllByRole('meter')).toHaveLength(4)
    expect(await screen.findByAltText(/Latest snapshot from orpheus-eye-1/)).toBeInTheDocument()
    expect(await screen.findByTestId('kiosk-services')).toHaveTextContent('10 of 10 services running')
    expect(screen.getByTestId('kiosk-status')).toHaveTextContent('All systems normal')
    expect(screen.getByText('Demo data — not from a station')).toBeInTheDocument()
  })

  it("hides Orpheus's own sounds unless asked", async () => {
    const own = {
      entity_id: 'own',
      timestamp: new Date().toISOString(),
      species_code: 'x',
      common_name: 'Played By Orpheus',
      confidence: 0.9,
      is_self_generated: true,
    }
    const api: KioskApi = {
      ...demoApi,
      entities: async () => ({ entities: [own], count: 1, stats: { total_count: 1, unique_species_count: 1, hourly_activity: [], species_distribution: {} } }),
    }
    renderView(api)
    expect(await screen.findByText('Nothing heard yet in this window.')).toBeInTheDocument()
    renderView(api, '?self=1')
    expect(await screen.findByText('Played By Orpheus')).toBeInTheDocument()
  })

  it('renders only the chosen panels', async () => {
    renderView(demoApi, '?panels=audio,system')
    await screen.findByTestId('kiosk-audio')
    expect(screen.getByTestId('kiosk-system')).toBeInTheDocument()
    expect(screen.queryByTestId('kiosk-sightings')).not.toBeInTheDocument()
    expect(screen.queryByTestId('kiosk-camera')).not.toBeInTheDocument()
  })

  it('says when the station is unreachable', { timeout: 12000 }, async () => {
    const down = () => Promise.reject(new Error('503'))
    const api: KioskApi = { ...demoApi, health: down, services: down, audio: down, entities: down }
    renderView(api)
    // The page retries twice with backoff before reporting the failure.
    await waitFor(() => expect(screen.getByTestId('kiosk-status')).toHaveTextContent('Station unreachable'), {
      timeout: 8000,
    })
  })

  it('names services that are not running', async () => {
    const api: KioskApi = {
      ...demoApi,
      services: async () => ({ services: [{ name: 'orpheus-ui', status: 'active' }, { name: 'orpheus-agent-audio-motion', status: 'failed' }] }),
    }
    renderView(api)
    const system = await screen.findByTestId('kiosk-system')
    await waitFor(() => expect(within(system).getByText(/Not running: orpheus-agent-audio-motion/)).toBeInTheDocument())
    expect(screen.getByTestId('kiosk-status')).toHaveTextContent('1 service need attention')
  })

  it('reports a station with no cameras', async () => {
    renderView({ ...demoApi, cameras: async () => [] })
    expect(await screen.findByText('No cameras configured')).toBeInTheDocument()
  })

  it('dims at night', async () => {
    const hour = new Date().getHours()
    renderView(demoApi, `?night=${hour}-${(hour + 1) % 24}`)
    expect((await screen.findByTestId('kiosk')).dataset.night).toBe('true')
  })
})

describe('KioskPage session', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    localStorage.clear()
    resetKioskSessionForTests()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function renderPage(search: string) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/kiosk${search}`]}>
          <Routes>
            <Route path="/kiosk" element={<KioskPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('asks for a viewer sign-in when guest viewing is off', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(403))
    renderPage('')
    expect(await screen.findByText('This display needs a viewer sign-in')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login?next=%2Fkiosk')
  })

  it('demo mode never touches the network', async () => {
    renderPage('?demo=1')
    expect(await screen.findByTestId('kiosk')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
