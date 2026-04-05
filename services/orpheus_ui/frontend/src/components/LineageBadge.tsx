/**
 * LineageBadge component for displaying detection event lineage (source tracing).
 *
 * Shows a stylised label with the truncated `source_event_id`, allowing users to
 * trace a detection back to the event that originally triggered it in the pipeline
 * (e.g. audio-motion → bird-detection → crow-analysis).
 *
 * @example
 * ```tsx
 * <LineageBadge source_event_id="abc-123-def" type="audio" />
 * ```
 */
import { GitBranch } from 'lucide-react'

/** Props for {@link LineageBadge}. */
export interface LineageBadgeProps {
  /** The UUID of the upstream event that produced this detection. */
  source_event_id?: string
  /** The detection type, used to tint the badge colour. */
  type?: 'audio' | 'video'
}

/**
 * Renders a compact lineage badge showing a truncated source event ID.
 *
 * - Displays a GitBranch icon followed by the first 8 characters of the ID.
 * - A `title` attribute shows the full ID on hover.
 * - Returns `null` when `source_event_id` is undefined or empty.
 */
export function LineageBadge({ source_event_id, type }: LineageBadgeProps) {
  if (!source_event_id) return null

  const colorClass = type === 'video' ? 'text-purple-400' : 'text-cyan-400'
  const truncated = source_event_id.length > 8
    ? `${source_event_id.slice(0, 8)}…`
    : source_event_id

  return (
    <span
      className={`inline-flex items-center gap-1 ${colorClass}`}
      title={`Source Event: ${source_event_id}`}
      data-testid="lineage-badge"
    >
      <GitBranch className="w-3.5 h-3.5" />
      <span className="text-xs font-mono">{truncated}</span>
    </span>
  )
}
