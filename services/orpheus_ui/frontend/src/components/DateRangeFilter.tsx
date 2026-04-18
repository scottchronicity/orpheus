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
import { Calendar, Clock } from 'lucide-react'
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
 * Hook that combines date + time-of-day range state with a page counter.
 * Resets to page 1 whenever the range changes.
 *
 * Usage:
 *   const { startDate, endDate, startTime, endTime, handleChange, page, setPage }
 *     = usePaginatedDateRange(1)
 */
export function usePaginatedDateRange(defaultDays: number = 1) {
  const [startDate, setStartDate] = useState(() => getDaysAgo(defaultDays))
  const [endDate, setEndDate] = useState(() => getToday())
  const [startTime, setStartTime] = useState(DEFAULT_START_TIME)
  const [endTime, setEndTime] = useState(DEFAULT_END_TIME)
  const [page, setPage] = useState(1)

  const handleChange = useCallback((value: DateTimeRange) => {
    setStartDate(value.startDate)
    setEndDate(value.endDate)
    setStartTime(value.startTime)
    setEndTime(value.endTime)
    setPage(1)
  }, [])

  return { startDate, endDate, startTime, endTime, handleChange, page, setPage }
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
