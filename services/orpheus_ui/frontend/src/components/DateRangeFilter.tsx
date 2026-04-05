/**
 * DateRangeFilter - Reusable date range filter component
 * 
 * Provides Start/End date pickers with preset buttons (1 day, 7 days, 30 days).
 * Used across Birds.tsx, Crows.tsx, and other data visualization pages.
 */
import { useState, useEffect, useCallback } from 'react'
import { Calendar } from 'lucide-react'
import { Card } from './ui'

interface DateRangeFilterProps {
  startDate: string
  endDate: string
  onDateChange: (startDate: string, endDate: string) => void
}

/**
 * Format date as YYYY-MM-DD
 */
function formatDate(date: Date): string {
  return date.toISOString().split('T')[0]
}

/**
 * Get date N days ago
 */
function getDaysAgo(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return formatDate(date)
}

/**
 * Get today's date
 */
function getToday(): string {
  return formatDate(new Date())
}

export function DateRangeFilter({ startDate, endDate, onDateChange }: DateRangeFilterProps) {
  const [localStart, setLocalStart] = useState(startDate)
  const [localEnd, setLocalEnd] = useState(endDate)
  const [activePreset, setActivePreset] = useState<number | null>(1)

  // Sync local state with props
  useEffect(() => {
    setLocalStart(startDate)
    setLocalEnd(endDate)
  }, [startDate, endDate])

  const handleApply = () => {
    setActivePreset(null)
    onDateChange(localStart, localEnd)
  }

  const handlePreset = (days: number) => {
    const newStart = getDaysAgo(days)
    const newEnd = getToday()
    setLocalStart(newStart)
    setLocalEnd(newEnd)
    setActivePreset(days)
    onDateChange(newStart, newEnd)
  }

  // Calculate days in range for display
  const start = new Date(localStart)
  const end = new Date(localEnd)
  const diffDays = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24))

  let rangeLabel = ''
  if (diffDays === 0 || diffDays === 1) {
    rangeLabel = 'Last 1 Day'
  } else if (diffDays === 7) {
    rangeLabel = 'Last 7 Days'
  } else if (diffDays === 30) {
    rangeLabel = 'Last 30 Days'
  } else {
    rangeLabel = `${diffDays} Days`
  }

  const presetClass = (days: number) =>
    activePreset === days
      ? 'px-3 py-1.5 bg-blue-600 text-white text-sm rounded transition-colors'
      : 'px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm rounded transition-colors'

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-4">
        {/* Date Range Icon and Label */}
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-slate-400" />
          <span className="text-sm text-slate-400">Date Range:</span>
          <span className="text-sm text-blue-400 font-medium">({rangeLabel})</span>
        </div>

        {/* Date Inputs */}
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={localStart}
            onChange={(e) => { setLocalStart(e.target.value); setActivePreset(null) }}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <span className="text-slate-400">to</span>
          <input
            type="date"
            value={localEnd}
            onChange={(e) => { setLocalEnd(e.target.value); setActivePreset(null) }}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Apply Button */}
        <button
          onClick={handleApply}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
        >
          Apply
        </button>

        {/* Preset Buttons */}
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
 * Hook to manage date range state with defaults
 */
export function useDateRange(defaultDays: number = 7) {
  const [startDate, setStartDate] = useState(() => getDaysAgo(defaultDays))
  const [endDate, setEndDate] = useState(() => getToday())

  const handleDateChange = (start: string, end: string) => {
    setStartDate(start)
    setEndDate(end)
  }

  return {
    startDate,
    endDate,
    handleDateChange,
  }
}

/**
 * Hook that combines date range state with a page counter.
 * Resets to page 1 whenever the date range changes.
 *
 * Usage:
 *   const { startDate, endDate, handleDateChange, page, setPage } = usePaginatedDateRange(1)
 */
export function usePaginatedDateRange(defaultDays: number = 1) {
  const [startDate, setStartDate] = useState(() => getDaysAgo(defaultDays))
  const [endDate, setEndDate] = useState(() => getToday())
  const [page, setPage] = useState(1)

  const handleDateChange = useCallback((start: string, end: string) => {
    setStartDate(start)
    setEndDate(end)
    setPage(1)
  }, [])

  return { startDate, endDate, handleDateChange, page, setPage }
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
