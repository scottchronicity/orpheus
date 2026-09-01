/**
 * Tests for page components and app structure.
 * 
 * These tests verify:
 * - Pages render correctly with mocked data
 * - Data fetching hooks are called
 * - Components compose shared UI correctly
 * 
 * NOTE: These are unit tests with mocked fetch.
 * For real user interaction flows, see e2e/navigation.spec.ts
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../src/contexts/AuthContext'

// Create a fresh mock for each test file
let mockFetch: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockFetch = vi.fn()
  vi.stubGlobal('fetch', mockFetch)
})

/**
 * Render helper with all required providers.
 */
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

describe('App', () => {
  it('exports a valid React component', async () => {
    const { default: App } = await import('../src/App')
    expect(typeof App).toBe('function')
  })
})

describe('Login page', () => {
  it('renders email and password inputs', async () => {
    const { default: Login } = await import('../src/pages/Login')
    renderWithProviders(<Login />)

    // Look for inputs by their labels, not placeholders
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
  })

  it('renders sign in button', async () => {
    const { default: Login } = await import('../src/pages/Login')
    renderWithProviders(<Login />)

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in as Guest' })).toBeInTheDocument()
  })

  it('never displays account credentials', async () => {
    const { default: Login } = await import('../src/pages/Login')
    const { container } = renderWithProviders(<Login />)

    // The page used to print working logins for anyone who could reach it.
    expect(container.textContent).not.toMatch(/guest@orpheus\.example\.com/)
    expect(container.textContent).not.toMatch(/admin@orpheus\.example\.com/)
    expect(container.textContent).not.toContain('changeme')
  })
})

describe('Layout', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({
        id: '123',
        email: 'test@example.com',
        role: 'admin',
        is_active: true,
      }))
    )
  })

  it('renders navigation with all menu items', async () => {
    const { default: Layout } = await import('../src/components/Layout')
    renderWithProviders(<Layout><div>Content</div></Layout>)

    // All navigation items should be present. Use exact names where needed
    // to avoid ambiguity (e.g. "audio" matches both "Audio" and "Audio Events").
    const navItems = ['dashboard', 'entities', 'birds', 'crows', 'cameras', 'video', 'settings']
    for (const item of navItems) {
      expect(screen.getByRole('link', { name: new RegExp(item, 'i') })).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: 'Audio' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Audio Events' })).toBeInTheDocument()
  })

  it('renders children in content area', async () => {
    const { default: Layout } = await import('../src/components/Layout')
    renderWithProviders(<Layout><div data-testid="content">Page Content</div></Layout>)

    expect(screen.getByTestId('content')).toBeInTheDocument()
  })
})

describe('Dashboard page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/health')) {
        return Promise.resolve(new Response(JSON.stringify({
          status: 'ok',
          cpu_percent: 25,
          memory_percent: 50,
          disk_percent: 30,
          uptime_seconds: 86400,
        })))
      }
      if (url.includes('/api/services/status')) {
        return Promise.resolve(new Response(JSON.stringify({
          services: [{ name: 'orpheus-ui', status: 'running', reason: '' }],
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({ running: true })))
    })
  })

  it('renders page header', async () => {
    const { default: Dashboard } = await import('../src/pages/Dashboard')
    renderWithProviders(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /dashboard/i })).toBeInTheDocument()
    })
  })

  it('fetches health data on mount', async () => {
    const { default: Dashboard } = await import('../src/pages/Dashboard')
    renderWithProviders(<Dashboard />)

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/health'),
        expect.any(Object)
      )
    })
  })
})

describe('Settings page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({
        id: '123',
        email: 'admin@example.com',
        role: 'admin',
        is_active: true,
      }))
    )
  })

  it('renders account section', async () => {
    const { default: Settings } = await import('../src/pages/Settings')
    renderWithProviders(<Settings />)

    expect(screen.getByText(/account/i)).toBeInTheDocument()
  })
})

describe('Birds page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/entities')) {
        return Promise.resolve(new Response(JSON.stringify({
          entities: [],
          count: 0,
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({
        detections: [],
        count: 0,
        filtered_count: 0,
        start_date: '2025-01-01',
        end_date: '2025-01-07',
      })))
    })
  })

  it('renders page header', async () => {
    const { default: Birds } = await import('../src/pages/Birds')
    renderWithProviders(<Birds />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /bird detections/i })).toBeInTheDocument()
    })
  })
})

describe('Crows page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/entities')) {
        return Promise.resolve(new Response(JSON.stringify({
          entities: [],
          count: 0,
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({
        total_detections: 42,
        age_distribution: { adult: 30, juvenile: 12 },
        hourly_activity: Array.from({ length: 24 }, (_, i) => ({ hour: i, count: i % 5 })),
        call_types: { alert: 20, contact: 15, territory: 7 },
        intents: { warning: 10, greeting: 5 },
        start_date: '2025-01-01',
        end_date: '2025-01-07',
      })))
    })
  })

  it('renders page header', async () => {
    const { default: Crows } = await import('../src/pages/Crows')
    renderWithProviders(<Crows />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /crow analysis/i })).toBeInTheDocument()
    })
  })
})

describe('AudioEvents page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/data/audio-events/history')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detections: [
                {
                  timestamp: '2026-05-21T12:00:00Z',
                  species_code: 'audioset_/m/0bt9lr',
                  species_common: 'Dog',
                  confidence: 0.85,
                  channel: 1,
                  intervals: [
                    { start_seconds: 1.0, end_seconds: 2.5, confidence: 0.85 },
                  ],
                  taxonomy: {
                    namespace: 'audioset',
                    id: '/m/0bt9lr',
                    common_name: 'Dog',
                  },
                },
              ],
              count: 1,
              start_date: '2025-01-01',
              end_date: '2025-01-07',
              stats: {
                total_count: 1,
                unique_label_count: 1,
                hourly_activity: Array.from({ length: 24 }, (_, h) => ({ hour: h, count: 0 })),
                daily_activity: [],
                label_distribution: { Dog: 1 },
                all_labels: { Dog: 1 },
              },
              page: 1,
              page_size: 100,
              total_pages: 1,
            }),
          ),
        )
      }
      if (url.includes('/api/data/audio-events/bird-correlation')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              start_date: '2025-01-01',
              end_date: '2025-01-07',
              daily_counts: [
                {
                  date: '2025-01-01',
                  audio_motion_count: 10,
                  both: 6,
                  audio_events_only: 1,
                  birdnet_only: 2,
                  neither: 1,
                },
              ],
              summary: {
                audio_motion_count: 10,
                birdnet_caught_count: 8,
                audio_events_caught_count: 7,
                both_count: 6,
                audio_events_only_count: 1,
                birdnet_only_count: 2,
                neither_count: 1,
                parity_ratio: 0.875,
                ready_to_gate: false,
              },
              birdnet_only_clips: [],
            }),
          ),
        )
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })
  })

  it('renders page header', async () => {
    const { default: AudioEvents } = await import('../src/pages/AudioEvents')
    renderWithProviders(<AudioEvents />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /audio events/i })).toBeInTheDocument()
    })
  })

  it('renders a detection row with the label and intervals chip', async () => {
    const { default: AudioEvents } = await import('../src/pages/AudioEvents')
    renderWithProviders(<AudioEvents />)

    await waitFor(() => {
      // The label name appears in the table
      const cells = screen.getAllByText(/dog/i)
      expect(cells.length).toBeGreaterThanOrEqual(1)
    })
    // The intervals cell rendered the chip with a start-second value
    expect(screen.getByText(/1\.0s/)).toBeInTheDocument()
  })

  it('renders the Bird Correlation panel with parity ratio', async () => {
    const { default: AudioEvents } = await import('../src/pages/AudioEvents')
    renderWithProviders(<AudioEvents />)

    await waitFor(() => {
      // Wait for the parity ratio text — it only appears AFTER the panel
      // finishes its react-query load (the title text is present even in
      // the loading state, so don't wait on it).
      expect(screen.getByText(/88%/)).toBeInTheDocument()
    })
    // ready_to_gate=false → shows "Not ready" not "Ready to gate".
    expect(screen.getByText(/not ready/i)).toBeInTheDocument()
    // The panel title is also visible.
    expect(screen.getByText(/bird correlation vs birdnet/i)).toBeInTheDocument()
  })
})

describe('CrowEntitySection', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
  })

  it('does not crash when API returns a 500 error body', async () => {
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Failed to get entities: unable to open database' }), { status: 500 })
    )

    const { CrowEntitySection } = await import('../src/components/CrowEntitySection')
    expect(() => renderWithProviders(
      <CrowEntitySection startDate="2026-01-01" endDate="2026-01-07" />
    )).not.toThrow()

    await waitFor(() => {
      expect(screen.queryByText(/loading entity data/i)).toBeInTheDocument()
    })
  })
})

describe('Entities page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/entities')) {
        return Promise.resolve(new Response(JSON.stringify({
          entities: [],
          count: 0,
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({
        id: '123',
        email: 'test@example.com',
        role: 'admin',
        is_active: true,
      })))
    })
  })

  it('renders page header', async () => {
    const { default: Entities } = await import('../src/pages/Entities')
    renderWithProviders(<Entities />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /entities/i })).toBeInTheDocument()
    })
  })

  it('shows empty state message when no entities', async () => {
    const { default: Entities } = await import('../src/pages/Entities')
    renderWithProviders(<Entities />)

    await waitFor(() => {
      expect(screen.getByText(/no entity events yet/i)).toBeInTheDocument()
    })
  })
})


describe('Equivalences page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/equivalences')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              accepted: [
                {
                  a: { namespace: 'ioc', id: 'Corvus brachyrhynchos' },
                  b: { namespace: 'audioset', id: '/m/04s8yn' },
                  confidence: 1.0,
                  source: 'auto_discovered',
                  status: 'accepted',
                  created_at: '2026-01-01T12:00:00Z',
                  notes: null,
                },
              ],
              pending_review: [
                {
                  a: { namespace: 'ioc', id: 'Turdus migratorius' },
                  b: { namespace: 'audioset', id: '/m/020bb7' },
                  confidence: 0.72,
                  source: 'auto_discovered',
                  status: 'pending_review',
                  created_at: '2026-01-02T12:00:00Z',
                  notes: 'jaccard=0.72 cooc=8',
                },
              ],
              non_equivalences: [],
              counts: { accepted: 1, pending_review: 1, non_equivalences: 0 },
            }),
          ),
        )
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })
  })

  it('renders page header', async () => {
    const { default: Equivalences } = await import('../src/pages/Equivalences')
    renderWithProviders(<Equivalences />)
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { level: 1, name: /equivalences/i }),
      ).toBeInTheDocument()
    })
  })

  it('renders accepted + pending sections with content', async () => {
    const { default: Equivalences } = await import('../src/pages/Equivalences')
    renderWithProviders(<Equivalences />)

    // The label appears both in the intro description AND in the
    // rendered row — use getAllByText to handle the multi-match.
    await waitFor(() => {
      const crowMatches = screen.getAllByText(/ioc:Corvus brachyrhynchos/)
      expect(crowMatches.length).toBeGreaterThanOrEqual(1)
    })
    // Pending row's data also rendered (Turdus only appears in mock data).
    expect(screen.getByText(/ioc:Turdus migratorius/)).toBeInTheDocument()
    // Action buttons on the pending row.
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument()
  })

  it('shows background worker last-scan status when available', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/auto-discovery/status')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: 'ok',
              ran_at: '2026-05-22T03:30:11+00:00',
              total_proposals: 5,
              recorded: 3,
              skipped_existing: 1,
              skipped_blocked: 1,
              lifetime_runs: 12,
              lifetime_proposals: 14,
            }),
          ),
        )
      }
      if (url.includes('/api/equivalences')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              accepted: [],
              pending_review: [],
              non_equivalences: [],
              counts: { accepted: 0, pending_review: 0, non_equivalences: 0 },
            }),
          ),
        )
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })

    const { default: Equivalences } = await import('../src/pages/Equivalences')
    renderWithProviders(<Equivalences />)

    await waitFor(() => {
      expect(screen.getByText(/Last scan:/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/2026-05-22T03:30:11/)).toBeInTheDocument()
    expect(screen.getByText(/3 recorded/i)).toBeInTheDocument()
    expect(screen.getByText(/12 runs/i)).toBeInTheDocument()
  })
})
