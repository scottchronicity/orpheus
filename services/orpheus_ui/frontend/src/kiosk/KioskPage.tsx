/**
 * /kiosk — a glanceable, always-on station display.
 *
 * A route of the existing dashboard, not a separate application: it uses the
 * same backend endpoints and polling tiers, and renders in any modern browser
 * (a laptop tab, a Raspberry Pi in Chromium's kiosk mode, the Jetson itself).
 * Nothing is installed or started for it; a station that never opens /kiosk
 * pays nothing. Settings come from the URL (see settings.ts).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { CloudSun, WifiOff } from 'lucide-react'
import { OrpheusMark } from '../components/OrpheusMark'
import { POLLING_INTERVALS } from '../config'
import {
  AudioPanel,
  CameraPanel,
  SightingsPanel,
  SystemPanel,
  SystemStrip,
  TodayPanel,
  serviceSummary,
} from './KioskPanels'
import {
  KioskAuthError,
  demoApi,
  guestSignIn,
  liveApi,
  type KioskApi,
  type KioskEntity,
} from './kioskApi'
import { clockDate, clockTime, timeAgo } from './format'
import { isNightHour, parseKioskSettings, type KioskSettings } from './settings'

const SIGHTINGS_SHOWN = 7

/** Small screens (the 7-inch 800x480 station display, a phone) get the compact layout. */
export function isCompactViewport(width: number, height: number): boolean {
  return width < 900 || height < 640
}

function useCompact(): boolean {
  const read = () => isCompactViewport(window.innerWidth, window.innerHeight)
  const [compact, setCompact] = useState(read)
  useEffect(() => {
    const onResize = () => setCompact(read())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return compact
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

/** A blob/object URL for an image that needs auth, revoked when replaced. */
function useImage(api: KioskApi, path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!path) {
      setUrl(null)
      return
    }
    let cancelled = false
    let made: string | null = null
    api
      .imageUrl(path)
      .then((u) => {
        if (cancelled) {
          if (u.startsWith('blob:')) URL.revokeObjectURL(u)
          return
        }
        made = u
        setUrl(u)
      })
      .catch(() => {
        if (!cancelled) setUrl(null)
      })
    return () => {
      cancelled = true
      if (made && made.startsWith('blob:')) URL.revokeObjectURL(made)
    }
  }, [api, path])
  return url
}

type Session = 'checking' | 'ready' | 'needs-sign-in'

function useSession(demo: boolean): [Session, (s: Session) => void] {
  const [session, setSession] = useState<Session>(demo ? 'ready' : 'checking')
  useEffect(() => {
    if (demo) return
    let cancelled = false
    // Probe with a cheap endpoint: kioskFetch signs in as the guest if needed.
    liveApi
      .health()
      .then(() => !cancelled && setSession('ready'))
      .catch((err) => {
        if (cancelled) return
        setSession(err instanceof KioskAuthError ? 'needs-sign-in' : 'ready')
      })
    return () => {
      cancelled = true
    }
  }, [demo])
  return [session, setSession]
}

function SignInNeeded() {
  const location = useLocation()
  const next = encodeURIComponent(location.pathname + location.search)
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-950 p-8 text-center text-slate-200">
      <OrpheusMark className="h-14 w-14" />
      <h1 className="text-3xl font-semibold">This display needs a viewer sign-in</h1>
      <p className="max-w-xl text-lg text-slate-400">
        Guest viewing is turned off on this station (<code>ui.guest_quick_login</code>). Sign in once
        with a viewer account in this browser; the display keeps that session.
      </p>
      <div className="flex gap-3">
        <Link to={`/login?next=${next}`} className="rounded-lg bg-orpheus-600 px-5 py-2 text-lg text-white">
          Sign in
        </Link>
        <button
          type="button"
          onClick={() => guestSignIn().then((ok) => ok && window.location.reload())}
          className="rounded-lg border border-slate-700 px-5 py-2 text-lg"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

export function KioskView({ api, settings }: { api: KioskApi; settings: KioskSettings }) {
  const now = useNow(15_000)
  const nowDate = new Date(now)
  const compact = useCompact()
  const show = (p: KioskSettings['panels'][number]) => settings.panels.includes(p)
  const retry = { retry: (count: number, err: unknown) => !(err instanceof KioskAuthError) && count < 2 }

  const sightingsQ = useQuery({
    queryKey: ['kiosk', 'entities', settings.windowHours, settings.demo],
    // Ask for a few extra rows so hiding Orpheus's own sounds still fills the list.
    queryFn: () => api.entities(settings.windowHours, SIGHTINGS_SHOWN + 5),
    refetchInterval: POLLING_INTERVALS.HISTORY,
    enabled: show('sightings') || show('today'),
    ...retry,
  })
  const audioQ = useQuery({
    queryKey: ['kiosk', 'audio', settings.demo],
    queryFn: () => api.audio(),
    refetchInterval: POLLING_INTERVALS.REALTIME,
    enabled: show('audio'),
    ...retry,
  })
  const healthQ = useQuery({
    queryKey: ['kiosk', 'health', settings.demo],
    queryFn: () => api.health(),
    refetchInterval: POLLING_INTERVALS.HISTORY,
    ...retry,
  })
  const servicesQ = useQuery({
    queryKey: ['kiosk', 'services', settings.demo],
    queryFn: () => api.services(),
    refetchInterval: POLLING_INTERVALS.HISTORY * 2,
    ...retry,
  })
  const weatherQ = useQuery({
    queryKey: ['kiosk', 'weather', settings.demo],
    queryFn: () => api.weather(),
    refetchInterval: POLLING_INTERVALS.MEDIA * 5,
    ...retry,
  })
  // Camera names: from the URL, else the station's list (fetched rarely; the
  // endpoint probes every camera).
  const camerasQ = useQuery({
    queryKey: ['kiosk', 'cameras', settings.demo],
    queryFn: () => api.cameras(),
    refetchInterval: 10 * 60_000,
    staleTime: 10 * 60_000,
    enabled: show('cameras') && !settings.cameras,
    ...retry,
  })
  const cameraNames = useMemo(
    () => settings.cameras ?? (camerasQ.data ?? []).map((c) => c.name).filter(Boolean),
    [settings.cameras, camerasQ.data],
  )
  const [cameraIndex, setCameraIndex] = useState(0)
  useEffect(() => {
    if (cameraNames.length < 2) return
    const id = window.setInterval(
      () => setCameraIndex((i) => (i + 1) % cameraNames.length),
      settings.rotateSeconds * 1000,
    )
    return () => window.clearInterval(id)
  }, [cameraNames.length, settings.rotateSeconds])
  const camera = cameraNames.length ? cameraNames[cameraIndex % cameraNames.length] : null
  const snapshotQ = useQuery({
    queryKey: ['kiosk', 'snapshot', camera, settings.demo],
    queryFn: () => api.latestSnapshot(camera as string),
    refetchInterval: POLLING_INTERVALS.MEDIA,
    enabled: show('cameras') && !!camera,
    ...retry,
  })
  const imageUrl = useImage(api, snapshotQ.data?.download_url ?? null)

  const sightings: KioskEntity[] = (sightingsQ.data?.entities ?? [])
    .filter((e) => settings.includeSelfGenerated || !e.is_self_generated)
    .slice(0, SIGHTINGS_SHOWN)

  // Connection state: data shown but the latest refresh failed.
  const queries = [sightingsQ, audioQ, healthQ, servicesQ]
  const authLost = [...queries, snapshotQ, camerasQ, weatherQ].some((q) => q.error instanceof KioskAuthError)
  const failing = queries.filter((q) => q.isError)
  const lastUpdate = Math.max(...queries.map((q) => q.dataUpdatedAt || 0))
  const summary = serviceSummary(servicesQ.data)
  const status = failing.length
    ? { tone: 'bg-rose-500/20 text-rose-200', text: 'Station unreachable' }
    : summary.down.length
      ? { tone: 'bg-amber-500/20 text-amber-200', text: `${summary.down.length} service${summary.down.length > 1 ? 's' : ''} need attention` }
      : { tone: 'bg-emerald-500/20 text-emerald-200', text: 'All systems normal' }

  // Burn-in: drift the whole layout by a few pixels every few minutes.
  const shift = settings.burnInShift ? Math.floor(now / 180_000) % 4 : 0
  const offset = [
    [0, 0],
    [2, 1],
    [1, 2],
    [-1, 1],
  ][shift]
  const night = isNightHour(settings.night, nowDate.getHours())

  const weather = weatherQ.data
  const sideCount = (show('cameras') ? 1 : 0) + (show('audio') ? 1 : 0) + (show('system') ? 1 : 0)
  const mainCount = (show('sightings') ? 1 : 0) + (show('today') ? 1 : 0)

  // Guest viewing was turned off while the display was running.
  if (authLost) return <SignInNeeded />

  const cameraPanel = (small: boolean) => (
    <CameraPanel
      camera={camera}
      imageUrl={imageUrl}
      capturedIso={snapshotQ.data?.timestamp_iso ?? null}
      nowMs={now}
      compact={small}
      message={
        cameraNames.length === 0 && !camerasQ.isLoading
          ? 'No cameras configured'
          : snapshotQ.isSuccess && !snapshotQ.data
            ? 'No snapshot saved yet'
            : undefined
      }
    />
  )

  return (
    <div
      className="kiosk min-h-screen overflow-hidden bg-slate-950 text-slate-100 transition-[filter] duration-1000"
      style={{ filter: night ? 'brightness(0.35)' : undefined }}
      data-testid="kiosk"
      data-night={night ? 'true' : 'false'}
    >
      <div
        className={`flex h-screen flex-col ${compact ? 'gap-2 p-2' : 'gap-4 p-4 lg:p-6'}`}
        style={{ transform: `translate(${offset[0]}px, ${offset[1]}px)` }}
        data-layout={compact ? 'compact' : 'full'}
      >
        <header className={`flex items-center ${compact ? 'gap-3' : 'flex-wrap gap-4'}`}>
          <OrpheusMark className={compact ? 'h-7 w-7' : 'h-10 w-10'} />
          <div className="mr-auto min-w-0">
            <p className={`font-semibold text-white ${compact ? 'text-base' : 'text-xl'}`}>Orpheus</p>
            <p className={`mt-0.5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm ${status.tone}`} data-testid="kiosk-status">
              {failing.length > 0 && <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />}
              {status.text}
              {failing.length > 0 && lastUpdate > 0 && ` · showing data from ${clockTime(new Date(lastUpdate))}`}
            </p>
          </div>
          {weather?.available && weather.temperature_c != null && (
            <div className="flex items-center gap-2 text-lg text-slate-300" data-testid="kiosk-weather">
              <CloudSun className="h-6 w-6" aria-hidden="true" />
              <span className="tabular-nums">{weather.temperature_c.toFixed(0)}°C</span>
              {weather.humidity_pct != null && <span className="text-slate-500">{Math.round(weather.humidity_pct)}%</span>}
            </div>
          )}
          <div className="text-right">
            <p
              className={`font-semibold tabular-nums text-white ${compact ? 'text-2xl' : 'text-4xl'}`}
              data-testid="kiosk-clock"
            >
              {clockTime(nowDate)}
            </p>
            {!compact && <p className="text-sm text-slate-400">{clockDate(nowDate)}</p>}
          </div>
        </header>

        {compact ? (
          // Two columns, two rows; the station summary moves to the footer.
          <main className="grid min-h-0 flex-1 grid-cols-2 grid-rows-2 gap-2">
            {show('sightings') && <SightingsPanel entities={sightings} nowMs={now} compact />}
            {show('cameras') && cameraPanel(true)}
            {show('today') && (
              <TodayPanel stats={sightingsQ.data?.stats} windowHours={settings.windowHours} currentHour={nowDate.getHours()} compact />
            )}
            {show('audio') && <AudioPanel audio={audioQ.data} compact />}
          </main>
        ) : (
          <main
            className={`grid min-h-0 flex-1 gap-4 ${
              sideCount && mainCount ? 'md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]' : ''
            }`}
          >
            {mainCount > 0 && (
              <div className={`grid min-h-0 gap-4 ${mainCount === 2 ? 'lg:grid-cols-2' : ''}`}>
                {show('sightings') && <SightingsPanel entities={sightings} nowMs={now} />}
                {show('today') && (
                  <TodayPanel stats={sightingsQ.data?.stats} windowHours={settings.windowHours} currentHour={nowDate.getHours()} />
                )}
              </div>
            )}
            {sideCount > 0 && (
              <div className="grid min-h-0 auto-rows-fr gap-4">
                {show('cameras') && cameraPanel(false)}
                {show('audio') && <AudioPanel audio={audioQ.data} />}
                {show('system') && <SystemPanel health={healthQ.data} services={servicesQ.data} />}
              </div>
            )}
          </main>
        )}

        <footer className="flex justify-between gap-3 text-xs text-slate-500">
          {compact && show('system') ? (
            <span className="flex min-w-0 gap-2">
              {settings.demo && <span className="shrink-0 text-amber-300">Demo data ·</span>}
              <SystemStrip health={healthQ.data} services={servicesQ.data} />
            </span>
          ) : (
            <span>{settings.demo ? 'Demo data — not from a station' : 'Read-only display'}</span>
          )}
          <span data-testid="kiosk-updated">
            {lastUpdate > 0 ? `Updated ${timeAgo(new Date(lastUpdate).toISOString(), now)}` : 'Connecting…'}
          </span>
        </footer>
      </div>
    </div>
  )
}

export default function KioskPage() {
  const location = useLocation()
  const settings = useMemo(() => parseKioskSettings(location.search), [location.search])
  const api = settings.demo ? demoApi : liveApi
  const [session] = useSession(settings.demo)
  const root = useRef(document.documentElement.style.fontSize)

  // Text scale for distant or tiny screens; restored when leaving the kiosk.
  useEffect(() => {
    const previous = root.current
    document.documentElement.style.fontSize = settings.scale === 1 ? previous : `${16 * settings.scale}px`
    return () => {
      document.documentElement.style.fontSize = previous
    }
  }, [settings.scale])

  useEffect(() => {
    const previous = document.title
    document.title = 'Orpheus · Kiosk'
    return () => {
      document.title = previous
    }
  }, [])

  if (session === 'needs-sign-in') return <SignInNeeded />
  if (session === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400" data-testid="kiosk-connecting">
        Connecting to the station…
      </div>
    )
  }
  return <KioskView api={api} settings={settings} />
}
