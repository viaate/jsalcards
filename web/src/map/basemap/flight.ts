/**
 * How a flight into streets keeps them on screen all the way in.
 *
 * A search pick flies from the whole country to a street: first to a stop
 * over its destination at the street tiles' first zoom, where the bundled
 * lines still show (FLIGHT_STOP_ZOOM), then straight in. MapLibre
 * asks for each zoom's street tiles only as the camera reaches it, and draws
 * the closest ones it has, scaled up, until they arrive. On a busy phone the
 * camera outruns them: zoom 13 drawn from zoom 7 tiles is a few highways on
 * black, and before the first street tiles are in, nothing at all.
 *
 * So the last leg is paced by the tiles: the camera never goes more than
 * FLIGHT_LEAD zoom levels past the coarsest street tiles the map draws across
 * the screen (streetTileZoom), and not past its stop while some part of the
 * screen has none yet. Where they keep up, the flight is one smooth glide;
 * where they lag, it waits for them, drawn, and glides on. A wait that
 * outlasts FLIGHT_HOLD_MS, or tiles that fail, end the pacing: the flight
 * goes on without them.
 */

import { OPENFREEMAP_MIN_ZOOM } from './openfreemap';

/**
 * Where a flight into streets the map has none of stops first: the first
 * zoom of the street tiles, where the bundled lines still show.
 */
export const FLIGHT_STOP_ZOOM = OPENFREEMAP_MIN_ZOOM;

/** Zoom levels past the coarsest street tiles on screen a flight may be: tiles drawn at most 8 times their size. */
export const FLIGHT_LEAD = 3;

/** The longest a flight waits for street tiles still loading, in milliseconds, before going on without them. */
export const FLIGHT_HOLD_MS = 8000;

/** How long the last leg takes per zoom level, in milliseconds: 3.2 s from the stop to a school. */
export const FLIGHT_MS_PER_ZOOM = 400;

/**
 * The closest zoom the camera may be at with street tiles of zoom `coarsest`
 * the coarsest on screen; `stopZoom` while none is drawn yet, where the
 * bundled lines still show.
 */
export function flightCeiling(coarsest: number | null, stopZoom: number): number {
  return coarsest === null ? stopZoom : Math.max(stopZoom, coarsest + FLIGHT_LEAD);
}

/** A loaded tile: its place in the tile pyramid, and the zoom it is drawn from (MapLibre's overscaledZ). */
export interface LoadedTile {
  readonly z: number;
  readonly x: number;
  readonly y: number;
  readonly zoom: number;
}

/** A point on the screen, in Web Mercator units (0 to 1 across the world). */
export interface WorldPoint {
  readonly x: number;
  readonly y: number;
}

/** Columns and rows of points across the screen that streetTileZoom looks at. */
export const COVER_GRID = { columns: 6, rows: 4 } as const;

/**
 * The zoom of the coarsest street tiles the map draws across the screen: at
 * each point, the closest loaded tile there, which MapLibre draws (scaled up
 * where the ideal one is still loading), and the coarsest of those; null
 * while some point has no loaded tile, where MapLibre draws nothing.
 */
export function streetTileZoom(
  points: readonly WorldPoint[],
  tiles: readonly LoadedTile[],
): number | null {
  let coarsest: number | null = null;
  for (const point of points) {
    let closest: number | null = null;
    for (const tile of tiles) {
      const count = 2 ** tile.z;
      if (Math.floor(point.x * count) !== tile.x || Math.floor(point.y * count) !== tile.y)
        continue;
      if (closest === null || tile.zoom > closest) closest = tile.zoom;
    }
    if (closest === null) return null;
    if (coarsest === null || closest < coarsest) coarsest = closest;
  }
  return coarsest;
}

/** The points streetTileZoom looks at on a screen of `width` by `height`: the middle of each cell of COVER_GRID. */
export function coverPoints(width: number, height: number): [number, number][] {
  const points: [number, number][] = [];
  for (let row = 0; row < COVER_GRID.rows; row++) {
    for (let column = 0; column < COVER_GRID.columns; column++) {
      points.push([
        ((column + 0.5) / COVER_GRID.columns) * width,
        ((row + 0.5) / COVER_GRID.rows) * height,
      ]);
    }
  }
  return points;
}

/**
 * How far along a zoom from `from` to `to` the camera is at `zoom`, 0 to 1:
 * MapLibre's easeTo moves the zoom evenly with its progress. A leg that goes
 * nowhere is done.
 */
export function progressAt(from: number, to: number, zoom: number): number {
  if (!(to - from > 1e-9)) return 1;
  return Math.min(1, Math.max(0, (zoom - from) / (to - from)));
}

/**
 * The leg's progress this frame: as far as its easing wants, no further than
 * `limit`, and never back.
 */
export function pacedProgress(shown: number, wanted: number, limit: number): number {
  return Math.max(shown, Math.min(wanted, limit));
}

/** Eases in and out, as MapLibre's own flights do: slow off the stop, slow onto the school. */
export function flightEasing(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
}

/**
 * The zooms of the street tiles a flight paced from tiles of zoom `from` (its
 * stop's) in to tiles of zoom `top` draws on its way, where the tiles lag:
 * FLIGHT_LEAD apart from `from`, and `top` itself. The tiles fetched ahead of
 * it (prefetch.ts).
 */
export function flightZooms(top: number, from: number = FLIGHT_STOP_ZOOM): number[] {
  const zooms: number[] = [];
  for (let zoom = from + FLIGHT_LEAD; zoom < top; zoom += FLIGHT_LEAD) zooms.push(zoom);
  if (top >= FLIGHT_STOP_ZOOM) zooms.push(top);
  return zooms;
}
