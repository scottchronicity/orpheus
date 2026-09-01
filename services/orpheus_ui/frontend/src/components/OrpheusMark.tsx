/**
 * The Orpheus mark: a lyre whose arms curve to read as wings, with a bird's
 * head where the crossbar sits.
 *
 * This is the same drawing the documentation site uses (docs/assets/logo.svg),
 * kept in sync by hand — it is eleven path commands and has not changed since
 * it was drawn. The dashboard previously used Lucide's stock `Bird` icon here,
 * which meant the two surfaces showed different marks for the same project.
 *
 * Strokes use `currentColor` so the caller sets the colour with a text class,
 * the way the Lucide icons it sits beside do.
 */
export function OrpheusMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.3}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label="Orpheus"
    >
      {/* lyre arms, curved so they read as wings */}
      <path d="M16 38C9.5 31 8.5 20.5 13.5 12.5c3 5.6 3.2 11 2.2 15.5" />
      <path d="M32 38c6.5-7 7.5-17.5 2.5-25.5-3 5.6-3.2 11-2.2 15.5" />
      {/* strings */}
      <path d="M19.5 34.5V19" />
      <path d="M24 34.5V19.5" />
      <path d="M28.5 34.5V19" />
      {/* bird head and beak where the crossbar sits */}
      <circle cx="24" cy="14" r="3.4" />
      <path d="M27.2 12.7 33 11" />
      {/* base */}
      <path d="M15 39h18" />
    </svg>
  )
}
