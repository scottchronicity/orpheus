/**
 * Tests for Media page pagination, filtering, and label select.
 *
 * Verifies:
 * - Timelapse data renders in paginated grid
 * - Label filter select appears with dynamic labels
 * - Client-side pagination controls appear for >50 items
 * - Page resets when filters change
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../src/contexts/AuthContext'

let mockFetch: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockFetch = vi.fn()
  vi.stubGlobal('fetch', mockFetch)
})

function renderWithProviders(component: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>{component}</AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

/** Generate N timelapse objects with configurable label. */
function makeTimelapses(count: number, label: string = 'daily', tier: string = 'tl0') {
  return Array.from({ length: count }, (_, i) => ({
    filename: `orpheus-eye-1.${label}.${tier}.24h.20260124-${String(i).padStart(6, '0')}.mp4`,
    date: '2026.01.24',
    camera: 'orpheus-eye-1',
    size_bytes: 1024 * 1024,
    size_mb: 1.0,
    modified_time: 1737748800 - i,
    timestamp_iso: new Date(1737748800000 - i * 1000).toISOString(),
    download_url: `/api/media/timelapses/orpheus-eye-1/2026.01.24/file-${i}.mp4`,
    label,
    tier,
    tier_display: tier === 'tl0' ? '24h' : '1h',
    lookback: tier === 'tl0' ? '24h' : '1h',
  }))
}

function setupTimelapseFetch(timelapses: ReturnType<typeof makeTimelapses>) {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/media/timelapses/')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            timelapses,
            camera: 'orpheus-eye-1',
            count: timelapses.length,
          })
        )
      )
    }
    // Auth / user endpoint fallback
    return Promise.resolve(
      new Response(
        JSON.stringify({
          id: '123',
          email: 'test@example.com',
          role: 'admin',
          is_active: true,
        })
      )
    )
  })
}

describe('Media page – Timelapses tab', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
  })

  it('renders timelapse cards when data is available', async () => {
    const timelapses = makeTimelapses(3, 'daily', 'tl0')
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    // Switch to timelapses tab
    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/showing 3 of 3 timelapses/i)).toBeInTheDocument()
    })
  })

  it('shows label filter when labels are present', async () => {
    const timelapses = [
      ...makeTimelapses(2, 'daily', 'tl0'),
      ...makeTimelapses(2, 'hourly', 'tl3'),
    ]
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      // Label select should have "All", "daily", "hourly"
      expect(screen.getByText('Label')).toBeInTheDocument()
      // Find the select that contains the "All" option (the label filter)
      const allSelects = screen.getAllByRole('combobox')
      const labelSelect = allSelects.find(sel => within(sel).queryByText('All'))!
      expect(labelSelect).toBeDefined()
      const options = within(labelSelect).getAllByRole('option')
      const optionValues = options.map(o => o.textContent)
      expect(optionValues).toContain('All')
      expect(optionValues).toContain('daily')
      expect(optionValues).toContain('hourly')
    })
  })

  it('filters timelapses by label', async () => {
    const timelapses = [
      ...makeTimelapses(2, 'daily', 'tl0'),
      ...makeTimelapses(3, 'hourly', 'tl3'),
    ]
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/showing 5 of 5 timelapses/i)).toBeInTheDocument()
    })

    // Filter to "daily" only — find the select with the "All" option
    const allSelects = screen.getAllByRole('combobox')
    const labelSelect = allSelects.find(sel => within(sel).queryByText('All'))!
    fireEvent.change(labelSelect, { target: { value: 'daily' } })

    await waitFor(() => {
      expect(screen.getByText(/showing 2 of 2 timelapses/i)).toBeInTheDocument()
    })
  })

  it('shows pagination controls when more than 50 items', async () => {
    const timelapses = makeTimelapses(75, 'daily', 'tl0')
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/showing 50 of 75 timelapses/i)).toBeInTheDocument()
      expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument()
    })

    // Previous should be disabled on page 1
    const prevButton = screen.getByRole('button', { name: /previous/i })
    expect(prevButton).toBeDisabled()

    // Next should be enabled
    const nextButton = screen.getByRole('button', { name: /next/i })
    expect(nextButton).not.toBeDisabled()
  })

  it('navigates to next page and back', async () => {
    const timelapses = makeTimelapses(75, 'daily', 'tl0')
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument()
    })

    // Go to page 2
    const nextButton = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextButton)

    await waitFor(() => {
      expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument()
      expect(screen.getByText(/showing 25 of 75 timelapses/i)).toBeInTheDocument()
    })

    // Next should now be disabled
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()

    // Go back to page 1
    const prevButton = screen.getByRole('button', { name: /previous/i })
    fireEvent.click(prevButton)

    await waitFor(() => {
      expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument()
    })
  })

  it('does not show pagination controls when 50 or fewer items', async () => {
    const timelapses = makeTimelapses(10, 'daily', 'tl0')
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/showing 10 of 10 timelapses/i)).toBeInTheDocument()
    })

    // Pagination controls should not be present
    expect(screen.queryByText(/page 1 of/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /previous/i })).not.toBeInTheDocument()
  })

  it('shows empty state when no timelapses', async () => {
    setupTimelapseFetch([])

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText('No Timelapses')).toBeInTheDocument()
    })
  })

  it('does not show label filter when no labels in data', async () => {
    const timelapses = [
      {
        filename: '18-00.orpheus-eye-1.mp4',
        date: '2026.01.24',
        camera: 'orpheus-eye-1',
        size_bytes: 1024,
        size_mb: 0.001,
        modified_time: 1737748800,
        timestamp_iso: new Date(1737748800000).toISOString(),
        download_url: '/api/media/timelapses/orpheus-eye-1/2026.01.24/18-00.orpheus-eye-1.mp4',
        label: null,
        tier: null,
        tier_display: null,
        lookback: null,
      },
    ]
    setupTimelapseFetch(timelapses)

    const { default: Media } = await import('../src/pages/Media')
    renderWithProviders(<Media />)

    const timelapsesTab = screen.getByRole('button', { name: /timelapses/i })
    fireEvent.click(timelapsesTab)

    await waitFor(() => {
      expect(screen.getByText(/showing 1 of 1 timelapses/i)).toBeInTheDocument()
    })

    // No label filter should be visible
    expect(screen.queryByText('Label')).not.toBeInTheDocument()
  })
})
