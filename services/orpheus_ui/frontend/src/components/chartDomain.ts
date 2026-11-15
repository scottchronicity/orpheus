/**
 * X-axis domain for the time-vs-confidence scatter charts
 * (Birds / Crows / Entities / Audio Events).
 *
 * Prefers the extent of the DATA being plotted, falling back to the selected
 * [startDate, endDate] range when there is none.
 *
 * Why the data and not the range: the range is a whole day (or 30 days), but a
 * time-of-day filter selects a slice of it. Spanning the full day meant an
 * hour-long selection rendered as a single vertical line of points stacked on
 * one edge — every point at effectively the same x — which reads as a broken
 * chart rather than as "these all happened within one hour". Fitting the axis
 * to the data spreads those points across the width, which is the only way the
 * time axis says anything useful about a narrow selection.
 *
 * The range still bounds the fallback, and the upper bound is CLAMPED to `now`
 * so the axis never runs hours into the future (endDate is the end of the day,
 * so without the clamp the right side rendered as a big empty gap).
 */

/** Smallest span we will render, so a single point isn't an infinitely thin axis. */
const MIN_SPAN_MS = 10 * 60 * 1000 // 10 minutes

/** A day, in ms — the point where tick labels stop needing a clock time. */
const ONE_DAY_MS = 24 * 60 * 60 * 1000

/**
 * Tick label for a time axis spanning ``domain``: a clock time when the axis
 * covers less than a day (every tick would otherwise print the same date and
 * the axis would say nothing), a date when it covers more.
 *
 * ``timeZone`` undefined renders in the viewer's local zone; pass "UTC" to
 * follow the page's Local/UTC toggle.
 */
export function scatterTickFormatter(
  domain: [number | string, number | string],
  timeZone?: string,
): (value: number) => string {
  const [lo, hi] = domain
  const spansLessThanADay =
    typeof lo === 'number' && typeof hi === 'number' && hi - lo < ONE_DAY_MS
  const opts: Intl.DateTimeFormatOptions = spansLessThanADay
    ? { hour: 'numeric', minute: '2-digit' }
    : { month: 'numeric', day: 'numeric' }
  if (timeZone) opts.timeZone = timeZone
  return (value: number) => new Date(value).toLocaleString(undefined, opts)
}

export function scatterXDomain(
  startDate?: string,
  endDate?: string,
  now: number = Date.now(),
  /** Epoch-ms x values of the points being plotted, if any. */
  dataX?: number[],
): [number | string, number | string] {
  // Data-driven: what is actually on screen decides the axis.
  if (dataX && dataX.length > 0) {
    const valid = dataX.filter((x) => Number.isFinite(x))
    if (valid.length > 0) {
      const lo = Math.min(...valid)
      const hi = Math.max(...valid)
      const span = Math.max(hi - lo, MIN_SPAN_MS)
      // A little breathing room so points never sit on the axis line itself.
      const pad = span * 0.05
      const mid = (lo + hi) / 2
      const half = Math.max(span / 2, MIN_SPAN_MS / 2)
      return [Math.round(mid - half - pad), Math.round(mid + half + pad)]
    }
  }

  if (!startDate || !endDate) return ['auto', 'auto']
  const start = new Date(startDate + 'T00:00:00').getTime()
  const end = new Date(endDate + 'T23:59:59').getTime()
  // Never run past 'now'; never collapse the upper bound below start.
  return [start, Math.max(start, Math.min(end, now))]
}
