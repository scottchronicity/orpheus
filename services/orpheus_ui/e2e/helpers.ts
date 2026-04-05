import type { Page } from '@playwright/test'

/** Login as admin and wait for dashboard. */
export async function login(page: Page) {
  await page.goto('/')
  await page.getByLabel(/email address/i).fill('admin@orpheus.example.com')
  await page.getByLabel(/password/i).fill('changeme')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByRole('heading', { name: /dashboard/i }).waitFor({ state: 'visible', timeout: 10000 })
}

/** Returns true when the sidebar is in its closed (off-screen) state on mobile. */
async function isSidebarClosed(page: Page): Promise<boolean> {
  return page.locator('aside').evaluate(
    el => el.classList.contains('-translate-x-full') && window.innerWidth < 1024
  )
}

/**
 * Navigate via the sidebar link.
 * On mobile the sidebar is hidden via CSS class; we detect this with a class
 * check (not boundingBox, which races with the 200ms CSS transition) and open
 * the hamburger menu first when needed.
 */
export async function navigateTo(page: Page, linkName: string | RegExp) {
  if (await isSidebarClosed(page)) {
    await page.getByRole('button', { name: 'Open menu' }).click()
    await page.waitForTimeout(300)
  }
  await page.getByRole('link', { name: linkName }).click()
}

/**
 * Open the sidebar on mobile if it's currently closed.
 * Used when accessing sidebar-anchored controls (e.g. User menu) after navigation.
 */
export async function openSidebarIfNeeded(page: Page) {
  if (await isSidebarClosed(page)) {
    await page.getByRole('button', { name: 'Open menu' }).click()
    await page.waitForTimeout(300)
  }
}
