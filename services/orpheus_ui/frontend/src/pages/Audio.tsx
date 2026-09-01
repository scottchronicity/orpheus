import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { formatDateTime } from '../lib/utils'
import { fetchJson } from '../lib/api'
import { AUDIO_CHANNEL_IDS, POLLING_INTERVALS } from '../config'
import { Mic, Activity, Volume2, X, MapPin, GitBranch, Code } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  Card,
  StatCard,
  StatusIcon,
  getStatusColor,
  Pagination,
} from '../components/ui'
import { paginate } from '../components/DateRangeFilter'
import { AudioPlaybackControl } from '../components/AudioPlaybackControl'
import { ClipActions } from '../components/ClipActions'
import { LocationBadge, SpatiotemporalContext } from '../components/LocationBadge'

interface AudioDiagnostics {
  running: boolean
  message?: string
  channels?: { id: string; active: boolean }[]
  xrun?: { total: number }
  hardware?: Record<string, unknown>
}

/**
 * V2 Detection schema for audio motion detections.
 *
 * The audio motion agent publishes a nested payload (channel_id, duration_seconds,
 * peak_energy_db inside a `metadata` dict). The UI backend flattens these to
 * top-level fields before serving them to the frontend.
 */
interface AudioDetection {
  /** Channel identifier, flattened from metadata by the backend. */
  channel_id?: string
  timestamp: string
  /** Duration in seconds, promoted from metadata.duration_seconds. */
  duration_seconds?: number
  /** Peak energy in dB, promoted from metadata.peak_energy_db. */
  peak_energy_db?: number
  audio_clip_path?: string
  /** Original numeric channel from the Detection event. */
  channel?: number
  /** Raw metadata dict from the Detection event (preserved for diagnostics). */
  metadata?: Record<string, unknown>
  /** V2: Spatiotemporal context (GPS location, sensor ID). */
  context?: SpatiotemporalContext
  /** V2: UUID of the upstream event that triggered this detection. */
  source_event_id?: string
}

interface AudioDetectionsResponse {
  summary: Record<string, AudioDetection | null>
  history: AudioDetection[]
  mqtt_connected: boolean
}

/**
 * Detail drawer for a single audio detection.
 * Shows context, lineage, and raw JSON toggle.
 */
function AudioDetectionDetail({ detection, onClose }: { detection: AudioDetection; onClose: () => void }) {
  const [showJson, setShowJson] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-800 border-l border-slate-700 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-white">Channel {detection.channel_id ?? '-'}</h2>
            <p className="text-sm text-slate-400">{formatDateTime(detection.timestamp)}</p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Duration</p>
              <p className="text-2xl font-bold text-white">
                {detection.duration_seconds?.toFixed(1) ?? '-'}s
              </p>
            </div>
            <div className="bg-slate-700/50 rounded-lg p-4">
              <p className="text-sm text-slate-400">Peak Energy</p>
              <p className="text-2xl font-bold text-white">
                {detection.peak_energy_db?.toFixed(1) ?? '-'} dB
              </p>
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

export default function AudioPage() {
  const [selectedDetection, setSelectedDetection] = useState<AudioDetection | null>(null)
  const [page, setPage] = useState(1)
  const { data: diagnostics, isLoading: diagLoading } = useQuery<AudioDiagnostics>({
    queryKey: ['audio-diagnostics'],
    queryFn: () => fetchJson<AudioDiagnostics>('/api/diagnostics/audio'),
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  const { data: detections, isLoading: detectionsLoading } = useQuery<AudioDetectionsResponse>({
    queryKey: ['audio-detections'],
    queryFn: () => fetchJson<AudioDetectionsResponse>('/api/diagnostics/audio/detections'),
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  if (diagLoading || detectionsLoading) {
    return <LoadingSpinner />
  }

  const systemStatus = diagnostics?.running ? 'running' : 'stopped'
  const mqttStatus = detections?.mqtt_connected ? 'connected' : 'disconnected'
  const activeChannels = diagnostics?.channels?.filter((c) => c.active).length ?? 0

  return (
    <div className="space-y-6">
      <PageHeader title="Audio Detection" description="Audio motion detection and monitoring" />

      {/* Status */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className={`p-2 rounded-lg ${diagnostics?.running ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
              <StatusIcon status={systemStatus} />
            </div>
            <span className="text-sm text-slate-400">System Status</span>
          </div>
          <p className={`text-xl font-bold ${getStatusColor(systemStatus)}`}>
            {diagnostics?.running ? 'Running' : 'Stopped'}
          </p>
        </Card>
        <StatCard
          title="Active Channels"
          value={activeChannels}
          icon={Mic}
          color="blue"
        />
        <Card>
          <div className="flex items-center gap-3 mb-2">
            <div className={`p-2 rounded-lg ${detections?.mqtt_connected ? 'bg-green-500/20 text-green-400' : 'bg-amber-500/20 text-amber-400'}`}>
              <Activity className="w-5 h-5" />
            </div>
            <span className="text-sm text-slate-400">MQTT Status</span>
          </div>
          <p className={`text-xl font-bold ${getStatusColor(mqttStatus)}`}>
            {detections?.mqtt_connected ? 'Connected' : 'Disconnected'}
          </p>
        </Card>
      </div>

      {/* Channel Summary */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Channel Status</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {AUDIO_CHANNEL_IDS.map((channelId) => {
            const detection = detections?.summary[channelId]
            return (
              <div
                key={channelId}
                className={`p-4 rounded-lg border ${
                  detection
                    ? 'bg-green-500/10 border-green-500/30'
                    : 'bg-slate-700/50 border-slate-600'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Volume2 className={`w-4 h-4 ${detection ? 'text-green-400' : 'text-slate-500'}`} />
                  <span className="font-medium text-white">Channel {channelId}</span>
                </div>
                {detection ? (
                  <div className="text-sm text-slate-400">
                    <p>Last: {formatDateTime(detection.timestamp)}</p>
                    {detection.duration_seconds && (
                      <p>Duration: {detection.duration_seconds.toFixed(1)}s</p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">No recent activity</p>
                )}
              </div>
            )
          })}
        </div>
      </Card>

      {/* Recent Detections — live MQTT cache, up to 200 events */}
      <Card>
        {(() => {
          const allHistory = detections?.history ?? []
          const { pageItems, totalPages } = paginate(allHistory, page)
          return (
            <>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-medium text-white">Recent Detections (Live)</h2>
                {allHistory.length > 0 && (
                  <span className="text-sm text-slate-400">{allHistory.length} cached events</span>
                )}
              </div>
              {allHistory.length > 0 ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-slate-400 border-b border-slate-700">
                          <th className="pb-3 pr-4">Time (local)</th>
                          <th className="pb-3 pr-4">Channel</th>
                          <th className="pb-3 pr-4">Duration</th>
                          <th className="pb-3 pr-4">Peak Energy</th>
                          <th className="pb-3 pr-4">Location</th>
                          <th className="pb-3">Audio</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pageItems.map((det, i) => (
                          <tr key={i} className="border-b border-slate-700/50 cursor-pointer hover:bg-slate-700/30 transition-colors" onClick={() => setSelectedDetection(det)}>
                            <td className="py-3 pr-4 text-slate-300">
                              {formatDateTime(det.timestamp)}
                            </td>
                            <td className="py-3 pr-4 text-white">Ch {det.channel_id ?? '-'}</td>
                            <td className="py-3 pr-4 text-slate-400">
                              {det.duration_seconds?.toFixed(1) ?? '-'}s
                            </td>
                            <td className="py-3 pr-4 text-slate-400">
                              {det.peak_energy_db?.toFixed(1) ?? '-'} dB
                            </td>
                            <td className="py-3 pr-4">
                              <LocationBadge context={det.context} />
                            </td>
                            <td className="py-3">
                              <ClipActions
                                clipPath={det.audio_clip_path}
                                type="audio"
                                channelId={det.channel_id}
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
                <p className="text-slate-500 text-center py-8">No recent audio detections</p>
              )}
            </>
          )
        })()}
      </Card>

      {/* Audio Playback Control */}
      <AudioPlaybackControl />

      {/* Detail Drawer */}
      {selectedDetection && (
        <AudioDetectionDetail detection={selectedDetection} onClose={() => setSelectedDetection(null)} />
      )}
    </div>
  )
}
