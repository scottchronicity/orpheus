import { useRef, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Terminal, Mic, Activity, AlertTriangle, HardDrive, Radio } from 'lucide-react'
import { fetchAudioHealth, fetchServiceLogs, fetchJson } from '../lib/api'
import { fetchWithAuth, formatBytes, formatDaysUntilFull } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Card, CardHeader, PageHeader, LoadingSpinner } from '../components/ui'
import { StorageTrendChart } from '../components/Charts'
import type { AudioChannel } from '../lib/api'

const ORPHEUS_SERVICES = [
  'orpheus-agent-audio-motion',
  'orpheus-agent-audio-playback',
  'orpheus-agent-audio-events',
  'orpheus-agent-video-motion',
  'orpheus-agent-video-snapshotter',
  'orpheus-agent-video-timelapser',
  'orpheus-agent-bird-detection',
  'orpheus-agent-crow-detection',
  'orpheus-agent-event-correlator',
  'orpheus-ui',
  'orpheus-backplane',
  'orpheus-gps',
  'orpheus-bluetooth-autoconnect',
] as const

// ---------------------------------------------------------------------------
// AudioHealthPanel
// ---------------------------------------------------------------------------

const LEVEL_COLOR_MAP: Record<string, string> = {
  green: 'bg-green-500',
  yellow: 'bg-yellow-400',
  red: 'bg-red-500',
  none: 'bg-slate-600',
}

function ChannelBar({ channel }: { channel: AudioChannel }) {
  const isActive = channel.has_signal
  const barColor = LEVEL_COLOR_MAP[channel.level_color] ?? LEVEL_COLOR_MAP.none

  // Map dB range [-80, 0] → width percentage [0, 100]
  const levelDb = channel.level_db ?? -100
  const peakDbVal = channel.peak_db ?? -100
  const clampedDb = Math.max(-80, Math.min(0, levelDb))
  const widthPct = Math.round(((clampedDb + 80) / 80) * 100)

  const peakDb = peakDbVal === -100 ? '--' : `${peakDbVal.toFixed(1)} dB`
  const currentDb = levelDb === -100 ? '--' : `${levelDb.toFixed(1)} dB`

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-300 font-medium">Ch {channel.id}</span>
        <span
          className={`px-1.5 py-0.5 rounded text-xs font-semibold ${
            isActive
              ? 'bg-green-500/20 text-green-400'
              : 'bg-slate-600/40 text-slate-500'
          }`}
        >
          {isActive ? 'TRIGGERED' : 'IDLE'}
        </span>
      </div>

      {/* Level bar */}
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-200 ${barColor}`}
          style={{ width: `${widthPct}%` }}
        />
      </div>

      <div className="flex justify-between text-xs text-slate-500">
        <span>Level: {currentDb}</span>
        <span>Peak: {peakDb}</span>
      </div>
    </div>
  )
}

/**
 * Displays the audio input channels the agent reports (4 on the Jetson's
 * UMC404HD, 1 on a laptop mic) with dB levels and IDLE/TRIGGERED status.
 * Matches the existing dark-mode Tailwind aesthetic.
 */
export function AudioHealthPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['audio-health'],
    queryFn: fetchAudioHealth,
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader title="Audio System Health" icon={Mic} iconColor="green" />
        <LoadingSpinner className="h-32" />
      </Card>
    )
  }

  const channels = data?.channels ?? []
  const isRunning = data?.running ?? false

  // Show the channels the agent actually reports (a single-mic laptop gets
  // one row, the Jetson's 4-channel interface gets four). Only when nothing
  // is reported yet (agent down / first poll) keep the 4 placeholder slots.
  const reported = [...channels].sort((a, b) => Number(a.id) - Number(b.id))
  const displayChannels: AudioChannel[] =
    reported.length > 0
      ? reported
      : ['1', '2', '3', '4'].map((id) => ({
          id,
          active: false,
          level_db: -100,
          peak_db: -100,
          level_color: 'none' as const,
          has_signal: false,
        }))

  return (
    <Card>
      <CardHeader title="Audio System Health" icon={Mic} iconColor="green" />
      <div className="flex items-center gap-2 mb-4">
        <span
          className={`inline-block w-2 h-2 rounded-full ${isRunning ? 'bg-green-400' : 'bg-slate-500'}`}
        />
        <span className="text-xs text-slate-400">
          {isRunning ? 'Agent running' : data?.message ?? 'Agent not running'}
        </span>
        {data?.health_status && (
          <span
            className={`ml-auto text-xs px-2 py-0.5 rounded ${
              data.health_status === 'good'
                ? 'bg-green-500/20 text-green-400'
                : data.health_status === 'warning'
                ? 'bg-yellow-500/20 text-yellow-400'
                : 'bg-red-500/20 text-red-400'
            }`}
          >
            {data.health_status}
          </span>
        )}
      </div>

      <div className="space-y-4">
        {displayChannels.map((ch) => (
          <ChannelBar key={ch.id} channel={ch} />
        ))}
      </div>

      {data?.xrun && (
        <p className="text-xs text-slate-500 mt-4">
          XRUNs: {data.xrun.total}
          {data.xrun.rate_per_minute !== undefined &&
            ` · ${data.xrun.rate_per_minute.toFixed(1)}/min`}
        </p>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// LogViewer
// ---------------------------------------------------------------------------

/**
 * Terminal-style log viewer that polls journalctl output for a systemd service.
 * Includes a dropdown to pick from all known Orpheus services.
 */
export function LogViewer() {
  const [selectedService, setSelectedService] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['service-logs', selectedService],
    queryFn: () => fetchServiceLogs(selectedService),
    refetchInterval: POLLING_INTERVALS.REALTIME,
    enabled: selectedService !== '',
  })

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [data?.lines])

  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <CardHeader title="Service Logs" icon={Terminal} iconColor="blue" />
        <select
          value={selectedService}
          onChange={(e) => setSelectedService(e.target.value)}
          className="bg-slate-700 text-slate-200 text-xs rounded px-2 py-1.5 border border-slate-600 focus:outline-none focus:border-blue-500"
        >
          <option value="">Select a service...</option>
          {ORPHEUS_SERVICES.map((svc) => (
            <option key={svc} value={svc}>{svc}</option>
          ))}
        </select>
      </div>

      <div className="bg-black rounded-lg p-3 font-mono text-xs leading-relaxed overflow-y-auto max-h-96 min-h-48 flex-1">
        {isLoading && (
          <span className="text-slate-500 animate-pulse">Loading logs&hellip;</span>
        )}

        {error && (
          <span className="text-red-400">Failed to fetch logs: {String(error)}</span>
        )}

        {!selectedService && (
          <span className="text-slate-600">Select a service to view logs.</span>
        )}

        {selectedService && !isLoading && !error && (!data?.lines || data.lines.length === 0) && (
          <span className="text-slate-600">No log output available.</span>
        )}

        {data?.lines?.map((line, idx) => (
          <div key={idx} className="text-green-300 whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Correlator health — late-arrival detection
// ---------------------------------------------------------------------------

/**
 * Layer 2 health panel: surfaces the late-arrival case where multiple
 * Entities share the same audio_motion_source_id because a downstream
 * classifier (PANNs, crow-tools) emitted after the cluster window
 * closed. The healthy state is 1:1 — every histogram bucket beyond "1"
 * is a real signal that ops should consider widening
 * ``correlation.window_seconds`` in orpheus.yaml.
 */
interface CorrelatorHealth {
  lookback_hours: number
  ran_at: string
  roots_examined: number
  multi_entity_root_count: number
  multi_entity_root_pct: number
  entities_per_root_histogram: { '1': number; '2': number; '3+': number }
  late_arrival_examples: Array<{
    root_event_id: string
    entity_count: number
    entities: Array<{ entity_id: string; timestamp: string }>
  }>
  chain_completion_ms: {
    samples: number
    p50: number
    p95: number
    max: number
  }
}

function CorrelatorHealthPanel() {
  const [lookback, setLookback] = useState(24)
  const { data, isLoading } = useQuery<CorrelatorHealth>({
    queryKey: ['correlator-health', lookback],
    queryFn: async () => {
      const res = await fetchWithAuth(
        `/api/correlator/health?lookback_hours=${lookback}`,
      )
      if (!res.ok) throw new Error('Failed to load correlator health')
      return res.json()
    },
    refetchInterval: 60_000,
  })

  return (
    <Card>
      <CardHeader icon={Activity} title="Correlator health" />
      <p className="text-xs text-slate-500 -mt-2 mb-2">
        Late-arrival detection + window-tuning signal
      </p>
      <div className="mt-3 mb-4 flex items-center gap-2">
        <label className="text-xs text-slate-500">Lookback:</label>
        <select
          value={lookback}
          onChange={(e) => setLookback(parseInt(e.target.value, 10))}
          className="bg-slate-700 text-slate-200 text-xs rounded px-2 py-1 border border-slate-600"
        >
          <option value={1}>1h</option>
          <option value={6}>6h</option>
          <option value={24}>24h</option>
          <option value={168}>7d</option>
        </select>
      </div>
      {isLoading || !data ? (
        <LoadingSpinner />
      ) : (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-slate-500">Roots in window</p>
              <p className="text-lg text-slate-200">{data.roots_examined}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Multi-entity roots</p>
              <p
                className={
                  data.multi_entity_root_pct > 5
                    ? 'text-lg text-red-400'
                    : data.multi_entity_root_pct > 0
                      ? 'text-lg text-amber-400'
                      : 'text-lg text-emerald-400'
                }
              >
                {data.multi_entity_root_count} ({data.multi_entity_root_pct}%)
              </p>
            </div>
          </div>

          <div>
            <p className="text-xs text-slate-500 mb-1">Entities per root</p>
            <div className="flex gap-4 text-sm">
              <span className="text-emerald-400">
                1: {data.entities_per_root_histogram['1']}
              </span>
              <span className="text-amber-300">
                2: {data.entities_per_root_histogram['2']}
              </span>
              <span className="text-red-300">
                3+: {data.entities_per_root_histogram['3+']}
              </span>
            </div>
          </div>

          <div>
            <p className="text-xs text-slate-500 mb-1">
              Chain completion latency (audio.motion → last detection)
            </p>
            <p className="text-sm font-mono text-slate-200">
              p50 {data.chain_completion_ms.p50.toFixed(0)} ms · p95{' '}
              <span
                className={
                  data.chain_completion_ms.p95 > 5000
                    ? 'text-red-400'
                    : data.chain_completion_ms.p95 > 3000
                      ? 'text-amber-400'
                      : 'text-emerald-400'
                }
              >
                {data.chain_completion_ms.p95.toFixed(0)} ms
              </span>{' '}
              · max {data.chain_completion_ms.max.toFixed(0)} ms
            </p>
            <p className="text-[10px] text-slate-600 mt-1">
              If p95 exceeds <code>correlation.window_seconds</code> (default
              3000ms), downstream classifiers are routinely missing the
              cluster. Widen the window in orpheus.yaml.
            </p>
          </div>

          {data.late_arrival_examples.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                {data.late_arrival_examples.length} late-arrival example
                {data.late_arrival_examples.length === 1 ? '' : 's'}
              </summary>
              <div className="mt-2 space-y-2">
                {data.late_arrival_examples.map((ex) => (
                  <div
                    key={ex.root_event_id}
                    className="border-l-2 border-amber-500/40 pl-2"
                  >
                    <p className="font-mono text-slate-300">
                      {ex.root_event_id}
                    </p>
                    <p className="text-slate-500">
                      → {ex.entity_count} Entities (
                      {ex.entities.map((e) => e.entity_id.slice(0, 8)).join(', ')}
                      )
                    </p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </Card>
  )
}


// ---------------------------------------------------------------------------
// Recent errors feed
// ---------------------------------------------------------------------------

interface ErrorEntry {
  agent: string
  message: string
  first_seen: string
  last_seen: string
  count: number
  errors_count: number
}

interface ErrorFeedResponse {
  errors: ErrorEntry[]
  total: number
  buffer_max: number
}

/**
 * Cross-agent error feed. Reads /api/errors/recent which is fed by the
 * UI backend's wildcard subscription to ``orpheus/system/+/health``.
 * Bounded ring buffer + 60s dedup keeps the backend safe even under
 * tight error loops.
 */
function RecentErrorsPanel() {
  const [limit, setLimit] = useState(20)
  const { data, isLoading } = useQuery<ErrorFeedResponse>({
    queryKey: ['errors-recent', limit],
    queryFn: async () => {
      const res = await fetchWithAuth(`/api/errors/recent?limit=${limit}`)
      if (!res.ok) throw new Error('Failed to load errors')
      return res.json()
    },
    refetchInterval: 30_000,
    placeholderData: (previousData) => previousData,
  })

  return (
    <Card>
      <CardHeader icon={AlertTriangle} title="Recent agent errors" />
      <p className="text-xs text-slate-500 -mt-2 mb-3">
        Cross-agent error feed. Last {data?.buffer_max ?? 200} entries
        kept in memory; identical errors from the same agent within 60s
        coalesce into one entry with a count bump.
      </p>
      <div className="mb-3 flex items-center gap-2">
        <label className="text-xs text-slate-500">Show last:</label>
        <select
          value={limit}
          onChange={(e) => setLimit(parseInt(e.target.value, 10))}
          className="bg-slate-700 text-slate-200 text-xs rounded px-2 py-1 border border-slate-600"
        >
          <option value={10}>10</option>
          <option value={20}>20</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <span className="text-xs text-slate-600">
          ({data?.total ?? 0} total in buffer)
        </span>
      </div>
      {isLoading ? (
        <LoadingSpinner />
      ) : !data?.errors.length ? (
        <p className="text-sm text-emerald-400">
          ✓ No agent errors recorded.
        </p>
      ) : (
        <div className="space-y-2">
          {data.errors.map((e, i) => (
            <div
              key={`${e.agent}-${e.first_seen}-${i}`}
              className="border-l-2 border-red-500/40 pl-3 py-1"
            >
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <span className="text-xs font-mono text-red-300">
                  {e.agent}
                </span>
                <span className="text-xs text-slate-500">
                  {e.last_seen.slice(11, 19)}
                  {e.count > 1 && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 text-[10px]">
                      ×{e.count}
                    </span>
                  )}
                </span>
              </div>
              <p className="text-xs text-slate-300 font-mono break-all">
                {e.message}
              </p>
              {e.count > 1 && (
                <p className="text-[10px] text-slate-600 mt-0.5">
                  first seen: {e.first_seen.slice(11, 19)} · lifetime errors:{' '}
                  {e.errors_count}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}


// ---------------------------------------------------------------------------
// Agent presence — KV-TTL liveness consumer
// ---------------------------------------------------------------------------

interface PresenceResponse {
  supported: boolean
  // Optional: a supported:true payload from a degraded backend may omit it.
  agents?: Record<string, Record<string, unknown>>
}

/**
 * Lists agents currently live in the KV-TTL presence bucket
 * (GET /api/diagnostics/presence). An agent that dies stops refreshing its
 * key and drops off within the TTL, so this is "who is online right now".
 * supported:false only means the backend can't serve KV at all (e.g. mqtt).
 * On JetStream with producers off (event_bus.presence_enabled=false, the
 * default) the bucket is simply absent/empty, so the panel shows the empty
 * state — hence the hint it renders alongside "no agents".
 */
export function PresencePanel() {
  const { data, isLoading } = useQuery<PresenceResponse>({
    queryKey: ['agent-presence'],
    queryFn: () => fetchJson<PresenceResponse>('/api/diagnostics/presence'),
    // Back off to 60s once the backend reports the feature unsupported —
    // no point hammering an absent bucket at the HEALTH tier forever.
    refetchInterval: (query) =>
      query.state.data && !query.state.data.supported ? 60_000 : POLLING_INTERVALS.HEALTH,
  })

  // ``agents`` is guarded so a supported:true payload without the key (e.g. a
  // degraded/partial backend response) renders the empty state, not a crash.
  const agentIds = data?.supported ? Object.keys(data.agents ?? {}).sort() : []

  return (
    <Card>
      <CardHeader icon={Radio} title="Agent presence" />
      <p className="text-xs text-slate-500 -mt-2 mb-3">
        Live agents from the presence bucket — a dead agent stops refreshing
        its key and drops off within the TTL.
      </p>
      {isLoading ? (
        <LoadingSpinner />
      ) : !data?.supported ? (
        <p className="text-sm text-slate-500">
          Presence not available on this backend/config.
        </p>
      ) : agentIds.length === 0 ? (
        <p className="text-sm text-slate-500">
          No agents currently online — or presence producers are disabled
          (event_bus.presence_enabled).
        </p>
      ) : (
        <div className="space-y-2">
          {agentIds.map((agentId) => (
            <div key={agentId} className="flex items-center justify-between">
              <span className="text-sm font-mono text-slate-300">{agentId}</span>
              <span className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-green-400" />
                <span className="text-xs text-green-400">online</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}


// ---------------------------------------------------------------------------
// StorageTrendPanel — daily free-space history + days-until-full per volume
// ---------------------------------------------------------------------------

interface StorageVolumeTrend {
  key: string
  label: string
  path: string
  total: number | null
  used: number | null
  free: number | null
  percent: number
  ok: boolean
  error: string | null
  series: Array<{ day: string; free_bytes: number | null; total_bytes: number | null }>
  free_bytes_per_day: number | null
  projected_days_until_full: number | null
}

interface StorageHistoryResponse {
  days: number
  volumes: StorageVolumeTrend[]
}

function StorageTrendPanel() {
  const { data, isLoading } = useQuery<StorageHistoryResponse>({
    queryKey: ['storage-history'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/system/storage/history?days=30')
      if (!res.ok) throw new Error('Failed to load storage history')
      return res.json()
    },
    refetchInterval: 60_000,
  })

  return (
    <Card>
      <CardHeader icon={HardDrive} title="Storage trend" />
      <p className="text-xs text-slate-500 -mt-2 mb-3">
        Free space over time and projected days until full, per volume. History
        starts the day this was deployed; the rate needs ≥ 2 days.
      </p>
      {isLoading || !data ? (
        <LoadingSpinner />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {data.volumes.map((vol) => {
            const fillRate = vol.free_bytes_per_day
            // free_bytes_per_day is signed: negative = filling up.
            const filling = fillRate !== null && fillRate < 0
            return (
              <div key={vol.key} className="space-y-2">
                <div className="flex items-baseline justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-200">{vol.label}</p>
                    <p className="text-xs text-slate-500">{vol.path}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-slate-300">
                      {formatBytes(vol.used)} / {formatBytes(vol.total)}
                    </p>
                    <p className="text-xs text-slate-500">{vol.percent.toFixed(0)}% used</p>
                  </div>
                </div>

                {vol.ok ? (
                  <>
                    <StorageTrendChart series={vol.series} />
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-500">
                        {filling ? 'Filling' : 'Trend'}:{' '}
                        <span className={filling ? 'text-amber-400' : 'text-slate-300'}>
                          {fillRate === null
                            ? 'collecting…'
                            : `${formatBytes(Math.abs(fillRate))}/day ${filling ? 'less free' : 'more free'}`}
                        </span>
                      </span>
                      <span className="text-slate-500">
                        Full in:{' '}
                        <span
                          className={
                            vol.projected_days_until_full !== null &&
                            vol.projected_days_until_full < 14
                              ? 'text-red-400 font-medium'
                              : 'text-slate-300'
                          }
                        >
                          {formatDaysUntilFull(vol.projected_days_until_full)}
                        </span>
                      </span>
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-red-400 py-4">
                    Unavailable{vol.error ? `: ${vol.error}` : ''}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}


// ---------------------------------------------------------------------------
// StorageHeadroomPanel
// ---------------------------------------------------------------------------

interface HeadroomSweep {
  at: string | null
  files_removed: number
  bytes_freed: number
  oldest_removed: string | null
  newest_removed: string | null
}

interface HeadroomCategory {
  key: string
  label: string
  description: string
  path: string
  measured: boolean
  bytes: number | null
  file_count: number | null
  has_policy: boolean
  policy_kind: 'size_budget' | null
  limit_bytes: number | null
  percent_of_limit: number | null
  trigger_percent: number | null
  retention_days: number | null
  policy_note: string | null
  last_sweep: HeadroomSweep | null
  // What a sweep would have removed had it been enforcing. Mutually exclusive
  // with last_sweep: the sweep publishes one or the other, never both.
  would_remove: HeadroomSweep | null
}

/** What orpheus-storage-sweep is doing. Only 'enforcing' deletes anything. */
type SweepState = 'enforcing' | 'report_only' | 'disabled' | 'never_run' | 'stale'

interface HeadroomResponse {
  data_root: string
  measured_at: string | null
  check_interval_hours: number
  sweep_state: SweepState
  categories: HeadroomCategory[]
  filesystem: {
    total_bytes: number | null
    free_bytes: number | null
    free_percent: number | null
    min_free_space_percent: number
    reserve_bytes: number | null
    guard_enabled: boolean
    guard_tripped: boolean
    blocked_under_reserve: boolean
  }
}

/**
 * Whether anything is actually deleting, said plainly.
 *
 * The panel existed for a while above an arrangement where nothing trimmed
 * the largest directory on the disk, and it had no way to say so. Every
 * state but 'enforcing' means recordings are accumulating untouched, and
 * each one has a different fix, so they are not collapsed into "inactive".
 */
const SWEEP_STATE_NOTE: Record<SweepState, { text: string; tone: string } | null> = {
  enforcing: null,
  report_only: {
    text: 'Reporting only — the first-run grace is still in effect, so nothing has been deleted yet. Review with `make storage-report`; enforcement starts automatically, or now with `orpheus-storage-sweep --force`.',
    tone: 'text-amber-400',
  },
  disabled: {
    text: 'Disabled — storage.retention.sweep_enabled is false. Nothing on this station deletes recordings; these numbers will only grow.',
    tone: 'text-amber-400',
  },
  never_run: {
    text: 'The storage sweep has not run yet, so nothing is deleting recordings. Check that orpheus-storage-sweep.timer is enabled.',
    tone: 'text-amber-400',
  },
  stale: {
    text: 'These numbers are older than the sweep cadence, which means the sweep has stopped running — nothing is deleting recordings and everything below is out of date. Check orpheus-storage-sweep.timer and `journalctl -u orpheus-storage-sweep`.',
    tone: 'text-red-400',
  },
}

/** "15 min" or "6h" — the cadence in the unit that reads naturally. */
function formatCadence(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)} min`
  return `${hours}h`
}

/** "3h ago" for a report timestamp, so staleness is legible at a glance. */
function formatAge(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'unknown'
  const minutes = Math.floor((Date.now() - then) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/**
 * One category: what it is using, and what (if anything) trims it.
 *
 * The bar is drawn only where there is a ceiling, because that is the only
 * case where a percentage means something. "Nothing cleans this" is not a
 * measurement at all, and drawing it as a fraction would invent a ceiling
 * that does not exist. The floor is stated in words next to the bar rather
 * than drawn on it: it is a promise about time, not about size.
 */
function CategoryRow({ cat }: { cat: HeadroomCategory }) {
  const pct = cat.percent_of_limit
  const trigger = cat.trigger_percent
  const overTrigger = pct !== null && trigger !== null && pct >= trigger

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-200">{cat.label}</p>
          <p className="text-xs text-slate-500 truncate" title={cat.path}>
            {cat.description}
          </p>
        </div>
        <div className="text-right shrink-0">
          {cat.measured ? (
            <>
              <p className="text-sm text-slate-300">
                {formatBytes(cat.bytes)}
                {cat.limit_bytes !== null && (
                  <span className="text-slate-500"> / {formatBytes(cat.limit_bytes)}</span>
                )}
              </p>
              {cat.file_count !== null && (
                <p className="text-xs text-slate-500">
                  {cat.file_count.toLocaleString()} files
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-500">not yet measured</p>
          )}
        </div>
      </div>

      {cat.policy_kind === 'size_budget' && cat.measured && pct !== null ? (
        <>
          <div className="relative h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${overTrigger ? 'bg-amber-400' : 'bg-blue-500'}`}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
            {trigger !== null && trigger < 100 && (
              <div
                className="absolute top-0 h-full w-px bg-slate-300/70"
                style={{ left: `${Math.min(trigger, 100)}%` }}
                title={`Trimmed at ${trigger}%`}
              />
            )}
          </div>
          <p className="text-xs text-slate-500">
            {pct.toFixed(1)}% of budget
            {cat.retention_days !== null && ` · keeps the last ${cat.retention_days} days`}
          </p>
        </>
      ) : (
        <p className="text-xs text-slate-500">
          {cat.has_policy
            ? 'Waiting for the first sweep to report against its limit.'
            : 'Nothing cleans this up.'}
        </p>
      )}

      {cat.policy_note && <p className="text-xs text-amber-400">{cat.policy_note}</p>}

      {cat.last_sweep && cat.last_sweep.files_removed > 0 && (
        <p className="text-xs text-slate-400">
          Last pass removed {cat.last_sweep.files_removed.toLocaleString()} files (
          {formatBytes(cat.last_sweep.bytes_freed)})
          {cat.last_sweep.oldest_removed && cat.last_sweep.newest_removed && (
            <span className="text-slate-500">
              {' '}
              from {cat.last_sweep.oldest_removed.slice(0, 10)} to{' '}
              {cat.last_sweep.newest_removed.slice(0, 10)}
            </span>
          )}
        </p>
      )}

      {/* A forecast, not history: the sweep decided this and deleted nothing,
          because it is inside the first-run grace or switched off. Worded so
          it cannot be misread as a deletion that happened. */}
      {cat.would_remove && cat.would_remove.files_removed > 0 && (
        <p className="text-xs text-amber-400">
          Would remove {cat.would_remove.files_removed.toLocaleString()} files (
          {formatBytes(cat.would_remove.bytes_freed)}) — nothing was deleted
          {cat.would_remove.oldest_removed && cat.would_remove.newest_removed && (
            <span className="text-amber-400/70">
              {' '}
              from {cat.would_remove.oldest_removed.slice(0, 10)} to{' '}
              {cat.would_remove.newest_removed.slice(0, 10)}
            </span>
          )}
        </p>
      )}
    </div>
  )
}

export function StorageHeadroomPanel() {
  const { data, isLoading, error } = useQuery<HeadroomResponse>({
    queryKey: ['storage-headroom'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/system/storage/headroom')
      if (!res.ok) throw new Error('Failed to load storage headroom')
      return res.json()
    },
    refetchInterval: 60_000,
  })

  const fs = data?.filesystem
  const guardTight =
    fs?.guard_enabled &&
    fs.free_bytes !== null &&
    fs.free_bytes !== undefined &&
    fs.reserve_bytes !== null &&
    fs.free_bytes <= fs.reserve_bytes * 1.5

  return (
    <Card>
      <CardHeader icon={HardDrive} title="Storage headroom" />
      <p className="text-xs text-slate-500 -mt-2 mb-3">
        What each kind of recording is using, and which of them are trimmed
        automatically. Measured by orpheus-storage-sweep
        {data ? ` (every ${formatCadence(data.check_interval_hours)})` : ''}
        {data?.measured_at ? `, last ${formatAge(data.measured_at)}` : ''}.
      </p>

      {data && SWEEP_STATE_NOTE[data.sweep_state] && (
        <p className={`text-xs mb-3 ${SWEEP_STATE_NOTE[data.sweep_state]!.tone}`}>
          {SWEEP_STATE_NOTE[data.sweep_state]!.text}
        </p>
      )}

      {isLoading ? (
        <LoadingSpinner />
      ) : error || !data ? (
        <p className="text-xs text-red-400 py-4">
          Unavailable — the storage report could not be loaded.
        </p>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-5">
            {data.categories.map((cat) => (
              <CategoryRow key={cat.key} cat={cat} />
            ))}
          </div>

          <div className="pt-3 border-t border-slate-700">
            <div className="flex items-baseline justify-between">
              <p className="text-sm text-slate-300">Free-space reserve</p>
              <p className="text-sm text-slate-300">
                {fs?.free_bytes !== null && fs?.free_bytes !== undefined ? (
                  <span className={guardTight ? 'text-amber-400 font-medium' : ''}>
                    {formatBytes(fs.free_bytes)} free
                    {fs.free_percent !== null && (
                      <span className="text-slate-500"> ({fs.free_percent.toFixed(1)}%)</span>
                    )}
                  </span>
                ) : (
                  <span className="text-slate-500">not reported</span>
                )}
              </p>
            </div>
            <p className="text-xs text-slate-500">
              {fs?.guard_enabled
                ? `Below ${formatBytes(fs.reserve_bytes)} free, every category above its floor gives up data in proportion to what it has to give.`
                : 'Disabled — nothing acts on low disk space; categories are limited only by their own ceilings.'}
              {fs?.guard_tripped && !fs?.blocked_under_reserve && (
                <span className="text-amber-400"> Currently below the reserve.</span>
              )}
            </p>
            {fs?.blocked_under_reserve && (
              <p className="text-xs text-red-400 mt-1">
                Below the reserve with every category at its retention floor. The sweep
                will not delete inside a floor, so it has stopped. Lower a floor, lower the
                reserve, or add capacity.
              </p>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}

export default function DiagnosticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Diagnostics"
        description="Correlator health, storage, errors, presence, audio, and service logs"
      />

      <CorrelatorHealthPanel />
      <StorageTrendPanel />
      <StorageHeadroomPanel />
      <RecentErrorsPanel />
      <PresencePanel />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AudioHealthPanel />
        <LogViewer />
      </div>
    </div>
  )
}
