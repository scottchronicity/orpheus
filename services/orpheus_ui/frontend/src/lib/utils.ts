import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// API base URL (uses proxy in dev, relative path in prod)
export const API_BASE = ''

// Token storage
const TOKEN_KEY = 'orpheus_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/**
 * Build a URL with the JWT token as a query parameter.
 * Used for HTML media elements (<video>, <audio>) that cannot send
 * Authorization headers. The backend accepts ?token= on media endpoints.
 */
export function getTokenUrl(path: string): string {
  // Resolve against the page origin before anything else. The result of this
  // function becomes the ``src`` of an <audio> element and the ``href`` of a
  // download link, so a path that carried its own scheme -- ``javascript:``,
  // ``data:`` -- would execute on click. Resolving first means a scheme in the
  // input produces a foreign origin, which the check below rejects, and a
  // ``//host/x`` input cannot silently become cross-origin either.
  const url = new URL(path, window.location.origin)
  if (url.origin !== window.location.origin) {
    throw new Error('Refusing to build a media URL outside this origin')
  }
  const token = getToken()
  if (token) {
    url.searchParams.set('token', token)
  }
  // Relative, because API_BASE is empty and callers expect a same-origin path.
  return `${API_BASE}${url.pathname}${url.search}`
}

// Fetch with auth
export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = getToken()
  const headers = new Headers(options.headers)
  
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  
  // Only set Content-Type for methods that typically send a body
  // This allows binary responses (audio/video) to work properly
  const method = (options.method || 'GET').toUpperCase()
  if (!headers.has('Content-Type') && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  })

  if (response.status === 401) {
    removeToken()
    // Hard navigation drops React Router's in-memory ``location.state``,
    // so the ProtectedLayout's ``state={{ from }}`` channel is lost when
    // a token expires mid-session. Pass the current URL via a
    // ``?next=`` query param instead — Login.tsx falls back to it when
    // ``state.from`` is absent, so the user lands back where they were
    // after re-authentication.
    const current =
      window.location.pathname + window.location.search + window.location.hash
    const isAlreadyAtLogin =
      window.location.pathname === '/login' ||
      window.location.pathname === '/'
    const target = isAlreadyAtLogin
      ? '/login'
      : `/login?next=${encodeURIComponent(current)}`
    window.location.href = target
    throw new Error('Unauthorized')
  }

  return response
}

/**
 * Map well-known species codes to human-readable display names.
 *
 * Used as a fallback when the backend does not supply a common_name.
 */
const SPECIES_DISPLAY_NAMES: Record<string, string> = {
  crow: 'Crow',
  corvus: 'Corvid',
}

/**
 * Return a human-readable display name for a species code.
 *
 * Falls back to the raw code when no mapping exists.
 */
export function getSpeciesDisplayName(code: string, commonName?: string): string {
  if (commonName) return commonName
  return SPECIES_DISPLAY_NAMES[code] ?? code
}

/**
 * Format an ISO 8601 timestamp to the user's local timezone
 * 
 * @param isoString - ISO 8601 timestamp string (e.g., "2026-01-18T10:00:00Z")
 * @returns Formatted date-time string in user's locale (e.g., "Jan 18, 2026, 4:30:05 PM")
 */
export function formatDateTime(isoString: string): string {
  try {
    const date = new Date(isoString)
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
      return isoString // Return original string if invalid
    }
    
    // Use Intl.DateTimeFormat for locale-aware formatting
    // Medium date + medium time format
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }).format(date)
  } catch (error) {
    console.error('Error formatting date:', error)
    return isoString // Fallback to original string
  }
}

/**
 * Human-readable byte size in binary units, labelled as binary units.
 *
 * It divides by 1024 and used to print "GB", so a storage panel reading 277.1
 * disagreed with every decimal-GB figure it was checked against — the same
 * 297.5e9 bytes. The maths is unchanged; only the suffix is now honest, and
 * it matches what `df -h` and orpheus-storage-sweep print.
 *
 * formatBytes(0) -> "0 B"; formatBytes(null) -> "—".
 */
export function formatBytes(bytes: number | null | undefined, decimals = 1): string {
  if (bytes === null || bytes === undefined || isNaN(bytes)) return '—'
  if (bytes === 0) return '0 B'
  const k = 1024
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(k)), units.length - 1)
  return `${(bytes / Math.pow(k, i)).toFixed(decimals)} ${units[i]}`
}

/**
 * Format a "days until full" projection as a friendly string.
 * null -> "—" (not enough history, or free space flat/growing).
 */
export function formatDaysUntilFull(days: number | null | undefined): string {
  if (days === null || days === undefined || isNaN(days)) return '—'
  if (days >= 365) return `${(days / 365).toFixed(1)} yr`
  if (days >= 1) return `${Math.round(days)} days`
  return '< 1 day'
}
