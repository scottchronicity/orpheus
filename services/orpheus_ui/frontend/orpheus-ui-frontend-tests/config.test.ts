/**
 * Tests for frontend configuration constants.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import {
  AUDIO_CHANNEL_IDS,
  CAMERA_IDS,
  POLLING_INTERVALS,
  derivePollingIntervals,
  applyPollInterval,
  loadServedPollInterval,
  CONFIG_FETCH_TIMEOUT_MS,
  type AudioChannelId,
  type CameraId,
} from '../src/config'

describe('config', () => {
  describe('AUDIO_CHANNEL_IDS', () => {
    it('should have 4 audio channels', () => {
      expect(AUDIO_CHANNEL_IDS).toHaveLength(4)
    })

    it('should contain channel IDs 1-4', () => {
      expect(AUDIO_CHANNEL_IDS).toContain('1')
      expect(AUDIO_CHANNEL_IDS).toContain('2')
      expect(AUDIO_CHANNEL_IDS).toContain('3')
      expect(AUDIO_CHANNEL_IDS).toContain('4')
    })

    it('should be readonly', () => {
      // TypeScript ensures this at compile time, but we verify the values are strings
      AUDIO_CHANNEL_IDS.forEach((id) => {
        expect(typeof id).toBe('string')
      })
    })
  })

  describe('CAMERA_IDS', () => {
    it('should have 4 cameras', () => {
      expect(CAMERA_IDS).toHaveLength(4)
    })

    it('should contain orpheus-eye-1 through orpheus-eye-4', () => {
      expect(CAMERA_IDS).toContain('orpheus-eye-1')
      expect(CAMERA_IDS).toContain('orpheus-eye-2')
      expect(CAMERA_IDS).toContain('orpheus-eye-3')
      expect(CAMERA_IDS).toContain('orpheus-eye-4')
    })

    it('should follow naming convention', () => {
      CAMERA_IDS.forEach((id) => {
        expect(id).toMatch(/^orpheus-eye-\d+$/)
      })
    })
  })

  describe('POLLING_INTERVALS', () => {
    it('should have reasonable realtime interval', () => {
      expect(POLLING_INTERVALS.REALTIME).toBe(5000)
      expect(POLLING_INTERVALS.REALTIME).toBeLessThanOrEqual(10000)
    })

    it('should have cameras interval >= realtime', () => {
      expect(POLLING_INTERVALS.CAMERAS).toBeGreaterThanOrEqual(POLLING_INTERVALS.REALTIME)
    })

    it('should have history interval >= health interval', () => {
      expect(POLLING_INTERVALS.HISTORY).toBeGreaterThanOrEqual(POLLING_INTERVALS.HEALTH)
    })

    it('should have all intervals in milliseconds (> 1000)', () => {
      Object.values(POLLING_INTERVALS).forEach((interval) => {
        expect(interval).toBeGreaterThanOrEqual(1000)
      })
    })
  })

  describe('derivePollingIntervals', () => {
    it('returns the hardcoded defaults when no base is provided', () => {
      expect(derivePollingIntervals()).toEqual({
        REALTIME: 5000,
        CAMERAS: 10000,
        HEALTH: 10000,
        HISTORY: 30000,
        MEDIA: 60000,
      })
    })

    it.each([null, undefined, 0, -1, NaN, Infinity])(
      'falls back to defaults for invalid base %p',
      (bad) => {
        expect(derivePollingIntervals(bad as number)).toEqual({
          REALTIME: 5000,
          CAMERAS: 10000,
          HEALTH: 10000,
          HISTORY: 30000,
          MEDIA: 60000,
        })
      },
    )

    it('scales every tier proportionally from the served base', () => {
      // Base 1000ms is 1/5 of the 5000ms default → every tier is 1/5.
      expect(derivePollingIntervals(1000)).toEqual({
        REALTIME: 1000,
        CAMERAS: 2000,
        HEALTH: 2000,
        HISTORY: 6000,
        MEDIA: 12000,
      })
    })

    it('clamps a units-confused tiny base (poll_interval: 5 "seconds") to 1s and warns', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      try {
        // 5ms would be a request storm; the clamp floors the base at 1000ms.
        expect(derivePollingIntervals(5)).toEqual({
          REALTIME: 1000,
          CAMERAS: 2000,
          HEALTH: 2000,
          HISTORY: 6000,
          MEDIA: 12000,
        })
        expect(warn).toHaveBeenCalledOnce()
        expect(warn.mock.calls[0][0]).toContain('clamped')
      } finally {
        warn.mockRestore()
      }
    })

    it('clamps an absurdly large base to 10 minutes and warns', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      try {
        expect(derivePollingIntervals(10_000_000).REALTIME).toBe(600_000)
        expect(warn).toHaveBeenCalledOnce()
      } finally {
        warn.mockRestore()
      }
    })

    it('does not warn for an in-range base', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      try {
        derivePollingIntervals(5000)
        expect(warn).not.toHaveBeenCalled()
      } finally {
        warn.mockRestore()
      }
    })
  })

  describe('applyPollInterval', () => {
    afterEach(() => {
      // Restore module-level defaults so other suites see the baseline.
      applyPollInterval(5000)
    })

    it('mutates the live POLLING_INTERVALS in place', () => {
      applyPollInterval(2500)
      expect(POLLING_INTERVALS.REALTIME).toBe(2500)
      expect(POLLING_INTERVALS.HISTORY).toBe(15000)
    })

    it('is a no-op (keeps defaults) for an invalid value', () => {
      applyPollInterval(undefined)
      expect(POLLING_INTERVALS.REALTIME).toBe(5000)
      expect(POLLING_INTERVALS.HISTORY).toBe(30000)
    })
  })

  describe('loadServedPollInterval', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
      // Restore module-level defaults so other suites see the baseline.
      applyPollInterval(5000)
    })

    it('fetches /api/config with an abort deadline and applies poll_interval', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ poll_interval: 2000 }),
      })
      vi.stubGlobal('fetch', fetchMock)

      await loadServedPollInterval()

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/config',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      )
      expect(POLLING_INTERVALS.REALTIME).toBe(2000)
    })

    it('keeps the defaults and warns when the fetch rejects (incl. timeout AbortError)', async () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
      vi.stubGlobal(
        'fetch',
        vi.fn().mockRejectedValue(new DOMException('The operation timed out.', 'TimeoutError')),
      )

      // Must resolve (never throw) — the app renders with defaults on failure.
      await expect(loadServedPollInterval()).resolves.toBeUndefined()

      expect(POLLING_INTERVALS.REALTIME).toBe(5000)
      expect(warn).toHaveBeenCalledOnce()
    })

    it('keeps the defaults on a non-OK response', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }))

      await loadServedPollInterval()

      expect(POLLING_INTERVALS.REALTIME).toBe(5000)
    })

    it('exposes a sane bootstrap deadline (short enough not to strand a blank page)', () => {
      expect(CONFIG_FETCH_TIMEOUT_MS).toBeGreaterThan(0)
      expect(CONFIG_FETCH_TIMEOUT_MS).toBeLessThanOrEqual(10_000)
    })
  })

  describe('type exports', () => {
    it('AudioChannelId type should accept valid channel IDs', () => {
      const validId: AudioChannelId = '1'
      expect(AUDIO_CHANNEL_IDS).toContain(validId)
    })

    it('CameraId type should accept valid camera IDs', () => {
      const validId: CameraId = 'orpheus-eye-1'
      expect(CAMERA_IDS).toContain(validId)
    })
  })
})
