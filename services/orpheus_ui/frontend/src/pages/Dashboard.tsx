import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'
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
 * Convert bytes to gigabytes with one decimal place.
 */
function bytesToGB(bytes: number | undefined): string {
  if (bytes === undefined) return 'Size unknown'
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

export default function Dashboard() {
  const { data: health, isLoading: healthLoading } = useQuery<HealthData>({
    queryKey: ['health'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/health')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HEALTH,
  })

  const { data: services, isLoading: servicesLoading } = useQuery<ServicesData>({
    queryKey: ['services'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/services/status')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HEALTH,
  })

  const { data: audioDiag } = useQuery<AudioDiagnostics>({
    queryKey: ['audio-diagnostics'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/diagnostics/audio')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  const { data: videoDiag } = useQuery<VideoDiagnostics>({
    queryKey: ['video-diagnostics'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/diagnostics/video')
      return res.json()
    },
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
                {health.disk_data.free ? `${bytesToGB(health.disk_data.free)} free` : 'Size unknown'}
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
            {health?.disk_system?.free ? `${bytesToGB(health.disk_system.free)} free` : 'Size unknown'}
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
