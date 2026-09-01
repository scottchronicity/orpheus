/**
 * Tests for the scatter-chart X-axis domain helper.
 *
 * Pins the fix for the "right side of the scatter is an empty future gap":
 * the axis upper bound must be clamped to `now`, never the end of the
 * (future) end-date.
 */
import { describe, it, expect } from 'vitest'

import { scatterXDomain } from '../src/components/chartDomain'

describe('scatterXDomain', () => {
  const start = new Date('2026-06-03T00:00:00').getTime()

  it('clamps the upper bound to now when the range extends into the future', () => {
    const now = new Date('2026-06-04T15:00:00').getTime()
    const [lo, hi] = scatterXDomain('2026-06-03', '2026-06-04', now)
    expect(lo).toBe(start)
    // not the end-of-day 2026-06-04T23:59:59 (which is hours in the future)
    expect(hi).toBe(now)
  })

  it('keeps the full end-of-day when the range is entirely in the past', () => {
    const now = new Date('2026-06-10T00:00:00').getTime()
    const [, hi] = scatterXDomain('2026-06-03', '2026-06-04', now)
    expect(hi).toBe(new Date('2026-06-04T23:59:59').getTime())
  })

  it('never collapses the upper bound below the start', () => {
    const now = new Date('2026-06-01T00:00:00').getTime() // before the range
    const [lo, hi] = scatterXDomain('2026-06-03', '2026-06-04', now)
    expect(hi).toBe(lo)
  })

  it('returns auto when dates are missing', () => {
    expect(scatterXDomain(undefined, undefined)).toEqual(['auto', 'auto'])
    expect(scatterXDomain('2026-06-03', undefined)).toEqual(['auto', 'auto'])
  })
})
