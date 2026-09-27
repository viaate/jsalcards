/**
 * What the app opens with, and where the map goes for a school, district,
 * ZIP code or city.
 *
 * A link wins: its selection and its view open as sent. A plain visit (no
 * selection, no view) opens the pinned school, if there is one, as if it had
 * been linked. A selection without a view moves the map to it once the data
 * that places it has loaded; with no such data the map stays where it is.
 */

import type { MapView } from '../map/basemap/bounds';
import type { SearchHit } from '../search';
import type { Selection, UrlState } from '../state/url';
import type { SchoolId } from '../types/generated';

/** How close the map comes for each kind of place. */
export const ZOOM = Object.freeze({
  /** Streets named and buildings drawn around the school. */
  school: 15,
  zip: 12,
  city: 11,
  district: 11,
  /** A district's schools are fitted, no closer than this. */
  districtMax: 13,
});

/** The selection to open at startup: the link's, else the pinned school on a plain visit. */
export function startupSelection(state: UrlState, pinned: SchoolId | null): Selection | null {
  if (state.selection !== null) return state.selection;
  if (state.view === null && pinned !== null) return { kind: 'school', id: pinned };
  return null;
}

/** Where the map goes for a search result. */
export function viewForHit(hit: Pick<SearchHit, 'kind' | 'lat' | 'lon'>): MapView {
  return { lat: hit.lat, lon: hit.lon, zoom: ZOOM[hit.kind] };
}

/** The selection a search result opens; a city opens none. */
export function selectionForHit(hit: Pick<SearchHit, 'kind' | 'id'>): Selection | null {
  switch (hit.kind) {
    case 'school':
      return { kind: 'school', id: hit.id };
    case 'district':
      return { kind: 'district', id: hit.id };
    case 'zip':
      return { kind: 'zip', id: hit.id };
    case 'city':
      return null;
  }
}

/** The ZIP code result for `zip` among search results, or null. */
export function zipHit(hits: readonly SearchHit[], zip: string): SearchHit | null {
  return hits.find((hit) => hit.kind === 'zip' && hit.id === zip) ?? null;
}
