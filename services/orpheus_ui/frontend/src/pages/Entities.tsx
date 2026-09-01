import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { formatDateTime } from '../lib/utils'
import { fetchJson } from '../lib/api'
import { POLLING_INTERVALS } from '../config'
import { Brain, Activity, MapPin, X, ChevronRight, Code, Volume2, GitBranch, ExternalLink } from 'lucide-react'
import { buildSpeciesLinks } from '../lib/speciesLinks'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  Card,
  StatCard,
  Pagination,
} from '../components/ui'
import { DateRangeFilter, usePaginatedDateRange, useUrlMultiSelect, ITEMS_PER_PAGE, DEFAULT_START_TIME, DEFAULT_END_TIME } from '../components/DateRangeFilter'
import { ClipActions } from '../components/ClipActions'
import { HourlyActivityChart, DistributionPieChart, DailyActivityChart, EntityScatterChart } from '../components/Charts'
import { SpeciesFilter } from '../components/SpeciesFilter'

/**
 * Layer 2 (event-based clustering): each piece of evidence carries its
 * own species claim and which classifier produced it. See
 * docs/designs/cross-classifier-identity.md §4.
 */
interface EntityTaxonomyRef {
  namespace: string
  id: string
  common_name?: string | null
}

interface EntityTemporalInterval {
  start_seconds: number
  end_seconds: number
  confidence?: number | null
}

interface EntityEvidence {
  event_id: string
  source_event_id?: string
  sensor_id: string
  clip_path?: string
  // Backend-computed: does the backing audio clip still exist on disk?
  // The DB row outlives the clip (retention rolls clips off), so old
  // evidence references files that are gone. Drives the preemptive
  // "Clip expired" state in ClipActions.
  clip_available?: boolean
  confidence: number
  intervals?: EntityTemporalInterval[] | null
  // Layer 2 per-evidence fields:
  species_code?: string | null
  species_common?: string | null
  taxonomy?: EntityTaxonomyRef | null
  detection_type?: string
}

interface EntityContext {
  lat?: number
  lon?: number
  timestamp?: string
}

interface EntityAlsoDetected {
  species_code: string
  species_common: string
  confidence: number
  detection_type: string
}

interface EntityEventSignature {
  audio_motion_source_ids?: string[]
  sensor_ids?: string[]
  start_time?: string
  end_time?: string
  // Co-occurring OTHER sources in the same window — context, not evidence
  // for this entity's label (source-identity, see design doc).
  also_detected?: EntityAlsoDetected[]
}

interface EntityEvent {
  entity_id: string
  timestamp: string
  // Legacy display label — populated from the highest-confidence evidence's
  // species. NOT authoritative; the truth is in evidence[].
  species_code: string
  common_name: string
  confidence: number
  context: EntityContext
  evidence: EntityEvidence[]
  // Layer 2 traceability metadata.
  event_signature?: EntityEventSignature | null
  // Corollary discharge — true when this entity overlapped our own audio
  // playback (the system hearing itself, not wildlife).
  is_self_generated?: boolean
  // Coarse state-space type, e.g. "Animal.Bird.Crow" ([ARCH] entity taxonomy).
  // Null/absent for legacy or unresolved entities.
  entity_type?: string | null
}

interface EntityStats {
  total_count: number
  unique_species_count: number
  hourly_activity: { hour: number; count: number }[]
  daily_activity: { date: string; count: number }[]
  species_distribution: Record<string, number>
  /** Unfiltered distribution of every species present in the date range,
   *  used to populate the species-filter dropdown. */
  all_species?: Record<string, number>
}

interface EntityScatterPoint {
  timestamp: string
  species_code: string
  common_name: string
  confidence: number
}

interface EntitiesResponse {
  entities: EntityEvent[]
  scatter_sample: EntityScatterPoint[]
  count: number  // full filtered count, not page size
  stats: EntityStats
  page?: number
  page_size?: number
  total_pages?: number
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.8) return 'text-green-400'
  if (confidence >= 0.5) return 'text-amber-400'
  return 'text-red-400'
}


/**
 * Chain panel — fetches every Detection in the lineage rooted at the
 * given audio.motion event(s). The "metadata appended to metadata" view.
 *
 * One Entity may have multiple audio.motion roots in multi-mic scenarios.
 * v1 fetches the chain for the FIRST root only — multi-root entities
 * just show that root's chain. Multi-root chain merging is a follow-up.
 */
interface ChainDetection {
  event_id: string
  timestamp: string
  detection_type: string
  channel?: number | null
  species_code?: string | null
  species_common?: string | null
  confidence?: number | null
  source_event_id?: string | null
  root_event_id?: string | null
  audio_clip_path?: string | null
  intervals?: EntityTemporalInterval[] | null
  taxonomy?: EntityTaxonomyRef | null
  metadata?: Record<string, unknown> | null
}

// Metadata keys worth surfacing inline on each chain row. Hand-curated
// to avoid drowning the reader in noise; these are the ones that carry
// downstream-enrichment value (model version, call-type analysis output,
// etc).
const NOTABLE_METADATA_KEYS = [
  'model_version',
  'model',
  'inference_time_ms',
  'call_type',
  'age',
  'quality_score',
  'duration_seconds',
  'peak_energy_db',
] as const

function notableMetadata(
  metadata: Record<string, unknown> | null | undefined,
): Array<[string, string]> {
  if (!metadata) return []
  const result: Array<[string, string]> = []
  for (const key of NOTABLE_METADATA_KEYS) {
    if (key in metadata) {
      const value = metadata[key]
      if (value === null || value === undefined) continue
      result.push([key, String(value)])
    }
  }
  return result
}

interface ChainResponse {
  root_event_id: string
  count: number
  chain: ChainDetection[]
}

function EntityChainPanel({ rootEventIds }: { rootEventIds: string[] }) {
  const [expanded, setExpanded] = useState(false)
  const primaryRoot = rootEventIds[0]
  const { data, isLoading, error } = useQuery<ChainResponse>({
    queryKey: ['entity-chain', primaryRoot],
    queryFn: () => fetchJson<ChainResponse>(`/api/chain/${encodeURIComponent(primaryRoot)}`),
    enabled: expanded,  // lazy — only fetch when user expands
  })

  return (
    <Card>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-medium text-white">
            Detection chain
          </h3>
        </div>
        <span className="text-xs text-slate-400">
          {expanded ? 'Hide' : 'Show'} ({rootEventIds.length} root
          {rootEventIds.length === 1 ? '' : 's'})
        </span>
      </button>

      {expanded && (
        <div className="mt-3">
          <p className="text-[11px] text-slate-500 mb-2">
            Every Detection in this physical event's lineage — audio.motion →
            classifier outputs → downstream enrichment. Source of truth for
            "metadata appended to metadata."
          </p>
          {isLoading && (
            <p className="text-xs text-slate-500">Loading chain…</p>
          )}
          {error && (
            <p className="text-xs text-red-400">Failed to load chain.</p>
          )}
          {data?.chain && (
            <ol className="space-y-2 text-xs">
              {data.chain.map((det, i) => (
                <li
                  key={det.event_id}
                  className="border-l-2 border-emerald-400/40 pl-3 py-1"
                >
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-700 text-slate-200">
                      {det.detection_type}
                    </span>
                    {det.species_common && (
                      <span className="text-white">{det.species_common}</span>
                    )}
                    {det.confidence != null && (
                      <span className={getConfidenceColor(det.confidence)}>
                        {(det.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    <span className="text-slate-500 ml-auto text-[10px] font-mono">
                      {det.timestamp.slice(11, 23)}
                    </span>
                  </div>
                  {det.taxonomy && (
                    <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                      {det.taxonomy.namespace}:{det.taxonomy.id}
                    </p>
                  )}
                  {/* Notable metadata — model_version, call_type, age, etc. */}
                  {(() => {
                    const md = notableMetadata(det.metadata)
                    if (md.length === 0) return null
                    return (
                      <div className="text-[10px] text-slate-500 mt-0.5 flex flex-wrap gap-x-2">
                        {md.map(([k, v]) => (
                          <span key={k}>
                            <span className="text-slate-600">{k}=</span>
                            <span className="text-slate-400">{v}</span>
                          </span>
                        ))}
                      </div>
                    )
                  })()}
                  {det.channel != null && (
                    <p className="text-[10px] text-slate-600 mt-0.5">
                      channel {det.channel}
                    </p>
                  )}
                  {det.source_event_id && i > 0 && (
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      ← {det.source_event_id}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  )
}


/**
 * Compact row of external species references (iNaturalist, Wikipedia,
 * GBIF) built from the IOC scientific name when known, common name as
 * fallback. ``onClick stopPropagation`` so clicking a link inside a
 * clickable row doesn't trigger the row's own onClick.
 */
function SpeciesExternalLinks({
  scientificName,
  commonName,
  audiosetMid,
}: {
  scientificName?: string | null
  commonName?: string | null
  audiosetMid?: string | null
}) {
  const links = buildSpeciesLinks({
    scientificName,
    commonName,
    audiosetMid,
  })
  if (links.length === 0) return null
  return (
    <div className="mt-1 flex items-center gap-2 flex-wrap">
      {links.map((link) => (
        <a
          key={link.label}
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          <ExternalLink className="w-3 h-3" />
          {link.label}
        </a>
      ))}
    </div>
  )
}


function EntityDetail({ entity, onClose }: { entity: EntityEvent; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Drawer */}
      <div className="relative w-full max-w-lg bg-slate-800 border-l border-slate-700 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-white">
              {entity.common_name}
              {entity.is_self_generated && (
                <span
                  className="ml-2 align-middle rounded bg-amber-900/60 px-1.5 py-0.5 text-xs text-amber-300"
                  title="Overlapped our own audio playback (corollary discharge)"
                >
                  self-generated
                </span>
              )}
            </h2>
            {/* Coarse state-space type ([ARCH] entity taxonomy). */}
            {entity.entity_type && (
              <div className="mt-0.5 text-xs text-slate-400" title="State-space entity type">
                {entity.entity_type}
              </div>
            )}
            {/* Scientific name from the highest-confidence evidence
                that has a TaxonomyRef in the IOC namespace, when
                available — falls back to nothing for legacy entities. */}
            {(() => {
              const iocEvidence = entity.evidence.find(
                (ev) => ev.taxonomy?.namespace === 'ioc',
              )
              const scientific = iocEvidence?.taxonomy?.id ?? null
              return (
                <>
                  {scientific && (
                    <p className="text-xs text-slate-500 italic">{scientific}</p>
                  )}
                  <p className="text-sm text-slate-400">{formatDateTime(entity.timestamp)}</p>
                  <SpeciesExternalLinks
                    scientificName={scientific}
                    commonName={entity.common_name}
                  />
                </>
              )
            })()}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Summary Stats */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Confidence</p>
              <p className={`text-2xl font-bold ${getConfidenceColor(entity.confidence)}`}>
                {(entity.confidence * 100).toFixed(0)}%
              </p>
            </div>
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Sensors</p>
              <p className="text-2xl font-bold text-white">{entity.evidence.length}</p>
            </div>
          </div>

          {/* Location */}
          {entity.context?.lat != null && entity.context?.lon != null && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <MapPin className="w-5 h-5 text-blue-400" />
                <h3 className="text-sm font-medium text-white">Location</h3>
              </div>
              <p className="text-sm text-slate-300">
                {entity.context.lat.toFixed(6)}, {entity.context.lon.toFixed(6)}
              </p>
            </Card>
          )}

          {/* Event Signature — Layer 2 traceability */}
          {entity.event_signature && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <Volume2 className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-medium text-white">Event Lineage</h3>
              </div>
              {entity.event_signature.audio_motion_source_ids &&
                entity.event_signature.audio_motion_source_ids.length > 0 && (
                  <div className="text-xs text-slate-400 mb-2">
                    <span className="text-slate-500">Audio.motion roots: </span>
                    <span className="font-mono break-all">
                      {entity.event_signature.audio_motion_source_ids.join(', ')}
                    </span>
                  </div>
                )}
              {entity.event_signature.sensor_ids &&
                entity.event_signature.sensor_ids.length > 0 && (
                  <div className="text-xs text-slate-400">
                    <span className="text-slate-500">Sensors: </span>
                    {entity.event_signature.sensor_ids.join(', ')}
                  </div>
                )}
              {entity.event_signature.start_time && entity.event_signature.end_time && (
                <div className="text-xs text-slate-400 mt-1">
                  <span className="text-slate-500">Time span: </span>
                  {entity.event_signature.start_time} → {entity.event_signature.end_time}
                </div>
              )}
            </Card>
          )}

          {/* Chain view — every Detection that traces back to the same
              audio.motion root via root_event_id. The "metadata appended
              to metadata" view. Only visible when event_signature has at
              least one audio.motion source_id. */}
          {entity.event_signature?.audio_motion_source_ids &&
            entity.event_signature.audio_motion_source_ids.length > 0 && (
              <EntityChainPanel
                rootEventIds={entity.event_signature.audio_motion_source_ids}
              />
            )}

          {/* Evidence List — Layer 2: shows each classifier's opinion */}
          <div>
            <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
              <Volume2 className="w-4 h-4 text-purple-400" />
              Evidence ({entity.evidence.length} classifier observations)
            </h3>
            <div className="space-y-2">
              {entity.evidence.map((ev, i) => (
                <div
                  key={ev.event_id || i}
                  className="bg-slate-700/50 rounded-lg p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      {/* Per-classifier species claim */}
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <p className="text-sm font-medium text-white">
                          {ev.species_common || ev.species_code || '—'}
                        </p>
                        {ev.detection_type && (
                          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-slate-600/60 text-slate-200">
                            {ev.detection_type}
                          </span>
                        )}
                      </div>
                      {/* Canonical taxonomy ref (when known) */}
                      {ev.taxonomy && (
                        <p className="text-xs text-slate-400 mt-0.5 font-mono">
                          {ev.taxonomy.namespace}:{ev.taxonomy.id}
                        </p>
                      )}
                      {/* Per-evidence species links — different classifier
                          opinions might want different lookups, so each
                          gets its own. */}
                      <SpeciesExternalLinks
                        scientificName={
                          ev.taxonomy?.namespace === 'ioc' ? ev.taxonomy.id : null
                        }
                        commonName={ev.species_common}
                        audiosetMid={
                          ev.taxonomy?.namespace === 'audioset' ? ev.taxonomy.id : null
                        }
                      />
                      <p className="text-xs text-slate-400 mt-1">
                        Sensor: <span className="text-slate-300">{ev.sensor_id || 'unknown'}</span>
                        <span className="mx-1">·</span>
                        Confidence: <span className={getConfidenceColor(ev.confidence)}>
                          {(ev.confidence * 100).toFixed(0)}%
                        </span>
                      </p>
                      {/* Intra-clip intervals when present (Layer 2 carries them per-evidence) */}
                      {ev.intervals && ev.intervals.length > 0 && (
                        <p className="text-xs text-slate-500 mt-1">
                          {ev.intervals.length} interval{ev.intervals.length === 1 ? '' : 's'}:{' '}
                          {ev.intervals
                            .slice(0, 3)
                            .map(
                              (iv) =>
                                `${iv.start_seconds.toFixed(1)}–${iv.end_seconds.toFixed(1)}s`,
                            )
                            .join(', ')}
                          {ev.intervals.length > 3 && ` +${ev.intervals.length - 3} more`}
                        </p>
                      )}
                    </div>
                    {ev.clip_path && (
                      <ClipActions
                        clipPath={ev.clip_path}
                        type="audio"
                        channelId={ev.sensor_id}
                        clipAvailable={ev.clip_available}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Also detected at this time — co-occurring OTHER sources in the
              same window. Context, NOT evidence for this entity's label. */}
          {entity.event_signature?.also_detected &&
            entity.event_signature.also_detected.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-white mb-2">
                  Also detected at this time
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  Other sources heard in the same window — not evidence for this entity.
                </p>
                <div className="flex flex-wrap gap-2">
                  {entity.event_signature.also_detected.map((a, i) => (
                    <span
                      key={`${a.species_code}-${i}`}
                      className="text-xs bg-slate-700/40 rounded px-2 py-1 text-slate-300"
                    >
                      {a.species_common || a.species_code || '—'}
                      <span className={`ml-1 ${getConfidenceColor(a.confidence)}`}>
                        {(a.confidence * 100).toFixed(0)}%
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}

          {/* Raw JSON Toggle */}
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
                {JSON.stringify(entity, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function EntitiesPage() {
  const { startDate, endDate, startTime, endTime, handleChange, page, setPage } = usePaginatedDateRange(1)
  const [selectedEntity, setSelectedEntity] = useState<EntityEvent | null>(null)
  // Species selection lives in ``?species=...`` so the URL captures the
  // full filter state — bookmark-able, shareable, reload-safe. No
  // date-change reset: the URL is the source of truth.
  const [selectedSpecies, setSelectedSpecies] = useUrlMultiSelect('species')

  const speciesCsv = useMemo(() => {
    const arr = Array.from(selectedSpecies)
    return arr.length === 0 ? '' : arr.join(',')
  }, [selectedSpecies])

  const timeFilterActive = startTime !== DEFAULT_START_TIME || endTime !== DEFAULT_END_TIME
  const browserTz = useMemo(() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
  }, [])

  const { data, isLoading, isFetching, error, isPlaceholderData } = useQuery<EntitiesResponse>({
    queryKey: ['entities', startDate, endDate, startTime, endTime, speciesCsv, page],
    queryFn: async () => {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        // Server-side pagination, same shape Birds/Crows use — client-side
        // slicing over a capped fetch silently truncates big filter results.
        page: String(page),
        page_size: String(ITEMS_PER_PAGE),
      })
      if (speciesCsv) params.set('species', speciesCsv)
      if (timeFilterActive) {
        params.set('start_time', startTime)
        params.set('end_time', endTime)
        params.set('tz', browserTz)
      }
      return fetchJson<EntitiesResponse>(`/api/entities?${params.toString()}`)
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
    // Keep the previous page visible while the new one fetches —
    // eliminates the "blank flash" when filters or page change.
    placeholderData: (previousData) => previousData,
  })

  if (isLoading) {
    return <LoadingSpinner />
  }

  if (error) {
    return (
      <ErrorMessage
        title="Entities"
        description="Correlated animal and audio events from multiple sensors"
        message="Failed to load entity data"
      />
    )
  }

  // Use server-side aggregated stats for charts (covers full date range, no row cap)
  const hourlyData = data?.stats?.hourly_activity ?? []
  const speciesDist = data?.stats?.species_distribution ?? {}
  const allSpecies = data?.stats?.all_species ?? {}
  const availableSpeciesItems = Object.entries(allSpecies)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([value, count]) => ({ value, count }))

  // Server-side pagination — the API returns just the current page's
  // entities + total_pages for the count footer. ``count`` is the full
  // filtered count, not page size.
  const pageEntities = data?.entities ?? []
  const totalCount = data?.count ?? 0
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="space-y-6">
      <PageHeader title="Entities" description="Correlated animal and audio events from multiple sensors" />

      {/* Date + Time Range Filter */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        startTime={startTime}
        endTime={endTime}
        onChange={handleChange}
        isPlaceholderData={isPlaceholderData}
      />

      {/* Species Filter */}
      <SpeciesFilter
        availableItems={availableSpeciesItems}
        selected={selectedSpecies}
        // No setPage(1): useUrlMultiSelect.setValue resets page atomically
        // inside the same setSearchParams call (avoids react-router-dom v6
        // stale-closure race that would silently lose the selection).
        onChange={setSelectedSpecies}
        label="Species"
      />

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Total Entities"
          value={data?.stats?.total_count ?? data?.count ?? 0}
          icon={Brain}
          color="purple"
        />
        <StatCard
          title="Unique Species"
          value={data?.stats?.unique_species_count ?? 0}
          icon={Activity}
          color="green"
        />
        <StatCard
          title="Avg Sensors"
          value={
            data && data.entities.length > 0
              ? (data.entities.reduce((sum, e) => sum + e.evidence.length, 0) / data.entities.length).toFixed(1)
              : '0'
          }
          icon={MapPin}
          color="blue"
        />
      </div>

      {/* Charts */}
      {data && (data.stats?.total_count ?? 0) > 0 && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <h2 className="text-lg font-medium text-white mb-4">Entities per Day</h2>
              <p className="text-xs text-slate-500 mb-3">All entities across selected date range</p>
              <DailyActivityChart data={data.stats?.daily_activity ?? []} />
            </Card>

            <Card>
              <h2 className="text-lg font-medium text-white mb-4">Species Distribution</h2>
              <p className="text-xs text-slate-500 mb-3">All entities in selected date range</p>
              <DistributionPieChart data={speciesDist} />
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <h2 className="text-lg font-medium text-white mb-4">Entity Confidence Over Time</h2>
              <p className="text-xs text-slate-500 mb-3">Sample of up to 500 entities evenly distributed across range</p>
              <EntityScatterChart data={data.scatter_sample || []} startDate={startDate} endDate={endDate} />
            </Card>

            <Card>
              <h2 className="text-lg font-medium text-white mb-4">Hourly Activity</h2>
              <p className="text-xs text-slate-500 mb-3">All entities grouped by hour of day</p>
              <HourlyActivityChart data={hourlyData} />
            </Card>
          </div>
        </>
      )}

      {/* Entities Table */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Entities in Date Range</h2>
          {totalCount > 0 && (
            <span className="text-sm text-slate-400">
              {totalCount.toLocaleString()} total, showing {pageEntities.length} (page {page} of {totalPages})
              {isPlaceholderData && (
                <span className="ml-2 text-slate-500 italic">updating…</span>
              )}
            </span>
          )}
        </div>
        {pageEntities.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-700">
                    <th className="pb-3 pr-4">Time</th>
                    <th className="pb-3 pr-4">Species</th>
                    <th className="pb-3 pr-4">Confidence</th>
                    <th className="pb-3 pr-4"># Sensors</th>
                    <th className="pb-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {pageEntities.map((entity) => (
                    <tr
                      key={entity.entity_id}
                      className="border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/30 transition-colors"
                      onClick={() => setSelectedEntity(entity)}
                    >
                      <td className="py-3 pr-4 text-slate-300">
                        {formatDateTime(entity.timestamp)}
                      </td>
                      <td className="py-3 pr-4 text-white">
                        {entity.common_name}
                        {entity.is_self_generated && (
                          <span
                            className="ml-2 rounded bg-amber-900/60 px-1.5 py-0.5 text-xs text-amber-300"
                            title="Overlapped our own audio playback (corollary discharge)"
                          >
                            echo
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={getConfidenceColor(entity.confidence)}>
                          {(entity.confidence * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-slate-400">{entity.evidence.length}</td>
                      <td className="py-3">
                        <ChevronRight className="w-4 h-4 text-slate-500" />
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
          <p className="text-slate-500 text-center py-8">No entity events yet. Waiting for correlated detections...</p>
        )}
      </Card>

      {/* Detail Drawer */}
      {selectedEntity && (
        <EntityDetail entity={selectedEntity} onClose={() => setSelectedEntity(null)} />
      )}
    </div>
  )
}
