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

function withData(services: Svc[], video = { running: true, camera_count: 4 }, gpu?: unknown) {
  const byKey: Record<string, unknown> = {
    health: { status: 'ok', cpu_percent: 10, memory_percent: 50, disk_percent: 70, uptime_seconds: 60, gpu },
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

const GiB = 1024 ** 3

describe('Dashboard GPU card', () => {
  it('shows utilization, temperature and the shared memory the worker uses', () => {
    withData([], undefined, {
      available: true,
      utilization_percent: 23.6,
      temperature_c: 59.4,
      memory: {
        shared: true,
        total_bytes: 15.1 * GiB,
        available_bytes: 6.8 * GiB,
        inference_reserved_bytes: 2.0 * GiB,
        inference_allocated_bytes: 0.3 * GiB,
        inference_floor_bytes: 3.7 * GiB,
      },
    })
    expect(screen.getByText('GPU')).toBeInTheDocument()
    expect(screen.getByText('24')).toBeInTheDocument()
    expect(screen.getByText('59')).toBeInTheDocument()
    expect(screen.getByText('Shared memory (CPU + GPU)')).toBeInTheDocument()
    expect(screen.getByText('6.8 GiB')).toBeInTheDocument()
    expect(screen.getByText('PANNs worker: 2.0 GiB CUDA (0.3 GiB in use)')).toBeInTheDocument()
    expect(screen.getByText('Worker pauses below 3.7 GiB free')).toBeInTheDocument()
    expect(screen.queryByText(/VRAM/)).toBeNull()
  })

  it('is hidden on a host without a GPU', () => {
    withData([], undefined, { available: false })
    expect(screen.queryByText('Shared memory (CPU + GPU)')).toBeNull()
  })
})
