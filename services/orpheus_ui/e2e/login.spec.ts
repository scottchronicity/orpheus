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

  test('displays default credentials hint', async ({ page }) => {
    await page.goto('/')
    
    // Should show the default credentials
    await expect(page.getByText('admin@orpheus.example.com')).toBeVisible()
    await expect(page.getByText('changeme')).toBeVisible()
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
    
    // Email field should have label
    const emailLabel = page.getByText('Email address')
    await expect(emailLabel).toBeVisible()
    
    // Password field should have label
    const passwordLabel = page.getByText('Password')
    await expect(passwordLabel).toBeVisible()
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
