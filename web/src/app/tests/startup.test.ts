import { describe, expect, it } from 'vitest';

import type { SearchHit } from '../../search';
import { ZOOM, selectionForHit, startupSelection, viewForHit, zipHit } from '../startup';

const PEMBROKE_HILL = 'A1902690';
const OTHER = '290000000001';

function hit(kind: SearchHit['kind'], id: string): SearchHit {
  return {
    kind,
    id,
    name: id,
    sub: '',
    state: 'MO',
    lat: 39.03606,
    lon: -94.593001,
    match: 'exact',
    highlight: [],
  };
}

describe('what the app opens with', () => {
  it('a link opens as sent, pin or not', () => {
    const linked = { selection: { kind: 'school', id: OTHER }, view: null } as const;
    expect(startupSelection(linked, PEMBROKE_HILL)).toBe(linked.selection);
    const view = { selection: null, view: { lat: 39, lon: -94.6, zoom: 10 } };
    expect(startupSelection(view, PEMBROKE_HILL)).toBeNull();
  });

  it('a plain visit opens the pinned school, and nothing without one', () => {
    const plain = { selection: null, view: null };
    expect(startupSelection(plain, PEMBROKE_HILL)).toEqual({ kind: 'school', id: PEMBROKE_HILL });
    expect(startupSelection(plain, null)).toBeNull();
  });
});

describe('search results', () => {
  it('open what they name: a school, district or ZIP code, and no selection for a city', () => {
    expect(selectionForHit(hit('school', PEMBROKE_HILL))).toEqual({
      kind: 'school',
      id: PEMBROKE_HILL,
    });
    expect(selectionForHit(hit('district', '2916400'))).toEqual({
      kind: 'district',
      id: '2916400',
    });
    expect(selectionForHit(hit('zip', '64113'))).toEqual({ kind: 'zip', id: '64113' });
    expect(selectionForHit(hit('city', '2938000'))).toBeNull();
  });

  it('take the map close enough to find the place', () => {
    expect(viewForHit(hit('school', PEMBROKE_HILL))).toEqual({
      lat: 39.03606,
      lon: -94.593001,
      zoom: ZOOM.school,
    });
    expect(viewForHit(hit('city', '2938000')).zoom).toBeLessThan(ZOOM.school);
  });

  it('find a ZIP code among results by its code', () => {
    const hits = [hit('zip', '64112'), hit('zip', '64113')];
    expect(zipHit(hits, '64113')).toBe(hits[1]);
    expect(zipHit(hits, '64114')).toBeNull();
  });
});
