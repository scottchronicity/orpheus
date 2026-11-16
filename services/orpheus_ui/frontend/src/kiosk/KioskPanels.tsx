/**
 * Presentational panels for the kiosk display. Pure: each takes plain data and
 * renders it; fetching and timing live in KioskPage.
 */
import { AudioLines, Bird, Camera, Cpu, PawPrint, Radio } from 'lucide-react'
import type {
  KioskAudio,
  KioskEntities,
  KioskEntity,
  KioskHealth,
  KioskServices,
} from './kioskApi'
import { channelLabel, entityKind, meterFraction, percent, timeAgo, uptime } from './format'

export function Panel({
  title,
  icon,
  children,
  className = '',
  testId,
  compact = false,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
  className?: string
  testId?: string
  compact?: boolean
}) {
  return (
    <section
      data-testid={testId}
      className={`flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 ${
        compact ? 'p-2.5' : 'p-4'
      } ${className}`}
    >
      <h2
        className={`flex items-center gap-2 font-semibold uppercase tracking-wider text-slate-400 ${
          compact ? 'mb-1.5 text-xs' : 'mb-3 text-sm'
        }`}
      >
        {icon}
        {title}
      </h2>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  )
}

function KindIcon({ entity, className }: { entity: KioskEntity; className?: string }) {
  const kind = entityKind(entity.entity_type)
  if (kind === 'bird') return <Bird className={className} aria-hidden="true" />
  if (kind === 'animal') return <PawPrint className={className} aria-hidden="true" />
  return <AudioLines className={className} aria-hidden="true" />
}

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 0.8 ? 'bg-emerald-400' : value >= 0.5 ? 'bg-amber-400' : 'bg-rose-400'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800" aria-hidden="true">
      <div className={`h-full ${color}`} style={{ width: percent(value) }} />
    </div>
  )
}

export function SightingsPanel({
  entities,
  nowMs,
  compact = false,
}: {
  entities: KioskEntity[] | undefined
  nowMs: number
  compact?: boolean
}) {
  const [latest, ...more] = entities ?? []
  const rest = compact ? more.slice(0, 2) : more
  return (
    <Panel title="Latest sightings" icon={<Bird className="h-4 w-4" />} testId="kiosk-sightings" compact={compact}>
      {!latest ? (
        <p className="text-lg text-slate-500">Nothing heard yet in this window.</p>
      ) : (
        <div className={`flex h-full flex-col ${compact ? 'gap-2' : 'gap-4'}`}>
          <div className={`rounded-xl bg-slate-800/60 ${compact ? 'p-2.5' : 'p-4'}`} data-testid="kiosk-latest">
            <div className="flex items-start gap-3">
              <KindIcon
                entity={latest}
                className={`shrink-0 text-orpheus-400 ${compact ? 'mt-0.5 h-6 w-6' : 'mt-1 h-8 w-8'}`}
              />
              <div className="min-w-0 flex-1">
                <p className={`truncate font-semibold text-white ${compact ? 'text-2xl' : 'text-4xl'}`}>
                  {latest.common_name || latest.species_code}
                </p>
                <p className={`mt-1 text-slate-300 ${compact ? 'text-sm' : 'text-lg'}`}>
                  {timeAgo(latest.timestamp, nowMs)}
                  {latest.evidence?.[0]?.sensor_id ? ` · ${channelLabel(latest.evidence[0].sensor_id)}` : ''}
                  {` · ${percent(latest.confidence)} confident`}
                </p>
              </div>
            </div>
            <div className={compact ? 'mt-2' : 'mt-3'}>
              <ConfidenceBar value={latest.confidence} />
            </div>
          </div>
          <ul className={`flex min-h-0 flex-1 flex-col overflow-hidden ${compact ? 'gap-1' : 'gap-2'}`}>
            {rest.map((e) => (
              <li key={e.entity_id} className={`flex items-center gap-3 ${compact ? 'text-sm' : 'text-lg'}`}>
                <KindIcon entity={e} className="h-5 w-5 shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1 truncate text-slate-100">{e.common_name || e.species_code}</span>
                <span className="shrink-0 tabular-nums text-slate-400">{timeAgo(e.timestamp, nowMs)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  )
}

export function TodayPanel({
  stats,
  windowHours,
  currentHour,
  compact = false,
}: {
  stats: KioskEntities['stats'] | undefined
  windowHours: number
  currentHour: number
  compact?: boolean
}) {
  const top = Object.entries(stats?.species_distribution ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, compact ? 2 : 6)
  const topMax = top[0]?.[1] ?? 1
  const hourly = stats?.hourly_activity ?? []
  const hourlyMax = Math.max(1, ...hourly.map((h) => h.count))
  const title = windowHours === 24 ? 'Last 24 hours' : `Last ${windowHours} hours`
  return (
    <Panel title={title} icon={<Radio className="h-4 w-4" />} testId="kiosk-today" compact={compact}>
      <div className={`flex h-full flex-col ${compact ? 'gap-2' : 'gap-4'}`}>
        <div className={`grid grid-cols-2 ${compact ? 'gap-2' : 'gap-3'}`}>
          <div className={`rounded-xl bg-slate-800/60 ${compact ? 'p-2' : 'p-3'}`}>
            <p className={`font-semibold tabular-nums text-white ${compact ? 'text-2xl' : 'text-4xl'}`} data-testid="kiosk-total">
              {stats ? stats.total_count : '—'}
            </p>
            <p className="text-sm text-slate-400">detections</p>
          </div>
          <div className={`rounded-xl bg-slate-800/60 ${compact ? 'p-2' : 'p-3'}`}>
            <p className={`font-semibold tabular-nums text-white ${compact ? 'text-2xl' : 'text-4xl'}`} data-testid="kiosk-species">
              {stats ? stats.unique_species_count : '—'}
            </p>
            <p className="text-sm text-slate-400">species</p>
          </div>
        </div>
        <ul className="flex flex-col gap-1.5" aria-label="Most heard">
          {top.map(([name, count]) => (
            <li key={name} className={compact ? 'text-sm' : 'text-base'}>
              <div className="flex justify-between gap-2">
                <span className="truncate text-slate-200">{name}</span>
                <span className="tabular-nums text-slate-400">{count}</span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-800" aria-hidden="true">
                <div className="h-full bg-orpheus-500" style={{ width: `${(count / topMax) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
        {hourly.length > 0 && !compact && (
          <div className="mt-auto" aria-label="Activity by hour">
            <div className="flex h-14 items-end gap-[2px]">
              {Array.from({ length: 24 }, (_, hour) => {
                const count = hourly.find((h) => h.hour === hour)?.count ?? 0
                return (
                  <div
                    key={hour}
                    title={`${hour}:00 — ${count}`}
                    className={`flex-1 rounded-sm ${hour === currentHour ? 'bg-orpheus-300' : 'bg-slate-600'}`}
                    style={{ height: `${Math.max(4, (count / hourlyMax) * 100)}%` }}
                  />
                )
              })}
            </div>
            <div className="mt-1 flex justify-between text-xs text-slate-500">
              <span>0</span>
              <span>6</span>
              <span>12</span>
              <span>18</span>
              <span>23</span>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

export function AudioPanel({ audio, compact = false }: { audio: KioskAudio | undefined; compact?: boolean }) {
  const channels = audio?.channels ?? []
  return (
    <Panel title="Listening" icon={<AudioLines className="h-4 w-4" />} testId="kiosk-audio" compact={compact}>
      {!audio ? (
        <p className="text-slate-500">Waiting for the microphones…</p>
      ) : !audio.running || channels.length === 0 ? (
        <p className="text-amber-300">{audio.message || 'Audio capture is not reporting'}</p>
      ) : (
        <ul className={`flex flex-col ${compact ? 'gap-1' : 'gap-2'}`}>
          {channels.map((ch) => (
            <li key={ch.id} className="flex items-center gap-3">
              <span className="w-14 shrink-0 text-sm text-slate-400">{channelLabel(ch.id)}</span>
              <div
                className="relative h-3 flex-1 overflow-hidden rounded-full bg-slate-800"
                role="meter"
                aria-label={`${channelLabel(ch.id)} level`}
                aria-valuemin={-60}
                aria-valuemax={0}
                aria-valuenow={Math.round(ch.level_db)}
              >
                <div
                  className={`h-full transition-[width] duration-700 ${
                    ch.level_color === 'red'
                      ? 'bg-rose-400'
                      : ch.level_color === 'yellow'
                        ? 'bg-amber-300'
                        : ch.has_signal
                          ? 'bg-emerald-400'
                          : 'bg-slate-600'
                  }`}
                  style={{ width: percent(meterFraction(ch.level_db)) }}
                />
              </div>
              <span className="w-16 shrink-0 text-right text-sm tabular-nums text-slate-400">
                {Math.round(ch.level_db)} dB
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function CameraPanel({
  camera,
  imageUrl,
  capturedIso,
  nowMs,
  message,
  compact = false,
}: {
  camera: string | null
  imageUrl: string | null
  capturedIso: string | null
  nowMs: number
  message?: string
  compact?: boolean
}) {
  return (
    <Panel
      title={camera ? `Camera · ${camera}` : 'Camera'}
      icon={<Camera className="h-4 w-4" />}
      testId="kiosk-camera"
      compact={compact}
    >
      <div className={`relative flex h-full items-center ${compact ? 'min-h-0' : 'min-h-[8rem]'} justify-center overflow-hidden rounded-xl bg-slate-950`}>
        {imageUrl ? (
          <img src={imageUrl} alt={camera ? `Latest snapshot from ${camera}` : 'Latest snapshot'} className="h-full w-full object-contain" />
        ) : (
          <p className="p-4 text-center text-slate-500">{message || 'No snapshot yet'}</p>
        )}
        {imageUrl && capturedIso && (
          <span className="absolute bottom-2 right-2 rounded bg-black/60 px-2 py-0.5 text-xs text-slate-200">
            {timeAgo(capturedIso, nowMs)}
          </span>
        )}
      </div>
    </Panel>
  )
}

function UsageRow({ label, value }: { label: string; value: number | undefined }) {
  const fraction = (value ?? 0) / 100
  const color = fraction > 0.9 ? 'bg-rose-400' : fraction > 0.75 ? 'bg-amber-300' : 'bg-orpheus-500'
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-20 shrink-0 whitespace-nowrap text-slate-400">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800" aria-hidden="true">
        <div className={`h-full ${color}`} style={{ width: percent(fraction) }} />
      </div>
      <span className="w-10 shrink-0 text-right tabular-nums text-slate-300">
        {value === undefined ? '—' : `${Math.round(value)}%`}
      </span>
    </div>
  )
}

export function serviceSummary(services: KioskServices | undefined): { running: number; total: number; down: string[] } {
  const list = services?.services ?? []
  const down = list.filter((s) => s.status !== 'active' && s.status !== 'running').map((s) => s.name)
  return { running: list.length - down.length, total: list.length, down }
}

export function SystemPanel({
  health,
  services,
}: {
  health: KioskHealth | undefined
  services: KioskServices | undefined
}) {
  const summary = serviceSummary(services)
  const gpu = health?.gpu?.available ? health.gpu : undefined
  return (
    <Panel title="Station" icon={<Cpu className="h-4 w-4" />} testId="kiosk-system">
      <div className="flex flex-col gap-2">
        <UsageRow label="CPU" value={health?.cpu_percent} />
        <UsageRow label="Memory" value={health?.memory_percent} />
        <UsageRow label="Disk" value={health?.disk_data?.percent ?? health?.disk_percent} />
        {gpu && (
          <UsageRow
            label={gpu.temperature_c != null ? `GPU ${Math.round(gpu.temperature_c)}°C` : 'GPU'}
            value={gpu.utilization_percent ?? undefined}
          />
        )}
        <p className="mt-1 text-sm text-slate-300" data-testid="kiosk-services">
          {services ? `${summary.running} of ${summary.total} services running` : 'Services: —'}
          {health ? ` · up ${uptime(health.uptime_seconds)}` : ''}
        </p>
        {summary.down.length > 0 && (
          <p className="truncate text-sm text-amber-300">Not running: {summary.down.join(', ')}</p>
        )}
      </div>
    </Panel>
  )
}

/** One-line station summary for small screens, in place of the Station panel. */
export function SystemStrip({
  health,
  services,
}: {
  health: KioskHealth | undefined
  services: KioskServices | undefined
}) {
  const summary = serviceSummary(services)
  const part = (label: string, v: number | undefined) => `${label} ${v === undefined ? '—' : `${Math.round(v)}%`}`
  const gpu = health?.gpu?.available ? health.gpu : undefined
  const gpuPart = gpu
    ? [
        part('GPU', gpu.utilization_percent ?? undefined),
        gpu.temperature_c != null ? `${Math.round(gpu.temperature_c)} °C` : null,
      ]
        .filter(Boolean)
        .join(' ')
    : null
  return (
    <span data-testid="kiosk-system" className="truncate">
      {[
        part('CPU', health?.cpu_percent),
        part('Mem', health?.memory_percent),
        part('Disk', health?.disk_data?.percent ?? health?.disk_percent),
        gpuPart,
        services ? `${summary.running}/${summary.total} services` : null,
      ]
        .filter(Boolean)
        .join(' · ')}
      {summary.down.length > 0 && <span className="text-amber-300">{` · Not running: ${summary.down.join(', ')}`}</span>}
    </span>
  )
}
