/**
 * Tests for ClipActions' clip-availability handling.
 *
 * The Entity/Detection DB outlives the on-disk audio (clips roll off after
 * the retention size cap). The backend now sends a preemptive
 * ``clip_available`` flag on entity evidence so the UI can render a
 * "Clip expired" state WITHOUT firing a doomed Play/Download request.
 * Callers that don't pass the prop (recent-detection rows) keep the
 * existing probe-on-error fallback, so the prop is purely additive.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ClipActions } from '../src/components/ClipActions'

const CLIP = '/data/orpheus/audio/audio_motion/2/20260609T110024.flac'

describe('ClipActions clip-availability', () => {
  it('renders "Clip expired" and no Play/Download when clipAvailable is false', () => {
    render(<ClipActions clipPath={CLIP} channelId="2" clipAvailable={false} />)
    expect(screen.getByText(/clip expired/i)).toBeInTheDocument()
    expect(screen.queryByTitle('Play')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Download')).not.toBeInTheDocument()
  })

  it('renders Play + Download when clipAvailable is true', () => {
    render(<ClipActions clipPath={CLIP} channelId="2" clipAvailable={true} />)
    expect(screen.getByTitle('Play')).toBeInTheDocument()
    expect(screen.getByTitle('Download')).toBeInTheDocument()
    expect(screen.queryByText(/clip expired/i)).not.toBeInTheDocument()
  })

  it('renders Play + Download when clipAvailable is undefined (legacy callers)', () => {
    render(<ClipActions clipPath={CLIP} channelId="2" />)
    expect(screen.getByTitle('Play')).toBeInTheDocument()
    expect(screen.getByTitle('Download')).toBeInTheDocument()
  })

  it('renders "No clip" when there is no clip path, regardless of clipAvailable', () => {
    render(<ClipActions clipPath={null} clipAvailable={false} />)
    expect(screen.getByText(/no clip/i)).toBeInTheDocument()
    expect(screen.queryByText(/clip expired/i)).not.toBeInTheDocument()
  })
})
