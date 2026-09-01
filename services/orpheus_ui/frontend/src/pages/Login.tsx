import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import type { Location } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { UI_FLAGS } from '../config'
import { Bird, Lock, Mail, AlertCircle } from 'lucide-react'

interface LocationState {
  from?: Location
}

/**
 * Build the post-login redirect target from a ``Location`` carried in
 * ``state.from``. Returns ``"/"`` if the state is missing, malformed,
 * or attempts an open-redirect (anything not starting with a single
 * ``/``).
 *
 * Why: ``Login.tsx`` reads ``location.state.from`` and navigates the
 * user there after a successful login so bookmarked filter URLs (e.g.
 * ``/entities?species=corvus``) survive the auth bounce. But
 * ``location.state`` can carry arbitrary client-supplied data —
 * blindly concatenating ``pathname + search + hash`` would let a
 * crafted ``state.from.pathname = "//evil.example.com/"`` bounce a
 * just-authenticated user off-site. Reject anything that doesn't look
 * like a same-app path.
 */
/**
 * True iff ``pathname`` is a single-app same-origin path. Rejects:
 *   - non-absolute paths
 *   - ``//`` protocol-relative URLs
 *   - ``/\\`` backslash-shape paths (modern browsers normalize ``\``
 *     to ``/`` in URL parsing, so ``/\\evil.com`` resolves to
 *     ``//evil.com``)
 *   - control characters / tab / newline (browsers strip these from
 *     URLs, which can also collapse a leading ``/`` into a protocol-
 *     relative form)
 */
function isSameOriginPath(pathname: string): boolean {
  if (!pathname.startsWith('/')) return false
  if (pathname.startsWith('//')) return false
  if (pathname.startsWith('/\\')) return false
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\s\\]/.test(pathname.slice(0, 4))) return false
  return true
}

function safeFromTarget(
  fromState: Location | undefined,
  nextParam: string | null,
): string {
  if (fromState) {
    const pathname = fromState.pathname ?? '/'
    if (isSameOriginPath(pathname)) {
      return `${pathname}${fromState.search ?? ''}${fromState.hash ?? ''}`
    }
  }
  // Fallback: ``?next=`` carries the original URL when fetchWithAuth
  // had to do a hard window.location redirect after a 401 (the
  // React-Router state channel doesn't survive a full-page reload).
  if (nextParam && isSameOriginPath(nextParam)) {
    return nextParam
  }
  return '/'
}

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const { login, loginAsGuest, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Where to send the user after a successful login.
  //
  // Two channels carry the original URL:
  //   1. ``location.state.from`` — set by ProtectedLayout's
  //      ``<Navigate state={{from}}>``. Survives React Router
  //      navigations; lost on full-page reload.
  //   2. ``?next=`` query param — set by ``fetchWithAuth``'s 401
  //      handler when it does a hard window.location redirect (a
  //      token-expired-mid-session bounce can't carry state).
  //
  // ``safeFromTarget`` prefers (1) then (2), and rejects anything
  // that isn't a same-origin path to block open-redirect class issues
  // (``//evil.com``, ``/\\evil.com``, control-char-prefixed paths).
  const fromState = (location.state as LocationState | null)?.from
  const nextParam = new URLSearchParams(location.search).get('next')
  const fromTarget = safeFromTarget(fromState, nextParam)

  // An already-authenticated user who lands on ``/login`` directly
  // (manual nav, back-button after login) should skip the form and go
  // to ``fromTarget`` immediately. Without this, they can re-submit
  // credentials on an already-valid session.
  useEffect(() => {
    if (isAuthenticated) {
      navigate(fromTarget, { replace: true })
    }
  }, [isAuthenticated, fromTarget, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    const success = await login(email, password)

    if (success) {
      navigate(fromTarget, { replace: true })
    } else {
      setError('Invalid email or password')
    }

    setIsLoading(false)
  }

  const handleGuestLogin = async () => {
    setError('')
    setIsLoading(true)

    const success = await loginAsGuest()

    if (success) {
      navigate(fromTarget, { replace: true })
    } else {
      setError('Guest sign-in is unavailable')
    }

    setIsLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 px-4">
      <div className="w-full max-w-md">
        {/* Logo and Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-500/20 mb-4">
            <Bird className="w-8 h-8 text-blue-400" />
          </div>
          <h1 className="text-3xl font-bold text-white">Orpheus</h1>
          <p className="text-slate-400 mt-2">Wildlife Monitoring System</p>
        </div>

        {/* Login Form */}
        <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-white mb-6">Sign in to your account</h2>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-500/20 border border-red-500/50 flex items-center gap-2 text-red-400">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-300 mb-1">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-700/50 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="you@example.com"
                  required
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-1">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-700/50 border border-slate-600 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="••••••••"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-800"
            >
              {isLoading ? 'Signing in...' : 'Sign in'}
            </button>

            {UI_FLAGS.guestQuickLogin && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={handleGuestLogin}
                  disabled={isLoading}
                  className="w-full py-2.5 px-4 bg-slate-600 hover:bg-slate-700 disabled:bg-slate-600/50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-800"
                >
                  {isLoading ? 'Signing in...' : 'Sign in as Guest'}
                </button>
              </div>
            )}
          </form>

          {/* The remediation named here has to work on a box that is ALREADY
              seeded — seeding is guarded on an empty user table, so setting the
              password variables and restarting is a no-op on exactly the
              installs that see this banner. */}
          {UI_FLAGS.defaultCredentialsInUse && (
            <div className="mt-6 pt-6 border-t border-slate-700">
              <p className="text-sm text-amber-400/90 text-center">
                This station still uses a password Orpheus ships with. Sign in and change
                it with{' '}
                <code className="text-amber-300">PATCH /users/me</code>, or delete the
                accounts database and restart with{' '}
                <code className="text-amber-300">ORPHEUS_UI_ADMIN_PASSWORD</code>,{' '}
                <code className="text-amber-300">ORPHEUS_UI_GUEST_PASSWORD</code> and{' '}
                <code className="text-amber-300">ORPHEUS_UI_JWT_SECRET</code> set. The
                server log names the file on startup.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
