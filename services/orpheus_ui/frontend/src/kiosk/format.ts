/** Formatting helpers for the kiosk display (locale-aware, no dependencies). */

export function timeAgo(iso: string | undefined | null, nowMs: number): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, Math.round((nowMs - t) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

export function clockTime(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function clockDate(d: Date): string {
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
}

export function percent(fraction: number): string {
  return `${Math.round(Math.min(Math.max(fraction, 0), 1) * 100)}%`
}

export function uptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  if (d > 0) return `${d} d ${h} h`
  const m = Math.floor((seconds % 3600) / 60)
  return `${h} h ${m} min`
}

/** Map an audio level in dBFS onto 0–1 for a meter (-60 dB and below is empty). */
export function meterFraction(db: number): number {
  if (!Number.isFinite(db)) return 0
  return Math.min(Math.max((db + 60) / 60, 0), 1)
}

/** Readable channel label from a sensor id like "channel_2" or "2". */
export function channelLabel(sensorId: string | undefined): string {
  if (!sensorId) return ''
  const m = /(\d+)$/.exec(sensorId)
  return m ? `Mic ${m[1]}` : sensorId
}

/** Coarse kind of an entity, from its type path (e.g. "Animal.Bird.Crow"). */
export function entityKind(entityType: string | null | undefined): 'bird' | 'animal' | 'sound' {
  const t = (entityType || '').toLowerCase()
  if (t.includes('bird')) return 'bird'
  if (t.startsWith('animal')) return 'animal'
  return 'sound'
}
