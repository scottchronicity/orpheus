/** Kiosk GPU telemetry: one compact line at 800×480, a row in the Station panel. */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SystemPanel, SystemStrip } from '../src/kiosk/KioskPanels'
import type { KioskHealth } from '../src/kiosk/kioskApi'

const base: KioskHealth = { status: 'ok', cpu_percent: 44, memory_percent: 53, disk_percent: 81, uptime_seconds: 60 }
const withGpu: KioskHealth = {
  ...base,
  gpu: { available: true, utilization_percent: 23.6, temperature_c: 59.4 },
}
const services = { services: [{ name: 'orpheus-ui', status: 'running' }] }

describe('kiosk GPU telemetry', () => {
  it('adds GPU load and temperature to the compact footer line', () => {
    render(<SystemStrip health={withGpu} services={services} />)
    expect(screen.getByTestId('kiosk-system').textContent).toBe('CPU 44% · Mem 53% · Disk 81% · GPU 24% 59 °C · 1/1 services')
  })

  it('adds a GPU row with its temperature to the Station panel, without a new line', () => {
    render(<SystemPanel health={withGpu} services={services} />)
    expect(screen.getByText('GPU 59°C')).toBeInTheDocument()
    expect(screen.getByText('24%')).toBeInTheDocument()
  })

  it.each([
    ['an older station without GPU telemetry', base],
    ['a host without a GPU', { ...base, gpu: { available: false } }],
  ])('leaves GPU out on %s', (_label, health) => {
    render(<SystemStrip health={health} services={services} />)
    expect(screen.getByTestId('kiosk-system').textContent).not.toContain('GPU')
  })
})
