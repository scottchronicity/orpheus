/**
 * Tests for the typed fetch helpers in src/lib/api.ts.
 *
 * fetchWithAuth is mocked so that tests exercise only the thin wrappers
 * (fetchAudioHealth, fetchServiceLogs) without hitting the network.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fetchWithAuth before importing the module under test
vi.mock('../src/lib/utils', () => ({
  fetchWithAuth: vi.fn(),
}))

import { fetchAudioHealth, fetchServiceLogs } from '../src/lib/api'
import { fetchWithAuth } from '../src/lib/utils'

const mockedFetchWithAuth = vi.mocked(fetchWithAuth)

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// fetchAudioHealth
// ---------------------------------------------------------------------------

describe('fetchAudioHealth', () => {
  it('calls fetchWithAuth with the correct URL and returns parsed JSON', async () => {
    const payload = {
      running: true,
      channels: [
        { id: '1', active: true, level_db: -30, peak_db: -20, level_color: 'green', has_signal: true },
      ],
    }

    mockedFetchWithAuth.mockResolvedValue({
      json: () => Promise.resolve(payload),
    } as unknown as Response)

    const result = await fetchAudioHealth()

    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/diagnostics/audio')
    expect(result).toEqual(payload)
  })

  it('propagates errors from fetchWithAuth', async () => {
    mockedFetchWithAuth.mockRejectedValue(new Error('Network error'))

    await expect(fetchAudioHealth()).rejects.toThrow('Network error')
  })
})

// ---------------------------------------------------------------------------
// fetchServiceLogs
// ---------------------------------------------------------------------------

describe('fetchServiceLogs', () => {
  it('calls fetchWithAuth with the encoded service name and returns parsed JSON', async () => {
    const payload = { service_name: 'orpheus-agent-audio-motion', lines: ['line1', 'line2'] }

    mockedFetchWithAuth.mockResolvedValue({
      json: () => Promise.resolve(payload),
    } as unknown as Response)

    const result = await fetchServiceLogs('orpheus-agent-audio-motion')

    expect(mockedFetchWithAuth).toHaveBeenCalledWith(
      '/api/diagnostics/logs/orpheus-agent-audio-motion',
    )
    expect(result).toEqual(payload)
  })

  it('encodes special characters in the service name', async () => {
    mockedFetchWithAuth.mockResolvedValue({
      json: () => Promise.resolve({ service_name: 'a/b', lines: [] }),
    } as unknown as Response)

    await fetchServiceLogs('a/b')

    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/diagnostics/logs/a%2Fb')
  })

  it('propagates errors from fetchWithAuth', async () => {
    mockedFetchWithAuth.mockRejectedValue(new Error('401 Unauthorized'))

    await expect(fetchServiceLogs('svc')).rejects.toThrow('401 Unauthorized')
  })
})
