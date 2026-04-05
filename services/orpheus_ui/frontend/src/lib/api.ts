/**
 * Typed fetch helpers for Orpheus backend API endpoints.
 *
 * All functions use fetchWithAuth so that the Bearer token is sent
 * automatically and 401 responses redirect to /login.
 */

import { fetchWithAuth } from './utils'

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
  const res = await fetchWithAuth('/api/diagnostics/audio')
  return res.json()
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
  const res = await fetchWithAuth(`/api/diagnostics/logs/${encodeURIComponent(serviceName)}`)
  return res.json()
}
