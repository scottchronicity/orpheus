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
  const token = getToken()
  const sep = path.includes('?') ? '&' : '?'
  return token ? `${API_BASE}${path}${sep}token=${token}` : `${API_BASE}${path}`
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
    window.location.href = '/login'
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
