/**
 * Tests for utility functions.
 * 
 * These tests verify utility functions work correctly in isolation.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { cn, fetchWithAuth, formatDateTime } from '../src/lib/utils'

describe('cn (class name utility)', () => {
  it('merges multiple class names', () => {
    const result = cn('foo', 'bar', 'baz')
    expect(result).toBe('foo bar baz')
  })

  it('handles conditional classes', () => {
    const isActive = true
    const isHidden = false
    const result = cn('base', isActive && 'active', isHidden && 'hidden')
    expect(result).toContain('base')
    expect(result).toContain('active')
    expect(result).not.toContain('hidden')
  })

  it('merges conflicting Tailwind classes (last wins)', () => {
    // tailwind-merge deduplicates conflicting utilities
    const result = cn('px-2', 'px-4')
    expect(result).toBe('px-4')
  })

  it('handles undefined and null gracefully', () => {
    const result = cn('foo', undefined, null, 'bar')
    expect(result).toBe('foo bar')
  })

  it('handles empty strings', () => {
    const result = cn('foo', '', 'bar')
    expect(result).toBe('foo bar')
  })

  it('handles arrays of classes', () => {
    const result = cn(['foo', 'bar'])
    expect(result).toContain('foo')
    expect(result).toContain('bar')
  })
})

describe('fetchWithAuth', () => {
  let mockFetch: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockFetch = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', mockFetch)
  })

  it('adds Authorization header when token exists in localStorage', async () => {
    localStorage.setItem('orpheus_token', 'test-jwt-token')
    
    await fetchWithAuth('/api/health')

    // Headers is a Headers object, so we need to check the actual call
    const callArgs = mockFetch.mock.calls[0]
    const headers = callArgs[1]?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer test-jwt-token')
  })

  it('omits Authorization header when no token', async () => {
    await fetchWithAuth('/api/public')

    const callArgs = mockFetch.mock.calls[0]
    const headers = callArgs[1]?.headers as Record<string, string> | undefined
    expect(headers?.Authorization).toBeUndefined()
  })

  it('preserves custom headers from options', async () => {
    localStorage.setItem('orpheus_token', 'test-token')
    
    await fetchWithAuth('/api/data', {
      headers: { 'Content-Type': 'application/json' },
    })

    // Headers is a Headers object
    const callArgs = mockFetch.mock.calls[0]
    const headers = callArgs[1]?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer test-token')
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('passes through fetch options (method, body, etc.)', async () => {
    const body = JSON.stringify({ test: true })
    
    await fetchWithAuth('/api/data', {
      method: 'POST',
      body,
    })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/data',
      expect.objectContaining({
        method: 'POST',
        body,
      })
    )
  })

  it('returns the fetch response', async () => {
    const mockResponse = new Response('{"status": "ok"}')
    mockFetch.mockResolvedValueOnce(mockResponse)

    const result = await fetchWithAuth('/api/test')
    
    expect(result).toBe(mockResponse)
  })
})

describe('formatDateTime', () => {
  it('formats ISO 8601 timestamp to local time', () => {
    const isoString = '2026-01-18T10:00:00Z'
    const result = formatDateTime(isoString)
    
    // Check that result contains expected components (but not exact format due to locale)
    expect(result).toMatch(/Jan/i) // Month abbreviation
    expect(result).toMatch(/18/) // Day
    expect(result).toMatch(/2026/) // Year
    expect(result).toMatch(/\d+:\d+/) // Time with minutes
  })

  it('handles timestamps with timezone offset', () => {
    const isoString = '2026-01-18T15:30:45+05:30'
    const result = formatDateTime(isoString)
    
    // Should contain date components
    expect(result).toMatch(/2026/)
    expect(result).toMatch(/\d+:\d+/)
  })

  it('returns original string for invalid date', () => {
    const invalidString = 'not-a-date'
    const result = formatDateTime(invalidString)
    
    expect(result).toBe(invalidString)
  })

  it('returns original string for empty string', () => {
    const result = formatDateTime('')
    
    expect(result).toBe('')
  })

  it('formats time with AM/PM markers', () => {
    // Morning time
    const morningTime = '2026-01-18T08:30:00Z'
    const morningResult = formatDateTime(morningTime)
    
    // Should contain AM or PM (depending on timezone offset)
    expect(morningResult).toMatch(/AM|PM/i)
  })

  it('includes seconds in formatted output', () => {
    const isoString = '2026-01-18T10:30:45Z'
    const result = formatDateTime(isoString)
    
    // Should include seconds (45)
    expect(result).toMatch(/:\d{2}:\d{2}/) // hh:mm:ss pattern
  })
})
