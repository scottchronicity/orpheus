/**
 * AudioPlaybackControl - Request audio playback via MQTT
 * 
 * Allows users to select a sound from the registry and request playback
 * with configurable repeat count and pause between repetitions.
 */
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Play, Volume2, RefreshCw } from 'lucide-react'
import { fetchWithAuth } from '../lib/utils'
import { fetchJson } from '../lib/api'
import { Card, CardHeader } from './ui'

interface SoundsResponse {
  sounds: string[]
  count: number
}

interface PlaybackRequest {
  sound_name: string
  repeat_count: number
  pause_between: number
}

interface PlaybackResponse {
  success: boolean
  message: string
}

export function AudioPlaybackControl() {
  const [selectedSound, setSelectedSound] = useState<string>('')
  const [repeatCount, setRepeatCount] = useState<number>(1)
  const [pauseBetween, setPauseBetween] = useState<number>(0)

  // Fetch available sounds
  const { data: soundsData, isLoading, error, refetch } = useQuery<SoundsResponse>({
    queryKey: ['playback-sounds'],
    queryFn: () => fetchJson<SoundsResponse>('/api/audio/playback/sounds'),
  })

  // Playback mutation
  const playMutation = useMutation<PlaybackResponse, Error, PlaybackRequest>({
    mutationFn: async (request) => {
      const res = await fetchWithAuth('/api/audio/playback/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })
      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Playback request failed')
      }
      return res.json()
    },
  })

  const handlePlay = () => {
    if (!selectedSound) return

    playMutation.mutate({
      sound_name: selectedSound,
      repeat_count: repeatCount,
      pause_between: pauseBetween,
    })
  }

  if (error) {
    return (
      <Card>
        <CardHeader title="Audio Playback" icon={Volume2} iconColor="purple" />
        <div className="text-center py-4">
          <p className="text-red-400 mb-2">Failed to load sounds</p>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded flex items-center gap-2 mx-auto"
          >
            <RefreshCw className="w-4 h-4" />
            Retry
          </button>
        </div>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader title="Audio Playback" icon={Volume2} iconColor="purple" />
      
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-purple-500" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Sound Selection */}
          <div>
            <label className="block text-sm text-slate-400 mb-2">Select Sound</label>
            <select
              value={selectedSound}
              onChange={(e) => setSelectedSound(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              <option value="">-- Select a sound --</option>
              {soundsData?.sounds.map((sound) => (
                <option key={sound} value={sound}>
                  {sound}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 mt-1">
              {soundsData?.count || 0} sounds available
            </p>
          </div>

          {/* Repeat Count */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-slate-400 mb-2">Repeat Count</label>
              <input
                type="number"
                min={1}
                max={10}
                value={repeatCount}
                onChange={(e) => setRepeatCount(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-2">Pause Between (s)</label>
              <input
                type="number"
                min={0}
                max={60}
                step={0.5}
                value={pauseBetween}
                onChange={(e) => setPauseBetween(Math.max(0, parseFloat(e.target.value) || 0))}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
          </div>

          {/* Play Button */}
          <button
            onClick={handlePlay}
            disabled={!selectedSound || playMutation.isPending}
            className={`w-full py-3 rounded-lg flex items-center justify-center gap-2 transition-colors ${
              !selectedSound || playMutation.isPending
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-purple-600 hover:bg-purple-700 text-white'
            }`}
          >
            {playMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                Sending...
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                Play Sound
              </>
            )}
          </button>

          {/* Status Messages */}
          {playMutation.isSuccess && (
            <div className="p-3 bg-green-500/20 border border-green-500/30 rounded text-green-400 text-sm">
              {playMutation.data.message}
            </div>
          )}
          {playMutation.isError && (
            <div className="p-3 bg-red-500/20 border border-red-500/30 rounded text-red-400 text-sm">
              {playMutation.error.message}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
