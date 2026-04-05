/**
 * ClipActions - Play/Download buttons for audio and video clips
 *
 * Used in Audio.tsx, Birds.tsx, and Crows.tsx tables to provide
 * clip interaction functionality.
 *
 * Audio uses blob-based loading (fetchWithAuth -> blob -> objectURL).
 * Video clips use OpenCV's mp4v codec which browsers can't play inline,
 * so only download is offered for video.
 */
import { useState, useRef, useEffect } from 'react'
import { Play, Pause, Download, Volume2 } from 'lucide-react'
import { fetchWithAuth } from '../lib/utils'

// Timeout constants for object URL cleanup
const DOWNLOAD_CLEANUP_TIMEOUT_MS = 1000 // 1 second for download to start

interface ClipActionsProps {
  clipPath: string | null | undefined
  type?: 'audio' | 'video'
  channelId?: string
}

/**
 * Construct the API URL for a clip
 *
 * For absolute paths (from database), the full path is passed through.
 * For relative filenames, only the filename portion is extracted.
 */
function getClipUrl(clipPath: string, type: 'audio' | 'video', channelId?: string): string {
  // Extract just the filename from the full path
  const filename = clipPath.split('/').pop() || clipPath

  if (type === 'audio') {
    // Audio clips: /api/audio/clips/{channel_id}/{filename}
    const channel = channelId || '1'
    return `/api/audio/clips/${channel}/${filename}`
  } else {
    // Video clips: /api/video/clips/{camera_id}/{filename}
    const camera = channelId || 'orpheus-eye-1'
    return `/api/video/clips/${camera}/${filename}`
  }
}

export function ClipActions({ clipPath, type = 'audio', channelId }: ClipActionsProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const currentUrlRef = useRef<string | null>(null)
  const objectUrlRef = useRef<string | null>(null)

  // Cleanup object URL on unmount — must be before any early returns
  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [])

  if (!clipPath) {
    return (
      <span className="text-slate-500 text-sm">No clip</span>
    )
  }

  const clipUrl = getClipUrl(clipPath, type, channelId)

  const handlePlay = async (e: React.MouseEvent) => {
    // Stop event from propagating to parent elements (e.g., table row click)
    e.stopPropagation()

    if (isPlaying && audioRef.current) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      setIsLoading(true)
      try {
        // Fetch audio with authentication and create blob URL
        const response = await fetchWithAuth(clipUrl)
        if (!response.ok) {
          throw new Error(`Failed to fetch audio: ${response.status}`)
        }

        const blob = await response.blob()

        // Revoke old object URL if exists
        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current)
        }

        // Create new object URL
        const objectUrl = URL.createObjectURL(blob)
        objectUrlRef.current = objectUrl

        // Create new audio element if URL changed or doesn't exist
        if (!audioRef.current || currentUrlRef.current !== clipUrl) {
          if (audioRef.current) {
            audioRef.current.pause()
          }
          audioRef.current = new Audio(objectUrl)
          audioRef.current.onended = () => setIsPlaying(false)
          audioRef.current.onerror = () => {
            setIsPlaying(false)
            console.error('Audio playback error')
          }
          currentUrlRef.current = clipUrl
        } else {
          // Update existing audio element's src
          audioRef.current.src = objectUrl
        }

        await audioRef.current.play()
        setIsPlaying(true)
      } catch (error) {
        console.error('Failed to play audio:', error)
        setIsPlaying(false)
      } finally {
        setIsLoading(false)
      }
    }
  }

  const handleDownload = async (e: React.MouseEvent) => {
    // Stop event from propagating to parent elements (e.g., table row click)
    e.stopPropagation()

    setIsLoading(true)
    try {
      // Fetch with authentication
      const response = await fetchWithAuth(clipUrl)
      if (!response.ok) {
        throw new Error(`Failed to fetch clip: ${response.status}`)
      }

      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)

      // Create download link
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = clipPath.split('/').pop() || 'clip'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)

      // Cleanup object URL after download has started
      setTimeout(() => {
        URL.revokeObjectURL(objectUrl)
      }, DOWNLOAD_CLEANUP_TIMEOUT_MS)
    } catch (error) {
      console.error('Failed to download clip:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      {/* Play button only for audio — video clips use a codec browsers can't play */}
      {type === 'audio' && (
        <button
          onClick={(e) => handlePlay(e)}
          disabled={isLoading}
          className="p-1.5 rounded bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? (
            <Pause className="w-4 h-4" />
          ) : (
            <Play className="w-4 h-4" />
          )}
        </button>
      )}
      <button
        onClick={(e) => handleDownload(e)}
        disabled={isLoading}
        className="p-1.5 rounded bg-slate-600/50 hover:bg-slate-600 text-slate-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        title="Download"
      >
        <Download className="w-4 h-4" />
      </button>
    </div>
  )
}

/**
 * Inline audio player with waveform visualization
 *
 * Uses blob-based loading for authentication support.
 */
export function AudioPlayer({ clipPath, channelId }: { clipPath: string; channelId?: string }) {
  const [audioSrc, setAudioSrc] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const objectUrlRef = useRef<string | null>(null)

  const clipUrl = getClipUrl(clipPath, 'audio', channelId)

  // Load audio with authentication
  useEffect(() => {
    let cancelled = false

    const loadAudio = async () => {
      setIsLoading(true)
      setError(null)

      try {
        const response = await fetchWithAuth(clipUrl)
        if (!response.ok) {
          throw new Error(`Failed to load audio: ${response.status}`)
        }

        const blob = await response.blob()

        if (cancelled) {
          return
        }

        // Revoke old URL if exists
        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current)
        }

        const objectUrl = URL.createObjectURL(blob)
        objectUrlRef.current = objectUrl
        setAudioSrc(objectUrl)
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load audio:', err)
          setError('Failed to load audio')
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    loadAudio()

    return () => {
      cancelled = true
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [clipUrl])

  if (error) {
    return (
      <div className="flex items-center gap-3 p-3 bg-red-500/10 rounded-lg">
        <Volume2 className="w-5 h-5 text-red-400" />
        <span className="text-sm text-red-400">{error}</span>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 p-3 bg-slate-700/50 rounded-lg">
        <Volume2 className="w-5 h-5 text-slate-400 animate-pulse" />
        <span className="text-sm text-slate-400">Loading audio...</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 p-3 bg-slate-700/50 rounded-lg">
      <Volume2 className="w-5 h-5 text-blue-400" />
      {audioSrc ? (
        <audio
          controls
          src={audioSrc}
          className="h-8 flex-1"
          style={{ maxWidth: '300px' }}
        >
          Your browser does not support the audio element.
        </audio>
      ) : (
        <span className="text-sm text-slate-400">No audio available</span>
      )}
    </div>
  )
}
