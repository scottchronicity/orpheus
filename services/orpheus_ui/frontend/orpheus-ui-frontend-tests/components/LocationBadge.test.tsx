/**
 * Unit tests for LocationBadge component.
 *
 * Verifies:
 * - Renders sensor ID and MapPin icon with valid context
 * - Tooltip shows full lat/lon/elevation coordinates
 * - Returns null for undefined context
 * - Returns null for empty context (no sensor_id, no coords)
 * - Falls back to coordinates when sensor_id is missing
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LocationBadge } from '../../src/components/LocationBadge'

describe('LocationBadge', () => {
  it('renders sensor_id with valid context', () => {
    const { container } = render(
      <LocationBadge
        context={{
          lat: 40.7128,
          lon: -74.006,
          sensor_id: 'mic-1',
          timestamp: '2025-01-01T00:00:00Z',
        }}
      />
    )

    const badge = screen.getByTestId('location-badge')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('mic-1')
    // Tooltip shows full coordinates
    expect(badge.getAttribute('title')).toContain('Lat: 40.712800')
    expect(badge.getAttribute('title')).toContain('Lon: -74.006000')
    expect(badge.getAttribute('title')).toContain('Sensor: mic-1')
    // MapPin icon is rendered (svg element)
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('shows elevation in tooltip when present', () => {
    render(
      <LocationBadge
        context={{
          lat: 40.7128,
          lon: -74.006,
          elevation: 10.5,
          sensor_id: 'mic-1',
        }}
      />
    )

    const badge = screen.getByTestId('location-badge')
    expect(badge.getAttribute('title')).toContain('Elev: 10.5m')
  })

  it('returns null for undefined context', () => {
    const { container } = render(<LocationBadge context={undefined} />)
    expect(container.innerHTML).toBe('')
  })

  it('returns null for empty context (no sensor_id, no coords)', () => {
    const { container } = render(<LocationBadge context={{}} />)
    expect(container.innerHTML).toBe('')
  })

  it('falls back to coordinates when sensor_id is missing', () => {
    render(
      <LocationBadge
        context={{ lat: 40.7128, lon: -74.006 }}
      />
    )

    const badge = screen.getByTestId('location-badge')
    expect(badge).toHaveTextContent('40.71,-74.01')
  })

  it('renders with only sensor_id (no coords)', () => {
    render(
      <LocationBadge
        context={{ sensor_id: 'mic-2' }}
      />
    )

    const badge = screen.getByTestId('location-badge')
    expect(badge).toHaveTextContent('mic-2')
    expect(badge.getAttribute('title')).toBe('Sensor: mic-2')
  })
})
