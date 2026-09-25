/**
 * The bounds every map view stays inside, whatever the screen: the zoom range
 * and the box the center of the map never leaves. The map (limits.ts) holds
 * each screen to tighter limits inside these; view links (src/state/url.ts)
 * are held to these, since a link does not know the screen it opens on.
 *
 * This module is tiny and ships in the entry chunk with the link code.
 */
import { US_BOUNDS } from './us-geo';

/** A map view: the center in degrees and the zoom level. */
export interface MapView {
  readonly lat: number;
  readonly lon: number;
  readonly zoom: number;
}

/** Street level: the map never zooms in further. */
export const MAX_ZOOM = 16;

/**
 * The lowest zoom any view can have. A screen fits the continental US at a
 * higher zoom than this from 320 px wide up, and never lets the map zoom out
 * much past that fit (limits.ts); this floor only keeps links sane.
 */
export const MIN_ZOOM = 1;

/** Degrees the center of the map can stray past the continental US at most, at any zoom. */
const CENTER_MARGIN = 3;

/**
 * West, south, east, north: the box the center of the map stays in. The US
 * bounds grown by CENTER_MARGIN and rounded out to whole degrees, so a view
 * rounded for a link never lands outside it.
 */
export const CENTER_BOUNDS: readonly [number, number, number, number] = [
  Math.floor(US_BOUNDS[0] - CENTER_MARGIN),
  Math.floor(US_BOUNDS[1] - CENTER_MARGIN),
  Math.ceil(US_BOUNDS[2] + CENTER_MARGIN),
  Math.ceil(US_BOUNDS[3] + CENTER_MARGIN),
];

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Longitude folded into [-180, 180); a longitude already in range is returned as is. */
export function wrapLongitude(lon: number): number {
  if (lon >= -180 && lon < 180) return lon === 0 ? 0 : lon;
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/** Degrees from a to b the short way around the globe. */
function arc(a: number, b: number): number {
  const d = Math.abs(a - b) % 360;
  return Math.min(d, 360 - d);
}

/**
 * The nearest view inside the bounds: zoom and latitude clamped, and a
 * longitude outside the box moved to whichever edge is nearer around the
 * globe. Null if any number is not finite.
 */
export function clampToBounds(view: MapView): MapView | null {
  const { lat, lon, zoom } = view;
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(zoom)) return null;
  const [west, south, east, north] = CENTER_BOUNDS;
  const wrapped = wrapLongitude(lon);
  const inside = wrapped >= west && wrapped <= east;
  return {
    lat: clamp(lat, south, north),
    lon: inside ? wrapped : arc(wrapped, west) <= arc(wrapped, east) ? west : east,
    zoom: clamp(zoom, MIN_ZOOM, MAX_ZOOM),
  };
}
