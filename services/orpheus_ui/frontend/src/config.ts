/**
 * Frontend configuration constants.
 * 
 * These values match the Orpheus system configuration.
 * In the future, these could be fetched from the backend API.
 */

/**
 * Audio channel IDs used in the system.
 * Corresponds to the 4-channel audio input on the Jetson.
 */
export const AUDIO_CHANNEL_IDS = ['1', '2', '3', '4'] as const

/**
 * Camera IDs used in the system.
 * Corresponds to the configured IP cameras.
 */
export const CAMERA_IDS = [
  'orpheus-eye-1',
  'orpheus-eye-2', 
  'orpheus-eye-3',
  'orpheus-eye-4',
] as const

/**
 * API polling intervals in milliseconds.
 */
export const POLLING_INTERVALS = {
  /** Real-time data like detections */
  REALTIME: 5000,
  /** Camera snapshots and status */
  CAMERAS: 10000,
  /** System health metrics */
  HEALTH: 10000,
  /** Historical data like bird/crow stats */
  HISTORY: 30000,
  /** Historical media (snapshots and timelapses) */
  MEDIA: 60000,
} as const

/**
 * Type helpers for the config values.
 */
export type AudioChannelId = typeof AUDIO_CHANNEL_IDS[number]
export type CameraId = typeof CAMERA_IDS[number]
