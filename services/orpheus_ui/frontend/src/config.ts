/**
 * Frontend configuration constants.
 * 
 * These values match the Orpheus system configuration.
 * In the future, these could be fetched from the backend API.
 */

/**
 * Audio channel IDs used in the system.
 * Corresponds to the 4-channel audio input on the Jetson.
 */
export const AUDIO_CHANNEL_IDS = ['1', '2', '3', '4'] as const

/**
 * Camera IDs used in the system.
 * Corresponds to the configured IP cameras.
 */
export const CAMERA_IDS = [
  'orpheus-eye-1',
  'orpheus-eye-2', 
  'orpheus-eye-3',
  'orpheus-eye-4',
] as const

/**
 * Default API polling intervals in milliseconds.
 *
 * ``REALTIME`` is the base tier; the backend's ``dashboard.poll_interval``
 * config knob (served on GET /api/config as ``poll_interval``, default 5000ms)
 * corresponds to it. The other tiers are defined as multiples of the base so
 * that raising ``poll_interval`` to relieve DB contention scales every tier
 * up proportionally. See ``derivePollingIntervals`` / ``applyPollInterval``.
 */
const DEFAULT_POLLING_INTERVALS = {
  /** Real-time data like detections */
  REALTIME: 5000,
  /** Camera snapshots and status */
  CAMERAS: 10000,
  /** System health metrics */
  HEALTH: 10000,
  /** Historical data like bird/crow stats */
  HISTORY: 30000,
  /** Historical media (snapshots and timelapses) */
  MEDIA: 60000,
} as const

export type PollingIntervals = Record<keyof typeof DEFAULT_POLLING_INTERVALS, number>

/**
 * Live API polling intervals in milliseconds.
 *
 * Seeded from ``DEFAULT_POLLING_INTERVALS``. ``applyPollInterval`` mutates this
 * object in place at app bootstrap (main.tsx) once GET /api/config has been
 * read, so pages that reference ``POLLING_INTERVALS.X`` pick up an operator's
 * configured value. When the served value is absent, unfetched, or invalid the
 * defaults are preserved — behavior is unchanged out of the box.
 */
export const POLLING_INTERVALS: PollingIntervals = { ...DEFAULT_POLLING_INTERVALS }

/**
 * Ratio of each tier to the ``REALTIME`` base, computed from the defaults.
 * Preserving these ratios keeps the relative cadence (e.g. history polls 6x
 * slower than realtime) intact when the base is rescaled.
 */
const TIER_RATIOS: PollingIntervals = Object.fromEntries(
  (Object.keys(DEFAULT_POLLING_INTERVALS) as (keyof PollingIntervals)[]).map((k) => [
    k,
    DEFAULT_POLLING_INTERVALS[k] / DEFAULT_POLLING_INTERVALS.REALTIME,
  ]),
) as PollingIntervals

/**
 * Bounds for a served ``poll_interval`` base. The backend only validates that
 * the knob is an int, so a units-confused config (``poll_interval: 5`` meant
 * as seconds — the sibling weather knob IS ``poll_interval_seconds``) would
 * otherwise give every open tab a 5ms REALTIME refetchInterval and hammer the
 * SQLite-backed endpoints. Clamp to a sane window instead of trusting it.
 */
const MIN_POLL_BASE_MS = 1000
const MAX_POLL_BASE_MS = 600_000

/**
 * Derive a full set of polling intervals from a served ``poll_interval`` base
 * (in milliseconds). Each tier is scaled by its default ratio to the REALTIME
 * base. A missing / non-finite / non-positive base falls back to the hardcoded
 * defaults, so callers never have to special-case the "no config" path. A
 * finite positive base outside [MIN_POLL_BASE_MS, MAX_POLL_BASE_MS] is clamped
 * (with a console warning) rather than honored — see the bounds above.
 */
export function derivePollingIntervals(baseMs?: number | null): PollingIntervals {
  if (baseMs == null || !Number.isFinite(baseMs) || baseMs <= 0) {
    return { ...DEFAULT_POLLING_INTERVALS }
  }
  const clamped = Math.min(Math.max(baseMs, MIN_POLL_BASE_MS), MAX_POLL_BASE_MS)
  if (clamped !== baseMs) {
    console.warn(
      `Served poll_interval ${baseMs}ms is out of range ` +
        `[${MIN_POLL_BASE_MS}, ${MAX_POLL_BASE_MS}]; clamped to ${clamped}ms. ` +
        'Note the knob is in milliseconds, not seconds.',
    )
  }
  return Object.fromEntries(
    (Object.keys(TIER_RATIOS) as (keyof PollingIntervals)[]).map((k) => [
      k,
      Math.round(clamped * TIER_RATIOS[k]),
    ]),
  ) as PollingIntervals
}

/**
 * Apply a served ``poll_interval`` (ms) to the live ``POLLING_INTERVALS``,
 * mutating it in place. Called once at bootstrap. A missing/invalid value is a
 * no-op, leaving the defaults intact.
 */
export function applyPollInterval(baseMs?: number | null): void {
  Object.assign(POLLING_INTERVALS, derivePollingIntervals(baseMs))
}

/**
 * Deadline for the bootstrap GET /api/config fetch. The first render waits on
 * this request, so a backend that accepts the connection but never responds
 * (wedged uvicorn threadpool, half-open proxy) must not leave the operator on
 * a blank page — index.html/JS often come from browser cache, so "SPA loaded"
 * does not imply "backend responsive".
 */
export const CONFIG_FETCH_TIMEOUT_MS = 2500

/**
 * Server-decided login-page state, filled in by the same bootstrap fetch that
 * reads the polling base.
 *
 * ``guestQuickLogin`` — whether the one-click guest button is offered. The
 * server refuses the endpoint independently, so the flag only decides whether
 * a user is shown a button that would work.
 *
 * ``defaultCredentialsInUse`` — a seeded account still accepts its shipped
 * password. Drives the rotation prompt; the server never says which account.
 *
 * The defaults are today's behavior, so a failed or slow config fetch leaves
 * the login page working and silent rather than warning about nothing.
 */
export const UI_FLAGS = {
  guestQuickLogin: true,
  defaultCredentialsInUse: false,
}

/** Apply served login-page flags, mutating ``UI_FLAGS`` in place. */
export function applyUiFlags(cfg: {
  guest_quick_login?: boolean
  default_credentials_in_use?: boolean
}): void {
  if (typeof cfg.guest_quick_login === 'boolean') {
    UI_FLAGS.guestQuickLogin = cfg.guest_quick_login
  }
  if (typeof cfg.default_credentials_in_use === 'boolean') {
    UI_FLAGS.defaultCredentialsInUse = cfg.default_credentials_in_use
  }
}

/**
 * Fetch the operator-served polling base (GET /api/config → ``poll_interval``,
 * ms) and apply it to the live ``POLLING_INTERVALS``. Called once at bootstrap
 * (main.tsx) BEFORE the first render. Any failure — offline, 500, malformed,
 * or a response that stalls past ``CONFIG_FETCH_TIMEOUT_MS`` — is swallowed
 * (with a console warning) and the hardcoded defaults stand, so the app never
 * blocks on config.
 */
export async function loadServedPollInterval(): Promise<void> {
  try {
    const res = await fetch('/api/config', {
      signal: AbortSignal.timeout(CONFIG_FETCH_TIMEOUT_MS),
    })
    if (res.ok) {
      const cfg = (await res.json()) as {
        poll_interval?: number
        guest_quick_login?: boolean
        default_credentials_in_use?: boolean
      }
      applyPollInterval(cfg.poll_interval)
      applyUiFlags(cfg)
    }
  } catch (err) {
    // Keep the hardcoded defaults; never block the app on config. The
    // timeout's AbortError lands here too.
    console.warn('GET /api/config failed or timed out; using default polling intervals', err)
  }
}

/**
 * Type helpers for the config values.
 */
export type AudioChannelId = typeof AUDIO_CHANNEL_IDS[number]
export type CameraId = typeof CAMERA_IDS[number]
