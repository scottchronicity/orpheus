/**
 * Crows and Entities review fixes: crow-call events are not presented as
 * individual birds and exclude corvid detections no crow classifier analysed;
 * entities the classifiers could not name get a label instead of a blank cell.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockUseQuery = vi.fn()
vi.mock('@tanstack/react-query', () => ({ useQuery: (...a: unknown[]) => mockUseQuery(...a) }))

import { CrowEntitySection, hasCrowCall } from '../src/components/CrowEntitySection'
import { entityDisplayName } from '../src/pages/Entities'

const ev = (detection_type: string) => ({ event_id: 'e', sensor_id: 'mic-1', confidence: 0.8, detection_type })
const entity = (id: string, name: string, types: string[]) => ({
  entity_id: id,
  timestamp: '2026-11-16T14:00:00+00:00',
  species_code: 'corvus',
  common_name: name,
  confidence: 0.8,
  evidence: types.map(ev),
})

beforeEach(() => vi.clearAllMocks())

describe('Crows: correlated crow-call events', () => {
  it('counts only events with a crow-call classification', () => {
    const entities = [
      entity('a', 'American Crow', ['crow.analyzed']),
      entity('b', 'Crow', ['crow.analyzed', 'species.detected']),
      entity('c', 'Common Raven', ['species.detected']), // BirdNET only
      entity('d', 'Crow', ['audio.classified']), // PANNs only
    ]
    mockUseQuery.mockReturnValue({ data: { entities, count: 4 }, isLoading: false, error: null })
    render(<CrowEntitySection startDate="2026-11-15" endDate="2026-11-16" />)
    expect(screen.getByText('Crow Call Events')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(entities.filter(hasCrowCall).map((e) => e.entity_id)).toEqual(['a', 'b'])
  })

  it('describes correlated events, never individual birds', () => {
    mockUseQuery.mockReturnValue({ data: { entities: [entity('a', 'Crow', ['crow.analyzed'])], count: 1 }, isLoading: false, error: null })
    const { container } = render(<CrowEntitySection startDate="2026-11-15" endDate="2026-11-16" />)
    expect(screen.getByText(/not an individual bird/)).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/real crow|Verified/)
  })

  it('shows a failed request instead of loading forever', () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: false, error: new Error('HTTP 500') })
    render(<CrowEntitySection startDate="2026-11-15" endDate="2026-11-16" />)
    expect(screen.getByText('Could not load crow call events')).toBeInTheDocument()
    expect(screen.queryByText(/Loading/)).toBeNull()
  })
})

describe('Entities: a name for every row', () => {
  it.each([
    [{ common_name: 'Blue Jay', species_code: 'cyanoc' }, 'Blue Jay', true],
    [{ common_name: '', species_code: 'cyanoc' }, 'cyanoc', true],
    [{ common_name: '', species_code: 'unknown', entity_type: 'Animal.Bird.Crow' }, 'Unidentified (crow classifier)', false],
    [{ common_name: null, species_code: '', entity_type: 'Animal.Sound' }, 'Unidentified', false],
  ])('%j → %s', (e, label, identified) => {
    expect(entityDisplayName(e)).toEqual({ label, identified })
  })
})
