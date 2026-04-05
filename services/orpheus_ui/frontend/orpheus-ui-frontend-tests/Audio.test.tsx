/**
 * Tests for the Audio page component.
 *
 * Verifies that the AudioPage correctly renders flattened detection data
 * (channel_id, duration_seconds, peak_energy_db) produced by the backend
 * from the nested Detection MQTT payload.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

/**
 * Build a flattened detection payload matching the shape produced by
 * `on_audio_detection_message` in the backend after promoting nested
 * metadata fields to the top level.
 */
function makeFlattenedDetection(channelId: string, overrides: Record<string, unknown> = {}) {
  return {
    event_id: `evt-${channelId}`,
    timestamp: '2026-02-22T10:47:10Z',
    detection_type: 'audio.motion',
    channel: Number(channelId),
    channel_id: channelId,
    duration_seconds: 30.17,
    peak_energy_db: -35.23,
    audio_clip_path: `/data/orpheus/audio/audio_motion/${channelId}/20260222T104710.flac`,
    context: { lat: 47.6, lon: -122.3, sensor_id: `mic-${channelId}` },
    metadata: {
      channel_id: channelId,
      duration_seconds: 30.17,
      peak_energy_db: -35.23,
      average_energy_db: -48.09,
      frame_count: 143,
    },
    ...overrides,
  }
}

describe('Audio page', () => {
  beforeEach(() => {
    localStorage.setItem('orpheus_token', 'test-token')
  })

  it('renders page header', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/diagnostics/audio/detections')) {
        return Promise.resolve(new Response(JSON.stringify({
          summary: { '1': null, '2': null, '3': null, '4': null },
          history: [],
          mqtt_connected: true,
        })))
      }
      if (url.includes('/api/diagnostics/audio')) {
        return Promise.resolve(new Response(JSON.stringify({
          running: true,
          channels: [{ id: '1', active: true }],
          xrun: { total: 0 },
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })

    const { default: AudioPage } = await import('../src/pages/Audio')
    renderWithProviders(<AudioPage />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /audio detection/i })).toBeInTheDocument()
    })
  })

  it('renders flattened detection data (channel, duration, peak energy)', async () => {
    const det1 = makeFlattenedDetection('1')
    const det2 = makeFlattenedDetection('2', {
      duration_seconds: 12.5,
      peak_energy_db: -20.0,
    })

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/diagnostics/audio/detections')) {
        return Promise.resolve(new Response(JSON.stringify({
          summary: { '1': det1, '2': det2, '3': null, '4': null },
          history: [det1, det2],
          mqtt_connected: true,
        })))
      }
      if (url.includes('/api/diagnostics/audio')) {
        return Promise.resolve(new Response(JSON.stringify({
          running: true,
          channels: [
            { id: '1', active: true },
            { id: '2', active: true },
          ],
          xrun: { total: 0 },
        })))
      }
      if (url.includes('/api/audio/playback/sounds')) {
        return Promise.resolve(new Response(JSON.stringify({ sounds: [], count: 0 })))
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })

    const { default: AudioPage } = await import('../src/pages/Audio')
    renderWithProviders(<AudioPage />)

    await waitFor(() => {
      // Verify channel numbers render from flattened channel_id
      expect(screen.getByText('Ch 1')).toBeInTheDocument()
      expect(screen.getByText('Ch 2')).toBeInTheDocument()
    })

    // Verify duration renders from flattened duration_seconds
    expect(screen.getByText('30.2s')).toBeInTheDocument()
    expect(screen.getByText('12.5s')).toBeInTheDocument()

    // Verify peak energy renders from flattened peak_energy_db
    expect(screen.getByText('-35.2 dB')).toBeInTheDocument()
    expect(screen.getByText('-20.0 dB')).toBeInTheDocument()
  })

  it('renders active channel count from transformed health payload', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/diagnostics/audio/detections')) {
        return Promise.resolve(new Response(JSON.stringify({
          summary: { '1': null, '2': null, '3': null, '4': null },
          history: [],
          mqtt_connected: true,
        })))
      }
      if (url.includes('/api/diagnostics/audio')) {
        return Promise.resolve(new Response(JSON.stringify({
          running: true,
          channels: [
            { id: '1', active: true },
            { id: '2', active: true },
            { id: '3', active: false },
          ],
          xrun: { total: 0 },
        })))
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })

    const { default: AudioPage } = await import('../src/pages/Audio')
    renderWithProviders(<AudioPage />)

    await waitFor(() => {
      // Active channel count should be 2 (channels 1 and 2)
      expect(screen.getByText('2')).toBeInTheDocument()
      expect(screen.getByText('Active Channels')).toBeInTheDocument()
    })
  })

  it('renders channel status from detection summary', async () => {
    const det1 = makeFlattenedDetection('1')

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/diagnostics/audio/detections')) {
        return Promise.resolve(new Response(JSON.stringify({
          summary: { '1': det1, '2': null, '3': null, '4': null },
          history: [det1],
          mqtt_connected: true,
        })))
      }
      if (url.includes('/api/diagnostics/audio')) {
        return Promise.resolve(new Response(JSON.stringify({
          running: true,
          channels: [],
          xrun: { total: 0 },
        })))
      }
      if (url.includes('/api/audio/playback/sounds')) {
        return Promise.resolve(new Response(JSON.stringify({ sounds: [], count: 0 })))
      }
      return Promise.resolve(new Response(JSON.stringify({})))
    })

    const { default: AudioPage } = await import('../src/pages/Audio')
    renderWithProviders(<AudioPage />)

    await waitFor(() => {
      // Channel 1 should show activity; channels 2-4 show "No recent activity"
      expect(screen.getByText('Channel 1')).toBeInTheDocument()
      const noActivity = screen.getAllByText('No recent activity')
      expect(noActivity.length).toBe(3)
    })
  })
})
