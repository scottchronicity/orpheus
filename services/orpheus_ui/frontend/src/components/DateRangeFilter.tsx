/**
 * DateRangeFilter - Reusable date + time-of-day range filter.
 *
 * Provides Start/End date pickers, Start/End time-of-day pickers, and preset
 * buttons (1 day / 7 days / 30 days). Used by Birds, Crows, and Entities pages.
 *
 * Time-of-day semantics:
 *   - Defaults to 00:00 — 23:59 (full day; equivalent to "no time filter").
 *   - If startTime <= endTime, matches that window on each date in the range
 *     (e.g. 08:00—18:00 keeps daytime only).
 *   - If startTime > endTime, wraps around midnight (e.g. 20:00—06:00 keeps
 *     night-time: evening of each day plus early morning of the next).
 *   - Times are interpreted in the BROWSER's local timezone. The active IANA
 *     zone is shown next to the inputs so the user knows what they picked.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Clock, RefreshCw } from 'lucide-react'
import { Card } from './ui'

export interface DateTimeRange {
  startDate: string
  endDate: string
  /** HH:MM in browser-local time. Default "00:00". */
  startTime: string
  /** HH:MM in browser-local time. Default "23:59". */
  endTime: string
}

interface DateRangeFilterProps {
  startDate: string
  endDate: string
  startTime: string
  endTime: string
  onChange: (value: DateTimeRange) => void
  /**
   * react-query ``isPlaceholderData`` for the page's primary query. True
   * exactly when the displayed table is the PREVIOUS query's data held as a
   * placeholder while a NEW key (filter/page change) refetches — which is
   * the only thing this indicator should signal. It is false on the initial
   * mount (the full LoadingSpinner owns that) AND false on the 30s
   * background poll of an unchanged key (same data, no placeholder), so the
   * spinner doesn't flash every poll. Optional; pages that don't wire it up
   * are unaffected. (Matches the precedent already in Entities.tsx.)
   */
  isPlaceholderData?: boolean
}

function formatDate(date: Date): string {
  return date.toISOString().split('T')[0]
}

function getDaysAgo(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return formatDate(date)
}

function getToday(): string {
  return formatDate(new Date())
}

/** User's IANA timezone name (e.g. "America/Los_Angeles"). */
function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'
  } catch {
    return 'local'
  }
}

/** Derive which preset button (if any) matches the given range. */
function presetForRange(startDate: string, endDate: string): number | null {
  const today = getToday()
  if (endDate !== today) return null
  const diffDays = Math.round(
    (new Date(endDate).getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24)
  )
  if (diffDays === 0 || diffDays === 1) return 1
  if (diffDays === 7) return 7
  if (diffDays === 30) return 30
  return null
}

export const DEFAULT_START_TIME = '00:00'
export const DEFAULT_END_TIME = '23:59'

export function DateRangeFilter({
  startDate,
  endDate,
  startTime,
  endTime,
  onChange,
  isPlaceholderData = false,
}: DateRangeFilterProps) {
  const [localStart, setLocalStart] = useState(startDate)
  const [localEnd, setLocalEnd] = useState(endDate)
  const [localStartTime, setLocalStartTime] = useState(startTime)
  const [localEndTime, setLocalEndTime] = useState(endTime)

  // Sync local state with props (e.g. after a remount or external change).
  useEffect(() => { setLocalStart(startDate) }, [startDate])
  useEffect(() => { setLocalEnd(endDate) }, [endDate])
  useEffect(() => { setLocalStartTime(startTime) }, [startTime])
  useEffect(() => { setLocalEndTime(endTime) }, [endTime])

  // Derive active preset from the committed props so it survives remounts
  // (e.g. when a page re-renders during a react-query refetch and drops
  // back to <LoadingSpinner />).
  const activePreset = useMemo(() => presetForRange(startDate, endDate), [startDate, endDate])

  const browserTz = useMemo(getBrowserTimezone, [])

  const handleApply = () => {
    onChange({
      startDate: localStart,
      endDate: localEnd,
      startTime: localStartTime,
      endTime: localEndTime,
    })
  }

  const handlePreset = (days: number) => {
    const newStart = getDaysAgo(days)
    const newEnd = getToday()
    setLocalStart(newStart)
    setLocalEnd(newEnd)
    // Preset buttons do not touch time-of-day: user's time filter persists.
    onChange({
      startDate: newStart,
      endDate: newEnd,
      startTime: localStartTime,
      endTime: localEndTime,
    })
  }

  // Label describing the date window width.
  const diffDays = Math.round(
    (new Date(localEnd).getTime() - new Date(localStart).getTime()) / (1000 * 60 * 60 * 24)
  )
  let rangeLabel = ''
  if (diffDays === 0 || diffDays === 1) rangeLabel = 'Last 1 Day'
  else if (diffDays === 7) rangeLabel = 'Last 7 Days'
  else if (diffDays === 30) rangeLabel = 'Last 30 Days'
  else rangeLabel = `${diffDays} Days`

  const timeRangeIsFullDay = localStartTime === DEFAULT_START_TIME && localEndTime === DEFAULT_END_TIME
  const timeWrapsMidnight = localStartTime > localEndTime

  const presetClass = (days: number) =>
    activePreset === days
      ? 'px-3 py-1.5 bg-blue-600 text-white text-sm rounded transition-colors'
      : 'px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm rounded transition-colors'

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-slate-400" />
          <span className="text-sm text-slate-400">Date:</span>
          <span className="text-sm text-blue-400 font-medium">({rangeLabel})</span>
          {/* Refetch indicator: a filter/page change is in flight while the
              old data stays on screen (placeholderData). Driven by
              isPlaceholderData so it fires only on key changes — not on the
              initial mount (LoadingSpinner owns that) or the 30s poll. */}
          {isPlaceholderData && (
            <span role="status" aria-label="Updating" title="Updating…">
              <RefreshCw className="w-4 h-4 text-blue-400 animate-spin" aria-hidden="true" />
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <input
            type="date"
            value={localStart}
            onChange={(e) => setLocalStart(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-slate-400">to</span>
          <input
            type="date"
            value={localEnd}
            onChange={(e) => setLocalEnd(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-slate-400" />
          <span className="text-sm text-slate-400">Time:</span>
          <input
            type="time"
            value={localStartTime}
            onChange={(e) => setLocalStartTime(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-slate-400">to</span>
          <input
            type="time"
            value={localEndTime}
            onChange={(e) => setLocalEndTime(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span
            className="text-xs text-slate-500"
            title="Times are interpreted in your browser's local timezone"
          >
            {browserTz}
            {!timeRangeIsFullDay && timeWrapsMidnight && ' · wraps midnight'}
          </span>
        </div>

        <button
          onClick={handleApply}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
        >
          Apply
        </button>

        <div className="flex items-center gap-2">
          <button onClick={() => handlePreset(1)} className={presetClass(1)}>
            1 Day
          </button>
          <button onClick={() => handlePreset(7)} className={presetClass(7)}>
            7 Days
          </button>
          <button onClick={() => handlePreset(30)} className={presetClass(30)}>
            30 Days
          </button>
        </div>
      </div>
    </Card>
  )
}

/**
 * Hook that combines date + time-of-day range state with a page counter,
 * backed by URL query params so filter state survives page reload and is
 * bookmark/shareable. Resets to page 1 whenever the range changes.
 *
 * URL param schema (per ``services/orpheus_ui/frontend/src/lib/urlState.ts``
 * convention — see ``useUrlMultiSelect`` below for the matching selection
 * params):
 *   ``?start=YYYY-MM-DD&end=YYYY-MM-DD`` — always present once the user
 *     interacts. Dates are written verbatim so a bookmark loaded next
 *     week still points at the same snapshot.
 *   ``?start_time=HH:MM&end_time=HH:MM`` — omitted when at full-day default.
 *   ``?page=N`` — omitted when 1.
 *
 * Usage:
 *   const { startDate, endDate, startTime, endTime, handleChange, page, setPage }
 *     = usePaginatedDateRange(1)
 */
export function usePaginatedDateRange(defaultDays: number = 1) {
  const [searchParams, setSearchParams] = useSearchParams()

  // Defaults are computed once per render. Today/getDaysAgo are dynamic
  // but only matter when the URL doesn't pin a value — the user-visible
  // URL is the source of truth otherwise.
  const defaultStart = useMemo(() => getDaysAgo(defaultDays), [defaultDays])
  const defaultEnd = useMemo(() => getToday(), [])

  const startDate = searchParams.get('start') ?? defaultStart
  const endDate = searchParams.get('end') ?? defaultEnd
  const startTime = searchParams.get('start_time') ?? DEFAULT_START_TIME
  const endTime = searchParams.get('end_time') ?? DEFAULT_END_TIME
  const pageParam = parseInt(searchParams.get('page') ?? '1', 10)
  const page = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1

  const updateParams = useCallback(
    (updates: {
      startDate?: string
      endDate?: string
      startTime?: string
      endTime?: string
      page?: number
    }) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          // Dates: always written. A user who bookmarks a date range
          // expects the same range when they come back next week.
          if (updates.startDate !== undefined) params.set('start', updates.startDate)
          if (updates.endDate !== undefined) params.set('end', updates.endDate)
          // Time-of-day + page: elided at default to keep URLs short.
          const elideOrSet = (key: string, value: string | undefined, dflt: string) => {
            if (value === undefined) return
            if (value === dflt) params.delete(key)
            else params.set(key, value)
          }
          elideOrSet('start_time', updates.startTime, DEFAULT_START_TIME)
          elideOrSet('end_time', updates.endTime, DEFAULT_END_TIME)
          if (updates.page !== undefined) {
            if (updates.page === 1) params.delete('page')
            else params.set('page', String(updates.page))
          }
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const handleChange = useCallback(
    (value: DateTimeRange) => {
      // Applying a new filter resets to page 1 (the existing detection
      // pages do this manually for their own selection setters — keep
      // that behaviour for the date/time path here).
      updateParams({
        startDate: value.startDate,
        endDate: value.endDate,
        startTime: value.startTime,
        endTime: value.endTime,
        page: 1,
      })
    },
    [updateParams],
  )

  const setPage = useCallback(
    (next: number | ((current: number) => number)) => {
      const newPage = typeof next === 'function' ? next(page) : next
      updateParams({ page: newPage })
    },
    [page, updateParams],
  )

  return { startDate, endDate, startTime, endTime, handleChange, page, setPage }
}

/**
 * URL-backed multi-select state for filter chips (selectedSpecies,
 * selectedLabels, selectedCallTypes, etc.). Reads/writes a single
 * separator-joined query param so URLs stay compact and bookmark-able.
 *
 * The returned ``Set`` identity is memoised against the raw URL value
 * so it's safe to feed into a react-query ``queryKey`` — identical
 * selection across renders produces an identical Set reference and
 * won't trigger spurious refetches.
 *
 * Empty selection deletes the param entirely so default views have
 * clean URLs. The encoded value is always sorted so ``{a,b}`` and
 * ``{b,a}`` produce identical URLs.
 *
 * ``separator`` defaults to ``","`` (matches the existing backend CSV
 * convention for ``species`` / ``call_type`` / ``exclude_species``
 * params where values are slugs / 6-char codes that never contain
 * commas). For AudioEvents ``labels``, pass ``"|"`` — AudioSet display
 * names routinely contain literal commas (e.g. ``"Heart sounds,
 * heartbeat"``) and would silently split into the wrong filter
 * otherwise. The backend ``labels=`` parser must split on the same
 * separator.
 *
 * ``resetPageKey`` (default ``"page"``) — the URL param to delete in
 * the SAME ``setSearchParams`` call. Pass ``null`` to disable.
 *
 * The atomic-reset behavior fixes a subtle stale-closure race: react-
 * router-dom v6 ``setSearchParams`` is ``useCallback`` with
 * ``[navigate, searchParams]`` deps and passes the closure-captured
 * ``searchParams`` to its functional updater. Two sequential
 * ``setSearchParams`` calls in the same event handler (e.g.
 * ``setSelectedSpecies(next); setPage(1)``) BOTH see the same stale
 * pre-update snapshot, and the second ``navigate(..., {replace:
 * true})`` clobbers the first. Doing chip-change + page-reset in one
 * functional update is the only safe pattern.
 */
export function useUrlMultiSelect(
  key: string,
  options: { separator?: string; resetPageKey?: string | null } = {},
): [Set<string>, (next: Set<string>) => void] {
  const separator = options.separator ?? ','
  // ``undefined`` (default) → reset "page". Explicit ``null`` → no reset.
  const resetPageKey =
    options.resetPageKey === undefined ? 'page' : options.resetPageKey
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get(key) ?? ''

  const value = useMemo(() => {
    return new Set(raw.split(separator).filter((s) => s.length > 0))
  }, [raw, separator])

  const setValue = useCallback(
    (next: Set<string>) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          if (next.size === 0) {
            params.delete(key)
          } else {
            params.set(key, Array.from(next).sort().join(separator))
          }
          // Atomic: reset page in the SAME setSearchParams call. See
          // the docstring above — splitting this into two calls is
          // the stale-closure-race bug that loses either the
          // selection or the page reset.
          if (resetPageKey) {
            params.delete(resetPageKey)
          }
          return params
        },
        { replace: true },
      )
    },
    [key, separator, resetPageKey, setSearchParams],
  )

  return [value, setValue]
}

/** Items shown per page across all paginated tables. */
export const ITEMS_PER_PAGE = 50

/**
 * Compute pagination slice helpers.
 * Returns the current page's slice and the total page count.
 */
export function paginate<T>(items: T[], page: number): { pageItems: T[]; totalPages: number } {
  const totalPages = Math.max(1, Math.ceil(items.length / ITEMS_PER_PAGE))
  const pageItems = items.slice((page - 1) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE)
  return { pageItems, totalPages }
}
