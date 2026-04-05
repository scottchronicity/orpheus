import { useRef, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Terminal, Mic } from 'lucide-react'
import { fetchAudioHealth, fetchServiceLogs } from '../lib/api'
import { POLLING_INTERVALS } from '../config'
import { Card, CardHeader, PageHeader, LoadingSpinner } from '../components/ui'
import type { AudioChannel } from '../lib/api'

const ORPHEUS_SERVICES = [
  'orpheus-agent-audio-motion',
  'orpheus-agent-audio-playback',
  'orpheus-agent-video-motion',
  'orpheus-agent-video-snapshotter',
  'orpheus-agent-video-timelapser',
  'orpheus-agent-bird-detection',
  'orpheus-agent-event-correlator',
  'orpheus-dashboard',
  'orpheus-ui',
  'orpheus-mqtt',
  'orpheus-gps',
  'orpheus-bluetooth-autoconnect',
] as const

// ---------------------------------------------------------------------------
// AudioHealthPanel
// ---------------------------------------------------------------------------

const LEVEL_COLOR_MAP: Record<string, string> = {
  green: 'bg-green-500',
  yellow: 'bg-yellow-400',
  red: 'bg-red-500',
  none: 'bg-slate-600',
}

function ChannelBar({ channel }: { channel: AudioChannel }) {
  const isActive = channel.has_signal
  const barColor = LEVEL_COLOR_MAP[channel.level_color] ?? LEVEL_COLOR_MAP.none

  // Map dB range [-80, 0] → width percentage [0, 100]
  const levelDb = channel.level_db ?? -100
  const peakDbVal = channel.peak_db ?? -100
  const clampedDb = Math.max(-80, Math.min(0, levelDb))
  const widthPct = Math.round(((clampedDb + 80) / 80) * 100)

  const peakDb = peakDbVal === -100 ? '--' : `${peakDbVal.toFixed(1)} dB`
  const currentDb = levelDb === -100 ? '--' : `${levelDb.toFixed(1)} dB`

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-300 font-medium">Ch {channel.id}</span>
        <span
          className={`px-1.5 py-0.5 rounded text-xs font-semibold ${
            isActive
              ? 'bg-green-500/20 text-green-400'
              : 'bg-slate-600/40 text-slate-500'
          }`}
        >
          {isActive ? 'TRIGGERED' : 'IDLE'}
        </span>
      </div>

      {/* Level bar */}
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-200 ${barColor}`}
          style={{ width: `${widthPct}%` }}
        />
      </div>

      <div className="flex justify-between text-xs text-slate-500">
        <span>Level: {currentDb}</span>
        <span>Peak: {peakDb}</span>
      </div>
    </div>
  )
}

/**
 * Displays the 4 audio input channels with dB levels and IDLE/TRIGGERED status.
 * Matches the existing dark-mode Tailwind aesthetic.
 */
export function AudioHealthPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['audio-health'],
    queryFn: fetchAudioHealth,
    refetchInterval: POLLING_INTERVALS.REALTIME,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader title="Audio System Health" icon={Mic} iconColor="green" />
        <LoadingSpinner className="h-32" />
      </Card>
    )
  }

  const channels = data?.channels ?? []
  const isRunning = data?.running ?? false

  // Ensure we always show 4 channel slots (pad with placeholders if needed)
  const displayChannels: AudioChannel[] = ['1', '2', '3', '4'].map((id) => {
    return (
      channels.find((c) => c.id === id) ?? {
        id,
        active: false,
        level_db: -100,
        peak_db: -100,
        level_color: 'none' as const,
        has_signal: false,
      }
    )
  })

  return (
    <Card>
      <CardHeader title="Audio System Health" icon={Mic} iconColor="green" />
      <div className="flex items-center gap-2 mb-4">
        <span
          className={`inline-block w-2 h-2 rounded-full ${isRunning ? 'bg-green-400' : 'bg-slate-500'}`}
        />
        <span className="text-xs text-slate-400">
          {isRunning ? 'Agent running' : data?.message ?? 'Agent not running'}
        </span>
        {data?.health_status && (
          <span
            className={`ml-auto text-xs px-2 py-0.5 rounded ${
              data.health_status === 'good'
                ? 'bg-green-500/20 text-green-400'
                : data.health_status === 'warning'
                ? 'bg-yellow-500/20 text-yellow-400'
                : 'bg-red-500/20 text-red-400'
            }`}
          >
            {data.health_status}
          </span>
        )}
      </div>

      <div className="space-y-4">
        {displayChannels.map((ch) => (
          <ChannelBar key={ch.id} channel={ch} />
        ))}
      </div>

      {data?.xrun && (
        <p className="text-xs text-slate-500 mt-4">
          XRUNs: {data.xrun.total}
          {data.xrun.rate_per_minute !== undefined &&
            ` · ${data.xrun.rate_per_minute.toFixed(1)}/min`}
        </p>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// LogViewer
// ---------------------------------------------------------------------------

/**
 * Terminal-style log viewer that polls journalctl output for a systemd service.
 * Includes a dropdown to pick from all known Orpheus services.
 */
export function LogViewer() {
  const [selectedService, setSelectedService] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['service-logs', selectedService],
    queryFn: () => fetchServiceLogs(selectedService),
    refetchInterval: POLLING_INTERVALS.REALTIME,
    enabled: selectedService !== '',
  })

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [data?.lines])

  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <CardHeader title="Service Logs" icon={Terminal} iconColor="blue" />
        <select
          value={selectedService}
          onChange={(e) => setSelectedService(e.target.value)}
          className="bg-slate-700 text-slate-200 text-xs rounded px-2 py-1.5 border border-slate-600 focus:outline-none focus:border-blue-500"
        >
          <option value="">Select a service...</option>
          {ORPHEUS_SERVICES.map((svc) => (
            <option key={svc} value={svc}>{svc}</option>
          ))}
        </select>
      </div>

      <div className="bg-black rounded-lg p-3 font-mono text-xs leading-relaxed overflow-y-auto max-h-96 min-h-48 flex-1">
        {isLoading && (
          <span className="text-slate-500 animate-pulse">Loading logs&hellip;</span>
        )}

        {error && (
          <span className="text-red-400">Failed to fetch logs: {String(error)}</span>
        )}

        {!selectedService && (
          <span className="text-slate-600">Select a service to view logs.</span>
        )}

        {selectedService && !isLoading && !error && (!data?.lines || data.lines.length === 0) && (
          <span className="text-slate-600">No log output available.</span>
        )}

        {data?.lines?.map((line, idx) => (
          <div key={idx} className="text-green-300 whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DiagnosticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Diagnostics"
        description="Audio system health and service log viewer"
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AudioHealthPanel />
        <LogViewer />
      </div>
    </div>
  )
}
