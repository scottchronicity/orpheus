/**
 * Typed fetch helpers for Orpheus backend API endpoints.
 *
 * All functions use fetchWithAuth so that the Bearer token is sent
 * automatically and 401 responses redirect to /login.
 */

import { fetchWithAuth } from './utils'

// ---------------------------------------------------------------------------
// Core helper
// ---------------------------------------------------------------------------

/**
 * Authenticated fetch that throws on a non-2xx response, then parses JSON.
 *
 * Wraps ``fetchWithAuth`` (so the Bearer token + 401 redirect are preserved)
 * and adds the ``res.ok`` check that most hand-rolled react-query ``queryFn``s
 * were missing: without it a 500 / timeout resolves as an empty body and the
 * chart renders blank instead of surfacing react-query's ``error`` state. On a
 * failed response we throw an Error that includes the status and URL so the
 * error boundary / message shows something actionable.
 *
 * @param input - URL (or Request) passed through to ``fetchWithAuth``.
 * @param init  - Optional fetch init (method, body, headers, …).
 */
export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithAuth(input, init)
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${input}`)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AudioChannel {
  id: string
  active: boolean
  level_db: number
  peak_db: number
  level_color: 'green' | 'yellow' | 'red' | 'none'
  has_signal: boolean
}

export interface AudioHealthData {
  running: boolean
  message?: string
  health_status?: string
  health_description?: string
  channels: AudioChannel[]
  xrun?: { total: number; rate_per_minute?: number }
  hardware?: Record<string, unknown>
  timing?: Record<string, unknown>
  system?: Record<string, unknown>
}

export interface ServiceLogsData {
  service_name: string
  lines: string[]
}

// ---------------------------------------------------------------------------
// Fetch functions
// ---------------------------------------------------------------------------

/**
 * Fetch audio system health diagnostics.
 *
 * Polls GET /api/diagnostics/audio which returns real-time channel status
 * (level_db, peak_db, level_color) sourced from the MQTT audio agent.
 */
export async function fetchAudioHealth(): Promise<AudioHealthData> {
  return fetchJson<AudioHealthData>('/api/diagnostics/audio')
}

/**
 * Fetch recent systemd journal logs for a service.
 *
 * Calls GET /api/diagnostics/logs/{serviceName} which runs
 * journalctl -u {serviceName} -n 100 --no-pager on the backend.
 *
 * @param serviceName - systemd unit name, e.g. "orpheus-agent-audio-motion"
 */
export async function fetchServiceLogs(serviceName: string): Promise<ServiceLogsData> {
  return fetchJson<ServiceLogsData>(`/api/diagnostics/logs/${encodeURIComponent(serviceName)}`)
}
