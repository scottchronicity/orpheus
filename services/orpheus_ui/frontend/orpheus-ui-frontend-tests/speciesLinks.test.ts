import { describe, it, expect } from 'vitest'
import { buildSpeciesLinks } from '../src/lib/speciesLinks'

describe('buildSpeciesLinks', () => {
  it('returns 3 links for an IOC scientific name', () => {
    const links = buildSpeciesLinks({
      scientificName: 'Corvus brachyrhynchos',
      commonName: 'American Crow',
    })
    const labels = links.map((l) => l.label)
    expect(labels).toContain('iNaturalist')
    expect(labels).toContain('Wikipedia')
    expect(labels).toContain('GBIF')
  })

  it('encodes scientific name with underscores for Wikipedia', () => {
    const links = buildSpeciesLinks({
      scientificName: 'Corvus brachyrhynchos',
    })
    const wiki = links.find((l) => l.label === 'Wikipedia')
    expect(wiki?.href).toContain('Corvus_brachyrhynchos')
  })

  it('encodes scientific name for iNaturalist as a search query', () => {
    const links = buildSpeciesLinks({
      scientificName: 'Corvus brachyrhynchos',
    })
    const inat = links.find((l) => l.label === 'iNaturalist')
    expect(inat?.href).toContain('q=Corvus%20brachyrhynchos')
  })

  it('falls back to common-name search when no scientific name', () => {
    const links = buildSpeciesLinks({
      commonName: 'American Crow',
    })
    // Only the iNaturalist fallback.
    expect(links.length).toBe(1)
    expect(links[0].label).toBe('iNaturalist')
    expect(links[0].href).toContain('American%20Crow')
  })

  it('returns AudioSet link when given an AudioSet machine_id', () => {
    const links = buildSpeciesLinks({
      scientificName: 'Corvus brachyrhynchos',
      audiosetMid: '/m/04s8yn',
    })
    const audioset = links.find((l) => l.label === 'AudioSet')
    expect(audioset?.href).toBe(
      'https://research.google.com/audioset/ontology/04s8yn.html',
    )
  })

  it('returns empty array when nothing is provided', () => {
    expect(buildSpeciesLinks({})).toEqual([])
  })

  it('still works with only the audioset_mid', () => {
    const links = buildSpeciesLinks({ audiosetMid: '/m/04s8yn' })
    expect(links.length).toBe(1)
    expect(links[0].label).toBe('AudioSet')
  })

  it('handles whitespace-only inputs as empty', () => {
    const links = buildSpeciesLinks({
      scientificName: '   ',
      commonName: '   ',
    })
    expect(links).toEqual([])
  })
})
