/**
 * The login page must not disclose credentials.
 *
 * It previously printed the seeded guest and admin logins on screen and
 * called the login API with the guest password hardcoded in the bundle.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../src/contexts/AuthContext'
import { UI_FLAGS } from '../src/config'
import Login from '../src/pages/Login'

let mockFetch: ReturnType<typeof vi.fn>
const originalFlags = { ...UI_FLAGS }

beforeEach(() => {
  mockFetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) })
  vi.stubGlobal('fetch', mockFetch)
})

afterEach(() => {
  Object.assign(UI_FLAGS, originalFlags)
})

function renderLogin() {
  return render(
    <BrowserRouter>
      <AuthProvider>
        <Login />
      </AuthProvider>
    </BrowserRouter>,
  )
}

describe('Login page', () => {
  it('shows no password anywhere in the rendered page', async () => {
    UI_FLAGS.guestQuickLogin = true
    UI_FLAGS.defaultCredentialsInUse = true
    const { container } = renderLogin()

    await waitFor(() => expect(screen.getByText('Sign in to your account')).toBeInTheDocument())

    const text = container.textContent ?? ''
    expect(text).not.toContain('changeme')
    expect(text).not.toMatch(/guest@orpheus\.example\.com/)
    expect(text).not.toMatch(/admin@orpheus\.example\.com/)
  })

  it('offers the guest button when the server enables it', async () => {
    UI_FLAGS.guestQuickLogin = true
    renderLogin()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /sign in as guest/i })).toBeInTheDocument(),
    )
  })

  it('hides the guest button when the server disables it', async () => {
    UI_FLAGS.guestQuickLogin = false
    renderLogin()

    await waitFor(() => expect(screen.getByText('Sign in to your account')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /sign in as guest/i })).not.toBeInTheDocument()
  })

  it('asks the server to sign the guest in, sending no credential', async () => {
    UI_FLAGS.guestQuickLogin = true
    renderLogin()

    const button = await screen.findByRole('button', { name: /sign in as guest/i })
    fireEvent.click(button)

    await waitFor(() => {
      const guestCall = mockFetch.mock.calls.find(([url]) =>
        String(url).includes('/auth/guest-login'),
      )
      expect(guestCall).toBeTruthy()
      expect(guestCall?.[1]?.method).toBe('POST')
      // No body at all: the password lives on the server.
      expect(guestCall?.[1]?.body).toBeUndefined()
    })
  })

  it('prompts for rotation only while defaults are in use', async () => {
    UI_FLAGS.defaultCredentialsInUse = true
    const { unmount } = renderLogin()
    await waitFor(() =>
      expect(screen.getByText(/password Orpheus ships with/i)).toBeInTheDocument(),
    )
    unmount()

    UI_FLAGS.defaultCredentialsInUse = false
    renderLogin()
    await waitFor(() => expect(screen.getByText('Sign in to your account')).toBeInTheDocument())
    expect(screen.queryByText(/password Orpheus ships with/i)).not.toBeInTheDocument()
  })

  it('names a rotation that works on an already-seeded station', async () => {
    // Seeding is guarded on an empty user table, so telling the operator to set
    // the password variables and restart is a no-op on exactly the installs
    // that see this banner.
    UI_FLAGS.defaultCredentialsInUse = true
    const { container } = renderLogin()
    await waitFor(() =>
      expect(screen.getByText(/password Orpheus ships with/i)).toBeInTheDocument(),
    )

    const text = container.textContent ?? ''
    expect(text).toContain('PATCH /users/me')
    expect(text).toContain('ORPHEUS_UI_ADMIN_PASSWORD')
    // No filesystem path: the browser cannot know where this station keeps its
    // accounts, and naming the station default sends every other install to a
    // file that isn't there. The backend logs the resolved path instead.
    expect(text).not.toContain('/data/orpheus')
  })
})
