import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchWithAuth, formatDateTime } from '../lib/utils'
import { fetchJson } from '../lib/api'
import { POLLING_INTERVALS } from '../config'
import { Waves, Activity, X, MapPin, Code, Sparkles, Clock, GitCompare, AlertTriangle, CheckCircle2 } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  Card,
  StatCard,
  Pagination,
} from '../components/ui'
import {
  DateRangeFilter,
  usePaginatedDateRange,
  useUrlMultiSelect,
  ITEMS_PER_PAGE,
  DEFAULT_START_TIME,
  DEFAULT_END_TIME,
} from '../components/DateRangeFilter'
import { ConfidenceScatterChart, DistributionPieChart, SpeciesBarChart, DailyActivityChart, HourlyActivityChart } from '../components/Charts'
import { ClipActions } from '../components/ClipActions'
import { LocationBadge, SpatiotemporalContext } from '../components/LocationBadge'
import { SpeciesFilter } from '../components/SpeciesFilter'

/**
 * ADR 0010 — Temporal Localisation and Taxonomy References.
 */
interface TemporalInterval {
  start_seconds: number
  end_seconds: number
  confidence?: number | null
}

interface TaxonomyRef {
  namespace: string
  id: string
  common_name?: string | null
}

interface AudioEventDetection {
  /** Unique event id from the backend Detection model — stable across
   *  pagination so it's the right thing to use as a React key. */
  event_id?: string
  timestamp: string
  species_code: string
  species_common: string
  confidence: number
  channel: string | number
  audio_clip_path?: string
  context?: SpatiotemporalContext
  source_event_id?: string
  /** Intra-clip time ranges where the label fired (PANNs SED frames). */
  intervals?: TemporalInterval[] | null
  /** Taxonomy reference — AudioSet machine_id is canonical. */
  taxonomy?: TaxonomyRef | null
}

interface AudioEventsStats {
  total_count: number
  unique_label_count: number
  hourly_activity: { hour: number; count: number }[]
  daily_activity: { date: string; count: number }[]
  label_distribution: Record<string, number>
  all_labels?: Record<string, number>
}

interface AudioEventScatterPoint {
  timestamp: string
  species_code: string
  species_common: string
  confidence: number
}

interface AudioEventsHistoryResponse {
  detections: AudioEventDetection[]
  scatter_sample: AudioEventScatterPoint[]
  count: number
  start_date: string
  end_date: string
  stats: AudioEventsStats
  page?: number
  page_size?: number
  total_pages?: number
}

/**
 * Bird-detection parity dashboard payload. See
 * docs/designs/audio-events-smoke-test.md §4 for the gating-decision rules.
 */
interface BirdCorrelationDay {
  date: string
  audio_motion_count: number
  both: number
  audio_events_only: number
  birdnet_only: number
  neither: number
}

interface BirdCorrelationSummary {
  audio_motion_count: number
  birdnet_caught_count: number
  audio_events_caught_count: number
  both_count: number
  audio_events_only_count: number
  birdnet_only_count: number
  neither_count: number
  parity_ratio: number | null
  ready_to_gate: boolean
}

interface BirdnetOnlyClip {
  audio_motion_event_id: string
  timestamp: string
  audio_clip_path?: string
  channel?: string | number
}

interface BirdCorrelationResponse {
  start_date: string
  end_date: string
  daily_counts: BirdCorrelationDay[]
  summary: BirdCorrelationSummary
  birdnet_only_clips: BirdnetOnlyClip[]
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return 'text-green-400'
  if (confidence >= 0.4) return 'text-amber-400'
  return 'text-red-400'
}

function formatInterval(iv: TemporalInterval): string {
  const dur = iv.end_seconds - iv.start_seconds
  return `${iv.start_seconds.toFixed(1)}–${iv.end_seconds.toFixed(1)}s (${dur.toFixed(1)}s)`
}

function IntervalsCell({ intervals }: { intervals?: TemporalInterval[] | null }) {
  if (!intervals || intervals.length === 0) {
    return <span className="text-slate-500 text-xs">—</span>
  }
  const visible = intervals.slice(0, 2)
  const overflow = intervals.length - visible.length
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((iv, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-slate-700 text-slate-200 rounded"
          title={formatInterval(iv)}
        >
          <Clock className="w-3 h-3" />
          {iv.start_seconds.toFixed(1)}s
        </span>
      ))}
      {overflow > 0 && (
        <span className="text-xs text-slate-400">+{overflow}</span>
      )}
    </div>
  )
}

function BirdCorrelationPanel({ startDate, endDate }: { startDate: string; endDate: string }) {
  const { data, isLoading, error } = useQuery<BirdCorrelationResponse>({
    queryKey: ['audio-events-bird-correlation', startDate, endDate],
    queryFn: async () => {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
      })
      return fetchJson<BirdCorrelationResponse>(`/api/data/audio-events/bird-correlation?${params.toString()}`)
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
    placeholderData: (previousData) => previousData,
  })

  if (isLoading) {
    return (
      <Card>
        <h2 className="text-lg font-medium text-white mb-2 flex items-center gap-2">
          <GitCompare className="w-5 h-5 text-blue-400" />
          Bird Correlation vs BirdNET
        </h2>
        <p className="text-sm text-slate-500">Loading…</p>
      </Card>
    )
  }

  if (error || !data || !data.summary || !data.daily_counts) {
    return (
      <Card>
        <h2 className="text-lg font-medium text-white mb-2 flex items-center gap-2">
          <GitCompare className="w-5 h-5 text-blue-400" />
          Bird Correlation vs BirdNET
        </h2>
        <p className="text-sm text-slate-500">
          {error ? 'Failed to load correlation data.' : 'No correlation data yet.'}
        </p>
      </Card>
    )
  }

  const summary = data.summary
  const daily_counts = data.daily_counts
  const birdnet_only_clips = data.birdnet_only_clips ?? []

  const parityPct =
    summary.parity_ratio == null ? null : Math.round(summary.parity_ratio * 100)

  // Color logic: ≥ 100% = green (parity), 80-99% = amber (close), <80% = red (gap).
  const parityColor =
    parityPct == null
      ? 'text-slate-400'
      : parityPct >= 100
      ? 'text-green-400'
      : parityPct >= 80
      ? 'text-amber-400'
      : 'text-red-400'

  // Max counts per day for proportional bar widths.
  const maxDay = Math.max(
    1,
    ...daily_counts.map((d) => d.both + d.audio_events_only + d.birdnet_only + d.neither),
  )

  return (
    <Card>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-lg font-medium text-white flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-blue-400" />
            Bird Correlation vs BirdNET
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Per audio-motion event: did each classifier catch a bird? Watch this
            until the parity ratio is ≥ 100% over several days — that's the gate
            condition for putting bird-detection downstream of audio-events.
          </p>
        </div>
      </div>

      {/* Big parity gauge */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="p-4">
          <div className="text-xs uppercase text-slate-500 mb-1">Parity ratio</div>
          <div className={`text-3xl font-medium ${parityColor}`}>
            {parityPct == null ? '—' : `${parityPct}%`}
          </div>
          <div className="text-xs text-slate-400 mt-2 flex items-center gap-1">
            {summary.ready_to_gate ? (
              <>
                <CheckCircle2 className="w-3 h-3 text-green-400" />
                <span className="text-green-400">Ready to gate</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-3 h-3 text-amber-400" />
                <span>Not ready</span>
              </>
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs uppercase text-slate-500 mb-1">Both caught</div>
          <div className="text-2xl font-medium text-green-400">{summary.both_count}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs uppercase text-slate-500 mb-1">BirdNET only (misses)</div>
          <div className={`text-2xl font-medium ${summary.birdnet_only_count > 0 ? 'text-red-400' : 'text-slate-400'}`}>
            {summary.birdnet_only_count}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs uppercase text-slate-500 mb-1">Audio-events only</div>
          <div className="text-2xl font-medium text-blue-400">
            {summary.audio_events_only_count}
          </div>
        </Card>
      </div>

      {/* Daily breakdown */}
      {daily_counts.length > 0 ? (
        <div className="space-y-2">
          <div className="text-xs uppercase text-slate-500 mb-1">By day</div>
          <div className="flex items-center gap-3 text-xs text-slate-400 mb-2">
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-green-500/70 rounded-sm" />
              Both
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-blue-500/70 rounded-sm" />
              Audio-events only
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-red-500/70 rounded-sm" />
              BirdNET only
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-slate-500/40 rounded-sm" />
              Neither (non-bird)
            </span>
          </div>
          {daily_counts.map((d) => {
            const total = d.both + d.audio_events_only + d.birdnet_only + d.neither
            const w = (n: number) => `${(n / maxDay) * 100}%`
            return (
              <div key={d.date} className="flex items-center gap-3 text-xs">
                <span className="text-slate-300 w-24 font-mono">{d.date}</span>
                <div className="flex-1 h-4 bg-slate-800 rounded overflow-hidden flex">
                  {d.both > 0 && (
                    <div className="bg-green-500/70" style={{ width: w(d.both) }} title={`both: ${d.both}`} />
                  )}
                  {d.audio_events_only > 0 && (
                    <div className="bg-blue-500/70" style={{ width: w(d.audio_events_only) }} title={`audio-events only: ${d.audio_events_only}`} />
                  )}
                  {d.birdnet_only > 0 && (
                    <div className="bg-red-500/70" style={{ width: w(d.birdnet_only) }} title={`birdnet only: ${d.birdnet_only}`} />
                  )}
                  {d.neither > 0 && (
                    <div className="bg-slate-500/40" style={{ width: w(d.neither) }} title={`neither: ${d.neither}`} />
                  )}
                </div>
                <span className="text-slate-400 w-12 text-right">{total}</span>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-slate-500 text-center py-4 text-sm">
          No audio-motion events in the selected range yet.
        </p>
      )}

      {/* Actionable misses */}
      {birdnet_only_clips.length > 0 && (
        <div className="mt-6 pt-6 border-t border-slate-700">
          <h3 className="text-sm font-medium text-white mb-2">
            BirdNET caught these — audio-events missed them
          </h3>
          <p className="text-xs text-slate-500 mb-3">
            These are the clips that block gating. Listen to a sample, then
            tune <code className="text-slate-300">clip_threshold</code> or{' '}
            <code className="text-slate-300">frame_threshold</code> in
            audio-events config. Showing up to 200.
          </p>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {birdnet_only_clips.slice(0, 50).map((c) => (
              <div
                key={c.audio_motion_event_id}
                className="flex items-center justify-between text-xs py-1.5 border-b border-slate-700/40"
              >
                <span className="text-slate-400 font-mono truncate">
                  {c.audio_motion_event_id}
                </span>
                <span className="text-slate-500">{formatDateTime(c.timestamp)}</span>
                <ClipActions
                  clipPath={c.audio_clip_path}
                  type="audio"
                  channelId={String(c.channel ?? '')}
                />
              </div>
            ))}
            {birdnet_only_clips.length > 50 && (
              <div className="text-xs text-slate-500 pt-2 text-center">
                {birdnet_only_clips.length - 50} more not shown
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}

function AudioEventDetail({
  detection,
  onClose,
}: {
  detection: AudioEventDetection
  onClose: () => void
}) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-slate-800 shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-slate-800 border-b border-slate-700 p-6 flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-medium text-white">{detection.species_common}</h2>
            <p className="text-sm text-slate-400 mt-1">{formatDateTime(detection.timestamp)}</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white"
            aria-label="Close"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <Card className="p-4">
              <div className="text-xs uppercase text-slate-500 mb-1">Confidence</div>
              <div className={`text-2xl font-medium ${getConfidenceColor(detection.confidence)}`}>
                {(detection.confidence * 100).toFixed(0)}%
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs uppercase text-slate-500 mb-1">Channel</div>
              <div className="text-2xl font-medium text-white">Ch {detection.channel}</div>
            </Card>
          </div>

          {detection.taxonomy && (
            <Card className="p-4">
              <div className="text-xs uppercase text-slate-500 mb-1">Taxonomy</div>
              <div className="text-sm">
                <span className="text-slate-400">{detection.taxonomy.namespace}</span>
                {' / '}
                <span className="text-white font-mono">{detection.taxonomy.id}</span>
              </div>
              {detection.taxonomy.common_name && (
                <div className="text-xs text-slate-400 mt-1">{detection.taxonomy.common_name}</div>
              )}
            </Card>
          )}

          {detection.intervals && detection.intervals.length > 0 && (
            <Card className="p-4">
              <div className="text-xs uppercase text-slate-500 mb-2">Intra-clip intervals</div>
              <div className="space-y-1">
                {detection.intervals.map((iv, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2 text-slate-200">
                      <Clock className="w-4 h-4 text-blue-400" />
                      {formatInterval(iv)}
                    </div>
                    {iv.confidence != null && (
                      <span className={`text-xs ${getConfidenceColor(iv.confidence)}`}>
                        {(iv.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {detection.context && (detection.context.lat != null || detection.context.lon != null) && (
            <Card className="p-4">
              <div className="flex items-center gap-2 text-sm text-slate-300">
                <MapPin className="w-4 h-4 text-purple-400" />
                {detection.context.lat?.toFixed(5)}, {detection.context.lon?.toFixed(5)}
                {detection.context.sensor_id && (
                  <span className="text-xs text-slate-500 ml-2">({detection.context.sensor_id})</span>
                )}
              </div>
            </Card>
          )}

          {detection.source_event_id && (
            <Card className="p-4">
              <div className="text-xs uppercase text-slate-500 mb-1">Triggered by</div>
              <p className="text-xs text-slate-400 font-mono break-all">
                {detection.source_event_id}
              </p>
            </Card>
          )}

          <div>
            <button
              onClick={() => setShowJson(!showJson)}
              className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
            >
              <Code className="w-4 h-4" />
              {showJson ? 'Hide' : 'Show'} Raw JSON
            </button>
            {showJson && (
              <pre className="mt-3 bg-slate-900 rounded-lg p-4 text-xs text-slate-300 overflow-x-auto max-h-96">
                {JSON.stringify(detection, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Health card for the audio-events agent. Reads /api/audio-events/health
 * which is fed by MQTT heartbeats from the agent. Surfaces:
 *   - model_loaded status (catches PANNs OOM / checkpoint-missing on Jetson)
 *   - rolling inference latency (p50 / p95 / max) — flags thermal throttling
 *   - events processed + detections emitted (throughput sanity)
 *   - error count + last error message
 *
 * Polled every 30s. The biggest deployment risk on Jetson is the PANNs
 * model itself; this card is how ops sees it's healthy.
 */
interface AudioEventsHealth {
  status?: 'online' | 'offline' | 'never_seen'
  model_loaded?: boolean
  model_variant?: string
  started_at?: string
  timestamp?: string
  events_processed?: number
  detections_emitted?: number
  errors_count?: number
  last_error?: string | null
  last_inference_at?: string | null
  inference_latency_ms?: {
    samples: number
    p50: number
    p95: number
    max: number
  }
}

function AudioEventsAgentHealth() {
  const { data, isLoading } = useQuery<AudioEventsHealth>({
    queryKey: ['audio-events-health'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/audio-events/health')
      if (!res.ok) throw new Error('Failed to load audio-events health')
      return res.json()
    },
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <Card className="p-4">
        <p className="text-xs text-slate-500">Loading agent health…</p>
      </Card>
    )
  }
  if (!data) return null

  if (data.status === 'never_seen') {
    return (
      <Card className="p-4 border-amber-500/30 bg-amber-500/5">
        <p className="text-sm text-amber-200">
          ⚠ Agent health not yet observed. The audio-events agent may not be
          running, or hasn&apos;t sent its first 30s heartbeat yet.
        </p>
      </Card>
    )
  }

  const isOnline = data.status === 'online'
  const lat = data.inference_latency_ms
  const latencyColor =
    lat && lat.p95 > 3000
      ? 'text-red-400'
      : lat && lat.p95 > 1500
        ? 'text-amber-400'
        : 'text-emerald-400'
  const errColor = (data.errors_count ?? 0) > 0 ? 'text-amber-400' : 'text-slate-400'

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-medium text-white">Agent health</h3>
        <span
          className={
            isOnline
              ? 'text-xs text-emerald-400 font-mono'
              : 'text-xs text-red-400 font-mono'
          }
        >
          ● {data.status?.toUpperCase()}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div>
          <p className="text-slate-500">Model</p>
          <p className="text-slate-200 font-mono">
            {data.model_loaded ? data.model_variant ?? 'loaded' : 'NOT LOADED'}
          </p>
        </div>
        <div>
          <p className="text-slate-500">Throughput</p>
          <p className="text-slate-200">
            {data.events_processed ?? 0} events ·{' '}
            {data.detections_emitted ?? 0} detections
          </p>
        </div>
        <div>
          <p className="text-slate-500">Inference latency p50/p95/max</p>
          <p className={`font-mono ${latencyColor}`}>
            {lat
              ? `${lat.p50.toFixed(0)} / ${lat.p95.toFixed(0)} / ${lat.max.toFixed(0)} ms`
              : '—'}
          </p>
        </div>
        <div>
          <p className="text-slate-500">Errors</p>
          <p className={`font-mono ${errColor}`}>{data.errors_count ?? 0}</p>
        </div>
      </div>
      {data.last_error && (
        <p className="text-xs text-amber-300 mt-3 font-mono break-all">
          Last error: {data.last_error}
        </p>
      )}
      {data.last_inference_at && (
        <p className="text-xs text-slate-600 mt-1">
          Last inference: {data.last_inference_at}
        </p>
      )}
    </Card>
  )
}


export default function AudioEventsPage() {
  const { startDate, endDate, startTime, endTime, handleChange, page, setPage } =
    usePaginatedDateRange(1)
  const [selectedDetection, setSelectedDetection] = useState<AudioEventDetection | null>(null)
  // Label selection lives in ``?label=...`` so the URL captures the
  // full filter state — bookmark-able, shareable, reload-safe. No
  // date-change reset: the URL is the source of truth. Uses ``|`` as
  // separator because AudioSet display names routinely contain literal
  // commas (e.g. ``"Heart sounds, heartbeat"`` — AudioSet machine_id
  // /m/03qc9zr); the backend ``labels=`` parser splits on the same
  // separator (see api/diagnostics.py).
  const [selectedLabels, setSelectedLabels] = useUrlMultiSelect('label', {
    separator: '|',
  })

  const labelsParam = useMemo(() => {
    const arr = Array.from(selectedLabels)
    return arr.length === 0 ? '' : arr.join('|')
  }, [selectedLabels])

  const timeFilterActive = startTime !== DEFAULT_START_TIME || endTime !== DEFAULT_END_TIME
  const browserTz = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
      return 'UTC'
    }
  }, [])

  const { data, isLoading, isFetching, error, isPlaceholderData } = useQuery<AudioEventsHistoryResponse>({
    queryKey: ['audio-events-history', startDate, endDate, startTime, endTime, page, labelsParam],
    queryFn: async () => {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        page: String(page),
        page_size: String(ITEMS_PER_PAGE),
      })
      if (labelsParam) params.set('labels', labelsParam)
      if (timeFilterActive) {
        params.set('start_time', startTime)
        params.set('end_time', endTime)
        params.set('tz', browserTz)
      }
      return fetchJson<AudioEventsHistoryResponse>(`/api/data/audio-events/history?${params.toString()}`)
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
    placeholderData: (previousData) => previousData,
  })

  if (isLoading) {
    return <LoadingSpinner />
  }

  if (error) {
    return (
      <ErrorMessage
        title="Audio Events"
        description="General-purpose AudioSet classifier output (PANNs SED)"
        message="Failed to load audio events data"
      />
    )
  }

  const labelDist = data?.stats?.label_distribution ?? {}
  const allLabels = data?.stats?.all_labels ?? {}
  const sortedLabels = Object.entries(labelDist)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)

  const availableLabelItems = Object.entries(allLabels)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([value, count]) => ({ value, count }))

  const pageDetections = data?.detections ?? []
  const totalCount = data?.stats?.total_count ?? data?.count ?? 0
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audio Events"
        description="General-purpose AudioSet 527-class classifier output (PANNs SED)"
      />

      <Card className="p-4 flex items-start gap-3">
        <Sparkles className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-slate-300">
          This page shows <span className="text-white">raw audio-event classifier output</span> from
          PANNs Sound Event Detection on the AudioSet ontology. For de-duplicated, multi-sensor-correlated
          sightings see{' '}
          <Link to="/entities" className="text-blue-400 hover:text-blue-300 underline">
            Entities
          </Link>
          .
        </div>
      </Card>

      <AudioEventsAgentHealth />

      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        startTime={startTime}
        endTime={endTime}
        onChange={handleChange}
        isPlaceholderData={isPlaceholderData}
      />

      <SpeciesFilter
        availableItems={availableLabelItems}
        selected={selectedLabels}
        // No separate setPage(1) here: useUrlMultiSelect.setValue
        // resets ``page`` atomically inside the SAME setSearchParams
        // call. Two sequential setSearchParams calls would race
        // (react-router-dom v6 closes over the stale searchParams
        // and the second navigate clobbers the first), losing the
        // selection. See DateRangeFilter.tsx useUrlMultiSelect
        // docstring.
        onChange={setSelectedLabels}
        label="Labels"
      />

      {/* Bird Correlation panel — the gating signal for putting bird-detection
          behind audio-events. See docs/designs/audio-events-smoke-test.md §4. */}
      <BirdCorrelationPanel startDate={startDate} endDate={endDate} />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <StatCard title="Total Events" value={totalCount} icon={Waves} color="blue" />
        <StatCard
          title="Unique Labels"
          value={data?.stats?.unique_label_count ?? 0}
          icon={Activity}
          color="green"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Events per Day</h2>
          <p className="text-xs text-slate-500 mb-3">All events across selected date range</p>
          <DailyActivityChart data={data?.stats?.daily_activity ?? []} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Label Distribution</h2>
          <p className="text-xs text-slate-500 mb-3">All events in selected date range</p>
          <DistributionPieChart data={labelDist} />
        </Card>
      </div>

      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Top Labels</h2>
        <p className="text-xs text-slate-500 mb-3">All events in selected date range</p>
        {sortedLabels.length > 0 ? (
          <SpeciesBarChart data={sortedLabels.map(([species, count]) => ({ species, count }))} />
        ) : (
          <p className="text-slate-500 text-center py-8">No events in selected date range</p>
        )}
      </Card>

      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Hourly Activity</h2>
        <p className="text-xs text-slate-500 mb-3">All events grouped by hour of day</p>
        <HourlyActivityChart data={data?.stats?.hourly_activity ?? []} />
      </Card>

      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Confidence Over Time</h2>
        <p className="text-xs text-slate-500 mb-3">Sample of up to 500 events evenly distributed across range</p>
        <ConfidenceScatterChart data={data?.scatter_sample || []} startDate={startDate} endDate={endDate} />
      </Card>

      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Events in Date Range</h2>
          {totalCount > 0 && (
            <span className="text-sm text-slate-400">
              {totalCount.toLocaleString()} total, showing {pageDetections.length} (page {page} of {totalPages})
            </span>
          )}
        </div>
        {pageDetections.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-700">
                    <th className="pb-3 pr-4">Time</th>
                    <th className="pb-3 pr-4">Label</th>
                    <th className="pb-3 pr-4">Confidence</th>
                    <th className="pb-3 pr-4">Intervals</th>
                    <th className="pb-3 pr-4">Channel</th>
                    <th className="pb-3 pr-4">Location</th>
                    <th className="pb-3">Audio</th>
                  </tr>
                </thead>
                <tbody>
                  {pageDetections.map((det, i) => (
                    <tr
                      key={det.event_id ?? `${det.timestamp}-${i}`}
                      className="border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/30 transition-colors"
                      onClick={() => setSelectedDetection(det)}
                    >
                      <td className="py-3 pr-4 text-slate-300">{formatDateTime(det.timestamp)}</td>
                      <td className="py-3 pr-4 text-white">{det.species_common}</td>
                      <td className="py-3 pr-4">
                        <span className={getConfidenceColor(det.confidence)}>
                          {(det.confidence * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <IntervalsCell intervals={det.intervals} />
                      </td>
                      <td className="py-3 pr-4 text-slate-400">Ch {det.channel}</td>
                      <td className="py-3 pr-4">
                        <LocationBadge context={det.context} />
                      </td>
                      <td className="py-3" onClick={(e) => e.stopPropagation()}>
                        <ClipActions
                          clipPath={det.audio_clip_path}
                          type="audio"
                          channelId={String(det.channel)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={page}
              totalPages={totalPages}
              onPageChange={setPage}
              isLoading={isFetching && !isLoading}
            />
          </>
        ) : (
          <p className="text-slate-500 text-center py-8">No events</p>
        )}
      </Card>

      {selectedDetection && (
        <AudioEventDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}
    </div>
  )
}
