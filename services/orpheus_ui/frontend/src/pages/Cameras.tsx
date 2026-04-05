import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWithAuth } from '../lib/utils'
import { POLLING_INTERVALS } from '../config'
import { Camera, RefreshCw } from 'lucide-react'
import {
  LoadingSpinner,
  PageHeader,
  ErrorMessage,
  StatusBadge,
  EmptyState,
} from '../components/ui'

interface CameraStatus {
  name: string
  status: string
  last_snapshot?: string
  error?: string
}

/**
 * Hook to fetch camera snapshot with authentication.
 * Regular <img> tags can't include auth headers, so we fetch as blob.
 */
function useCameraSnapshot(cameraName: string) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    let currentObjectUrl: string | null = null

    async function fetchSnapshot() {
      try {
        const response = await fetchWithAuth(`/api/cameras/${cameraName}/snapshot`)
        if (cancelled) return
        
        if (!response.ok) {
          setError(true)
          return
        }
        const blob = await response.blob()
        if (cancelled) return
        
        currentObjectUrl = URL.createObjectURL(blob)
        setImageUrl(currentObjectUrl)
        setError(false)
      } catch {
        if (!cancelled) {
          setError(true)
        }
      }
    }

    fetchSnapshot()

    // Cleanup object URL on unmount or when cameraName changes
    return () => {
      cancelled = true
      if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl)
      }
    }
  }, [cameraName])

  return { imageUrl, error }
}

/**
 * Individual camera card component.
 * Fetches snapshot with auth headers via blob URL.
 */
function CameraCard({ camera }: { camera: CameraStatus }) {
  const { imageUrl, error: imageError } = useCameraSnapshot(camera.name)

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
      {/* Camera Preview */}
      <div className="aspect-video bg-slate-900 flex items-center justify-center relative">
        {imageUrl && !imageError && (
          <img
            src={imageUrl}
            alt={camera.name}
            className="w-full h-full object-cover absolute inset-0 z-10"
          />
        )}
        <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80">
          <Camera className="w-12 h-12 text-slate-600" />
        </div>
      </div>

      {/* Camera Info */}
      <div className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/20 text-blue-400">
              <Camera className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-medium text-white">{camera.name}</h3>
              {camera.last_snapshot && (
                <p className="text-xs text-slate-500">
                  Last snapshot: {new Date(camera.last_snapshot).toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
          <StatusBadge status={camera.status} />
        </div>
        {camera.error && <p className="mt-2 text-sm text-red-400">{camera.error}</p>}
      </div>
    </div>
  )
}

export default function CamerasPage() {
  const { data: cameras, isLoading, error, refetch } = useQuery<CameraStatus[]>({
    queryKey: ['cameras'],
    queryFn: async () => {
      const res = await fetchWithAuth('/api/cameras')
      return res.json()
    },
    refetchInterval: POLLING_INTERVALS.CAMERAS,
  })

  if (isLoading) {
    return <LoadingSpinner />
  }

  if (error) {
    return (
      <ErrorMessage
        title="Cameras"
        description="View and manage camera feeds"
        message="Failed to load camera data"
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Cameras" description="View and manage camera feeds">
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </PageHeader>

      {cameras && cameras.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {cameras.map((camera) => (
            <CameraCard key={camera.name} camera={camera} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Camera}
          title="No cameras configured"
          description="Add cameras to orpheus.yaml to see them here"
        />
      )}
    </div>
  )
}
