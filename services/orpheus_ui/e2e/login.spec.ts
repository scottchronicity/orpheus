import { test, expect } from '@playwright/test'

/**
 * Login flow e2e tests.
 * 
 * These tests verify the complete login experience:
 * 1. User sees login page when not authenticated
 * 2. User can log in with valid credentials
 * 3. After login, user sees dashboard
 * 4. Invalid credentials show error message
 */

test.describe('Login Flow', () => {
  test.beforeEach(async ({ page }) => {
    // Clear any existing auth state
    await page.context().clearCookies()
  })

  test('shows login page when not authenticated', async ({ page }) => {
    await page.goto('/')

    // Should redirect to login or show login page
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
    await expect(page.getByLabel(/email address/i)).toBeVisible()
    await expect(page.getByLabel(/password/i)).toBeVisible()
  })

  test('never displays credentials', async ({ page }) => {
    await page.goto('/')

    // The page must not hand out a working account to anyone who loads it.
    const body = await page.locator('body').innerText()
    expect(body).not.toContain('changeme')
    expect(body).not.toContain('guest@orpheus.example.com')
    expect(body).not.toContain('admin@orpheus.example.com')
  })

  test('offers one-click guest sign-in', async ({ page }) => {
    await page.goto('/')

    // Quick sign-in is on by default; the password stays on the server.
    await expect(page.getByRole('button', { name: /guest/i })).toBeVisible()
  })

  test('successful login redirects to dashboard', async ({ page }) => {
    await page.goto('/')

    // Fill in credentials
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    
    // Click sign in
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Should redirect to dashboard
    await expect(page).toHaveURL('/', { timeout: 10000 })
    
    // Dashboard should show system health or similar content
    await expect(page.getByText(/system health|dashboard|cpu|memory/i)).toBeVisible({ timeout: 10000 })
  })

  test('invalid credentials show error message', async ({ page }) => {
    await page.goto('/')

    // Fill in wrong credentials
    await page.getByLabel(/email address/i).fill('wrong@email.com')
    await page.getByLabel(/password/i).fill('wrongpassword')
    
    // Click sign in
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Should show error message
    await expect(page.getByText(/invalid|error|failed/i)).toBeVisible({ timeout: 5000 })
  })

  test('login button shows loading state', async ({ page }) => {
    await page.goto('/')

    // Fill in credentials
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    
    // Click sign in and check for loading state
    const signInButton = page.getByRole('button', { name: 'Sign in', exact: true })
    await signInButton.click()
    
    // Button should show loading text (use first() since "Sign in as Guest" also shows "Signing in...")
    await expect(page.getByRole('button', { name: /signing in/i }).first()).toBeVisible()
  })
})

test.describe('Login Page Accessibility', () => {
  test('has proper form labels', async ({ page }) => {
    await page.goto('/')
    
    // Scoped to the label elements: other copy on the page mentions
    // passwords, so a loose text match is ambiguous.
    await expect(page.locator('label[for="email"]')).toHaveText('Email address')
    await expect(page.locator('label[for="password"]')).toHaveText('Password')
  })

  test('form is keyboard navigable', async ({ page }) => {
    await page.goto('/')

    // Click email to establish window focus, then test Tab order
    await page.getByLabel(/email address/i).click()
    await expect(page.getByLabel(/email address/i)).toBeFocused()

    await page.keyboard.press('Tab')
    await expect(page.getByLabel(/password/i)).toBeFocused()

    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeFocused()
  })
})

test.describe('Mobile Login', () => {
  test.use({ viewport: { width: 375, height: 667 } })

  test('login form is usable on mobile', async ({ page }) => {
    await page.goto('/')

    // Form should be visible and usable
    await expect(page.getByLabel(/email address/i)).toBeVisible()
    await expect(page.getByLabel(/password/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()

    // Fill and submit
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Should work on mobile too
    await expect(page.getByText(/system health|dashboard|cpu|memory/i)).toBeVisible({ timeout: 10000 })
  })
})
