/**
 * Tests for SpeciesFilter and DateRangeFilter components.
 *
 * Covers the positive-selection UX (empty set = "All"), the midnight-
 * wrapping time window, and the derived-from-props preset highlight.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, renderHook, act } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { SpeciesFilter } from '../src/components/SpeciesFilter'
import {
  DateRangeFilter,
  DEFAULT_START_TIME,
  DEFAULT_END_TIME,
  useUrlMultiSelect,
  usePaginatedDateRange,
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

  it('shows the refetch indicator when showing placeholder data (filter/page change)', () => {
    render(<DateRangeFilter {...baseProps} onChange={() => {}} isPlaceholderData />)
    expect(screen.getByRole('status', { name: /updating/i })).toBeInTheDocument()
  })

  it('hides the refetch indicator when not showing placeholder data', () => {
    // No placeholder = either the initial mount (the full LoadingSpinner owns
    // that) or a 30s background poll of an unchanged key — neither should
    // flash the inline indicator.
    render(<DateRangeFilter {...baseProps} onChange={() => {}} isPlaceholderData={false} />)
    expect(screen.queryByRole('status', { name: /updating/i })).not.toBeInTheDocument()
  })

  it('hides the refetch indicator by default (prop omitted)', () => {
    render(<DateRangeFilter {...baseProps} onChange={() => {}} />)
    expect(screen.queryByRole('status', { name: /updating/i })).not.toBeInTheDocument()
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

// Memoised wrapper that lets a renderHook test introspect the URL the
// hook is writing to via useLocation.
function makeRouterWrapper(initialEntries: string[] = ['/']) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  )
}

describe('useUrlMultiSelect', () => {
  it('reads an empty Set when the URL has no value for the key', () => {
    const { result } = renderHook(() => useUrlMultiSelect('species'), {
      wrapper: makeRouterWrapper(['/birds']),
    })
    expect(result.current[0].size).toBe(0)
  })

  it('parses a comma-separated value into a Set', () => {
    const { result } = renderHook(() => useUrlMultiSelect('species'), {
      wrapper: makeRouterWrapper(['/birds?species=amecro,amerob']),
    })
    expect(Array.from(result.current[0]).sort()).toEqual(['amecro', 'amerob'])
  })

  it('writing a Set sorts and encodes into the URL', () => {
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('species')
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/birds']) },
    )
    act(() => {
      result.current.ms[1](new Set(['amerob', 'amecro']))
    })
    // Sorted alphabetically so identical sets always produce identical URLs.
    expect(result.current.location.search).toBe('?species=amecro%2Camerob')
  })

  it('writing an empty Set deletes the URL param', () => {
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('species')
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/birds?species=amecro']) },
    )
    expect(Array.from(result.current.ms[0])).toEqual(['amecro'])
    act(() => {
      result.current.ms[1](new Set())
    })
    expect(result.current.location.search).toBe('')
  })

  it('does NOT clobber other URL params on write', () => {
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('species')
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/birds?start=2026-05-18&end=2026-05-25']) },
    )
    act(() => {
      result.current.ms[1](new Set(['amecro']))
    })
    expect(result.current.location.search).toContain('start=2026-05-18')
    expect(result.current.location.search).toContain('end=2026-05-25')
    expect(result.current.location.search).toContain('species=amecro')
  })

  it('atomically resets ?page= in the same setSearchParams call as a chip change', () => {
    // Regression for the react-router-dom v6 stale-closure race:
    // setSearchParams((prev) => ...) closes over the render-time
    // ``searchParams`` snapshot, NOT the live URL. Two back-to-back
    // setSearchParams calls (chip + setPage(1)) in the same event
    // handler would both see the same stale snapshot and the second
    // navigate clobbers the first, silently losing the selection.
    // ``useUrlMultiSelect.setValue`` must reset page in the SAME
    // setSearchParams call to avoid the race.
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('species')
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/birds?page=5']) },
    )
    act(() => {
      result.current.ms[1](new Set(['amecro']))
    })
    // The chip-selection is preserved.
    expect(result.current.location.search).toContain('species=amecro')
    // The page param was reset (atomically — single navigate call).
    expect(result.current.location.search).not.toContain('page=')
  })

  it('resetPageKey: null disables the atomic page reset (for callers that own pagination differently)', () => {
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('species', { resetPageKey: null })
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/birds?page=5']) },
    )
    act(() => {
      result.current.ms[1](new Set(['amecro']))
    })
    expect(result.current.location.search).toContain('species=amecro')
    // resetPageKey: null leaves page intact.
    expect(result.current.location.search).toContain('page=5')
  })

  it('returns a stable Set identity when the underlying value does not change', () => {
    const { result, rerender } = renderHook(() => useUrlMultiSelect('species'), {
      wrapper: makeRouterWrapper(['/birds?species=amecro']),
    })
    const firstSet = result.current[0]
    rerender()
    // Memoised against the raw URL string, so re-rendering without a URL
    // change returns the same Set — important for react-query queryKey
    // identity stability.
    expect(result.current[0]).toBe(firstSet)
  })

  it('round-trips values that contain the default separator (comma) when given a pipe separator', () => {
    // Regression for AudioSet display labels: many AudioSet labels
    // contain a literal comma (e.g. "Heart sounds, heartbeat",
    // "Whoosh, swoosh, swish"). Splitting on comma would silently
    // bisect them into ghost filters. With separator: '|' the value
    // round-trips cleanly.
    const { result } = renderHook(
      () => {
        const ms = useUrlMultiSelect('label', { separator: '|' })
        const location = useLocation()
        return { ms, location }
      },
      { wrapper: makeRouterWrapper(['/audio-events']) },
    )
    act(() => {
      result.current.ms[1](new Set(['Heart sounds, heartbeat', 'Crow']))
    })
    // Sorted alphabetically — "Crow" < "Heart" so Crow comes first.
    expect(result.current.location.search).toBe(
      '?label=Crow%7CHeart+sounds%2C+heartbeat',
    )
    // Round-trip: the Set comes back with the comma-bearing value intact.
    expect(Array.from(result.current.ms[0]).sort()).toEqual([
      'Crow',
      'Heart sounds, heartbeat',
    ])
  })
})

describe('usePaginatedDateRange', () => {
  it('falls back to defaults when the URL has no params', () => {
    const { result } = renderHook(() => usePaginatedDateRange(7), {
      wrapper: makeRouterWrapper(['/birds']),
    })
    // startTime/endTime/page default to full-day / page 1.
    expect(result.current.startTime).toBe(DEFAULT_START_TIME)
    expect(result.current.endTime).toBe(DEFAULT_END_TIME)
    expect(result.current.page).toBe(1)
    // start/end derive from today / today-7days. We don't assert the
    // exact string (depends on the clock) but they should be non-empty
    // ISO-like ``YYYY-MM-DD``.
    expect(result.current.startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(result.current.endDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('reads values from the URL when present', () => {
    const { result } = renderHook(() => usePaginatedDateRange(1), {
      wrapper: makeRouterWrapper([
        '/birds?start=2026-05-01&end=2026-05-10&start_time=08:00&end_time=18:00&page=3',
      ]),
    })
    expect(result.current.startDate).toBe('2026-05-01')
    expect(result.current.endDate).toBe('2026-05-10')
    expect(result.current.startTime).toBe('08:00')
    expect(result.current.endTime).toBe('18:00')
    expect(result.current.page).toBe(3)
  })

  it('handleChange writes dates always but elides default time-of-day', () => {
    const { result } = renderHook(
      () => {
        const range = usePaginatedDateRange(1)
        const location = useLocation()
        return { range, location }
      },
      { wrapper: makeRouterWrapper(['/birds']) },
    )
    act(() => {
      result.current.range.handleChange({
        startDate: '2026-05-01',
        endDate: '2026-05-10',
        // Default full-day window.
        startTime: DEFAULT_START_TIME,
        endTime: DEFAULT_END_TIME,
      })
    })
    expect(result.current.location.search).toContain('start=2026-05-01')
    expect(result.current.location.search).toContain('end=2026-05-10')
    // Default time-of-day is elided.
    expect(result.current.location.search).not.toContain('start_time')
    expect(result.current.location.search).not.toContain('end_time')
  })

  it('handleChange writes time-of-day when non-default', () => {
    const { result } = renderHook(
      () => {
        const range = usePaginatedDateRange(1)
        const location = useLocation()
        return { range, location }
      },
      { wrapper: makeRouterWrapper(['/birds']) },
    )
    act(() => {
      result.current.range.handleChange({
        startDate: '2026-05-01',
        endDate: '2026-05-10',
        startTime: '08:00',
        endTime: '18:00',
      })
    })
    expect(result.current.location.search).toContain('start_time=08%3A00')
    expect(result.current.location.search).toContain('end_time=18%3A00')
  })

  it('handleChange resets page to 1 (elides from URL)', () => {
    const { result } = renderHook(
      () => {
        const range = usePaginatedDateRange(1)
        const location = useLocation()
        return { range, location }
      },
      { wrapper: makeRouterWrapper(['/birds?page=5']) },
    )
    expect(result.current.range.page).toBe(5)
    act(() => {
      result.current.range.handleChange({
        startDate: '2026-05-01',
        endDate: '2026-05-10',
        startTime: DEFAULT_START_TIME,
        endTime: DEFAULT_END_TIME,
      })
    })
    expect(result.current.range.page).toBe(1)
    expect(result.current.location.search).not.toContain('page=')
  })

  it('setPage writes page>1 and elides page=1', () => {
    const { result } = renderHook(
      () => {
        const range = usePaginatedDateRange(1)
        const location = useLocation()
        return { range, location }
      },
      { wrapper: makeRouterWrapper(['/birds']) },
    )
    act(() => {
      result.current.range.setPage(4)
    })
    expect(result.current.location.search).toContain('page=4')
    act(() => {
      result.current.range.setPage(1)
    })
    expect(result.current.location.search).not.toContain('page=')
  })

  it('does NOT clobber other params (like species) when changing date or page', () => {
    const { result } = renderHook(
      () => {
        const range = usePaginatedDateRange(1)
        const location = useLocation()
        return { range, location }
      },
      { wrapper: makeRouterWrapper(['/birds?species=amecro']) },
    )
    act(() => {
      result.current.range.handleChange({
        startDate: '2026-05-01',
        endDate: '2026-05-10',
        startTime: DEFAULT_START_TIME,
        endTime: DEFAULT_END_TIME,
      })
    })
    expect(result.current.location.search).toContain('species=amecro')
    expect(result.current.location.search).toContain('start=2026-05-01')
  })
})
