import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth, formatDateTime } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Bird, Activity, X, MapPin, GitBranch, Code } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  Card,
  StatCard,
  Pagination,
} from '../components/ui'
import { DateRangeFilter, usePaginatedDateRange, paginate } from '../components/DateRangeFilter'
import { ConfidenceScatterChart, DistributionPieChart, SpeciesBarChart, DailyActivityChart } from '../components/Charts'
import { ClipActions } from '../components/ClipActions'
import { LocationBadge, SpatiotemporalContext } from '../components/LocationBadge'
import { BirdEntitySection } from '../components/BirdEntitySection'

/**
 * V2 Detection schema for bird detections.
 * Includes optional spatiotemporal context and lineage fields.
 */
interface BirdDetection {
  timestamp: string
  species_code: string
  species_common: string
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
}

/**
 * Get confidence level color based on value.
 */
function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.8) return 'text-green-400'
  if (confidence >= 0.5) return 'text-amber-400'
  return 'text-red-400'
}

/**
 * Detail drawer for a single bird detection.
 * Shows context (GPS coordinates), lineage (source event), and raw JSON toggle.
 */
function BirdDetectionDetail({ detection, onClose }: { detection: BirdDetection; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-800 border-l border-slate-700 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-white">{detection.species_common}</h2>
            <p className="text-sm text-slate-400">{formatDateTime(detection.timestamp)}</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Summary */}
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

          {/* Context */}
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

          {/* Lineage */}
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
  const { startDate, endDate, handleDateChange, page, setPage } = usePaginatedDateRange(1)
  const [selectedDetection, setSelectedDetection] = useState<BirdDetection | null>(null)

  const { data, isLoading, error } = useQuery<BirdHistoryResponse>({
    queryKey: ['bird-history', startDate, endDate],
    queryFn: async () => {
      const res = await fetchWithAuth(`/api/data/birds/history?start_date=${startDate}&end_date=${endDate}`)
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
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

  // Use server-side aggregated stats for charts (full date range, no row cap)
  const speciesDist = data?.stats?.species_distribution ?? {}
  const sortedSpecies = Object.entries(speciesDist)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)

  // Paginate detections table (2000 most recent returned by backend)
  const allDetections = data?.detections || []
  const { pageItems: pageDetections, totalPages } = paginate(allDetections, page)

  return (
    <div className="space-y-6">
      <PageHeader title="Bird Detections" description="BirdNET species identification history" />

      {/* Date Range Filter */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onDateChange={handleDateChange}
      />

      {/* Correlated Bird Entities — "Clean Signal" section */}
      <BirdEntitySection startDate={startDate} endDate={endDate} />

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Total Detections"
          value={data?.stats?.total_count ?? data?.count ?? 0}
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

      {/* Recent Detections - paginated */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Detections in Date Range</h2>
          {allDetections.length > 0 && (
            <span className="text-sm text-slate-400">
              {allDetections.length} total, showing {pageDetections.length} (page {page} of {totalPages})
            </span>
          )}
        </div>
        {allDetections.length > 0 ? (
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
                    <tr key={i} className="border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/30 transition-colors" onClick={() => setSelectedDetection(det)}>
                      <td className="py-3 pr-4 text-slate-300">
                        {formatDateTime(det.timestamp)}
                      </td>
                      <td className="py-3 pr-4 text-white">{det.species_common}</td>
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
            <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
          </>
        ) : (
          <p className="text-slate-500 text-center py-8">No recent detections</p>
        )}
      </Card>

      {/* Detail Drawer */}
      {selectedDetection && (
        <BirdDetectionDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}
    </div>
  )
}
