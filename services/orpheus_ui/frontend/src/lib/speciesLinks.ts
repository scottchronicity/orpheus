/**
 * Build external-reference links for a species detection.
 *
 * Prefers the IOC scientific name from the Detection's taxonomy ref
 * (introduced in the cross-classifier-identity work — every new
 * Detection from BirdNET has this). Falls back to the common name as
 * a text-search query for legacy rows that lack taxonomy.
 *
 * No mapping tables to maintain: each external site supports either
 * a deterministic URL pattern off the scientific name or a search
 * query. We never hit their APIs, just construct URLs the user can
 * click through.
 */

export interface SpeciesLink {
  label: string
  href: string
  external: true
}

interface SpeciesLinkSource {
  /** IOC scientific name when known (e.g. "Corvus brachyrhynchos"). */
  scientificName?: string | null
  /** Common name (e.g. "American Crow"). */
  commonName?: string | null
  /** AudioSet machine_id for audio-events rows (e.g. "/m/04s8yn"). */
  audiosetMid?: string | null
}

function inaturalistUrl(scientific: string): string {
  // /taxa/search resolves by scientific name with a single result hop.
  return `https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(scientific)}`
}

function wikipediaUrl(scientific: string): string {
  // Title-cased species pages are the convention; spaces → underscores.
  // Wikipedia redirects from search if the exact title doesn't exist.
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(scientific.replace(/ /g, '_'))}`
}

function gbifUrl(scientific: string): string {
  return `https://www.gbif.org/species/search?q=${encodeURIComponent(scientific)}`
}

function audiosetReferenceUrl(mid: string): string {
  // The AudioSet ontology browser at Research at Google.
  // Pattern: https://research.google.com/audioset/ontology/<mid>.html
  // but the mid format /m/<rest> needs adapting (their pages drop "/m/").
  const cleaned = mid.startsWith('/m/') ? mid.slice('/m/'.length) : mid
  return `https://research.google.com/audioset/ontology/${cleaned}.html`
}

/**
 * Build the click-through links for a species detection.
 *
 * Returns 0-4 links depending on what info is available:
 * - With scientific name: iNaturalist + Wikipedia + GBIF
 * - With AudioSet mid: an AudioSet ontology reference page
 * - Falls back to iNaturalist text search by common name when neither
 *   is available
 * - Returns an empty list if nothing usable
 */
export function buildSpeciesLinks(src: SpeciesLinkSource): SpeciesLink[] {
  const links: SpeciesLink[] = []
  const scientific = src.scientificName?.trim()
  const common = src.commonName?.trim()
  const mid = src.audiosetMid?.trim()

  if (scientific) {
    links.push(
      { label: 'iNaturalist', href: inaturalistUrl(scientific), external: true },
      { label: 'Wikipedia', href: wikipediaUrl(scientific), external: true },
      { label: 'GBIF', href: gbifUrl(scientific), external: true },
    )
  } else if (common) {
    // No scientific name — fall back to iNaturalist text search by
    // common name. Less precise but still useful.
    links.push({
      label: 'iNaturalist',
      href: inaturalistUrl(common),
      external: true,
    })
  }

  if (mid) {
    links.push({
      label: 'AudioSet',
      href: audiosetReferenceUrl(mid),
      external: true,
    })
  }

  return links
}
