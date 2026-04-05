import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth, formatDateTime } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Bird, Clock, Activity, BarChart3, X, MapPin, GitBranch, Code } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  Card,
  StatCard,
  Pagination,
} from '../components/ui'
import { DateRangeFilter, usePaginatedDateRange, paginate } from '../components/DateRangeFilter'
import { ClipActions } from '../components/ClipActions'
import { HourlyActivityChart, DistributionPieChart, HourlyStackedBarChart, DailyActivityChart, CrowScatterChart } from '../components/Charts'
import { LocationBadge, SpatiotemporalContext } from '../components/LocationBadge'
import { CrowEntitySection } from '../components/CrowEntitySection'

/**
 * V2 Detection schema for crow detections.
 * Includes optional spatiotemporal context and lineage fields.
 */
interface CrowDetection {
  timestamp: string
  confidence: number | null
  call_type: string
  age?: string
  audio_clip_path: string | null
  channel: number | null
  /** V2: Spatiotemporal context (GPS location, sensor ID). */
  context?: SpatiotemporalContext
  /** V2: UUID of the upstream event that triggered this detection. */
  source_event_id?: string
}

interface CrowScatterPoint {
  timestamp: string
  call_type: string
  confidence: number | null
}

interface CrowStatsResponse {
  total_detections: number
  age_distribution: Record<string, number>
  hourly_activity: { hour: number; count: number }[]
  daily_activity: { date: string; count: number }[]
  call_types: Record<string, number>
  intents: Record<string, number>
  detections: CrowDetection[]
  scatter_sample: CrowScatterPoint[]
  start_date: string
  end_date: string
}

/**
 * Detail drawer for a single crow detection.
 * Shows context, lineage, and raw JSON toggle.
 */
function CrowDetectionDetail({ detection, onClose }: { detection: CrowDetection; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-800 border-l border-slate-700 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-white capitalize">{detection.call_type}</h2>
            <p className="text-sm text-slate-400">{formatDateTime(detection.timestamp)}</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Confidence</p>
              <p className={`text-2xl font-bold ${
                detection.confidence !== null
                  ? detection.confidence >= 0.8 ? 'text-green-400'
                    : detection.confidence >= 0.5 ? 'text-amber-400'
                    : 'text-red-400'
                  : 'text-slate-500'
              }`}>
                {detection.confidence !== null ? `${(detection.confidence * 100).toFixed(0)}%` : '-'}
              </p>
            </div>
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Channel</p>
              <p className="text-2xl font-bold text-white">{detection.channel ?? '-'}</p>
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

/**
 * Derive hourly call type breakdown from raw detections.
 * Returns array of { hour, call_type1_count, call_type2_count, ... }
 */
function deriveHourlyCallTypes(detections: CrowDetection[]): { hour: number; [key: string]: number }[] {
  const hourlyData: Record<number, Record<string, number>> = {}

  // Initialize all hours
  for (let h = 0; h < 24; h++) {
    hourlyData[h] = {}
  }

  // Aggregate call types by hour
  for (const detection of detections) {
    const hour = new Date(detection.timestamp).getHours()
    const callType = detection.call_type || 'unknown'
    hourlyData[hour][callType] = (hourlyData[hour][callType] || 0) + 1
  }

  return Object.entries(hourlyData).map(([h, types]) => ({
    hour: Number(h),
    ...types,
  }))
}

/**
 * Derive hourly age breakdown from raw detections.
 * Returns array of { hour, adult_count, juvenile_count, ... }
 */
function deriveHourlyAges(detections: CrowDetection[]): { hour: number; [key: string]: number }[] {
  const hourlyData: Record<number, Record<string, number>> = {}

  // Initialize all hours
  for (let h = 0; h < 24; h++) {
    hourlyData[h] = {}
  }

  // Aggregate ages by hour
  for (const detection of detections) {
    if (detection.age) {
      const hour = new Date(detection.timestamp).getHours()
      hourlyData[hour][detection.age] = (hourlyData[hour][detection.age] || 0) + 1
    }
  }

  return Object.entries(hourlyData).map(([h, ages]) => ({
    hour: Number(h),
    ...ages,
  }))
}

export default function CrowsPage() {
  const { startDate, endDate, handleDateChange, page, setPage } = usePaginatedDateRange(1)
  const [selectedDetection, setSelectedDetection] = useState<CrowDetection | null>(null)

  const { data, isLoading, error } = useQuery<CrowStatsResponse>({
    queryKey: ['crow-stats', startDate, endDate],
    queryFn: async () => {
      const res = await fetchWithAuth(`/api/data/crows/stats?start_date=${startDate}&end_date=${endDate}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
  })

  // Find peak hour
  const peakHour = data?.hourly_activity?.reduce(
    (max, curr) => (curr.count > max.count ? curr : max),
    { hour: 0, count: 0 }
  )

  // Derive hourly call types and ages
  const hourlyCallTypes = data?.detections ? deriveHourlyCallTypes(data.detections) : []
  const hourlyAges = data?.detections ? deriveHourlyAges(data.detections) : []

  const allDetections = data?.detections || []
  const { pageItems: pageDetections, totalPages } = paginate(allDetections, page)

  return (
    <div className="space-y-6">
      <PageHeader title="Crow Analysis" description="Crow detection and vocalization analysis" />

      {/* Date Range Filter */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onDateChange={handleDateChange}
      />

      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-center">
          <p className="text-red-400">Failed to load crow data</p>
        </div>
      ) : (
      <>

      {/* Correlated Crow Entities — "Clean Signal" section */}
      <CrowEntitySection startDate={startDate} endDate={endDate} />

      {/* Raw Sensor Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Raw Detections"
          value={data?.total_detections ?? 0}
          icon={Bird}
          color="blue"
        />
        <StatCard
          title="Call Types"
          value={Object.keys(data?.call_types ?? {}).length}
          icon={Activity}
          color="green"
        />
        <StatCard
          title="Peak Hour"
          value={peakHour && peakHour.count > 0 ? `${peakHour.hour}:00` : '-'}
          icon={Clock}
          color="purple"
        />
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400">
              <BarChart3 className="w-5 h-5" />
            </div>
            <span className="text-sm text-slate-400">Date Range</span>
          </div>
          <p className="text-lg font-medium text-white">
            {data?.start_date} &ndash; {data?.end_date}
          </p>
        </Card>
      </div>

      {/* Trends over time + call types */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Detections per Day</h2>
          <p className="text-xs text-slate-500 mb-3">All crow detections across selected date range</p>
          <DailyActivityChart data={data?.daily_activity ?? []} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Call Types Distribution</h2>
          <p className="text-xs text-slate-500 mb-3">Breakdown of detected call types in selected date range</p>
          <DistributionPieChart data={data?.call_types || {}} />
        </Card>
      </div>

      {/* Confidence scatter + hourly activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Detection Confidence Over Time</h2>
          <p className="text-xs text-slate-500 mb-3">Sample of up to 500 detections evenly distributed across range</p>
          <CrowScatterChart data={data?.scatter_sample || []} startDate={startDate} endDate={endDate} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Hourly Activity</h2>
          <p className="text-xs text-slate-500 mb-3">Total crow detections per hour of day, across selected date range</p>
          <HourlyActivityChart data={data?.hourly_activity || []} />
        </Card>
      </div>

      {/* Age Distribution and Intents */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Age Distribution</h2>
          <p className="text-xs text-slate-500 mb-3">Adult vs juvenile crow detections in selected date range</p>
          <DistributionPieChart data={data?.age_distribution || {}} />
        </Card>

        {data && Object.keys(data.intents).length > 0 && (
          <Card>
            <h2 className="text-lg font-medium text-white mb-4">Detected Intents</h2>
            <p className="text-xs text-slate-500 mb-3">Behavioral intent classification in selected date range</p>
            <DistributionPieChart data={data.intents} />
          </Card>
        )}
      </div>

      {/* Time-of-Day Breakdown Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Call Types by Time of Day</h2>
          <p className="text-xs text-slate-500 mb-3">Stacked: how call types are distributed across 24 hours (aggregated over selected date range)</p>
          <HourlyStackedBarChart data={hourlyCallTypes} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Age Groups by Time of Day</h2>
          <p className="text-xs text-slate-500 mb-3">Stacked: adult vs juvenile sightings per hour across selected date range</p>
          <HourlyStackedBarChart data={hourlyAges} />
        </Card>
      </div>

      {/* Recent Detections Table - paginated */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-white">Raw Detections in Date Range</h2>
          {allDetections.length > 0 && (
            <span className="text-sm text-slate-400">
              {allDetections.length} shown (most recent first), page {page} of {totalPages}
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
                    <th className="pb-3 pr-4">Call Type</th>
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
                      <td className="py-3 pr-4 text-white capitalize">{det.call_type}</td>
                      <td className="py-3 pr-4">
                        <span className={
                          det.confidence !== null
                            ? det.confidence >= 0.8 ? 'text-green-400'
                              : det.confidence >= 0.5 ? 'text-amber-400'
                              : 'text-red-400'
                            : 'text-slate-500'
                        }>
                          {det.confidence !== null ? `${(det.confidence * 100).toFixed(0)}%` : '-'}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-slate-400">
                        {det.channel !== null ? `Ch ${det.channel}` : '-'}
                      </td>
                      <td className="py-3 pr-4">
                        <LocationBadge context={det.context} />
                      </td>
                      <td className="py-3">
                        <ClipActions
                          clipPath={det.audio_clip_path}
                          type="audio"
                          channelId={det.channel !== null ? String(det.channel) : undefined}
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
          <p className="text-slate-500 text-center py-8">No crow detections in selected date range</p>
        )}
      </Card>

      {/* Detail Drawer */}
      {selectedDetection && (
        <CrowDetectionDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}

      </>
      )}
    </div>
  )
}
