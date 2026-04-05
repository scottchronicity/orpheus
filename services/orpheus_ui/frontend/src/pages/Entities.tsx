import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth, formatDateTime } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Brain, Activity, MapPin, X, ChevronRight, Code, Volume2 } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  Card,
  StatCard,
  Pagination,
} from '../components/ui'
import { DateRangeFilter, usePaginatedDateRange, paginate } from '../components/DateRangeFilter'
import { ClipActions } from '../components/ClipActions'
import { HourlyActivityChart, DistributionPieChart, DailyActivityChart, EntityScatterChart } from '../components/Charts'

interface EntityEvidence {
  event_id: string
  source_event_id?: string
  sensor_id: string
  clip_path?: string
  confidence: number
}

interface EntityContext {
  lat?: number
  lon?: number
  timestamp?: string
}

interface EntityEvent {
  entity_id: string
  timestamp: string
  species_code: string
  common_name: string
  confidence: number
  context: EntityContext
  evidence: EntityEvidence[]
}

interface EntityStats {
  total_count: number
  unique_species_count: number
  hourly_activity: { hour: number; count: number }[]
  daily_activity: { date: string; count: number }[]
  species_distribution: Record<string, number>
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
  count: number
  stats: EntityStats
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.8) return 'text-green-400'
  if (confidence >= 0.5) return 'text-amber-400'
  return 'text-red-400'
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
            <h2 className="text-lg font-medium text-white">{entity.common_name}</h2>
            <p className="text-sm text-slate-400">{formatDateTime(entity.timestamp)}</p>
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

          {/* Evidence List */}
          <div>
            <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
              <Volume2 className="w-4 h-4 text-purple-400" />
              Evidence ({entity.evidence.length} sources)
            </h3>
            <div className="space-y-2">
              {entity.evidence.map((ev, i) => (
                <div
                  key={ev.event_id || i}
                  className="bg-slate-700/50 rounded-lg p-3 flex items-center justify-between"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">
                      Sensor: {ev.sensor_id || 'Unknown'}
                    </p>
                    <p className="text-xs text-slate-400">
                      Confidence: {(ev.confidence * 100).toFixed(0)}%
                    </p>
                  </div>
                  {ev.clip_path && (
                    <ClipActions
                      clipPath={ev.clip_path}
                      type="audio"
                      channelId={ev.sensor_id}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>

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
  const { startDate, endDate, handleDateChange, page, setPage } = usePaginatedDateRange(1)
  const [selectedEntity, setSelectedEntity] = useState<EntityEvent | null>(null)

  const { data, isLoading, error } = useQuery<EntitiesResponse>({
    queryKey: ['entities', startDate, endDate],
    queryFn: async () => {
      const res = await fetchWithAuth(`/api/entities?start_date=${startDate}&end_date=${endDate}`)
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
        title="Entities"
        description="Correlated animal detection events"
        message="Failed to load entity data"
      />
    )
  }

  // Use server-side aggregated stats for charts (covers full date range, no row cap)
  const hourlyData = data?.stats?.hourly_activity ?? []
  const speciesDist = data?.stats?.species_distribution ?? {}

  // Paginate the table
  const allEntities = data?.entities || []
  const { pageItems: pageEntities, totalPages } = paginate(allEntities, page)

  return (
    <div className="space-y-6">
      <PageHeader title="Entities" description="Correlated animal detection events from multiple sensors" />

      {/* Date Range Filter */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onDateChange={handleDateChange}
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
          {allEntities.length > 0 && (
            <span className="text-sm text-slate-400">
              {allEntities.length} total, showing {pageEntities.length} (page {page} of {totalPages})
            </span>
          )}
        </div>
        {allEntities.length > 0 ? (
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
                      <td className="py-3 pr-4 text-white">{entity.common_name}</td>
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
            <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
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
