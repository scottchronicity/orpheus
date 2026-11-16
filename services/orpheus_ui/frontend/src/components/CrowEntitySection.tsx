/**
 * CrowEntitySection — "Clean Signal" correlated entity view for the Crows page.
 *
 * Fetches correlated entities from `/api/entities?species=corvus,crow` and keeps
 * the ones whose evidence includes a crow-call classification (`crow.analyzed`,
 * the crow classifier); BirdNET- or PANNs-only corvid detections (ravens, jays)
 * are left out. Each is one correlated event, not an identified individual bird.
 * The charts mirror the raw-detection charts on the same page.
 *
 * Reuses the existing chart components from Charts.tsx for visual consistency.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '../lib/api'
import { POLLING_INTERVALS } from '../config'
import { Sparkles, Bird, Clock } from 'lucide-react'
import { Card, StatCard } from './ui'
import { HourlyActivityChart, DistributionPieChart, HourlyStackedBarChart } from './Charts'

interface EntityEvidence {
  event_id: string
  source_event_id?: string
  sensor_id: string
  clip_path?: string
  confidence: number
  detection_type?: string
}

interface MetadataAggregate {
  call_types: string[]
  ages: string[]
  avg_behaviors: Record<string, number>
  evidence_count: number
}

interface EntityEvent {
  entity_id: string
  timestamp: string
  species_code: string
  common_name: string
  confidence: number
  context?: { lat?: number; lon?: number; timestamp?: string }
  evidence: EntityEvidence[]
  metadata_aggregate?: MetadataAggregate
}

interface EntitiesResponse {
  entities: EntityEvent[]
  count: number
}

/**
 * Derive hourly activity data from a list of entities.
 */
function deriveHourlyActivity(entities: EntityEvent[]): { hour: number; count: number }[] {
  const counts: Record<number, number> = {}
  for (let h = 0; h < 24; h++) counts[h] = 0

  for (const e of entities) {
    const hour = new Date(e.timestamp).getHours()
    counts[hour] = (counts[hour] || 0) + 1
  }

  return Object.entries(counts).map(([h, c]) => ({ hour: Number(h), count: c }))
}

/**
 * Derive a per-sensor distribution from evidence across all entities.
 * Returns Record<sensor_id, count> for DistributionPieChart.
 */
function deriveSensorDistribution(entities: EntityEvent[]): Record<string, number> {
  const dist: Record<string, number> = {}
  for (const e of entities) {
    for (const ev of e.evidence) {
      const sid = ev.sensor_id || 'Unknown'
      dist[sid] = (dist[sid] || 0) + 1
    }
  }
  return dist
}

/**
 * Derive call type distribution from entity metadata.
 * Aggregates average behavior probabilities across all entities.
 */
function deriveCallTypeDistribution(entities: EntityEvent[]): Record<string, number> {
  const avgBehaviors: Record<string, number[]> = {
    alert: [],
    begging: [],
    soft_song: [],
    rattle: [],
    mob: [],
  }

  for (const entity of entities) {
    const meta = entity.metadata_aggregate
    if (meta?.avg_behaviors) {
      for (const [behavior, value] of Object.entries(meta.avg_behaviors)) {
        if (avgBehaviors[behavior]) {
          avgBehaviors[behavior].push(value)
        }
      }
    }
  }

  // Compute overall average for each behavior
  const result: Record<string, number> = {}
  for (const [behavior, values] of Object.entries(avgBehaviors)) {
    if (values.length > 0) {
      result[behavior] = values.reduce((sum, v) => sum + v, 0) / values.length
    }
  }
  return result
}

/**
 * Derive age distribution from entity metadata.
 * Returns count of adult vs juvenile across all evidence.
 */
function deriveAgeDistribution(entities: EntityEvent[]): Record<string, number> {
  const dist: Record<string, number> = {}
  for (const entity of entities) {
    const meta = entity.metadata_aggregate
    if (meta?.ages) {
      for (const age of meta.ages) {
        dist[age] = (dist[age] || 0) + 1
      }
    }
  }
  return dist
}

/**
 * Derive hourly call type breakdown from entities.
 * Returns array of { hour, call_type1_count, call_type2_count, ... }
 */
function deriveHourlyCallTypes(entities: EntityEvent[]): { hour: number; [key: string]: number }[] {
  const hourlyData: Record<number, Record<string, number>> = {}
  
  // Initialize all hours
  for (let h = 0; h < 24; h++) {
    hourlyData[h] = {}
  }
  
  // Aggregate call types by hour
  for (const entity of entities) {
    const hour = new Date(entity.timestamp).getHours()
    const meta = entity.metadata_aggregate
    if (meta?.call_types) {
      for (const callType of meta.call_types) {
        hourlyData[hour][callType] = (hourlyData[hour][callType] || 0) + 1
      }
    }
  }
  
  return Object.entries(hourlyData).map(([h, types]) => ({
    hour: Number(h),
    ...types,
  }))
}

/**
 * Derive hourly age breakdown from entities.
 * Returns array of { hour, adult_count, juvenile_count, ... }
 */
function deriveHourlyAges(entities: EntityEvent[]): { hour: number; [key: string]: number }[] {
  const hourlyData: Record<number, Record<string, number>> = {}
  
  // Initialize all hours
  for (let h = 0; h < 24; h++) {
    hourlyData[h] = {}
  }
  
  // Aggregate ages by hour
  for (const entity of entities) {
    const hour = new Date(entity.timestamp).getHours()
    const meta = entity.metadata_aggregate
    if (meta?.ages) {
      for (const age of meta.ages) {
        hourlyData[hour][age] = (hourlyData[hour][age] || 0) + 1
      }
    }
  }
  
  return Object.entries(hourlyData).map(([h, ages]) => ({
    hour: Number(h),
    ...ages,
  }))
}

/** An entity belongs here when the crow classifier analysed one of its calls. */
export function hasCrowCall(entity: { evidence?: { detection_type?: string }[] }): boolean {
  return entity.evidence?.some((ev) => ev.detection_type === 'crow.analyzed') ?? false
}

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function SectionHeader() {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <Sparkles className="w-5 h-5 text-emerald-400 self-center" />
      <h2 className="text-lg font-semibold text-white">Crow Call Events (correlated)</h2>
      <span className="text-xs text-slate-500">
        1 dot = 1 correlated event with a crow-call classification, not an individual bird
      </span>
    </div>
  )
}

export function CrowEntitySection({ startDate, endDate }: { startDate: string; endDate: string }) {
  const { data, isLoading, error } = useQuery<EntitiesResponse>({
    queryKey: ['crow-entities', startDate, endDate],
    queryFn: () => {
      const params = new URLSearchParams({
        species: 'corvus,crow',
        start_date: startDate,
        end_date: endDate,
        tz: browserTimeZone(),
      })
      return fetchJson<EntitiesResponse>(`/api/entities?${params.toString()}`)
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
  })

  if (error && !data) {
    return (
      <div className="space-y-4">
        <SectionHeader />
        <Card className="p-6 text-center">
          <p className="text-amber-300">Could not load crow call events</p>
          <p className="text-slate-500 text-sm mt-1">{String(error)}</p>
        </Card>
      </div>
    )
  }

  if (isLoading || !data?.entities) {
    return (
      <div className="space-y-4">
        <SectionHeader />
        <Card className="p-6 text-center">
          <p className="text-slate-400">Loading crow call events…</p>
        </Card>
      </div>
    )
  }

  const entities = data.entities.filter(hasCrowCall)

  // Show empty state if no entities
  if (entities.length === 0) {
    return (
      <div className="space-y-4">
        <SectionHeader />
        <Card className="p-6 text-center">
          <p className="text-slate-400">No crow call events in this date range</p>
          <p className="text-slate-500 text-sm mt-1">Entities appear once the event correlator processes detections</p>
        </Card>
      </div>
    )
  }

  const hourlyData = deriveHourlyActivity(entities)
  const sensorDist = deriveSensorDistribution(entities)
  const callTypeDist = deriveCallTypeDistribution(entities)
  const ageDist = deriveAgeDistribution(entities)
  const hourlyCallTypes = deriveHourlyCallTypes(entities)
  const hourlyAges = deriveHourlyAges(entities)

  // Find peak hour
  const peakHour = hourlyData.reduce(
    (max, curr) => (curr.count > max.count ? curr : max),
    { hour: 0, count: 0 }
  )

  return (
    <div className="space-y-4">
      {/* Section Header */}
      <SectionHeader />

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Crow Call Events"
          value={entities.length}
          icon={Bird}
          color="blue"
        />
        <StatCard
          title="Peak Hour"
          value={peakHour.count > 0 ? `${peakHour.hour}:00` : '-'}
          icon={Clock}
          color="purple"
        />
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-emerald-500/20 text-emerald-400">
              <Sparkles className="w-5 h-5" />
            </div>
            <span className="text-sm text-slate-400">Avg Evidence / Event</span>
          </div>
          <p className="text-lg font-medium text-white">
            {entities.length > 0
              ? (entities.reduce((sum, e) => sum + e.evidence.length, 0) / entities.length).toFixed(1)
              : '0'}
          </p>
        </Card>
      </div>

      {/* Charts Grid - 2x2 layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Crow Call Events Over Time</h2>
          <HourlyActivityChart data={hourlyData} />
        </Card>

        <Card>
          <h2 className="text-lg font-medium text-white mb-4">Sensor Distribution</h2>
          <DistributionPieChart data={sensorDist} />
        </Card>

        {Object.keys(callTypeDist).length > 0 && (
          <Card>
            <h2 className="text-lg font-medium text-white mb-4">Call Types Distribution</h2>
            <p className="text-xs text-slate-500 mb-3">Average behavior scores across all entities</p>
            <DistributionPieChart data={callTypeDist} />
          </Card>
        )}

        {Object.keys(ageDist).length > 0 && (
          <Card>
            <h2 className="text-lg font-medium text-white mb-4">Age Distribution</h2>
            <p className="text-xs text-slate-500 mb-3">Age classifications from evidence detections</p>
            <DistributionPieChart data={ageDist} />
          </Card>
        )}
      </div>

      {/* Time-of-Day Breakdown Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {hourlyCallTypes.some(d => Object.keys(d).length > 1) && (
          <Card>
            <h2 className="text-lg font-medium text-white mb-4">Call Types by Time of Day</h2>
            <p className="text-xs text-slate-500 mb-3">Call type distribution across 24 hours</p>
            <HourlyStackedBarChart data={hourlyCallTypes} />
          </Card>
        )}

        {hourlyAges.some(d => Object.keys(d).length > 1) && (
          <Card>
            <h2 className="text-lg font-medium text-white mb-4">Age Groups by Time of Day</h2>
            <p className="text-xs text-slate-500 mb-3">Age distribution across 24 hours</p>
            <HourlyStackedBarChart data={hourlyAges} />
          </Card>
        )}
      </div>

      {/* Visual separator between clean and raw sections */}
      <div className="border-t border-slate-700 pt-2">
        <p className="text-xs text-slate-500 italic">Raw Sensor Detections (below)</p>
      </div>
    </div>
  )
}
