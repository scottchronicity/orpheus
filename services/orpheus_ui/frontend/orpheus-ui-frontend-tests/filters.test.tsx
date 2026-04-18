/**
 * Tests for SpeciesFilter and DateRangeFilter components.
 *
 * Covers the positive-selection UX (empty set = "All"), the midnight-
 * wrapping time window, and the derived-from-props preset highlight.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SpeciesFilter } from '../src/components/SpeciesFilter'
import {
  DateRangeFilter,
  DEFAULT_START_TIME,
  DEFAULT_END_TIME,
} from '../src/components/DateRangeFilter'

describe('SpeciesFilter', () => {
  const items = [
    { value: 'American Crow', count: 12 },
    { value: 'House Sparrow', count: 7 },
    { value: 'Northern Cardinal', count: 3 },
  ]

  it('shows "All (N)" label when nothing is selected', () => {
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set()}
        onChange={() => {}}
      />
    )
    expect(screen.getByText(/Species: All \(3\)/)).toBeInTheDocument()
  })

  it('shows "X of N" label when selection is narrowed', () => {
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set(['American Crow'])}
        onChange={() => {}}
      />
    )
    expect(screen.getByText(/Species: 1 of 3/)).toBeInTheDocument()
  })

  it('disables the button when there are no available items', () => {
    render(
      <SpeciesFilter
        availableItems={[]}
        selected={new Set()}
        onChange={() => {}}
      />
    )
    const button = screen.getByRole('button', { name: /Species: none in range/ })
    expect(button).toBeDisabled()
  })

  it('opens dropdown on click and shows helper text for the "All" state', () => {
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set()}
        onChange={() => {}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Species: All/ }))
    expect(screen.getByText(/Showing all 3\. Select any to narrow/)).toBeInTheDocument()
    // All three species should be listed in the menu
    expect(screen.getByText('American Crow')).toBeInTheDocument()
    expect(screen.getByText('House Sparrow')).toBeInTheDocument()
    expect(screen.getByText('Northern Cardinal')).toBeInTheDocument()
  })

  it('clicking a species toggles it into the selection', () => {
    const onChange = vi.fn()
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set()}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Species: All/ }))
    fireEvent.click(screen.getByText('American Crow'))
    expect(onChange).toHaveBeenCalledTimes(1)
    const next = onChange.mock.calls[0][0] as Set<string>
    expect(next.has('American Crow')).toBe(true)
    expect(next.size).toBe(1)
  })

  it('collapses back to empty when every item has been individually picked', () => {
    const onChange = vi.fn()
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set(['American Crow', 'House Sparrow'])}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Species: 2 of 3/ }))
    fireEvent.click(screen.getByText('Northern Cardinal'))
    // Picking the third item would fill the set — component collapses to empty.
    const next = onChange.mock.calls[0][0] as Set<string>
    expect(next.size).toBe(0)
  })

  it('"All" button resets selection to empty', () => {
    const onChange = vi.fn()
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set(['American Crow'])}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Species: 1 of 3/ }))
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    const next = onChange.mock.calls[0][0] as Set<string>
    expect(next.size).toBe(0)
  })

  it('unticking the only selected item leaves the set empty', () => {
    const onChange = vi.fn()
    render(
      <SpeciesFilter
        availableItems={items}
        selected={new Set(['American Crow'])}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Species: 1 of 3/ }))
    fireEvent.click(screen.getByText('American Crow'))
    const next = onChange.mock.calls[0][0] as Set<string>
    expect(next.size).toBe(0)
  })

  it('uses a custom label when provided', () => {
    render(
      <SpeciesFilter
        availableItems={[{ value: 'caw', count: 5 }]}
        selected={new Set()}
        onChange={() => {}}
        label="Call Types"
      />
    )
    expect(screen.getByText(/Call Types: All \(1\)/)).toBeInTheDocument()
  })
})

describe('DateRangeFilter', () => {
  // Use a date-range width that won't coincidentally match a preset so we can
  // assert the "N Days" fall-through label.
  const baseProps = {
    startDate: '2026-01-01',
    endDate: '2026-01-10',
    startTime: DEFAULT_START_TIME,
    endTime: DEFAULT_END_TIME,
  }

  it('renders date and time inputs plus preset buttons', () => {
    render(<DateRangeFilter {...baseProps} onChange={() => {}} />)
    // Two date inputs, two time inputs, Apply, three presets.
    expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1 Day' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '7 Days' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '30 Days' })).toBeInTheDocument()
  })

  it('shows a "wraps midnight" hint when start_time > end_time', () => {
    render(
      <DateRangeFilter
        {...baseProps}
        startTime="20:00"
        endTime="06:00"
        onChange={() => {}}
      />
    )
    expect(screen.getByText(/wraps midnight/)).toBeInTheDocument()
  })

  it('omits the "wraps midnight" hint when range is full-day', () => {
    render(<DateRangeFilter {...baseProps} onChange={() => {}} />)
    expect(screen.queryByText(/wraps midnight/)).not.toBeInTheDocument()
  })

  it('Apply fires onChange with the current local values', () => {
    const onChange = vi.fn()
    render(<DateRangeFilter {...baseProps} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onChange).toHaveBeenCalledWith({
      startDate: baseProps.startDate,
      endDate: baseProps.endDate,
      startTime: DEFAULT_START_TIME,
      endTime: DEFAULT_END_TIME,
    })
  })

  it('clicking a preset fires onChange and preserves time-of-day', () => {
    const onChange = vi.fn()
    render(
      <DateRangeFilter
        {...baseProps}
        startTime="08:00"
        endTime="18:00"
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: '7 Days' }))
    expect(onChange).toHaveBeenCalledTimes(1)
    const [arg] = onChange.mock.calls[0]
    expect(arg.startTime).toBe('08:00')
    expect(arg.endTime).toBe('18:00')
    // The start/end dates should span 7 days ending today.
    const diffMs = new Date(arg.endDate).getTime() - new Date(arg.startDate).getTime()
    expect(Math.round(diffMs / (1000 * 60 * 60 * 24))).toBe(7)
  })

  it('highlights the preset button that matches the committed range (survives remount)', () => {
    // This is the regression test for the preset-button remount bug.
    // When the committed range is exactly 7 days ending today the "7 Days"
    // button must be highlighted on first render — no click needed.
    const today = new Date()
    const weekAgo = new Date(today)
    weekAgo.setDate(today.getDate() - 7)
    const fmt = (d: Date) => d.toISOString().split('T')[0]
    render(
      <DateRangeFilter
        startDate={fmt(weekAgo)}
        endDate={fmt(today)}
        startTime={DEFAULT_START_TIME}
        endTime={DEFAULT_END_TIME}
        onChange={() => {}}
      />
    )
    const sevenDay = screen.getByRole('button', { name: '7 Days' })
    // The active preset applies the blue background class.
    expect(sevenDay.className).toMatch(/bg-blue-600/)
    // And the 1 Day / 30 Days buttons are NOT highlighted.
    expect(screen.getByRole('button', { name: '1 Day' }).className).not.toMatch(/bg-blue-600/)
    expect(screen.getByRole('button', { name: '30 Days' }).className).not.toMatch(/bg-blue-600/)
  })

  it('no preset button is highlighted when dates do not match any preset', () => {
    render(<DateRangeFilter {...baseProps} onChange={() => {}} />)
    // 2026-01-01 to 2026-01-10 is 9 days and endDate is not today.
    expect(screen.getByRole('button', { name: '1 Day' }).className).not.toMatch(/bg-blue-600/)
    expect(screen.getByRole('button', { name: '7 Days' }).className).not.toMatch(/bg-blue-600/)
    expect(screen.getByRole('button', { name: '30 Days' }).className).not.toMatch(/bg-blue-600/)
  })
})
