/**
 * LocationBadge component for displaying spatiotemporal context from V2 Detection events.
 *
 * Renders a MapPin icon alongside the sensor ID. A tooltip provides full GPS coordinates
 * (latitude, longitude, elevation) when available. Gracefully handles `undefined` or
 * partially missing context by rendering nothing.
 *
 * @example
 * ```tsx
 * <LocationBadge context={{ lat: 40.7128, lon: -74.006, sensor_id: 'mic-1', timestamp: '...' }} />
 * ```
 */
import { MapPin } from 'lucide-react'

/**
 * Spatiotemporal context attached to a V2 Detection event.
 *
 * Fields may be undefined if the originating agent did not have GPS data available.
 */
export interface SpatiotemporalContext {
  /** Latitude in decimal degrees (WGS-84). */
  lat?: number
  /** Longitude in decimal degrees (WGS-84). */
  lon?: number
  /** Elevation in metres above sea level. */
  elevation?: number
  /** Identifier of the sensor that captured the event (e.g. "mic-1"). */
  sensor_id?: string
  /** ISO-8601 timestamp of the GPS fix. */
  timestamp?: string
}

/** Props for {@link LocationBadge}. */
export interface LocationBadgeProps {
  /** The spatiotemporal context from a Detection event. May be undefined. */
  context?: SpatiotemporalContext
}

/**
 * Displays a compact location indicator for a detection event.
 *
 * - Shows a MapPin icon with the `sensor_id` as label text.
 * - A `title` attribute exposes full lat/lon/elevation on hover.
 * - Returns `null` when `context` is undefined or has no displayable data.
 */
export function LocationBadge({ context }: LocationBadgeProps) {
  if (!context) return null

  const hasSensor = !!context.sensor_id
  const hasCoords = context.lat != null && context.lon != null

  if (!hasSensor && !hasCoords) return null

  const tooltipParts: string[] = []
  if (hasCoords) {
    tooltipParts.push(`Lat: ${context.lat!.toFixed(6)}, Lon: ${context.lon!.toFixed(6)}`)
  }
  if (context.elevation != null) {
    tooltipParts.push(`Elev: ${context.elevation.toFixed(1)}m`)
  }
  if (context.sensor_id) {
    tooltipParts.push(`Sensor: ${context.sensor_id}`)
  }

  return (
    <span
      className="inline-flex items-center gap-1 text-blue-400"
      title={tooltipParts.join(' | ')}
      data-testid="location-badge"
    >
      <MapPin className="w-3.5 h-3.5" />
      <span className="text-xs">{context.sensor_id ?? `${context.lat!.toFixed(2)},${context.lon!.toFixed(2)}`}</span>
    </span>
  )
}
