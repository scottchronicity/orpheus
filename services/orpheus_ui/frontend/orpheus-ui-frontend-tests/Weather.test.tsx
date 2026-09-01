/**
 * Tests for the Dashboard WeatherCard.
 *
 * useQuery is mocked so each test can control the loading / success state
 * without a real QueryClient or network requests (same pattern as
 * Diagnostics.test.tsx). The card's contract: render nothing at all unless the
 * backend reports available:true (most deploys have no weather station).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

// ---------------------------------------------------------------------------
// Mock @tanstack/react-query – we only need useQuery
// ---------------------------------------------------------------------------

const mockUseQuery = vi.fn()

vi.mock('@tanstack/react-query', () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}))

// Import components *after* the mock is in place
import { WeatherCard } from '../src/pages/Dashboard'
import { formatDateTime } from '../src/lib/utils'
import { POLLING_INTERVALS } from '../src/config'

function renderWrapped(ui: React.ReactNode) {
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('WeatherCard', () => {
  it('renders nothing when the endpoint reports unavailable', () => {
    mockUseQuery.mockReturnValue({
      data: { available: false },
      isLoading: false,
      error: null,
    })

    const { container } = renderWrapped(<WeatherCard />)

    expect(container.firstChild).toBeNull()
    expect(screen.queryByText('Weather')).not.toBeInTheDocument()
  })

  it('renders nothing while loading (no data yet)', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: true, error: null })

    const { container } = renderWrapped(<WeatherCard />)

    expect(container.firstChild).toBeNull()
  })

  it('shows temperature, humidity, wind and a formatted reading timestamp when available', () => {
    // A fresh reading (1 min old) is presented as current conditions.
    const timestamp = new Date(Date.now() - 60_000).toISOString()
    mockUseQuery.mockReturnValue({
      data: {
        available: true,
        temperature_c: 12.5,
        humidity_pct: 81,
        pressure_hpa: 1013.2,
        wind_speed_mps: 3.4,
        wind_direction_deg: 270,
        rainfall_mm: 0.2,
        timestamp,
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<WeatherCard />)

    expect(screen.getByText('Weather')).toBeInTheDocument()
    expect(screen.getByText('12.5 °C')).toBeInTheDocument()
    expect(screen.getByText('81 %')).toBeInTheDocument()
    expect(screen.getByText('3.4 m/s')).toBeInTheDocument()
    // Locale-formatted via formatDateTime, not the raw ISO string.
    expect(screen.getByText(`Reading from ${formatDateTime(timestamp)}`)).toBeInTheDocument()
    expect(screen.queryByText(/Stale/)).not.toBeInTheDocument()
  })

  it('flags a reading older than 15 minutes as stale instead of presenting it as current', () => {
    const timestamp = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
    mockUseQuery.mockReturnValue({
      data: {
        available: true,
        temperature_c: 12.5,
        timestamp,
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<WeatherCard />)

    expect(
      screen.getByText(`Stale — last reading ${formatDateTime(timestamp)}`),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Reading from/)).not.toBeInTheDocument()
  })

  it('backs off polling to 60s when the feature reports unavailable', () => {
    mockUseQuery.mockReturnValue({
      data: { available: false },
      isLoading: false,
      error: null,
    })

    renderWrapped(<WeatherCard />)

    const opts = mockUseQuery.mock.calls[0][0] as {
      refetchInterval: (q: { state: { data?: { available: boolean } } }) => number
    }
    expect(typeof opts.refetchInterval).toBe('function')
    expect(opts.refetchInterval({ state: { data: { available: false } } })).toBe(60_000)
    expect(opts.refetchInterval({ state: { data: { available: true } } })).toBe(
      POLLING_INTERVALS.HEALTH,
    )
    // No data yet (first fetch pending) → keep the HEALTH cadence.
    expect(opts.refetchInterval({ state: {} })).toBe(POLLING_INTERVALS.HEALTH)
  })

  it('shows -- for readings a partial sensor did not report', () => {
    mockUseQuery.mockReturnValue({
      data: {
        available: true,
        temperature_c: 5.0,
        humidity_pct: null,
        wind_speed_mps: null,
        timestamp: '2026-07-01T06:00:00+00:00',
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<WeatherCard />)

    expect(screen.getByText('5.0 °C')).toBeInTheDocument()
    // humidity + wind both missing
    expect(screen.getAllByText('--').length).toBe(2)
  })
})
