/**
 * Test setup file for Vitest.
 * 
 * This file runs before each test file and sets up:
 * - jest-dom matchers for DOM assertions
 * - Global mocks that should be consistent across all tests
 */
import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock localStorage globally for all tests
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      store = {}
    }),
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
})

// Reset localStorage before each test
beforeEach(() => {
  localStorageMock.clear()
  vi.clearAllMocks()
})
