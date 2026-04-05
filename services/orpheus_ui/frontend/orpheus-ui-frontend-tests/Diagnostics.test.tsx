/**
 * Tests for the Diagnostics page components (AudioHealthPanel, LogViewer).
 *
 * useQuery is mocked so each test can control the loading / error / success
 * state without a real QueryClient or network requests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

// jsdom does not implement scrollIntoView
Element.prototype.scrollIntoView = vi.fn()

// ---------------------------------------------------------------------------
// Mock @tanstack/react-query – we only need useQuery
// ---------------------------------------------------------------------------

const mockUseQuery = vi.fn()

vi.mock('@tanstack/react-query', () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}))

// Import components *after* the mock is in place
import { AudioHealthPanel, LogViewer } from '../src/pages/Diagnostics'

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderWrapped(ui: React.ReactNode) {
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// AudioHealthPanel
// ---------------------------------------------------------------------------

describe('AudioHealthPanel', () => {
  it('shows a loading spinner while data is loading', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: true, error: null })

    renderWrapped(<AudioHealthPanel />)

    // The LoadingSpinner renders an SVG with the "animate-spin" class
    expect(screen.getByText('Audio System Health')).toBeInTheDocument()
    expect(document.querySelector('.animate-spin')).not.toBeNull()
  })

  it('renders channel bars and agent status on success', () => {
    mockUseQuery.mockReturnValue({
      data: {
        running: true,
        health_status: 'good',
        channels: [
          { id: '1', active: true, level_db: -25, peak_db: -18, level_color: 'green', has_signal: true },
          { id: '2', active: false, level_db: -60, peak_db: -55, level_color: 'yellow', has_signal: false },
        ],
        xrun: { total: 3, rate_per_minute: 0.5 },
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<AudioHealthPanel />)

    // Title
    expect(screen.getByText('Audio System Health')).toBeInTheDocument()

    // Agent status
    expect(screen.getByText('Agent running')).toBeInTheDocument()

    // Health badge
    expect(screen.getByText('good')).toBeInTheDocument()

    // Channels – we always render 4 slots
    expect(screen.getByText('Ch 1')).toBeInTheDocument()
    expect(screen.getByText('Ch 2')).toBeInTheDocument()
    expect(screen.getByText('Ch 3')).toBeInTheDocument()
    expect(screen.getByText('Ch 4')).toBeInTheDocument()

    // Active channel shows TRIGGERED, inactive shows IDLE
    expect(screen.getByText('TRIGGERED')).toBeInTheDocument()
    expect(screen.getAllByText('IDLE').length).toBe(3)

    // dB readings
    expect(screen.getByText('Level: -25.0 dB')).toBeInTheDocument()
    expect(screen.getByText('Peak: -18.0 dB')).toBeInTheDocument()

    // XRUN counter
    expect(screen.getByText(/XRUNs: 3/)).toBeInTheDocument()
    expect(screen.getByText(/0\.5\/min/)).toBeInTheDocument()
  })

  it('shows "Agent not running" with a custom message when agent is stopped', () => {
    mockUseQuery.mockReturnValue({
      data: {
        running: false,
        message: 'Service unavailable',
        channels: [],
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<AudioHealthPanel />)

    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
  })

  it('handles channels with undefined level_db and peak_db without crashing', () => {
    mockUseQuery.mockReturnValue({
      data: {
        running: true,
        channels: [
          { id: '1', active: true, level_db: undefined, peak_db: undefined, level_color: 'green', has_signal: true },
          { id: '2', active: false, level_db: null, peak_db: null, level_color: 'none', has_signal: false },
        ],
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<AudioHealthPanel />)

    // Should render without crashing and show '--' for missing dB values
    expect(screen.getByText('Ch 1')).toBeInTheDocument()
    expect(screen.getByText('Ch 2')).toBeInTheDocument()
    expect(screen.getAllByText('Level: --').length).toBe(4) // 2 from data + 2 placeholders
    expect(screen.getAllByText('Peak: --').length).toBe(4)
  })

  it('renders placeholder channels when data has no channels', () => {
    mockUseQuery.mockReturnValue({
      data: { running: false, channels: [] },
      isLoading: false,
      error: null,
    })

    renderWrapped(<AudioHealthPanel />)

    // All 4 placeholder channels rendered with IDLE and "--" dB
    expect(screen.getAllByText('IDLE').length).toBe(4)
    expect(screen.getAllByText('Level: --').length).toBe(4)
    expect(screen.getAllByText('Peak: --').length).toBe(4)
  })
})

// ---------------------------------------------------------------------------
// LogViewer
// ---------------------------------------------------------------------------

describe('LogViewer', () => {
  it('shows prompt text when no service is selected', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: false, error: null })

    renderWrapped(<LogViewer />)

    expect(screen.getByText('Service Logs')).toBeInTheDocument()
    expect(screen.getByText('Select a service to view logs.')).toBeInTheDocument()
  })

  it('shows an error message when the query fails', () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Connection refused'),
    })

    renderWrapped(<LogViewer />)

    // Select a service to trigger the query
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'orpheus-agent-audio-motion' } })

    expect(screen.getByText(/Failed to fetch logs/)).toBeInTheDocument()
    expect(screen.getByText(/Connection refused/)).toBeInTheDocument()
  })

  it('renders log lines on successful fetch', () => {
    mockUseQuery.mockReturnValue({
      data: {
        service_name: 'orpheus-agent-audio-motion',
        lines: ['Jan 01 INFO Starting agent', 'Jan 01 INFO Listening on MQTT'],
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<LogViewer />)

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'orpheus-agent-audio-motion' } })

    expect(screen.getByText('Jan 01 INFO Starting agent')).toBeInTheDocument()
    expect(screen.getByText('Jan 01 INFO Listening on MQTT')).toBeInTheDocument()
  })

  it('shows empty-state text when lines array is empty', () => {
    mockUseQuery.mockReturnValue({
      data: { service_name: 'svc', lines: [] },
      isLoading: false,
      error: null,
    })

    renderWrapped(<LogViewer />)

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'orpheus-agent-audio-motion' } })

    expect(screen.getByText('No log output available.')).toBeInTheDocument()
  })
})
