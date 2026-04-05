import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'
import { CAMERA_IDS, POLLING_INTERVALS } from '../config'
import { Image, Video, Download, Calendar, ChevronLeft, ChevronRight, Clock, Info } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  EmptyState,
  Card,
} from '../components/ui'

interface Snapshot {
  filename: string
  date: string
  camera: string
  size_bytes: number
  size_kb: number
  modified_time: number
  timestamp_iso: string
  download_url: string
}

interface Timelapse {
  filename: string
  date: string
  camera: string
  size_bytes: number
  size_mb: number
  modified_time: number
  timestamp_iso: string
  download_url: string
  label: string | null
  tier: string | null
  tier_display: string | null
  lookback: string | null
}

interface SnapshotsResponse {
  snapshots: Snapshot[]
  date: string
  camera: string
  hour: number | null
  count: number
}

interface TimelapsesResponse {
  timelapses: Timelapse[]
  camera: string
  count: number
}

interface TimelapseConfigEntry {
  label: string
  lookback_window: string
  sampling_interval: string
  start_time: string
  retention_days: number
  timezone: string
}

interface TimelapseConfigCamera {
  snapshot_interval: string | null
  timelapses: TimelapseConfigEntry[]
}

interface TimelapseConfigResponse {
  cameras: Record<string, TimelapseConfigCamera>
}

type TabType = 'snapshots' | 'timelapses'

const SNAPSHOT_ITEMS_PER_PAGE = 50

/**
 * Timelapse configuration display section — collapsed by default.
 * Click the header to expand and see schedule details.
 */
function TimelapsConfigSection({ selectedCamera }: { selectedCamera: string }) {
  const [isExpanded, setIsExpanded] = useState(false)
  const { data, isLoading } = useQuery<TimelapseConfigResponse>({
    queryKey: ['timelapse-config'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/media/timelapse-config')
      return res.json()
    },
    staleTime: 60000,
  })

  if (isLoading) return null

  const cameraConfig = data?.cameras?.[selectedCamera]
  if (!cameraConfig) return null

  return (
    <Card>
      <button
        onClick={() => setIsExpanded(e => !e)}
        className="w-full flex items-center justify-between"
      >
        <div className="flex items-center gap-2">
          <Info className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-medium text-white">Timelapse Schedule &mdash; {selectedCamera}</h2>
        </div>
        <ChevronRight className={`w-5 h-5 text-slate-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
      </button>
      {isExpanded && <div className="mt-4">
      {cameraConfig.snapshot_interval && (
        <p className="text-sm text-slate-400 mb-4">
          Snapshots taken every <span className="text-white font-medium">{cameraConfig.snapshot_interval}</span>
        </p>
      )}
      {cameraConfig.timelapses.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {cameraConfig.timelapses.map((tl) => (
            <div key={tl.label} className="bg-slate-700/50 rounded-lg p-3 border border-slate-600">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="w-4 h-4 text-blue-400" />
                <span className="font-medium text-white capitalize">{tl.label}</span>
              </div>
              <dl className="text-sm space-y-1">
                <div className="flex justify-between">
                  <dt className="text-slate-400">Covers</dt>
                  <dd className="text-slate-200">{tl.lookback_window}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-400">Samples every</dt>
                  <dd className="text-slate-200">{tl.sampling_interval}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-400">Generated at</dt>
                  <dd className="text-slate-200">{tl.start_time} {tl.timezone !== 'UTC' ? `(${tl.timezone})` : 'UTC'}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-400">Kept for</dt>
                  <dd className="text-slate-200">{tl.retention_days} days</dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-slate-500 text-sm">No timelapse schedules configured for this camera.</p>
      )}
      </div>}
    </Card>
  )
}

/**
 * Media Browser Page - Historical snapshots and timelapses.
 * Tabbed interface for viewing and downloading media files.
 */
export default function Media() {
  const [activeTab, setActiveTab] = useState<TabType>('snapshots')
  const [selectedCamera, setSelectedCamera] = useState<string>(CAMERA_IDS[0])
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date()
    return today.toISOString().split('T')[0].replace(/-/g, '.')
  })
  const [selectedHour, setSelectedHour] = useState<string>('all')
  const [snapshotPage, setSnapshotPage] = useState<number>(1)
  const [selectedTimelapseDate, setSelectedTimelapseDate] = useState<string>('')
  const [timelapsePage, setTimelapsePage] = useState<number>(1)
  const [labelFilter, setLabelFilter] = useState<string>('all')
  const [videoBlobUrls, setVideoBlobUrls] = useState<Record<string, string>>({})
  const videoBlobUrlsRef = useRef<Record<string, string>>({})

  // Reset pages when filters change
  useEffect(() => {
    setSnapshotPage(1)
  }, [selectedCamera, selectedDate, selectedHour])

  useEffect(() => {
    setTimelapsePage(1)
  }, [selectedCamera, selectedTimelapseDate, labelFilter])

  // Fetch snapshots - request up to 200, paginate client-side
  const snapshotsQuery = useQuery<SnapshotsResponse>({
    queryKey: ['snapshots', selectedCamera, selectedDate, selectedHour],
    queryFn: async () => {
      const hourParam = selectedHour !== 'all' ? `&hour=${selectedHour}` : ''
      const response = await fetchWithAuth(
        `/api/media/snapshots/${selectedCamera}?date=${selectedDate}&limit=200${hourParam}`
      )
      if (!response.ok) throw new Error('Failed to fetch snapshots')
      return response.json()
    },
    refetchInterval: POLLING_INTERVALS.MEDIA,
    enabled: activeTab === 'snapshots',
  })

  // Fetch timelapses
  const timelapsesQuery = useQuery<TimelapsesResponse>({
    queryKey: ['timelapses', selectedCamera, selectedTimelapseDate],
    queryFn: async () => {
      const dateParam = selectedTimelapseDate ? `?date=${selectedTimelapseDate}` : ''
      const response = await fetchWithAuth(`/api/media/timelapses/${selectedCamera}${dateParam}`)
      if (!response.ok) throw new Error('Failed to fetch timelapses')
      return response.json()
    },
    refetchInterval: POLLING_INTERVALS.MEDIA,
    enabled: activeTab === 'timelapses',
  })

  const handleDownload = async (url: string, filename: string) => {
    try {
      const response = await fetchWithAuth(url)
      if (!response.ok) throw new Error('Download failed')

      const blob = await response.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(downloadUrl)
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const formatTimestamp = (isoString: string) => {
    const date = new Date(isoString)
    return date.toLocaleString()
  }

  // Load authenticated video as blob URL for playback
  const loadVideoBlob = async (url: string, filename: string) => {
    if (videoBlobUrlsRef.current[filename]) return

    try {
      const response = await fetchWithAuth(url)
      if (!response.ok) throw new Error('Failed to load video')

      const blob = await response.blob()
      const blobUrl = URL.createObjectURL(blob)
      setVideoBlobUrls(prev => ({ ...prev, [filename]: blobUrl }))
    } catch (error) {
      console.error('Video load failed:', error)
    }
  }

  useEffect(() => {
    videoBlobUrlsRef.current = videoBlobUrls
  }, [videoBlobUrls])

  useEffect(() => {
    return () => {
      Object.values(videoBlobUrlsRef.current).forEach(url => URL.revokeObjectURL(url))
    }
  }, [])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Historical Media"
        description="Browse and download snapshots and timelapse videos"
      />

      {/* Timelapse Config - shown above filters on timelapses tab */}
      {activeTab === 'timelapses' && (
        <TimelapsConfigSection selectedCamera={selectedCamera} />
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        <button
          onClick={() => setActiveTab('snapshots')}
          className={`px-6 py-3 font-medium transition-colors ${
            activeTab === 'snapshots'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <div className="flex items-center gap-2">
            <Image className="w-4 h-4" />
            Snapshots
          </div>
        </button>
        <button
          onClick={() => setActiveTab('timelapses')}
          className={`px-6 py-3 font-medium transition-colors ${
            activeTab === 'timelapses'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <div className="flex items-center gap-2">
            <Video className="w-4 h-4" />
            Timelapses
          </div>
        </button>
      </div>

      {/* Filters */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex-1 min-w-32">
            <label className="block text-sm font-medium text-slate-400 mb-2">
              Camera
            </label>
            <select
              value={selectedCamera}
              onChange={(e) => setSelectedCamera(e.target.value)}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CAMERA_IDS.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
          {activeTab === 'snapshots' && (
            <>
              <div className="flex-1 min-w-32">
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Date
                </label>
                <div className="relative">
                  <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                  <input
                    type="date"
                    value={selectedDate.replace(/\./g, '-')}
                    onChange={(e) => {
                      setSelectedDate(e.target.value.replace(/-/g, '.'))
                    }}
                    className="w-full pl-10 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div className="flex-1 min-w-32">
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Hour (UTC)
                </label>
                <div className="relative">
                  <Clock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                  <select
                    value={selectedHour}
                    onChange={(e) => setSelectedHour(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="all">All hours</option>
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={String(i)}>
                        {String(i).padStart(2, '0')}:00 &ndash; {String(i).padStart(2, '0')}:59
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </>
          )}
          {activeTab === 'timelapses' && (
            <div className="flex-1 min-w-32">
              <label className="block text-sm font-medium text-slate-400 mb-2">
                Date (leave blank for all)
              </label>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type="date"
                  value={selectedTimelapseDate.replace(/\./g, '-')}
                  onChange={(e) =>
                    setSelectedTimelapseDate(e.target.value.replace(/-/g, '.'))
                  }
                  className="w-full pl-10 pr-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          )}
          {activeTab === 'timelapses' && timelapsesQuery.data && (() => {
            const availableLabels = Array.from(
              new Set(timelapsesQuery.data.timelapses.map(t => t.label).filter(Boolean))
            ) as string[]
            return availableLabels.length > 0 ? (
              <div className="flex-1 min-w-32">
                <label className="block text-sm font-medium text-slate-400 mb-2">
                  Label
                </label>
                <select
                  value={labelFilter}
                  onChange={(e) => setLabelFilter(e.target.value)}
                  className="w-full px-4 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="all">All</option>
                  {availableLabels.map((label) => (
                    <option key={label} value={label}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            ) : null
          })()}
        </div>
      </div>

      {/* Snapshots Content */}
      {activeTab === 'snapshots' && (
        <div>
          {snapshotsQuery.isLoading && <LoadingSpinner />}
          {snapshotsQuery.error && (
            <ErrorMessage title="Error" message="Failed to load snapshots" />
          )}
          {snapshotsQuery.data && snapshotsQuery.data.snapshots.length === 0 && (
            <EmptyState
              icon={Image}
              title="No Snapshots"
              description={`No snapshots found for ${selectedCamera} on ${selectedDate}${selectedHour !== 'all' ? ` at hour ${selectedHour}` : ''}`}
            />
          )}
          {snapshotsQuery.data && snapshotsQuery.data.snapshots.length > 0 && (() => {
            const allSnapshots = snapshotsQuery.data.snapshots
            const totalSnapshotPages = Math.max(1, Math.ceil(allSnapshots.length / SNAPSHOT_ITEMS_PER_PAGE))
            const pageSnapshots = allSnapshots.slice(
              (snapshotPage - 1) * SNAPSHOT_ITEMS_PER_PAGE,
              snapshotPage * SNAPSHOT_ITEMS_PER_PAGE
            )

            return (
              <div className="space-y-4">
                <div className="text-sm text-slate-400">
                  {allSnapshots.length} snapshots for {selectedCamera} on {selectedDate}
                  {selectedHour !== 'all' ? ` (hour ${selectedHour.padStart(2, '0')}:00)` : ''}
                  {' — '}showing page {snapshotPage} of {totalSnapshotPages}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {pageSnapshots.map((snapshot) => (
                    <div
                      key={snapshot.filename}
                      className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden"
                    >
                      <div className="aspect-video bg-slate-900 flex items-center justify-center">
                        <Image className="w-12 h-12 text-slate-600" />
                      </div>
                      <div className="p-4 space-y-3">
                        <div>
                          <div className="text-sm text-slate-400">
                            {formatTimestamp(snapshot.timestamp_iso)}
                          </div>
                          <div className="text-xs text-slate-500 mt-1">
                            {snapshot.size_kb} KB
                          </div>
                        </div>
                        <button
                          onClick={() =>
                            handleDownload(snapshot.download_url, snapshot.filename)
                          }
                          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                        >
                          <Download className="w-4 h-4" />
                          Download
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {totalSnapshotPages > 1 && (
                  <div className="flex items-center justify-center gap-4 pt-4">
                    <button
                      onClick={() => setSnapshotPage(p => Math.max(1, p - 1))}
                      disabled={snapshotPage <= 1}
                      className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                      Previous
                    </button>
                    <span className="text-sm text-slate-400">
                      Page {snapshotPage} of {totalSnapshotPages}
                    </span>
                    <button
                      onClick={() => setSnapshotPage(p => Math.min(totalSnapshotPages, p + 1))}
                      disabled={snapshotPage >= totalSnapshotPages}
                      className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
                    >
                      Next
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      {/* Timelapses Content */}
      {activeTab === 'timelapses' && (
        <div>
          {timelapsesQuery.isLoading && <LoadingSpinner />}
          {timelapsesQuery.error && (
            <ErrorMessage title="Error" message="Failed to load timelapses" />
          )}
          {timelapsesQuery.data && timelapsesQuery.data.timelapses.length === 0 && (
            <EmptyState
              icon={Video}
              title="No Timelapses"
              description={`No timelapses found for ${selectedCamera}`}
            />
          )}
          {timelapsesQuery.data && timelapsesQuery.data.timelapses.length > 0 && (() => {
            const ITEMS_PER_PAGE = 50
            const filteredTimelapses = timelapsesQuery.data.timelapses.filter(
              t => labelFilter === 'all' || t.label === labelFilter
            )
            const totalPages = Math.max(1, Math.ceil(filteredTimelapses.length / ITEMS_PER_PAGE))
            const paginatedTimelapses = filteredTimelapses.slice(
              (timelapsePage - 1) * ITEMS_PER_PAGE,
              timelapsePage * ITEMS_PER_PAGE
            )

            return (
            <div className="space-y-4">
              <div className="text-sm text-slate-400">
                Showing {paginatedTimelapses.length} of {filteredTimelapses.length} timelapses for {selectedCamera}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {paginatedTimelapses.map((timelapse) => (
                  <div
                    key={timelapse.filename}
                    className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden"
                  >
                    {videoBlobUrls[timelapse.filename] ? (
                      <video
                        controls
                        className="w-full aspect-video bg-slate-900"
                        preload="metadata"
                      >
                        <source src={videoBlobUrls[timelapse.filename]} type="video/mp4" />
                        Your browser does not support video playback.
                      </video>
                    ) : (
                      <div className="aspect-video bg-slate-900 flex items-center justify-center">
                        <button
                          onClick={() => loadVideoBlob(timelapse.download_url, timelapse.filename)}
                          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                        >
                          <Video className="w-4 h-4" />
                          Load Video
                        </button>
                      </div>
                    )}
                    <div className="p-4 space-y-3">
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="px-2 py-1 text-sm font-medium bg-blue-600/30 text-blue-300 rounded">
                            {timelapse.label || 'timelapse'}
                            {timelapse.tier_display && (
                              <span className="ml-1 text-blue-400/70">({timelapse.tier_display})</span>
                            )}
                          </span>
                          <span className="text-xs text-slate-500">
                            {timelapse.size_mb} MB
                          </span>
                        </div>
                        <div className="text-sm font-medium text-white">
                          {timelapse.date.replace(/\./g, '-')}
                        </div>
                        <div className="text-xs text-slate-400 mt-1">
                          {formatTimestamp(timelapse.timestamp_iso)}
                        </div>
                      </div>
                      <button
                        onClick={() =>
                          handleDownload(timelapse.download_url, timelapse.filename)
                        }
                        className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                      >
                        <Download className="w-4 h-4" />
                        Download
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Pagination Controls */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-4 pt-4">
                  <button
                    onClick={() => setTimelapsePage(p => Math.max(1, p - 1))}
                    disabled={timelapsePage <= 1}
                    className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Previous
                  </button>
                  <span className="text-sm text-slate-400">
                    Page {timelapsePage} of {totalPages}
                  </span>
                  <button
                    onClick={() => setTimelapsePage(p => Math.min(totalPages, p + 1))}
                    disabled={timelapsePage >= totalPages}
                    className="flex items-center gap-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-lg transition-colors"
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
