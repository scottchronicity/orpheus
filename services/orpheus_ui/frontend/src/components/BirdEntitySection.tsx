/**
 * BirdEntitySection — "Clean Signal" correlated entity view for the Birds page.
 *
 * Fetches entities (excluding crows) from `/api/entities` and renders charts
 * that mirror the raw-detection charts on the same page, enabling easy
 * comparison between de-duplicated entities and raw sensor detections.
 *
 * Reuses the existing chart components from Charts.tsx for visual consistency.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Sparkles, Activity } from 'lucide-react'
import { Card, StatCard } from './ui'
import { DailyActivityChart, DistributionPieChart, SpeciesBarChart, EntityScatterChart } from './Charts'

interface EntityEvidence {
  event_id: string
  source_event_id?: string
  sensor_id: string
  clip_path?: string
  confidence: number
}

interface EntityEvent {
  entity_id: string
  timestamp: string
  species_code: string
  common_name: string
  confidence: number
  context?: { lat?: number; lon?: number; timestamp?: string }
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
  scatter_sample?: EntityScatterPoint[]
  count: number
  stats?: EntityStats
}

/**
 * Derive species distribution from a list of entities.
 * Returns Record<common_name, count> for DistributionPieChart.
 */
function deriveSpeciesDistribution(entities: EntityEvent[]): Record<string, number> {
  const dist: Record<string, number> = {}
  for (const e of entities) {
    const name = e.common_name || e.species_code
    dist[name] = (dist[name] || 0) + 1
  }
  return dist
}

export function BirdEntitySection({
  startDate,
  endDate,
}: {
  startDate: string
  endDate: string
}) {
  const { data, isLoading } = useQuery<EntitiesResponse>({
    queryKey: ['bird-entities', startDate, endDate],
    queryFn: async () => {
      const res = await fetchWithAuth(
        `/api/entities?exclude_species=corvus,crow&start_date=${startDate}&end_date=${endDate}`
      )
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
  })

  if (isLoading || !data?.entities) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-semibold text-white">Verified Entities (De-duplicated)</h2>
          <span className="text-xs text-slate-500 ml-2">1 dot = 1 real bird</span>
        </div>
        <Card className="p-6 text-center">
          <p className="text-slate-400">Loading entity data...</p>
        </Card>
      </div>
    )
  }

  const entities = data.entities

  // Show empty state if no entities
  if ((data.stats?.total_count ?? entities.length) === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-semibold text-white">Verified Entities (De-duplicated)</h2>
          <span className="text-xs text-slate-500 ml-2">1 dot = 1 real bird</span>
        </div>
        <Card className="p-6 text-center">
          <p className="text-slate-400">No bird entities in this date range</p>
          <p className="text-slate-500 text-sm mt-1">Entities appear once the event correlator processes detections</p>
        </Card>
      </div>
    )
  }

  // Use server-side aggregated stats for charts (full date range, no row cap)
  const speciesDist = data.stats?.species_distribution ?? deriveSpeciesDistribution(entities)
  const dailyData = data.stats?.daily_activity ?? []
  const totalCount = data.stats?.total_count ?? entities.length

  const sortedSpecies = Object.entries(speciesDist)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([species, count]) => ({ species, count }))

  return (
    <div className="space-y-4">
      {/* Section Header */}
      <div className="flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-emerald-400" />
        <h2 className="text-lg font-semibold text-white">Verified Entities (De-duplicated)</h2>
        <span className="text-xs text-slate-500 ml-2">1 dot = 1 real bird</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Total Entities"
          value={totalCount}
          icon={Sparkles}
          color="green"
        />
        <StatCard
          title="Unique Species"
          value={data.stats?.unique_species_count ?? Object.keys(speciesDist).length}
          icon={Activity}
          color="blue"
        />
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-purple-500/20 text-purple-400">
              <Sparkles className="w-5 h-5" />
            </div>
            <span className="text-sm text-slate-400">Avg Sensors / Entity</span>
          </div>
          <p className="text-lg font-medium text-white">
            {entities.length > 0
              ? (entities.reduce((sum, e) => sum + e.evidence.length, 0) / entities.length).toFixed(1)
              : '0'}
          </p>
        </Card>
      </div>

      {/* Trends + species breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Entities per Day</h2>
          <p className="text-xs text-slate-500 mb-3">All entities across selected date range</p>
          <DailyActivityChart data={dailyData} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Entity Species Breakdown</h2>
          <p className="text-xs text-slate-500 mb-3">All entities in selected date range</p>
          <DistributionPieChart data={speciesDist} />
        </Card>
      </div>

      {/* Scatter + top species */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Entities by Species Over Time</h2>
          <p className="text-xs text-slate-500 mb-3">Sample of up to 500 entities evenly distributed across range</p>
          <EntityScatterChart data={data.scatter_sample || []} startDate={startDate} endDate={endDate} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Top Entity Species</h2>
          <p className="text-xs text-slate-500 mb-3">All entities in selected date range</p>
          <SpeciesBarChart data={sortedSpecies} />
        </Card>
      </div>

      {/* Visual separator between clean and raw sections */}
      <div className="border-t border-slate-700 pt-2">
        <p className="text-xs text-slate-500 italic">Raw Sensor Detections (below)</p>
      </div>
    </div>
  )
}
