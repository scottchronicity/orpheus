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

  it('shows default credentials hint for development', async () => {
    const { default: Login } = await import('../src/pages/Login')
    renderWithProviders(<Login />)

    expect(screen.getByText(/guest@orpheus\.example\.com/)).toBeInTheDocument()
    expect(screen.getByText(/admin@orpheus\.example\.com/)).toBeInTheDocument()
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

    // All navigation items should be present
    const navItems = ['dashboard', 'entities', 'birds', 'crows', 'cameras', 'audio', 'video', 'settings']
    for (const item of navItems) {
      expect(screen.getByRole('link', { name: new RegExp(item, 'i') })).toBeInTheDocument()
    }
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

describe('BirdEntitySection', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
  })

  it('does not crash when API returns a 500 error body', async () => {
    // Simulate the CI failure: /api/entities returns 500 with { detail: "..." }
    // instead of { entities: [...] }. The component must not throw.
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Failed to get entities: unable to open database' }), { status: 500 })
    )

    const { BirdEntitySection } = await import('../src/components/BirdEntitySection')
    expect(() => renderWithProviders(
      <BirdEntitySection startDate="2026-01-01" endDate="2026-01-07" />
    )).not.toThrow()

    // Should show loading/empty state, not blow up the page
    await waitFor(() => {
      expect(screen.queryByText(/loading entity data/i)).toBeInTheDocument()
    })
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
