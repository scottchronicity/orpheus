/**
 * Tests for the storage-trend formatting helpers (free size + days-until-full).
 */
import { describe, it, expect } from 'vitest'

import { formatBytes, formatDaysUntilFull } from '../src/lib/utils'

const GIB = 1024 ** 3

describe('formatBytes', () => {
  it('labels binary units as binary units', () => {
    // It divides by 1024, so it has to say KiB. Printing "GB" made the storage
    // panel disagree with every decimal-GB figure it was reconciled against.
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KiB')
    expect(formatBytes(5 * GIB)).toBe('5.0 GiB')
    expect(formatBytes(2 * 1024 ** 4)).toBe('2.0 TiB')
  })

  it('handles missing values', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(NaN)).toBe('—')
  })

  it('respects the decimals argument', () => {
    expect(formatBytes(1536, 0)).toBe('2 KiB')
    expect(formatBytes(1536, 2)).toBe('1.50 KiB')
  })
})

describe('formatDaysUntilFull', () => {
  it('formats day ranges', () => {
    expect(formatDaysUntilFull(0.5)).toBe('< 1 day')
    expect(formatDaysUntilFull(42)).toBe('42 days')
    expect(formatDaysUntilFull(400)).toBe('1.1 yr')
  })

  it('returns em dash when there is no projection', () => {
    expect(formatDaysUntilFull(null)).toBe('—')
    expect(formatDaysUntilFull(undefined)).toBe('—')
  })
})
