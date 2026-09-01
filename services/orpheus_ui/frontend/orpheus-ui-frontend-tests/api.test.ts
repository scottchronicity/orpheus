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

import { fetchJson, fetchAudioHealth, fetchServiceLogs } from '../src/lib/api'
import { fetchWithAuth } from '../src/lib/utils'

const mockedFetchWithAuth = vi.mocked(fetchWithAuth)

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// fetchJson
// ---------------------------------------------------------------------------

describe('fetchJson', () => {
  it('returns parsed JSON on an ok response', async () => {
    const payload = { hello: 'world' }
    mockedFetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    } as unknown as Response)

    const result = await fetchJson<typeof payload>('/api/thing')

    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/thing', undefined)
    expect(result).toEqual(payload)
  })

  it('forwards the init argument to fetchWithAuth', async () => {
    mockedFetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    } as unknown as Response)

    const init = { method: 'POST', body: '{}' }
    await fetchJson('/api/thing', init)

    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/thing', init)
  })

  it('throws with status, statusText and url on a non-ok response', async () => {
    mockedFetchWithAuth.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.resolve({}),
    } as unknown as Response)

    await expect(fetchJson('/api/boom')).rejects.toThrow(
      '500 Internal Server Error — /api/boom',
    )
  })

  it('propagates errors from fetchWithAuth', async () => {
    mockedFetchWithAuth.mockRejectedValue(new Error('Network error'))

    await expect(fetchJson('/api/thing')).rejects.toThrow('Network error')
  })
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
      ok: true,
      json: () => Promise.resolve(payload),
    } as unknown as Response)

    const result = await fetchAudioHealth()

    // fetchJson forwards an (input, init) pair; init is undefined here.
    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/diagnostics/audio', undefined)
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
      ok: true,
      json: () => Promise.resolve(payload),
    } as unknown as Response)

    const result = await fetchServiceLogs('orpheus-agent-audio-motion')

    expect(mockedFetchWithAuth).toHaveBeenCalledWith(
      '/api/diagnostics/logs/orpheus-agent-audio-motion',
      undefined,
    )
    expect(result).toEqual(payload)
  })

  it('encodes special characters in the service name', async () => {
    mockedFetchWithAuth.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ service_name: 'a/b', lines: [] }),
    } as unknown as Response)

    await fetchServiceLogs('a/b')

    expect(mockedFetchWithAuth).toHaveBeenCalledWith('/api/diagnostics/logs/a%2Fb', undefined)
  })

  it('propagates errors from fetchWithAuth', async () => {
    mockedFetchWithAuth.mockRejectedValue(new Error('401 Unauthorized'))

    await expect(fetchServiceLogs('svc')).rejects.toThrow('401 Unauthorized')
  })
})
