/**
 * Kiosk settings, read from the page URL (/kiosk?...).
 *
 * The URL is the whole configuration surface, so the same settings work in any
 * browser on any platform, and a launcher (a Chromium kiosk on a Pi, a
 * bookmark on a laptop) configures a display by choosing its URL. Every value
 * is validated and clamped; anything unrecognised falls back to the default.
 *
 *   panels   comma list of: sightings, today, audio, cameras, system
 *            (default: all, in that order)
 *   cameras  comma list of camera names to rotate through (default: every
 *            camera the station reports)
 *   rotate   seconds per camera in the rotation (default 20, 5–600)
 *   hours    window for "today" counts, in hours (default 24, 1–168)
 *   self     1 to include sounds Orpheus played itself (default 0)
 *   night    "22-6": dim the display between those local hours (default off)
 *   shift    0 to disable the slow burn-in shift (default 1)
 *   scale    text scale for distant or tiny screens (default 1, 0.75–2)
 *   demo     1 to show built-in sample data with no station (default 0)
 */

export const KIOSK_PANELS = ['sightings', 'today', 'audio', 'cameras', 'system'] as const
export type KioskPanel = (typeof KIOSK_PANELS)[number]

export interface KioskSettings {
  panels: KioskPanel[]
  cameras: string[] | null // null: every camera the station reports
  rotateSeconds: number
  windowHours: number
  includeSelfGenerated: boolean
  night: { startHour: number; endHour: number } | null
  burnInShift: boolean
  scale: number
  demo: boolean
}

export const DEFAULT_KIOSK_SETTINGS: KioskSettings = {
  panels: [...KIOSK_PANELS],
  cameras: null,
  rotateSeconds: 20,
  windowHours: 24,
  includeSelfGenerated: false,
  night: null,
  burnInShift: true,
  scale: 1,
  demo: false,
}

function clampNumber(raw: string | null, fallback: number, min: number, max: number): number {
  if (raw === null || raw.trim() === '') return fallback
  const value = Number(raw)
  if (!Number.isFinite(value)) return fallback
  return Math.min(Math.max(value, min), max)
}

function flag(raw: string | null, fallback: boolean): boolean {
  if (raw === null) return fallback
  const v = raw.trim().toLowerCase()
  if (['1', 'true', 'yes', 'on'].includes(v)) return true
  if (['0', 'false', 'no', 'off'].includes(v)) return false
  return fallback
}

function list(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function parseNight(raw: string | null): KioskSettings['night'] {
  if (!raw) return null
  const m = /^(\d{1,2})-(\d{1,2})$/.exec(raw.trim())
  if (!m) return null
  const startHour = Number(m[1])
  const endHour = Number(m[2])
  if (startHour > 23 || endHour > 23 || startHour === endHour) return null
  return { startHour, endHour }
}

// Camera names are path segments in API URLs: keep them to a safe charset.
const CAMERA_NAME = /^[A-Za-z0-9._-]{1,64}$/

export function parseKioskSettings(search: string): KioskSettings {
  const params = new URLSearchParams(search)
  const wanted = list(params.get('panels')).filter((p): p is KioskPanel =>
    (KIOSK_PANELS as readonly string[]).includes(p),
  )
  const cameras = list(params.get('cameras')).filter((c) => CAMERA_NAME.test(c))
  return {
    panels: wanted.length ? Array.from(new Set(wanted)) : [...KIOSK_PANELS],
    cameras: cameras.length ? cameras : null,
    rotateSeconds: Math.round(clampNumber(params.get('rotate'), 20, 5, 600)),
    windowHours: Math.round(clampNumber(params.get('hours'), 24, 1, 168)),
    includeSelfGenerated: flag(params.get('self'), false),
    night: parseNight(params.get('night')),
    burnInShift: flag(params.get('shift'), true),
    scale: clampNumber(params.get('scale'), 1, 0.75, 2),
    demo: flag(params.get('demo'), false),
  }
}

/** True when ``hour`` (0–23, local) falls in the night window, which may wrap midnight. */
export function isNightHour(night: KioskSettings['night'], hour: number): boolean {
  if (!night) return false
  const { startHour, endHour } = night
  return startHour < endHour
    ? hour >= startHour && hour < endHour
    : hour >= startHour || hour < endHour
}
