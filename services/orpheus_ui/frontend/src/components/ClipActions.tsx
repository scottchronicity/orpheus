/**
 * ClipActions - Play/Download buttons for audio and video clips
 *
 * Used in Audio.tsx, Birds.tsx, Crows.tsx, AudioEvents.tsx, Video.tsx,
 * and the Entities evidence drawer.
 *
 * Mobile-Safari note: ``play()`` and synthetic ``<a download>`` clicks
 * only count as user-initiated if they run synchronously inside the
 * same task as the originating ``click``/``touchend`` event. Any
 * ``await`` against a network resource consumes the gesture token and
 * the browser silently refuses the action. So this component does NOT
 * pre-fetch the clip as a blob; instead it builds a ``?token=``-
 * authenticated direct URL (``getTokenUrl``) and hands it to
 * ``<audio>.src`` / ``<a>.href`` synchronously. Auth on the backend
 * side is wired via ``current_user_or_token_param`` on the clip
 * routes in ``api/diagnostics.py``.
 *
 * Video clips use OpenCV's mp4v codec which browsers can't play
 * inline, so only Download is offered for video.
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { Play, Pause, Download, Volume2, Archive } from 'lucide-react'
import { fetchWithAuth, getTokenUrl } from '../lib/utils'

interface ClipActionsProps {
  clipPath: string | null | undefined
  type?: 'audio' | 'video'
  channelId?: string
  /**
   * Backend-computed availability for entity evidence (``clip_available``
   * from ``/api/entities``). When ``false`` the clip has rolled off the
   * storage-retention window — render the "Clip expired" state immediately
   * and DON'T fire a request that's doomed to 404. Left ``undefined`` by
   * callers that don't supply it (e.g. recent-detection rows on Birds /
   * Crows): those keep relying on the probe-on-error fallback below.
   */
  clipAvailable?: boolean
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

export function ClipActions({ clipPath, type = 'audio', channelId, clipAvailable }: ClipActionsProps) {
  const [isPlaying, setIsPlaying] = useState(false)
  // ``clipUnavailable`` flips true once we confirm the backend
  // returned 404 for this clip. The Entity / Detection DB keeps a
  // longer memory than the on-disk audio retention window (clips
  // roll off after the configured size cap), so any sufficiently-
  // old evidence row can reference a file that no longer exists.
  // Probe-on-error rather than probe-on-mount so we don't issue an
  // extra HEAD per visible row.
  const [clipUnavailable, setClipUnavailable] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const currentUrlRef = useRef<string | null>(null)
  const mountedRef = useRef(true)

  // Tear down the audio element on unmount so the browser stops
  // streaming bytes for a row that's no longer on screen. Null out
  // the event handlers FIRST: setting ``src = ''`` fires an async
  // ``error`` event (MEDIA_ELEMENT_ERROR: empty src) and an in-flight
  // ``play()`` promise can reject after unmount — without nulling the
  // handlers, those async callbacks would call ``setIsPlaying(false)``
  // on a stale closure and trigger React's unmounted-state-update
  // warning in dev (silent leak in prod).
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      const audio = audioRef.current
      if (audio) {
        audio.onplay = null
        audio.onpause = null
        audio.onended = null
        audio.onerror = null
        audio.pause()
        audio.src = ''
        audioRef.current = null
      }
    }
  }, [])

  // Reset the expired flag when the clip changes (e.g., row click on a
  // different entity reuses this component instance).
  useEffect(() => {
    setClipUnavailable(false)
  }, [clipPath, channelId])

  const probeClipStatus = useCallback(
    async (url: string) => {
      try {
        const res = await fetchWithAuth(url, { method: 'HEAD' })
        if (mountedRef.current && res.status === 404) {
          setClipUnavailable(true)
        }
        // 401 is handled inside fetchWithAuth (clears the token and
        // hard-redirects to /login). Any other non-OK status is a
        // transient/server issue — leave the buttons clickable so the
        // user can retry.
      } catch {
        // Network blip or fetchWithAuth's own redirect — nothing more
        // to do here.
      }
    },
    [],
  )

  if (!clipPath) {
    return (
      <span className="text-slate-500 text-sm">No clip</span>
    )
  }

  const clipUrl = getClipUrl(clipPath, type, channelId)

  // The clip is known to be gone — render a clear "expired" state
  // instead of a broken Play/Download. The audio-retention policy
  // (see ``StorageRetention`` in orpheus_common.config) eventually
  // deletes the file even though the DB row that references it
  // persists. Two ways we know: ``clipAvailable === false`` is the
  // backend's preemptive existence check (no request fired at all);
  // ``clipUnavailable`` is the reactive HEAD-probe fallback after a
  // failed play/download.
  if (clipAvailable === false || clipUnavailable) {
    return (
      <div
        className="flex items-center gap-1.5 text-slate-500 text-xs italic"
        title="The audio file for this evidence has been deleted by the storage-retention policy and is no longer available."
      >
        <Archive className="w-3.5 h-3.5" />
        <span>Clip expired</span>
      </div>
    )
  }

  const handlePlay = (e: React.MouseEvent) => {
    // Stop event from propagating to parent elements (e.g., table row click)
    e.stopPropagation()

    // Toggle: if already playing this clip, pause.
    if (isPlaying && audioRef.current) {
      audioRef.current.pause()
      // ``onpause`` will flip isPlaying=false.
      return
    }

    // First tap on this clip, or resuming after pause: build (or reuse)
    // the audio element synchronously inside the click handler so the
    // mobile-Safari gesture token survives. Any ``await`` here would
    // burn the gesture and ``.play()`` would reject silently.
    if (!audioRef.current || currentUrlRef.current !== clipUrl) {
      // New clip — build a fresh element. Lazy ``src`` resolution
      // means the browser starts streaming on .play(), not on
      // construction, so paginating past a row doesn't fire a
      // request for it.
      if (audioRef.current) {
        audioRef.current.pause()
      }
      const audio = new Audio()
      audio.preload = 'none'
      audio.onplay = () => setIsPlaying(true)
      audio.onpause = () => setIsPlaying(false)
      audio.onended = () => setIsPlaying(false)
      audio.onerror = () => {
        setIsPlaying(false)
        console.error('Audio playback error', audio.error)
        // The media element can't expose HTTP status codes, so a 401
        // or 404 surfaces as a generic MEDIA_ERR_NETWORK /
        // MEDIA_ERR_SRC_NOT_SUPPORTED. Probe the clip URL with HEAD
        // to disambiguate:
        //   - 401 → ``fetchWithAuth`` removes the token + redirects
        //     to /login (caller of probeClipStatus need do nothing).
        //   - 404 → ``probeClipStatus`` flips ``clipUnavailable`` so
        //     we render the "Clip expired" state on the next render.
        //   - 200 → file is there; this was a real media error
        //     (codec, network blip). Leave the buttons clickable so
        //     the user can retry.
        void probeClipStatus(clipUrl)
      }
      audio.src = getTokenUrl(clipUrl)
      audioRef.current = audio
      currentUrlRef.current = clipUrl
    }

    // Fire-and-attach: ``play()`` returns a promise but we MUST NOT
    // await it — that would happen after the click handler's task
    // returns, leaving nothing to fail. Attach .catch instead.
    const result = audioRef.current.play()
    if (result && typeof result.catch === 'function') {
      result.catch((err) => {
        // NotAllowedError on locked-down browsers, NotSupportedError
        // on codec mismatches, AbortError on rapid toggles — none
        // are worth blowing the UI for; surface to console for
        // debugging.
        console.error('Failed to start audio playback:', err)
        setIsPlaying(false)
      })
    }
  }

  const handleDownload = (e: React.MouseEvent) => {
    // Stop event from propagating to parent elements (e.g., table row click)
    e.stopPropagation()

    // Synchronous anchor click inside the gesture task. On mobile
    // Safari, anything that goes through an ``await`` first gets
    // silently dropped. The browser-side ``download`` attribute on
    // the synthetic ``<a>`` (combined with same-origin resource — no
    // cross-origin restrictions, no proxy stripping headers) drives
    // the file download. The backend clip routes return a plain
    // ``FileResponse`` without an explicit Content-Disposition; the
    // download works because of the ``<a download>`` attribute, not a
    // server-side hint. If clips ever move behind a CDN or another
    // origin, add a ``Content-Disposition: attachment`` header to the
    // ``FileResponse`` in api/diagnostics.py to harden this.
    const link = document.createElement('a')
    link.href = getTokenUrl(clipUrl)
    link.download = clipPath.split('/').pop() || 'clip'
    // Some browsers (older Safari) don't honour the ``download``
    // attribute without the link being in the DOM. Append + click +
    // remove keeps that path working.
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // Now that the synchronous click fired (preserving the mobile-
    // Safari gesture token), probe the backend to see if the file
    // actually exists. A 404 will flip the UI to the "Clip expired"
    // state so the user can see why the download did nothing —
    // without the probe the synthetic anchor click gives zero
    // feedback when the server has nothing to serve. The 200ms
    // delay lets the browser's download request fire first; the
    // HEAD then races back without blocking the user.
    window.setTimeout(() => {
      void probeClipStatus(clipUrl)
    }, 200)
  }

  return (
    <div className="flex items-center gap-2">
      {/* Play button only for audio — video clips use a codec browsers can't play */}
      {type === 'audio' && (
        <button
          onClick={(e) => handlePlay(e)}
          className="p-1.5 rounded bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 transition-colors"
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
        className="p-1.5 rounded bg-slate-600/50 hover:bg-slate-600 text-slate-300 transition-colors"
        title="Download"
      >
        <Download className="w-4 h-4" />
      </button>
    </div>
  )
}

/**
 * Inline audio player with native HTML5 controls.
 *
 * Streams the clip directly via a ``?token=``-authenticated URL —
 * same gesture-token reasoning as ``ClipActions`` above. Previously
 * this fetched the whole clip as a blob, which (a) held it in memory
 * and (b) meant the user-gesture for ``play()`` on the native
 * controls was lost on mobile.
 */
export function AudioPlayer({ clipPath, channelId }: { clipPath: string; channelId?: string }) {
  const [clipUnavailable, setClipUnavailable] = useState(false)
  const clipUrl = getClipUrl(clipPath, 'audio', channelId)
  // Resolve the tokenised URL once per render so the ``key`` swap
  // restarts the element cleanly when the clip changes.
  const tokenisedUrl = getTokenUrl(clipUrl)

  // Reset expired flag when the clip identity changes.
  useEffect(() => {
    setClipUnavailable(false)
  }, [clipPath, channelId])

  if (!clipPath) {
    return (
      <div className="flex items-center gap-3 p-3 bg-slate-700/50 rounded-lg">
        <Volume2 className="w-5 h-5 text-slate-400" />
        <span className="text-sm text-slate-400">No audio available</span>
      </div>
    )
  }

  if (clipUnavailable) {
    return (
      <div
        className="flex items-center gap-3 p-3 bg-slate-700/30 rounded-lg"
        title="The audio file has been deleted by the storage-retention policy and is no longer available."
      >
        <Archive className="w-5 h-5 text-slate-500" />
        <span className="text-sm text-slate-500 italic">Clip expired — file no longer on disk</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 p-3 bg-slate-700/50 rounded-lg">
      <Volume2 className="w-5 h-5 text-blue-400" />
      <audio
        key={tokenisedUrl}
        controls
        preload="none"
        src={tokenisedUrl}
        className="h-8 flex-1"
        style={{ maxWidth: '300px' }}
        onError={() => {
          // Same pattern as ClipActions: HEAD-probe to disambiguate
          // 404 (file rolled off retention) from other failures.
          fetchWithAuth(clipUrl, { method: 'HEAD' })
            .then((res) => {
              if (res.status === 404) setClipUnavailable(true)
            })
            .catch(() => {})
        }}
      >
        Your browser does not support the audio element.
      </audio>
    </div>
  )
}
