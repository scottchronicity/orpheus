import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth, formatDateTime } from '../lib/utils'
import { CAMERA_IDS, POLLING_INTERVALS } from '../config'
import { Video, Activity, Camera, FolderOpen } from 'lucide-react'
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
import { ClipActions } from '../components/ClipActions'

interface VideoDiagnostics {
  running: boolean
  camera_count?: number
  cameras?: { camera_id: string; last_detection?: string; running: boolean }[]
  mqtt_connected?: boolean
  message?: string
}

interface VideoDetection {
  camera_id: string
  timestamp: string
  duration_seconds?: number
  peak_motion_value?: number
  video_clip_path?: string
}

interface VideoDetectionsResponse {
  summary: Record<string, VideoDetection | null>
  history: VideoDetection[]
  mqtt_connected: boolean
}

interface VideoClip {
  filename: string
  path: string
  size_bytes: number
  modified_time: number
}

interface VideoClipsResponse {
  clips: VideoClip[]
  error: string | null
}

function getDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().split('T')[0]
}

export default function VideoPage() {
  const [selectedClipCamera, setSelectedClipCamera] = useState<string>(CAMERA_IDS[0])
  const [clipStartDate, setClipStartDate] = useState(() => getDaysAgo(7))
  const [clipEndDate, setClipEndDate] = useState(() => new Date().toISOString().split('T')[0])
  const [clipPage, setClipPage] = useState(1)

  const { data: diagnostics, isLoading: diagLoading } = useQuery<VideoDiagnostics>({
    queryKey: ['video-diagnostics'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/diagnostics/video')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  const { data: detections, isLoading: detectionsLoading } = useQuery<VideoDetectionsResponse>({
    queryKey: ['video-detections'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/diagnostics/video/detections')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  const { data: clips } = useQuery<VideoClipsResponse>({
    queryKey: ['video-clips', selectedClipCamera],
    queryFn: async () => {
      const res = await fetchWithAuth(`/api/diagnostics/video/clips/${selectedClipCamera}`)
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.HISTORY,
  })

  if (diagLoading || detectionsLoading) {
    return <LoadingSpinner />
  }

  const systemStatus = diagnostics?.running ? 'running' : 'stopped'
  const mqttStatus = detections?.mqtt_connected ? 'connected' : 'disconnected'

  // camera_count: use from diagnostics if available, else count cameras array
  const cameraCount = diagnostics?.camera_count ?? (diagnostics?.cameras?.length ?? 0)

  return (
    <div className="space-y-6">
      <PageHeader title="Video Detection" description="Video motion detection and clips" />

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
          title="Active Cameras"
          value={cameraCount}
          icon={Camera}
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

      {/* Camera Summary */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Camera Status</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {CAMERA_IDS.map((cameraId) => {
            const detection = detections?.summary[cameraId]
            const cameraNum = cameraId.split('-').pop()
            return (
              <div
                key={cameraId}
                className={`p-4 rounded-lg border ${
                  detection
                    ? 'bg-green-500/10 border-green-500/30'
                    : 'bg-slate-700/50 border-slate-600'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Video className={`w-4 h-4 ${detection ? 'text-green-400' : 'text-slate-500'}`} />
                  <span className="font-medium text-white">Camera {cameraNum}</span>
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

      {/* Recent Detections */}
      <Card>
        <h2 className="text-lg font-medium text-white mb-4">Recent Detections (Live)</h2>
        <p className="text-xs text-slate-500 mb-3">Real-time motion events from MQTT. Clips are saved asynchronously — use the clip browser below to find recorded footage.</p>
        {detections && detections.history.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-700">
                  <th className="pb-3 pr-4">Time</th>
                  <th className="pb-3 pr-4">Camera</th>
                  <th className="pb-3 pr-4">Duration</th>
                  <th className="pb-3 pr-4">Motion Value</th>
                  <th className="pb-3">Video</th>
                </tr>
              </thead>
              <tbody>
                {detections.history.map((det, i) => (
                  <tr key={i} className="border-b border-slate-700/50">
                    <td className="py-3 pr-4 text-slate-300">
                      {formatDateTime(det.timestamp)}
                    </td>
                    <td className="py-3 pr-4 text-white">{det.camera_id}</td>
                    <td className="py-3 pr-4 text-slate-400">
                      {det.duration_seconds?.toFixed(1) ?? '-'}s
                    </td>
                    <td className="py-3 pr-4 text-slate-400">
                      {det.peak_motion_value?.toFixed(1) ?? '-'}
                    </td>
                    <td className="py-3">
                      <ClipActions
                        clipPath={det.video_clip_path}
                        type="video"
                        channelId={det.camera_id}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-slate-500 text-center py-8">No recent video detections</p>
        )}
      </Card>

      {/* Clip Browser */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-medium text-white">Recorded Clips Browser</h2>
          </div>
          <select
            value={selectedClipCamera}
            onChange={(e) => { setSelectedClipCamera(e.target.value); setClipPage(1) }}
            className="px-3 py-1.5 bg-slate-700 border border-slate-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {CAMERA_IDS.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
        {/* Date filter - default last 7 days */}
        <div className="flex flex-wrap gap-3 mb-4 items-center">
          <span className="text-sm text-slate-400">Date range:</span>
          <input
            type="date"
            value={clipStartDate}
            onChange={(e) => { setClipStartDate(e.target.value); setClipPage(1) }}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-slate-500 text-sm">to</span>
          <input
            type="date"
            value={clipEndDate}
            onChange={(e) => { setClipEndDate(e.target.value); setClipPage(1) }}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        {(() => {
          const filteredClips = (clips?.clips ?? [])
            .filter((clip) => {
              const d = new Date(clip.modified_time * 1000).toISOString().split('T')[0]
              return d >= clipStartDate && d <= clipEndDate
            })
            .sort((a, b) => b.modified_time - a.modified_time)

          if (filteredClips.length === 0) {
            return <p className="text-slate-500 text-center py-8">No clips found for {selectedClipCamera} in selected date range</p>
          }

          const { pageItems, totalPages } = paginate(filteredClips, clipPage)

          return (
            <>
              {filteredClips.length > 0 && (
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-slate-400">{filteredClips.length} clips found</span>
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-400 border-b border-slate-700">
                      <th className="pb-3 pr-4">Time (local)</th>
                      <th className="pb-3 pr-4">Filename</th>
                      <th className="pb-3 pr-4">Size</th>
                      <th className="pb-3">Play</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((clip, i) => (
                      <tr key={i} className="border-b border-slate-700/50">
                        <td className="py-3 pr-4 text-slate-300 text-xs whitespace-nowrap">
                          {new Date(clip.modified_time * 1000).toLocaleString()}
                        </td>
                        <td className="py-3 pr-4 text-slate-400 font-mono text-xs">{clip.filename}</td>
                        <td className="py-3 pr-4 text-slate-400">
                          {(clip.size_bytes / (1024 * 1024)).toFixed(1)} MB
                        </td>
                        <td className="py-3">
                          <ClipActions
                            clipPath={clip.path}
                            type="video"
                            channelId={selectedClipCamera}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination page={clipPage} totalPages={totalPages} onPageChange={setClipPage} />
            </>
          )
        })()}
      </Card>
    </div>
  )
}
