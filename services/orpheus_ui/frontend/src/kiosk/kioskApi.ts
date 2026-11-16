/**
 * Data access for the kiosk display.
 *
 * Reuses the dashboard's existing, read-only API endpoints. Two differences from
 * the dashboard's ``fetchWithAuth``, both for an unattended screen:
 *
 * - A 401 never redirects to /login. The kiosk signs in again as the read-only
 *   guest (``POST /auth/guest-login``, allowed while ``ui.guest_quick_login`` is
 *   on) and retries once. If that is refused it reports ``KioskAuthError`` and
 *   the page asks for a one-time viewer sign-in instead.
 * - Its guest token is kept under its own storage key, so opening the kiosk
 *   in a browser where an operator is signed in never replaces their session.
 *   An operator's token, when present, is used as-is.
 */
import { API_BASE, getToken } from '../lib/utils'
import * as demo from './demoData'

export const KIOSK_TOKEN_KEY = 'orpheus_kiosk_token'

export class KioskAuthError extends Error {
  constructor(message = 'Viewer sign-in required') {
    super(message)
    this.name = 'KioskAuthError'
  }
}

// ---------------------------------------------------------------------------
// Wire types (subsets of what the endpoints return)
// ---------------------------------------------------------------------------

export interface KioskHealth {
  status: string
  cpu_percent: number
  memory_percent: number
  disk_percent: number
  uptime_seconds: number
  disk_data?: { percent: number; ok: boolean } | null
  /** Absent on an older station; ``available: false`` on a host without a GPU. */
  gpu?: {
    available: boolean
    utilization_percent?: number | null
    temperature_c?: number | null
  } | null
}

export interface KioskServices {
  services: { name: string; status: string; reason?: string }[]
}

export interface KioskAudioChannel {
  id: string
  level_db: number
  peak_db: number
  has_signal: boolean
  level_color: string
}

export interface KioskAudio {
  running: boolean
  message?: string
  channels?: KioskAudioChannel[]
}

export interface KioskEntity {
  entity_id: string
  timestamp: string
  species_code: string
  common_name: string
  confidence: number
  entity_type?: string | null
  is_self_generated?: boolean
  evidence?: { sensor_id: string; detection_type?: string }[]
}

export interface KioskEntities {
  entities: KioskEntity[]
  count: number
  stats: {
    total_count: number
    unique_species_count: number
    hourly_activity: { hour: number; count: number }[]
    species_distribution: Record<string, number>
  }
}

export interface KioskCamera {
  name: string
  status?: string
  ok?: boolean
}

export interface KioskSnapshot {
  filename: string
  timestamp_iso: string
  download_url: string
}

export interface KioskWeather {
  available: boolean
  temperature_c?: number | null
  humidity_pct?: number | null
  wind_speed_mps?: number | null
  timestamp?: string
}

// ---------------------------------------------------------------------------
// Token handling
// ---------------------------------------------------------------------------

function storedKioskToken(): string | null {
  try {
    return localStorage.getItem(KIOSK_TOKEN_KEY)
  } catch {
    return null
  }
}

function setKioskToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(KIOSK_TOKEN_KEY, token)
    else localStorage.removeItem(KIOSK_TOKEN_KEY)
  } catch {
    // Private mode / blocked storage: the token lives for this page only.
  }
}

let memoryToken: string | null = null
let guestLoginInFlight: Promise<boolean> | null = null
// An operator token the server rejected (expired): skip it rather than
// deleting it, which is the dashboard's business.
let rejectedOperatorToken: string | null = null

function currentToken(): string | null {
  // An operator's own session wins; otherwise the kiosk's guest session.
  const operator = getToken()
  if (operator && operator !== rejectedOperatorToken) return operator
  return memoryToken || storedKioskToken()
}

/** Sign in as the read-only guest. Concurrent callers share one request. */
export function guestSignIn(): Promise<boolean> {
  if (!guestLoginInFlight) {
    guestLoginInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/guest-login`, { method: 'POST' })
        if (!res.ok) return false
        const body = (await res.json()) as { access_token?: string }
        if (!body.access_token) return false
        memoryToken = body.access_token
        setKioskToken(body.access_token)
        return true
      } catch {
        return false
      } finally {
        // Let a later 401 try again.
        setTimeout(() => {
          guestLoginInFlight = null
        }, 0)
      }
    })()
  }
  return guestLoginInFlight
}

/** Authenticated GET with one silent guest re-sign-in on 401. */
export async function kioskFetch(path: string): Promise<Response> {
  const attempt = (token: string | null) =>
    fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })

  let res = await attempt(currentToken())
  if (res.status !== 401) return res

  // Set aside whichever token failed: never delete the operator's, drop the
  // kiosk's own, then sign in as the guest again.
  const operator = getToken()
  if (operator && operator !== rejectedOperatorToken) {
    rejectedOperatorToken = operator
  } else {
    memoryToken = null
    setKioskToken(null)
  }
  if (!(await guestSignIn())) throw new KioskAuthError()
  res = await attempt(currentToken())
  if (res.status === 401) throw new KioskAuthError()
  return res
}

async function getJson<T>(path: string): Promise<T> {
  const res = await kioskFetch(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return (await res.json()) as T
}

// ---------------------------------------------------------------------------
// Endpoints (demo mode answers from built-in sample data instead)
// ---------------------------------------------------------------------------

export interface KioskApi {
  health(): Promise<KioskHealth>
  services(): Promise<KioskServices>
  audio(): Promise<KioskAudio>
  entities(windowHours: number, pageSize: number): Promise<KioskEntities>
  cameras(): Promise<KioskCamera[]>
  latestSnapshot(camera: string): Promise<KioskSnapshot | null>
  imageUrl(path: string): Promise<string>
  weather(): Promise<KioskWeather>
}

function localTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

/** YYYY.MM.DD in UTC, the snapshotter's folder naming. */
export function utcFolderDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}.${pad(d.getUTCMonth() + 1)}.${pad(d.getUTCDate())}`
}

export const liveApi: KioskApi = {
  health: () => getJson<KioskHealth>('/api/health'),
  services: () => getJson<KioskServices>('/api/services/status'),
  audio: () => getJson<KioskAudio>('/api/diagnostics/audio'),
  entities: (windowHours, pageSize) => {
    const params = new URLSearchParams({
      start_date: new Date(Date.now() - windowHours * 3600_000).toISOString(),
      page: '1',
      page_size: String(pageSize),
    })
    const tz = localTimeZone()
    if (tz) params.set('tz', tz)
    return getJson<KioskEntities>(`/api/entities?${params.toString()}`)
  },
  cameras: () => getJson<KioskCamera[]>('/api/cameras'),
  latestSnapshot: async (camera) => {
    // Saved snapshots only (the snapshotter's files): no extra camera load.
    // Folders are UTC dates, so just after UTC midnight look at yesterday too.
    const base = `/api/media/snapshots/${encodeURIComponent(camera)}?limit=1`
    const today = await getJson<{ snapshots: KioskSnapshot[] }>(base)
    if (today.snapshots[0]) return today.snapshots[0]
    const yesterday = await getJson<{ snapshots: KioskSnapshot[] }>(
      `${base}&date=${utcFolderDate(new Date(Date.now() - 86400_000))}`,
    )
    return yesterday.snapshots[0] ?? null
  },
  imageUrl: async (path) => {
    const res = await kioskFetch(path)
    if (!res.ok) throw new Error(`${res.status} — ${path}`)
    return URL.createObjectURL(await res.blob())
  },
  weather: () => getJson<KioskWeather>('/api/weather/latest'),
}

export const demoApi: KioskApi = {
  health: async () => demo.health(),
  services: async () => demo.services(),
  audio: async () => demo.audio(Date.now()),
  entities: async (windowHours, pageSize) => demo.entities(Date.now(), windowHours, pageSize),
  cameras: async () => demo.cameras(),
  latestSnapshot: async (camera) => demo.snapshot(camera, Date.now()),
  imageUrl: async (path) => demo.imageDataUrl(path),
  weather: async () => demo.weather(),
}

/** For tests: forget the in-memory guest token. */
export function resetKioskSessionForTests(): void {
  memoryToken = null
  rejectedOperatorToken = null
  guestLoginInFlight = null
  setKioskToken(null)
}
