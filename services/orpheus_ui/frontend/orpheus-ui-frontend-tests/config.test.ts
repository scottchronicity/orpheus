/**
 * Tests for frontend configuration constants.
 */
import { describe, it, expect } from 'vitest'
import { 
  AUDIO_CHANNEL_IDS, 
  CAMERA_IDS, 
  POLLING_INTERVALS,
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
