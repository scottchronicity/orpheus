/**
 * AuthContext - Centralized authentication state management.
 * 
 * This context provides:
 * - Single source of truth for auth state (prevents duplicate API calls)
 * - Shared user data across all components
 * - Login/logout functions
 * 
 * IMPORTANT: This fixes the navigation blank page issue where each
 * ProtectedRoute was creating its own useAuth hook instance, causing
 * race conditions and re-authentication on every route change.
 */
import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { getToken, setToken, removeToken, API_BASE } from '../lib/utils'

interface User {
  id: string
  email: string
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  role: string
  display_name?: string
}

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<boolean>
  loginAsGuest: () => Promise<boolean>
  logout: () => void
  checkAuth: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const checkAuth = useCallback(async () => {
    const token = getToken()
    if (!token) {
      setUser(null)
      setIsAuthenticated(false)
      setIsLoading(false)
      return
    }

    try {
      const response = await fetch(`${API_BASE}/users/me`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (response.ok) {
        const userData = await response.json()
        setUser(userData)
        setIsAuthenticated(true)
      } else {
        removeToken()
        setUser(null)
        setIsAuthenticated(false)
      }
    } catch {
      removeToken()
      setUser(null)
      setIsAuthenticated(false)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  const login = async (email: string, password: string): Promise<boolean> => {
    try {
      const formData = new URLSearchParams()
      formData.append('username', email)
      formData.append('password', password)

      const response = await fetch(`${API_BASE}/auth/jwt/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        setToken(data.access_token)
        await checkAuth()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  /**
   * Sign in as the seeded read-only guest.
   *
   * The password stays on the server: this posts to an endpoint that
   * authenticates the guest account and returns a normal token, so no
   * credential ships in the bundle and the flow survives a password rotation.
   * The server refuses when ``ui.guest_quick_login`` is off.
   */
  const loginAsGuest = async (): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/auth/guest-login`, { method: 'POST' })
      if (response.ok) {
        const data = await response.json()
        setToken(data.access_token)
        await checkAuth()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  const logout = useCallback(() => {
    removeToken()
    setUser(null)
    setIsAuthenticated(false)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated,
        isLoading,
        login,
        loginAsGuest,
        logout,
        checkAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
