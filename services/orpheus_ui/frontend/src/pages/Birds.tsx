import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { formatDateTime } from '../lib/utils'
import { fetchJson } from '../lib/api'
import { POLLING_INTERVALS } from '../config'
import { Bird, Activity, X, MapPin, GitBranch, Code, Sparkles, ExternalLink } from 'lucide-react'
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
import { ConfidenceScatterChart, DistributionPieChart, SpeciesBarChart, DailyActivityChart, HourlyActivityChart } from '../components/Charts'
import { ClipActions } from '../components/ClipActions'
import { LocationBadge, SpatiotemporalContext } from '../components/LocationBadge'
import { SpeciesFilter } from '../components/SpeciesFilter'

/**
 * V2 Detection schema for bird detections.
 * Includes optional spatiotemporal context and lineage fields.
 */
interface BirdDetection {
  /** Unique event id from the backend Detection model — stable across
   *  pagination so it's the right thing to use as a React key. */
  event_id?: string
  timestamp: string
  species_code: string
  species_common: string
  /** IOC scientific name when available (Layer 1 of cross-classifier-identity). */
  species_scientific?: string | null
  /** TaxonomyRef serialised by the backend. */
  taxonomy?: { namespace: string; id: string; common_name?: string | null } | null
  confidence: number
  channel: string
  audio_clip_path?: string
  /** V2: Spatiotemporal context (GPS location, sensor ID). */
  context?: SpatiotemporalContext
  /** V2: UUID of the upstream event that triggered this detection. */
  source_event_id?: string
}

interface BirdStats {
  total_count: number
  unique_species_count: number
  hourly_activity: { hour: number; count: number }[]
  daily_activity: { date: string; count: number }[]
  species_distribution: Record<string, number>
  /** Unfiltered distribution of every species present in the date range,
   *  used to populate the species-filter dropdown. */
  all_species?: Record<string, number>
}

interface BirdScatterPoint {
  timestamp: string
  species_code: string
  species_common: string
  confidence: number
}

interface BirdHistoryResponse {
  detections: BirdDetection[]
  scatter_sample: BirdScatterPoint[]
  count: number
  filtered_count: number
  start_date: string
  end_date: string
  stats: BirdStats
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
 * Compact row of external species references (iNaturalist, Wikipedia,
 * GBIF). Built from the IOC scientific name when available, falls back
 * to common-name search for legacy detections. See lib/speciesLinks.ts.
 */
function SpeciesExternalLinks({
  scientificName,
  commonName,
}: {
  scientificName?: string | null
  commonName?: string | null
}) {
  const links = buildSpeciesLinks({ scientificName, commonName })
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


function BirdDetectionDetail({ detection, onClose }: { detection: BirdDetection; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-800 border-l border-slate-700 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-white">{detection.species_common}</h2>
            {detection.species_scientific && (
              <p className="text-xs text-slate-500 italic">
                {detection.species_scientific}
              </p>
            )}
            <p className="text-sm text-slate-400">{formatDateTime(detection.timestamp)}</p>
            <SpeciesExternalLinks
              scientificName={detection.species_scientific}
              commonName={detection.species_common}
            />
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Confidence</p>
              <p className={`text-2xl font-bold ${getConfidenceColor(detection.confidence)}`}>
                {(detection.confidence * 100).toFixed(0)}%
              </p>
            </div>
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Channel</p>
              <p className="text-2xl font-bold text-white">{detection.channel}</p>
            </div>
          </div>

          {detection.context && (detection.context.lat != null || detection.context.sensor_id) && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <MapPin className="w-5 h-5 text-blue-400" />
                <h3 className="text-sm font-medium text-white">Context</h3>
              </div>
              {detection.context.lat != null && detection.context.lon != null && (
                <p className="text-sm text-slate-300">
                  {detection.context.lat.toFixed(6)}, {detection.context.lon.toFixed(6)}
                </p>
              )}
              {detection.context.sensor_id && (
                <p className="text-sm text-slate-400 mt-1">Sensor: {detection.context.sensor_id}</p>
              )}
            </Card>
          )}

          {detection.source_event_id && (
            <Card>
              <div className="flex items-center gap-2 mb-3">
                <GitBranch className="w-5 h-5 text-cyan-400" />
                <h3 className="text-sm font-medium text-white">Lineage</h3>
              </div>
              <p className="text-sm text-slate-300 font-mono break-all" data-testid="source-event-id">
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

export default function BirdsPage() {
  const { startDate, endDate, startTime, endTime, handleChange, page, setPage } = usePaginatedDateRange(1)
  const [selectedDetection, setSelectedDetection] = useState<BirdDetection | null>(null)
  // Species selection lives in ``?species=...`` so the URL captures the
  // full filter state — bookmark-able, shareable, reload-safe. No
  // date-change reset: the URL is the source of truth.
  const [selectedSpecies, setSelectedSpecies] = useUrlMultiSelect('species')

  // Query key includes page and species selection so react-query caches per-slice
  // and prevents stale overwrites when the user changes filters rapidly.
  const speciesCsv = useMemo(() => {
    const arr = Array.from(selectedSpecies)
    return arr.length === 0 ? '' : arr.join(',')
  }, [selectedSpecies])

  const timeFilterActive = startTime !== DEFAULT_START_TIME || endTime !== DEFAULT_END_TIME
  const browserTz = useMemo(() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
  }, [])

  const { data, isLoading, isFetching, error, isPlaceholderData } = useQuery<BirdHistoryResponse>({
    queryKey: ['bird-history', startDate, endDate, startTime, endTime, page, speciesCsv],
    queryFn: async () => {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        page: String(page),
        page_size: String(ITEMS_PER_PAGE),
      })
      if (speciesCsv) params.set('species', speciesCsv)
      if (timeFilterActive) {
        params.set('start_time', startTime)
        params.set('end_time', endTime)
        params.set('tz', browserTz)
      }
      return fetchJson<BirdHistoryResponse>(`/api/data/birds/history?${params.toString()}`)
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
        title="Bird Detections"
        description="BirdNET species identification history"
        message="Failed to load bird detection data"
      />
    )
  }

  const speciesDist = data?.stats?.species_distribution ?? {}
  const allSpecies = data?.stats?.all_species ?? {}
  const sortedSpecies = Object.entries(speciesDist)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)

  const availableSpeciesItems = Object.entries(allSpecies)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([value, count]) => ({ value, count }))

  // Detections list comes pre-paginated from the backend.
  const pageDetections = data?.detections ?? []
  const totalCount = data?.stats?.total_count ?? data?.count ?? 0
  const totalPages = data?.total_pages ?? 1

  return (
    <div className="space-y-6">
      <PageHeader title="Bird Detections" description="BirdNET species identification history" />

      {/* Raw-vs-entities note: this page is about raw BirdNET detections. */}
      <Card className="p-4 flex items-start gap-3">
        <Sparkles className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-slate-300">
          This page shows <span className="text-white">raw BirdNET detections</span>.
          For de-duplicated, multi-sensor-correlated sightings see{' '}
          <Link to="/entities" className="text-blue-400 hover:text-blue-300 underline">
            Entities
          </Link>
          .
        </div>
      </Card>

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
          title="Total Detections"
          value={totalCount}
          icon={Bird}
          color="blue"
        />
        <StatCard
          title="Unique Species"
          value={data?.stats?.unique_species_count ?? 0}
          icon={Activity}
          color="green"
        />
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-purple-500/20 text-purple-400">
              <Bird className="w-5 h-5" />
            </div>
            <span className="text-sm text-slate-400">Filtered (Non-birds)</span>
          </div>
          <p className="text-lg font-medium text-white">
            {data?.filtered_count ?? 0}
          </p>
        </Card>
      </div>

      {/* Trends over time + species distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Detections per Day</h2>
          <p className="text-xs text-slate-500 mb-3">All detections across selected date range</p>
          <DailyActivityChart data={data?.stats?.daily_activity ?? []} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Species Distribution</h2>
          <p className="text-xs text-slate-500 mb-3">All detections in selected date range</p>
          <DistributionPieChart data={speciesDist} />
        </Card>
      </div>

      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Hourly Activity</h2>
        <p className="text-xs text-slate-500 mb-3">All detections grouped by hour of day</p>
        <HourlyActivityChart data={data?.stats?.hourly_activity ?? []} />
      </Card>

      {/* Confidence scatter + top species */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Detection Confidence Over Time</h2>
          <p className="text-xs text-slate-500 mb-3">Sample of up to 500 detections evenly distributed across range</p>
          <ConfidenceScatterChart data={data?.scatter_sample || []} startDate={startDate} endDate={endDate} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Top Species</h2>
          <p className="text-xs text-slate-500 mb-3">All detections in selected date range</p>
          {sortedSpecies.length > 0 ? (
            <SpeciesBarChart
              data={sortedSpecies.map(([species, count]) => ({ species, count }))}
            />
          ) : (
            <p className="text-slate-500 text-center py-8">No bird detections in selected date range</p>
          )}
        </Card>
      </div>

      {/* Detections - server-paginated */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Detections in Date Range</h2>
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
                    <th className="pb-3 pr-4">Species</th>
                    <th className="pb-3 pr-4">Confidence</th>
                    <th className="pb-3 pr-4">Channel</th>
                    <th className="pb-3 pr-4">Location</th>
                    <th className="pb-3">Audio</th>
                  </tr>
                </thead>
                <tbody>
                  {pageDetections.map((det, i) => (
                    <tr key={det.event_id ?? `${det.timestamp}-${i}`} className="border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/30 transition-colors" onClick={() => setSelectedDetection(det)}>
                      <td className="py-3 pr-4 text-slate-300">
                        {formatDateTime(det.timestamp)}
                      </td>
                      <td className="py-3 pr-4 text-white">
                        {det.species_common}
                        <SpeciesExternalLinks
                          scientificName={det.species_scientific}
                          commonName={det.species_common}
                        />
                      </td>
                      <td className="py-3 pr-4">
                        <span className={getConfidenceColor(det.confidence)}>
                          {(det.confidence * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-slate-400">Ch {det.channel}</td>
                      <td className="py-3 pr-4">
                        <LocationBadge context={det.context} />
                      </td>
                      <td className="py-3">
                        <ClipActions
                          clipPath={det.audio_clip_path}
                          type="audio"
                          channelId={det.channel}
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
          <p className="text-slate-500 text-center py-8">No detections</p>
        )}
      </Card>

      {selectedDetection && (
        <BirdDetectionDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}
    </div>
  )
}
