/**
 * Dashboard: the Service Status card renders whatever inventory the backend
 * returns (dashboard.services), and no card claims a state it was not given.
 *
 * Regression: after the NATS / audio-output upgrade the page showed the retired
 * orpheus-mqtt and orpheus-bluetooth-autoconnect, said nothing about why, hard-
 * coded "Bird Detection" and "Camera Feeds" as running, and promised MQTT live
 * updates that were never implemented.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

const mockUseQuery = vi.fn()
vi.mock('@tanstack/react-query', () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}))

import Dashboard from '../src/pages/Dashboard'

type Svc = { name: string; status: string; reason: string }

function withData(services: Svc[], video = { running: true, camera_count: 4 }) {
  const byKey: Record<string, unknown> = {
    health: { status: 'ok', cpu_percent: 10, memory_percent: 50, disk_percent: 70, uptime_seconds: 60 },
    services: { services },
    'audio-diagnostics': { running: true, channels: [{ id: '1', active: true }] },
    'video-diagnostics': video,
  }
  mockUseQuery.mockImplementation(({ queryKey }: { queryKey: string[] }) => ({
    data: byKey[queryKey[0]],
    isLoading: false,
    error: null,
  }))
  return render(
    <BrowserRouter>
      <Dashboard />
    </BrowserRouter>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('Dashboard service inventory', () => {
  it('lists exactly the services the backend returns, in order', () => {
    withData([
      { name: 'orpheus-backplane', status: 'running', reason: '' },
      { name: 'orpheus-audio-output', status: 'running', reason: '' },
      { name: 'orpheus-agent-bird-detection', status: 'running', reason: '' },
    ])
    const names = screen.getAllByText(/^orpheus-/).map((el) => el.textContent)
    expect(names).toEqual(['orpheus-backplane', 'orpheus-audio-output', 'orpheus-agent-bird-detection'])
    expect(screen.queryByText('orpheus-mqtt')).toBeNull()
    expect(screen.queryByText('orpheus-bluetooth-autoconnect')).toBeNull()
  })

  it('shows the reason for a stale entry', () => {
    const reason =
      'orpheus-bluetooth-autoconnect.service is not installed. Remove it from dashboard.services.'
    withData([{ name: 'orpheus-bluetooth-autoconnect', status: 'unknown', reason }])
    expect(screen.getByText(reason)).toBeInTheDocument()
  })

  it('takes Bird Detection from the configured inventory, not a constant', () => {
    withData([{ name: 'orpheus-agent-bird-detection', status: 'stopped', reason: 'failed' }])
    expect(screen.queryByText('BirdNET running')).toBeNull()
    expect(screen.getAllByText('stopped').length).toBeGreaterThan(0)
  })

  it('omits Bird Detection when the agent is not in the inventory', () => {
    withData([{ name: 'orpheus-backplane', status: 'running', reason: '' }])
    expect(screen.queryByText('Bird Detection')).toBeNull()
  })

  it('reports the cameras video-motion actually sees', () => {
    withData([], { running: true, camera_count: 2 })
    expect(screen.getAllByText('2 cameras').length).toBeGreaterThan(0)
    expect(screen.queryByText('4 cameras')).toBeNull()
  })

  it('does not promise live MQTT updates', () => {
    withData([])
    expect(screen.queryByText(/Connect to MQTT/)).toBeNull()
    expect(screen.queryByText(/Real-time detection events will appear here/)).toBeNull()
  })
})
