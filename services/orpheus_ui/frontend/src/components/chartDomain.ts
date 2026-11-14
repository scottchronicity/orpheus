/**
 * X-axis domain for the time-vs-confidence scatter charts
 * (Birds / Crows / Entities / Audio Events).
 *
 * Uses the selected [startDate, endDate] range, but CLAMPS the upper bound to
 * `now` so the axis never runs hours into the future. endDate is the end of
 * the *day*, so without this the right side of the chart rendered as a big
 * empty gap (data stops at "now", axis ran to 23:59). Local-time boundaries
 * (no 'Z') so the domain aligns with the displayed timestamps. Falls back to
 * ['auto', 'auto'] when no range is provided.
 */
export function scatterXDomain(
  startDate?: string,
  endDate?: string,
  now: number = Date.now(),
): [number | string, number | string] {
  if (!startDate || !endDate) return ['auto', 'auto']
  const start = new Date(startDate + 'T00:00:00').getTime()
  const end = new Date(endDate + 'T23:59:59').getTime()
  // Never run past 'now'; never collapse the upper bound below start.
  return [start, Math.max(start, Math.min(end, now))]
}
