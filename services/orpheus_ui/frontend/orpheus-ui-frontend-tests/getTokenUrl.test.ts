import { describe, it, expect, beforeEach } from 'vitest'
import { getTokenUrl, setToken, removeToken } from '../src/lib/utils'

// The return value becomes the ``src`` of an <audio> element and the ``href``
// of a download link, so a value carrying its own scheme would execute on click.
describe('getTokenUrl', () => {
  beforeEach(() => {
    removeToken()
  })

  it('returns a same-origin path unchanged when there is no token', () => {
    expect(getTokenUrl('/api/diagnostics/audio/clips/1/x.flac')).toBe(
      '/api/diagnostics/audio/clips/1/x.flac',
    )
  })

  it('appends the token as a query parameter', () => {
    setToken('abc123')
    expect(getTokenUrl('/api/clip.flac')).toBe('/api/clip.flac?token=abc123')
  })

  it('appends the token to a path that already has a query', () => {
    setToken('abc123')
    const url = getTokenUrl('/api/clip.flac?download=1')
    expect(url).toContain('download=1')
    expect(url).toContain('token=abc123')
  })

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
  ])('refuses a path carrying its own scheme: %s', (hostile) => {
    expect(() => getTokenUrl(hostile)).toThrow()
  })

  it('refuses a protocol-relative path that would go cross-origin', () => {
    expect(() => getTokenUrl('//evil.example.com/clip.flac')).toThrow()
  })

  it('refuses an absolute URL on another origin', () => {
    expect(() => getTokenUrl('https://evil.example.com/clip.flac')).toThrow()
  })

  it('does not leak the token into a thrown message', () => {
    setToken('super-secret-token')
    try {
      getTokenUrl('javascript:alert(1)')
    } catch (e) {
      expect(String(e)).not.toContain('super-secret-token')
    }
  })
})
