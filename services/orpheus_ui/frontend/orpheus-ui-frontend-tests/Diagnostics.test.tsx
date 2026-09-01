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
import {
  AudioHealthPanel,
  LogViewer,
  PresencePanel,
  StorageHeadroomPanel,
} from '../src/pages/Diagnostics'
import { POLLING_INTERVALS } from '../src/config'

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

    // Channels – exactly the reported ones (no phantom placeholder slots
    // when the agent reports a real channel list, e.g. 1 mic on a laptop)
    expect(screen.getByText('Ch 1')).toBeInTheDocument()
    expect(screen.getByText('Ch 2')).toBeInTheDocument()
    expect(screen.queryByText('Ch 3')).not.toBeInTheDocument()
    expect(screen.queryByText('Ch 4')).not.toBeInTheDocument()

    // Active channel shows TRIGGERED, inactive shows IDLE
    expect(screen.getByText('TRIGGERED')).toBeInTheDocument()
    expect(screen.getAllByText('IDLE').length).toBe(1)

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
    expect(screen.getAllByText('Level: --').length).toBe(2) // both reported channels
    expect(screen.getAllByText('Peak: --').length).toBe(2)
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

// ---------------------------------------------------------------------------
// PresencePanel
// ---------------------------------------------------------------------------

describe('PresencePanel', () => {
  it('shows a muted note when presence is not supported', () => {
    mockUseQuery.mockReturnValue({
      data: { supported: false, agents: {} },
      isLoading: false,
      error: null,
    })

    renderWrapped(<PresencePanel />)

    expect(screen.getByText('Agent presence')).toBeInTheDocument()
    expect(
      screen.getByText('Presence not available on this backend/config.'),
    ).toBeInTheDocument()
  })

  it('lists live agents sorted, each marked online', () => {
    mockUseQuery.mockReturnValue({
      data: {
        supported: true,
        agents: {
          'orpheus-agent-event-correlator': { status: 'online' },
          'orpheus-agent-audio-motion': { status: 'online' },
        },
      },
      isLoading: false,
      error: null,
    })

    renderWrapped(<PresencePanel />)

    expect(screen.getByText('orpheus-agent-audio-motion')).toBeInTheDocument()
    expect(screen.getByText('orpheus-agent-event-correlator')).toBeInTheDocument()
    expect(screen.getAllByText('online').length).toBe(2)
    // Sorted: audio-motion renders before event-correlator
    const rendered = screen.getAllByText(/orpheus-agent-/).map((el) => el.textContent)
    expect(rendered).toEqual([
      'orpheus-agent-audio-motion',
      'orpheus-agent-event-correlator',
    ])
  })

  it('shows an empty state when the bucket has no live agents', () => {
    mockUseQuery.mockReturnValue({
      data: { supported: true, agents: {} },
      isLoading: false,
      error: null,
    })

    renderWrapped(<PresencePanel />)

    expect(screen.getByText(/No agents currently online/)).toBeInTheDocument()
  })

  it('renders the empty state (not a crash) when a supported payload omits agents', () => {
    mockUseQuery.mockReturnValue({
      data: { supported: true },
      isLoading: false,
      error: null,
    })

    renderWrapped(<PresencePanel />)

    expect(screen.getByText(/No agents currently online/)).toBeInTheDocument()
  })

  it('shows a loading spinner while the query is in flight', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: true, error: null })

    renderWrapped(<PresencePanel />)

    expect(screen.getByText('Agent presence')).toBeInTheDocument()
    expect(document.querySelector('.animate-spin')).not.toBeNull()
  })

  it('backs off polling to 60s when the backend reports unsupported', () => {
    mockUseQuery.mockReturnValue({
      data: { supported: false, agents: {} },
      isLoading: false,
      error: null,
    })

    renderWrapped(<PresencePanel />)

    const opts = mockUseQuery.mock.calls[0][0] as {
      refetchInterval: (q: { state: { data?: { supported: boolean } } }) => number
    }
    expect(typeof opts.refetchInterval).toBe('function')
    expect(opts.refetchInterval({ state: { data: { supported: false } } })).toBe(60_000)
    expect(opts.refetchInterval({ state: { data: { supported: true } } })).toBe(
      POLLING_INTERVALS.HEALTH,
    )
    // No data yet (first fetch pending) → keep the HEALTH cadence.
    expect(opts.refetchInterval({ state: {} })).toBe(POLLING_INTERVALS.HEALTH)
  })
})

// ---------------------------------------------------------------------------
// StorageHeadroomPanel
// ---------------------------------------------------------------------------

const GIB = 1024 ** 3

function headroomCategory(overrides: Record<string, unknown> = {}) {
  return {
    key: 'audio_motion',
    label: 'Audio clips',
    description: 'Clips recorded when a microphone hears something',
    path: '/data/orpheus/audio/audio_motion',
    measured: true,
    bytes: 60 * GIB,
    file_count: 1234,
    has_policy: true,
    policy_kind: 'size_budget',
    limit_bytes: 100 * GIB,
    percent_of_limit: 60,
    trigger_percent: 100,
    retention_days: 30,
    policy_note: null,
    last_sweep: null,
    ...overrides,
  }
}

function headroomData(overrides: Record<string, unknown> = {}) {
  return {
    data_root: '/data/orpheus',
    measured_at: '2026-08-26T09:00:00Z',
    check_interval_hours: 0.25,
    sweep_state: 'enforcing',
    categories: [headroomCategory()],
    filesystem: {
      total_bytes: 1000 * GIB,
      free_bytes: 400 * GIB,
      free_percent: 40,
      min_free_space_percent: 10,
      reserve_bytes: 100 * GIB,
      guard_enabled: true,
      guard_tripped: false,
      blocked_under_reserve: false,
    },
    ...overrides,
  }
}

describe('StorageHeadroomPanel', () => {
  it('shows a spinner while loading', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: true, error: null })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText('Storage headroom')).toBeInTheDocument()
    expect(document.querySelector('.animate-spin')).not.toBeNull()
  })

  it('says so plainly when the report cannot be loaded', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: false, error: new Error('boom') })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument()
  })

  it('renders a swept category against both its ceiling and its floor', () => {
    // They pull in opposite directions, so showing one without the other
    // misleads: a ceiling alone reads as "this will be trimmed to fit".
    mockUseQuery.mockReturnValue({ data: headroomData(), isLoading: false, error: null })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText('Audio clips')).toBeInTheDocument()
    expect(screen.getByText(/60\.0% of budget/)).toBeInTheDocument()
    expect(screen.getByText(/keeps the last 30 days/)).toBeInTheDocument()
    expect(screen.getByText(/1,234 files/)).toBeInTheDocument()
  })

  it('shows the size of a category nothing cleans, and says so in one phrase', () => {
    // The bug this guards: the largest directory on the station omitted
    // because no cleanup reports it.
    mockUseQuery.mockReturnValue({
      data: headroomData({
        categories: [
          headroomCategory({
            key: 'timelapses',
            label: 'Timelapses',
            description: 'Rendered timelapse videos',
            bytes: 296 * GIB,
            has_policy: false,
            policy_kind: null,
            limit_bytes: null,
            percent_of_limit: null,
            trigger_percent: null,
            policy_note: null,
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText('Timelapses')).toBeInTheDocument()
    expect(screen.getByText(/296\.0 GiB/)).toBeInTheDocument()
    expect(screen.getByText('Nothing cleans this up.')).toBeInTheDocument()
    expect(screen.queryByText(/of budget/)).not.toBeInTheDocument()
  })

  it('explains a ceiling the floor will not let it reach', () => {
    // Otherwise the panel shows a category parked over its limit with
    // nothing saying why nothing is being deleted.
    mockUseQuery.mockReturnValue({
      data: headroomData({
        categories: [
          headroomCategory({
            percent_of_limit: 140,
            policy_note:
              'Over its 600 GiB ceiling, but everything it still holds is inside the ' +
              '30-day floor. Nothing further will be deleted until the floor or the ' +
              'ceiling changes.',
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/inside the 30-day floor/)).toBeInTheDocument()
  })

  it('says "not yet measured" rather than showing a zero', () => {
    // A zero reads as "this directory is empty"; the truth is that no agent
    // has surveyed yet — first boot, or every reporter down.
    mockUseQuery.mockReturnValue({
      data: headroomData({
        measured_at: null,
        categories: [
          headroomCategory({
            measured: false,
            bytes: null,
            file_count: null,
            percent_of_limit: null,
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText('not yet measured')).toBeInTheDocument()
    expect(screen.queryByText(/0 B/)).not.toBeInTheDocument()
  })

  it('renders a genuinely empty directory as zero, not as unknown', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        categories: [
          headroomCategory({
            key: 'timelapses',
            label: 'Timelapses',
            measured: true,
            bytes: 0,
            file_count: 0,
            has_policy: false,
            policy_kind: null,
            limit_bytes: null,
            percent_of_limit: null,
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.queryByText('not yet measured')).not.toBeInTheDocument()
    expect(screen.getByText(/0 files/)).toBeInTheDocument()
  })

  it('keeps the size when a category has a size but no reported policy', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        categories: [
          headroomCategory({
            measured: true,
            bytes: 60 * GIB,
            has_policy: true,
            policy_kind: 'size_budget',
            limit_bytes: null,
            percent_of_limit: null,
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/60\.0 GiB/)).toBeInTheDocument()
    expect(screen.getByText(/Waiting for the first sweep/)).toBeInTheDocument()
  })

  it('tells the reader how often the figures refresh', () => {
    mockUseQuery.mockReturnValue({ data: headroomData(), isLoading: false, error: null })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/every 15 min/)).toBeInTheDocument()
  })

  it('reports what the last pass removed, and from when', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        categories: [
          headroomCategory({
            last_sweep: {
              at: '2026-08-25T09:00:00Z',
              files_removed: 812,
              bytes_freed: 4 * GIB,
              oldest_removed: '2026-05-02T01:00:00Z',
              newest_removed: '2026-05-04T23:00:00Z',
            },
          }),
        ],
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/812 files/)).toBeInTheDocument()
    expect(screen.getByText(/2026-05-02/)).toBeInTheDocument()
    expect(screen.getByText(/2026-05-04/)).toBeInTheDocument()
  })

  it('states the reserve in bytes, because runway is what an operator needs', () => {
    mockUseQuery.mockReturnValue({ data: headroomData(), isLoading: false, error: null })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/400\.0 GiB free/)).toBeInTheDocument()
    expect(screen.getByText(/Below 100\.0 GiB free/)).toBeInTheDocument()
  })

  it('calls a disabled guard disabled rather than a 0% threshold', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        filesystem: {
          total_bytes: 1000 * GIB,
          free_bytes: 400 * GIB,
          free_percent: 40,
          min_free_space_percent: 0,
          reserve_bytes: 0,
          guard_enabled: false,
          guard_tripped: false,
          blocked_under_reserve: false,
        },
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/Disabled — nothing acts on low disk space/)).toBeInTheDocument()
  })

  it('flags a guard that is currently tripped', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        filesystem: {
          total_bytes: 1000 * GIB,
          free_bytes: 40 * GIB,
          free_percent: 4,
          min_free_space_percent: 10,
          reserve_bytes: 100 * GIB,
          guard_enabled: true,
          guard_tripped: true,
          blocked_under_reserve: false,
        },
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/Currently below the reserve/)).toBeInTheDocument()
  })

  it('separates being low on disk from being unable to do anything about it', () => {
    // Tripped means low. Blocked means low AND every category is at its
    // floor, which is the one storage condition that needs a person.
    mockUseQuery.mockReturnValue({
      data: headroomData({
        filesystem: {
          total_bytes: 1000 * GIB,
          free_bytes: 40 * GIB,
          free_percent: 4,
          min_free_space_percent: 10,
          reserve_bytes: 100 * GIB,
          guard_enabled: true,
          guard_tripped: true,
          blocked_under_reserve: true,
        },
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(/every category at its retention floor/)).toBeInTheDocument()
    expect(screen.queryByText(/Currently below the reserve/)).not.toBeInTheDocument()
  })

  it.each([
    ['report_only', /first-run grace is still in effect/],
    ['disabled', /Nothing on this station deletes recordings/],
    ['never_run', /has not run yet/],
  ])('says plainly when nothing is deleting: %s', (state, expected) => {
    // The panel shipped once above an arrangement where nothing trimmed the
    // largest directory on the disk, and could not say so.
    mockUseQuery.mockReturnValue({
      data: headroomData({ sweep_state: state }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('stays quiet about the sweep when it is enforcing', () => {
    mockUseQuery.mockReturnValue({ data: headroomData(), isLoading: false, error: null })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.queryByText(/has not run yet/)).not.toBeInTheDocument()
    expect(screen.queryByText(/first-run grace/)).not.toBeInTheDocument()
  })

  it('says "not reported" when nothing has read the disk', () => {
    mockUseQuery.mockReturnValue({
      data: headroomData({
        filesystem: {
          total_bytes: null,
          free_bytes: null,
          free_percent: null,
          min_free_space_percent: 10,
          reserve_bytes: 100 * GIB,
          guard_enabled: true,
          guard_tripped: false,
          blocked_under_reserve: false,
        },
      }),
      isLoading: false,
      error: null,
    })

    renderWrapped(<StorageHeadroomPanel />)

    expect(screen.getByText('not reported')).toBeInTheDocument()
  })
})
