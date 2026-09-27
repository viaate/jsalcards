/**
 * The street tiles a flight ends on, worked out before it starts, so they can
 * be asked for at once (openfreemap.ts) and be in the browser's cache by the
 * time the map needs them. A search pick flies from the whole country to a
 * street in a couple of seconds: MapLibre asks for each zoom's tiles only as
 * the camera reaches it, so without them the map would be empty from zoom 7
 * until the last tiles arrive.
 *
 * The tiles are the ones covering the screen at the view's own tile zoom,
 * and at a few zoom levels below it, which the flight passes on its way in
 * and which the map draws, scaled up, until the closer ones are in. Plain
 * math on Web Mercator tile numbers, as MapLibre counts them: 512 px tiles,
 * a view at zoom 13.2 drawn from zoom 13 tiles.
 */
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';
import type { MapView } from './bounds';
import type { Size } from './limits';
import { OPENFREEMAP_MAX_ZOOM, OPENFREEMAP_MIN_ZOOM } from './openfreemap';
import { US_BOUNDS } from './us-geo';

/** A tile: zoom, column, row. */
export type TileId = readonly [z: number, x: number, y: number];

/** MapLibre's vector tiles are 512 px. */
const TILE_SIZE = 512;

/**
 * Zoom levels below the view's tile zoom whose tiles are fetched, furthest
 * first: the flight passes those first, and they cover the most with the
 * fewest tiles.
 */
export const FLIGHT_STEPS: readonly number[] = Object.freeze([6, 3, 0]);

/** At most this many tiles for one flight: a large screen at street zoom and the steps above it. */
export const MAX_FLIGHT_TILES = 24;

/** Tile columns (or rows) from `lo` to `hi` world units at zoom `z`, inside the world. */
function span(lo: number, hi: number, z: number): number[] {
  const count = 2 ** z;
  const first = Math.max(0, Math.floor(lo * count));
  const last = Math.min(count - 1, Math.floor(hi * count));
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

/**
 * The street tiles covering a screen of `size` at `view`, at its tile zoom
 * and FLIGHT_STEPS below it, from OpenFreeMap's first zoom up: the furthest
 * zoom first and, within a zoom, the middle of the screen first. Only tiles
 * that reach the continental US's box: the rest would be cut away whole
 * (street-tiles.ts). None below OpenFreeMap's first zoom, where nothing is
 * fetched at all.
 */
export function flightTiles(view: MapView, size: Size): TileId[] {
  const top = Math.min(Math.floor(view.zoom), OPENFREEMAP_MAX_ZOOM);
  if (top < OPENFREEMAP_MIN_ZOOM) return [];
  const cx = mercatorXFromLng(view.lon);
  const cy = mercatorYFromLat(view.lat);
  // Half the screen in world units at the view's zoom.
  const world = TILE_SIZE * 2 ** view.zoom;
  const halfX = size.width / 2 / world;
  const halfY = size.height / 2 / world;
  const [west, south, east, north] = US_BOUNDS;
  const usX = [mercatorXFromLng(west), mercatorXFromLng(east)] as const;
  const usY = [mercatorYFromLat(north), mercatorYFromLat(south)] as const;
  const tiles: TileId[] = [];
  const seen = new Set<number>();
  for (const step of FLIGHT_STEPS) {
    const z = top - step;
    if (z < OPENFREEMAP_MIN_ZOOM || seen.has(z)) continue;
    seen.add(z);
    const count = 2 ** z;
    const zoomTiles: { tile: TileId; away: number }[] = [];
    for (const x of span(Math.max(cx - halfX, usX[0]), Math.min(cx + halfX, usX[1]), z)) {
      for (const y of span(Math.max(cy - halfY, usY[0]), Math.min(cy + halfY, usY[1]), z)) {
        const away = Math.hypot((x + 0.5) / count - cx, (y + 0.5) / count - cy);
        zoomTiles.push({ tile: [z, x, y], away });
      }
    }
    zoomTiles.sort((a, b) => a.away - b.away);
    tiles.push(...zoomTiles.map(({ tile }) => tile));
  }
  return tiles.slice(0, MAX_FLIGHT_TILES);
}
