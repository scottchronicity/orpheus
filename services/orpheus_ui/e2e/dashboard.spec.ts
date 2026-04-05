import { test, expect } from '@playwright/test'

/**
 * Dashboard e2e tests.
 * 
 * These tests verify the dashboard displays correctly after login:
 * - System health metrics
 * - Service status
 * - Responsive layout
 */

test.describe('Dashboard', () => {
  // Login before each test
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    
    // Login
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    
    // Wait for dashboard to load
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('displays system health section', async ({ page }) => {
    // Should show CPU, Memory, Disk metrics
    await expect(page.getByText(/cpu/i)).toBeVisible()
    await expect(page.getByText(/memory/i)).toBeVisible()
    await expect(page.getByText(/disk/i)).toBeVisible()
  })

  test('displays service status section', async ({ page }) => {
    // Should show service status section
    await expect(page.getByText('Service Status')).toBeVisible()
  })

  test('has working navigation/sidebar', async ({ page }) => {
    // Should have navigation elements
    const nav = page.locator('nav, [role="navigation"], aside')
    await expect(nav.first()).toBeVisible()
  })

  test('shows user info or logout option', async ({ page }) => {
    // User menu button is visible in sidebar when logged in
    await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible()
  })
})

test.describe('Dashboard Responsive Design', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
    await page.getByLabel(/password/i).fill('changeme')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText(/system health|dashboard|cpu/i)).toBeVisible({ timeout: 10000 })
  })

  test('desktop layout shows sidebar', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 })
    
    // Sidebar should be visible on desktop
    const sidebar = page.locator('aside, [class*="sidebar"]')
    await expect(sidebar.first()).toBeVisible()
  })

  test('mobile layout is usable', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    
    // Content should still be accessible
    await expect(page.getByText(/cpu|memory|system/i)).toBeVisible()
  })
})
