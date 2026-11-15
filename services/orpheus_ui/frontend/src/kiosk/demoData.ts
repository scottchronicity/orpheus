/**
 * Built-in sample data for /kiosk?demo=1.
 *
 * Lets anyone open the kiosk in a browser with no station or backend: on a
 * laptop for layout work, in screenshots, and in the browser tests. Values
 * change slowly with the clock so the screen looks alive. Nothing here is
 * real station data, and the page labels itself "Demo data".
 */
import type {
  KioskAudio,
  KioskCamera,
  KioskEntities,
  KioskEntity,
  KioskHealth,
  KioskServices,
  KioskSnapshot,
  KioskWeather,
} from './kioskApi'

const SPECIES: { code: string; name: string; type: string }[] = [
  { code: 'amecro', name: 'American Crow', type: 'Animal.Bird.Crow' },
  { code: 'norcar', name: 'Northern Cardinal', type: 'Animal.Bird' },
  { code: 'blujay', name: 'Blue Jay', type: 'Animal.Bird' },
  { code: 'carwre', name: 'Carolina Wren', type: 'Animal.Bird' },
  { code: 'amerob', name: 'American Robin', type: 'Animal.Bird' },
  { code: 'tuftit', name: 'Tufted Titmouse', type: 'Animal.Bird' },
  { code: 'audioset_dog', name: 'Dog', type: 'Animal.Mammal' },
  { code: 'audioset_rain', name: 'Rain', type: 'Environment.Weather' },
]

// Small deterministic generator so a given minute always renders the same.
function rand(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453
  return x - Math.floor(x)
}

export function health(): KioskHealth {
  return {
    status: 'healthy',
    cpu_percent: 38,
    memory_percent: 61,
    disk_percent: 47,
    uptime_seconds: 9 * 86400 + 4 * 3600,
    disk_data: { percent: 47, ok: true },
  }
}

export function services(): KioskServices {
  const names = [
    'orpheus-backplane',
    'orpheus-ui',
    'orpheus-agent-audio-motion',
    'orpheus-agent-audio-playback',
    'orpheus-agent-audio-events',
    'orpheus-agent-bird-detection',
    'orpheus-agent-crow-detection',
    'orpheus-agent-event-correlator',
    'orpheus-agent-video-snapshotter',
    'orpheus-audio-output',
  ]
  return { services: names.map((name) => ({ name, status: 'active' })) }
}

export function audio(nowMs: number): KioskAudio {
  const t = Math.floor(nowMs / 2000)
  return {
    running: true,
    channels: ['1', '2', '3', '4'].map((id, i) => {
      const level = -62 + 30 * rand(t * 4 + i)
      const signal = level > -48
      return {
        id,
        level_db: Math.round(level * 10) / 10,
        peak_db: Math.round((level + 6) * 10) / 10,
        has_signal: signal,
        level_color: level > -20 ? 'red' : level > -40 ? 'yellow' : signal ? 'green' : 'none',
      }
    }),
  }
}

export function entities(nowMs: number, windowHours: number, pageSize: number): KioskEntities {
  const minute = Math.floor(nowMs / 60_000)
  const items: KioskEntity[] = []
  for (let i = 0; i < 40; i++) {
    const s = SPECIES[Math.floor(rand(minute - i * 7) * SPECIES.length)]
    items.push({
      entity_id: `demo-${minute - i}`,
      timestamp: new Date(nowMs - (i * 9 + rand(i) * 6) * 60_000).toISOString(),
      species_code: s.code,
      common_name: s.name,
      confidence: 0.55 + 0.44 * rand(minute + i),
      entity_type: s.type,
      is_self_generated: i === 5,
      evidence: [{ sensor_id: `channel_${1 + (i % 4)}`, detection_type: 'species.detected' }],
    })
  }
  const distribution: Record<string, number> = {}
  for (const e of items) distribution[e.common_name] = (distribution[e.common_name] ?? 0) + 1
  const hourNow = new Date(nowMs).getHours()
  const hourly = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    count: Math.round(
      (hour <= hourNow || windowHours >= 24 ? 1 : 0) * (4 + 14 * rand(hour + 3)) *
        (hour >= 5 && hour <= 9 ? 2 : 1),
    ),
  }))
  return {
    entities: items.slice(0, pageSize),
    count: items.length,
    stats: {
      total_count: items.length * 6,
      unique_species_count: Object.keys(distribution).length,
      hourly_activity: hourly,
      species_distribution: distribution,
    },
  }
}

export function cameras(): KioskCamera[] {
  return [
    { name: 'orpheus-eye-1', status: 'online', ok: true },
    { name: 'orpheus-eye-2', status: 'online', ok: true },
  ]
}

export function snapshot(camera: string, nowMs: number): KioskSnapshot {
  return {
    filename: `demo.${camera}.jpg`,
    timestamp_iso: new Date(nowMs - 40_000).toISOString(),
    download_url: `demo://${camera}`,
  }
}

/** A small generated scene standing in for a camera snapshot. */
export function imageDataUrl(path: string): string {
  const hue = path.endsWith('2') ? 150 : 200
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">
<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="hsl(${hue},45%,62%)"/><stop offset="1" stop-color="hsl(${hue},35%,30%)"/></linearGradient></defs>
<rect width="640" height="360" fill="url(#s)"/>
<path d="M0 270 Q160 220 320 262 T640 250 V360 H0Z" fill="hsl(110,30%,24%)"/>
<path d="M0 300 Q200 270 380 306 T640 296 V360 H0Z" fill="hsl(110,28%,18%)"/>
<text x="20" y="40" font-family="sans-serif" font-size="22" fill="white" opacity=".8">${path.replace('demo://', '')} · demo</text>
</svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

export function weather(): KioskWeather {
  return { available: true, temperature_c: 11.4, humidity_pct: 72, wind_speed_mps: 2.6 }
}
