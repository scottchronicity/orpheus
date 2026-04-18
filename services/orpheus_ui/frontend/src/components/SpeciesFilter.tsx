/**
 * SpeciesFilter - Reusable multi-select checklist for filtering detections.
 *
 * UX model: positive-selection-only.
 *   - Empty set = "All" (no filtering).  Checkboxes appear unchecked in this
 *     state; the label reads "Species: All (N)".
 *   - Picking any item narrows the view to only the items in the set.
 *   - An "All" button (visible whenever narrowing is active) resets to empty.
 *   - If the user manually picks every available item, we collapse back to
 *     empty for URL cleanliness.
 *
 * Parent owns the selected Set and passes a CSV to the API. The API treats
 * an absent/empty param as "all", so there's no sentinel needed.
 */
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Filter } from 'lucide-react'
import { Card } from './ui'

interface SpeciesFilterProps {
  /** All items present in the date range, with counts for display. */
  availableItems: { value: string; count: number }[]
  /** Currently selected values. Empty set means "All". */
  selected: Set<string>
  onChange: (next: Set<string>) => void
  /** Label shown in the button, e.g. "Species" or "Call Types". */
  label?: string
}

export function SpeciesFilter({
  availableItems,
  selected,
  onChange,
  label = 'Species',
}: SpeciesFilterProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const allCount = availableItems.length
  const isAll = selected.size === 0
  const buttonLabel = isAll
    ? `${label}: All (${allCount})`
    : `${label}: ${selected.size} of ${allCount}`

  const toggle = (value: string) => {
    const next = new Set(selected)
    if (next.has(value)) {
      next.delete(value)
    } else {
      next.add(value)
    }
    // If the user picked every available item, collapse back to "All".
    if (next.size === allCount) {
      onChange(new Set())
    } else {
      onChange(next)
    }
  }

  const showAll = () => onChange(new Set())

  return (
    <Card className="p-4">
      <div ref={rootRef} className="relative inline-block">
        <button
          type="button"
          onClick={() => setOpen(v => !v)}
          disabled={availableItems.length === 0}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-200 text-sm rounded transition-colors"
        >
          <Filter className="w-4 h-4" />
          <span>{availableItems.length === 0 ? `${label}: none in range` : buttonLabel}</span>
          <ChevronDown className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {open && availableItems.length > 0 && (
          <div className="absolute left-0 z-40 mt-2 w-80 max-h-96 overflow-y-auto bg-slate-800 border border-slate-700 rounded-lg shadow-xl">
            <div className="sticky top-0 bg-slate-800 border-b border-slate-700 px-3 py-2 flex items-center justify-between gap-2">
              <span className="text-xs text-slate-400">
                {isAll
                  ? `Showing all ${allCount}. Select any to narrow.`
                  : `Showing ${selected.size} of ${allCount}.`}
              </span>
              {!isAll && (
                <button
                  onClick={showAll}
                  className="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap"
                >
                  All
                </button>
              )}
            </div>
            <ul className="py-1">
              {availableItems.map(item => {
                const checked = selected.has(item.value)
                return (
                  <li key={item.value}>
                    <button
                      type="button"
                      onClick={() => toggle(item.value)}
                      className="w-full flex items-center justify-between px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 text-left"
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <span className={`w-4 h-4 flex items-center justify-center rounded border ${checked ? 'bg-blue-600 border-blue-600' : 'border-slate-500'}`}>
                          {checked && <Check className="w-3 h-3 text-white" />}
                        </span>
                        <span className="truncate">{item.value}</span>
                      </span>
                      <span className="text-xs text-slate-400 ml-2">{item.count}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
