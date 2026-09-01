import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '../lib/api'
import { formatDateTime } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import {
  Cpu,
  HardDrive,
  MemoryStick,
  Clock,
  Camera,
  Mic,
  Video,
  Bird as BirdIcon,
  Activity,
  Server,
  Database,
  CloudSun,
} from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  Card,
  CardHeader,
  StatCard,
  StatusIcon,
  getStatusColor,
} from '../components/ui'

interface DiskInfo {
  path: string
  percent: number
  total?: number
  used?: number
  free?: number
  ok: boolean
  error?: string
}

interface HealthData {
  status: string
  cpu_percent: number
  memory_percent: number
  disk_percent: number
  uptime_seconds: number
  disk_system?: DiskInfo
  disk_data?: DiskInfo
}

interface ServiceStatus {
  name: string
  status: string
  reason: string
}

interface ServicesData {
  services: ServiceStatus[]
}

interface AudioDiagnostics {
  running: boolean
  message?: string
  channels?: { id: string; active: boolean }[]
}

interface VideoDiagnostics {
  running: boolean
  camera_count?: number
  message?: string
}

interface WeatherData {
  available: boolean
  temperature_c?: number | null
  humidity_pct?: number | null
  pressure_hpa?: number | null
  wind_speed_mps?: number | null
  wind_direction_deg?: number | null
  rainfall_mm?: number | null
  timestamp?: string
}

/**
 * Format an optional numeric reading with a unit, or '--' when the sensor
 * didn't report it (WeatherReading fields are all optional).
 */
function formatReading(value: number | null | undefined, unit: string, digits = 1): string {
  if (value === null || value === undefined) return '--'
  return `${value.toFixed(digits)}${unit}`
}

/**
 * A reading older than this is flagged stale instead of being presented as
 * current conditions. 15 minutes = 3x the weather ingestor's default 300s
 * poll interval — the same "3x the heartbeat" convention presence uses. If
 * the station or the orpheus-weather ingestor dies, the backend keeps serving
 * its last row indefinitely, so the tell has to be client-side.
 */
const WEATHER_STALE_MS = 15 * 60 * 1000

/**
 * Compact current-conditions card fed by the weather-station ingestor.
 *
 * Polls GET /api/weather/latest at the HEALTH tier and renders nothing at all
 * when the backend reports `available: false` — most deploys have no weather
 * station configured, so the card only appears once readings exist. On those
 * deploys the poll also backs off to 60s so the absent feature isn't hammered
 * at the HEALTH tier forever. A reading older than WEATHER_STALE_MS renders a
 * muted stale note rather than posing as live conditions.
 */
export function WeatherCard() {
  const { data } = useQuery<WeatherData>({
    queryKey: ['weather-latest'],
    queryFn: () => fetchJson<WeatherData>('/api/weather/latest'),
    refetchInterval: (query) =>
      query.state.data && !query.state.data.available ? 60_000 : POLLING_INTERVALS.HEALTH,
  })

  if (!data?.available) {
    return null
  }

  // An unparseable timestamp gives NaN → not flagged (matches formatDateTime's
  // fall-back-to-raw-string behavior rather than crying wolf).
  const readingAgeMs = data.timestamp ? Date.now() - new Date(data.timestamp).getTime() : NaN
  const isStale = Number.isFinite(readingAgeMs) && readingAgeMs > WEATHER_STALE_MS

  return (
    <Card>
      <CardHeader title="Weather" icon={CloudSun} iconColor="blue" />
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-slate-500">Temperature</p>
          <p className="text-lg text-slate-200">{formatReading(data.temperature_c, ' °C')}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Humidity</p>
          <p className="text-lg text-slate-200">{formatReading(data.humidity_pct, ' %', 0)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Wind</p>
          <p className="text-lg text-slate-200">{formatReading(data.wind_speed_mps, ' m/s')}</p>
        </div>
      </div>
      {data.timestamp &&
        (isStale ? (
          <p className="text-xs text-amber-400 mt-3">
            Stale — last reading {formatDateTime(data.timestamp)}
          </p>
        ) : (
          <p className="text-xs text-slate-500 mt-3">
            Reading from {formatDateTime(data.timestamp)}
          </p>
        ))}
    </Card>
  )
}

/**
 * Service status list component.
 */
function ServiceStatusCard({ services }: { services: ServiceStatus[] }) {
  return (
    <Card>
      <CardHeader title="Service Status" icon={Server} iconColor="purple" />
      <div className="space-y-3">
        {services.map((service) => (
          <div key={service.name} className="flex items-center justify-between">
            <span className="text-sm text-slate-300">{service.name}</span>
            <div className="flex items-center gap-2">
              <StatusIcon status={service.status} />
              <span className={`text-sm ${getStatusColor(service.status)}`}>
                {service.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

/**
 * Diagnostics status card for audio/video/bird detection.
 */
function DiagnosticsCard({
  title,
  icon: Icon,
  running,
  message,
}: {
  title: string
  icon: React.ElementType
  running: boolean
  message?: string
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-3 mb-2">
        <div
          className={`p-2 rounded-lg ${
            running
              ? 'bg-green-500/20 text-green-400 border-green-500/30'
              : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
          }`}
        >
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-medium text-slate-300">{title}</h3>
          <p className={`text-xs ${running ? 'text-green-400' : 'text-slate-500'}`}>
            {running ? 'Active' : 'Inactive'}
          </p>
        </div>
      </div>
      {message && <p className="text-sm text-slate-400">{message}</p>}
    </Card>
  )
}

/**
 * Format uptime seconds to human readable string.
 */
function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)

  if (days > 0) {
    return `${days}d ${hours}h ${mins}m`
  }
  if (hours > 0) {
    return `${hours}h ${mins}m`
  }
  return `${mins}m`
}

/**
 * Get color based on usage percentage.
 */
function getUsageColor(percent: number): 'blue' | 'green' | 'amber' | 'red' {
  if (percent > 80) return 'red'
  if (percent > 60) return 'amber'
  return 'blue'
}

/**
 * Convert bytes to gibibytes with one decimal place — the same unit and label
 * as formatBytes and orpheus-storage-sweep, so free space reads the same
 * wherever it appears.
 */
function bytesToGiB(bytes: number | undefined): string {
  if (bytes === undefined) return 'Size unknown'
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`
}

export default function Dashboard() {
  const { data: health, isLoading: healthLoading } = useQuery<HealthData>({
    queryKey: ['health'],
    queryFn: () => fetchJson<HealthData>('/api/health'),
    refetchInterval: POLLING_INTERVALS.HEALTH,
  })

  const { data: services, isLoading: servicesLoading } = useQuery<ServicesData>({
    queryKey: ['services'],
    queryFn: () => fetchJson<ServicesData>('/api/services/status'),
    refetchInterval: POLLING_INTERVALS.HEALTH,
  })

  const { data: audioDiag } = useQuery<AudioDiagnostics>({
    queryKey: ['audio-diagnostics'],
    queryFn: () => fetchJson<AudioDiagnostics>('/api/diagnostics/audio'),
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  const { data: videoDiag } = useQuery<VideoDiagnostics>({
    queryKey: ['video-diagnostics'],
    queryFn: () => fetchJson<VideoDiagnostics>('/api/diagnostics/video'),
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  if (healthLoading || servicesLoading) {
    return <LoadingSpinner />
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="Wildlife monitoring system overview" />

      {/* System Health Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="CPU Usage"
          value={health?.cpu_percent ?? 0}
          unit="%"
          icon={Cpu}
          color={getUsageColor(health?.cpu_percent ?? 0)}
        />
        <StatCard
          title="Memory Usage"
          value={health?.memory_percent ?? 0}
          unit="%"
          icon={MemoryStick}
          color={getUsageColor(health?.memory_percent ?? 0)}
        />
        <StatCard
          title="System Disk"
          value={health?.disk_system?.percent ?? health?.disk_percent ?? 0}
          unit="%"
          icon={HardDrive}
          color={getUsageColor(health?.disk_system?.percent ?? health?.disk_percent ?? 0)}
        />
        <StatCard
          title="Uptime"
          value={health ? formatUptime(health.uptime_seconds) : '-'}
          icon={Clock}
          color="blue"
        />
      </div>

      {/* Current conditions — hidden entirely unless a weather station reports */}
      <WeatherCard />

      {/* Data Storage Card */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <div className={`p-2 rounded-lg border ${
              health?.disk_data?.ok 
                ? 'bg-green-500/20 text-green-400 border-green-500/30'
                : 'bg-amber-500/20 text-amber-400 border-amber-500/30'
            }`}>
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-slate-400">Data Drive</h3>
              <p className="text-xs text-slate-500">{health?.disk_data?.path || '/data/orpheus'}</p>
            </div>
          </div>
          {health?.disk_data?.ok ? (
            <>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-3xl font-bold text-white">{health.disk_data.percent}</span>
                <span className="text-slate-400">%</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    health.disk_data.percent > 80 ? 'bg-red-500' :
                    health.disk_data.percent > 60 ? 'bg-amber-500' : 'bg-blue-500'
                  }`}
                  style={{ width: `${health.disk_data.percent}%` }}
                />
              </div>
              <p className="text-xs text-slate-500 mt-2">
                {health.disk_data.free ? `${bytesToGiB(health.disk_data.free)} free` : 'Size unknown'}
              </p>
            </>
          ) : (
            <div className="text-amber-400 text-sm">
              {health?.disk_data?.error || 'Data drive not available'}
            </div>
          )}
        </Card>
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 rounded-lg border bg-blue-500/20 text-blue-400 border-blue-500/30">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-slate-400">System Drive</h3>
              <p className="text-xs text-slate-500">{health?.disk_system?.path || '/'}</p>
            </div>
          </div>
          <div className="flex items-baseline gap-1 mb-2">
            <span className="text-3xl font-bold text-white">{health?.disk_system?.percent ?? health?.disk_percent ?? 0}</span>
            <span className="text-slate-400">%</span>
          </div>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                (health?.disk_system?.percent ?? 0) > 80 ? 'bg-red-500' :
                (health?.disk_system?.percent ?? 0) > 60 ? 'bg-amber-500' : 'bg-blue-500'
              }`}
              style={{ width: `${health?.disk_system?.percent ?? health?.disk_percent ?? 0}%` }}
            />
          </div>
          <p className="text-xs text-slate-500 mt-2">
            {health?.disk_system?.free ? `${bytesToGiB(health.disk_system.free)} free` : 'Size unknown'}
          </p>
        </Card>
      </div>

      {/* Services and Diagnostics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Service Status */}
        {services && <ServiceStatusCard services={services.services} />}

        {/* Diagnostics Grid */}
        <div className="grid grid-cols-2 gap-4">
          <DiagnosticsCard
            title="Audio Motion"
            icon={Mic}
            running={audioDiag?.running ?? false}
            message={audioDiag?.running ? `${audioDiag.channels?.length ?? 0} channels` : undefined}
          />
          <DiagnosticsCard
            title="Video Motion"
            icon={Video}
            running={videoDiag?.running ?? false}
            message={videoDiag?.running ? `${videoDiag.camera_count ?? 0} cameras` : undefined}
          />
          <DiagnosticsCard title="Bird Detection" icon={BirdIcon} running={true} message="BirdNET active" />
          <DiagnosticsCard title="Camera Feeds" icon={Camera} running={true} message="4 cameras" />
        </div>
      </div>

      {/* Activity Section */}
      <Card>
        <CardHeader title="Recent Activity" icon={Activity} iconColor="blue" />
        <div className="text-center py-8 text-slate-500">
          <p>Real-time detection events will appear here.</p>
          <p className="text-sm mt-1">Connect to MQTT for live updates.</p>
        </div>
      </Card>
    </div>
  )
}
