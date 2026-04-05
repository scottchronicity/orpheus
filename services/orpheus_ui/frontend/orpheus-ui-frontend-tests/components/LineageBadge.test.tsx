/**
 * Unit tests for LineageBadge component.
 *
 * Verifies:
 * - Renders truncated source event ID
 * - Tooltip shows full ID
 * - Returns null for undefined source_event_id
 * - Returns null for empty string source_event_id
 * - Applies correct colour based on detection type
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LineageBadge } from '../../src/components/LineageBadge'

describe('LineageBadge', () => {
  it('renders truncated source event ID', () => {
    render(
      <LineageBadge source_event_id="abcdef12-3456-7890-abcd-ef1234567890" type="audio" />
    )

    const badge = screen.getByTestId('lineage-badge')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('abcdef12…')
    expect(badge.getAttribute('title')).toBe('Source Event: abcdef12-3456-7890-abcd-ef1234567890')
  })

  it('renders short IDs without truncation', () => {
    render(<LineageBadge source_event_id="short" type="audio" />)

    const badge = screen.getByTestId('lineage-badge')
    expect(badge).toHaveTextContent('short')
  })

  it('returns null for undefined source_event_id', () => {
    const { container } = render(<LineageBadge source_event_id={undefined} />)
    expect(container.innerHTML).toBe('')
  })

  it('returns null for empty string source_event_id', () => {
    const { container } = render(<LineageBadge source_event_id="" />)
    expect(container.innerHTML).toBe('')
  })

  it('applies cyan colour for audio type', () => {
    render(<LineageBadge source_event_id="test-id-1234" type="audio" />)
    const badge = screen.getByTestId('lineage-badge')
    expect(badge.className).toContain('text-cyan-400')
  })

  it('applies purple colour for video type', () => {
    render(<LineageBadge source_event_id="test-id-1234" type="video" />)
    const badge = screen.getByTestId('lineage-badge')
    expect(badge.className).toContain('text-purple-400')
  })
})
