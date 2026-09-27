// @vitest-environment node
/**
 * The street tiles fetched ahead of a flight: the ones the view it ends on is
 * drawn from, and a few levels below, which the map draws scaled up on the
 * way in, and nothing outside the continental US's box or below zoom 7.
 */
import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import { OPENFREEMAP_MAX_ZOOM, OPENFREEMAP_MIN_ZOOM } from '../openfreemap';
import { FLIGHT_STEPS, MAX_FLIGHT_TILES, flightTiles } from '../prefetch';
import type { TileId } from '../prefetch';

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 412, height: 915 };
/** Pembroke Hill at street zoom, and Kansas City's Plaza a little further out. */
const PEMBROKE = { lat: 39.0362, lon: -94.593, zoom: 15.2 };
const PLAZA = { lat: 39.045, lon: -94.595, zoom: 13.2 };

/** The tile holding a point at zoom z. */
function tileAt(lat: number, lon: number, z: number): TileId {
  const count = 2 ** z;
  return [z, Math.floor(mercatorXFromLng(lon) * count), Math.floor(mercatorYFromLat(lat) * count)];
}

describe('the tiles fetched ahead of a flight', () => {
  it('cover the screen the flight ends on, from the tiles it is drawn from', () => {
    const tiles = flightTiles(PLAZA, DESKTOP);
    const top = tiles.filter(([z]) => z === 13);
    // 1440 x 900 at zoom 13.2 is 2.4 by 1.5 zoom-13 tiles: 3 or 4 across, 2 or 3 down.
    expect(top.length).toBeGreaterThanOrEqual(6);
    expect(top.length).toBeLessThanOrEqual(12);
    expect(top).toContainEqual(tileAt(PLAZA.lat, PLAZA.lon, 13));
    // Its corners too.
    const [z] = top[0] ?? [0];
    const world = 512 * 2 ** PLAZA.zoom;
    const cx = mercatorXFromLng(PLAZA.lon);
    const cy = mercatorYFromLat(PLAZA.lat);
    for (const [dx, dy] of [
      [-1, -1],
      [1, 1],
    ] as const) {
      const x = Math.floor((cx + (dx * DESKTOP.width) / 2 / world) * 2 ** z);
      const y = Math.floor((cy + (dy * DESKTOP.height) / 2 / world) * 2 ** z);
      expect(top).toContainEqual([z, x, y]);
    }
  });

  it('take the zooms the flight passes, furthest first, the middle of each first', () => {
    const tiles = flightTiles(PEMBROKE, DESKTOP);
    const zooms = [...new Set(tiles.map(([z]) => z))];
    // Street zoom is drawn from OpenFreeMap's deepest tiles, zoom 14.
    expect(zooms).toEqual(FLIGHT_STEPS.map((step) => OPENFREEMAP_MAX_ZOOM - step));
    expect(zooms).toEqual([...zooms].sort((a, b) => a - b));
    for (const zoom of zooms) {
      const first = tiles.find(([z]) => z === zoom);
      expect(first).toEqual(tileAt(PEMBROKE.lat, PEMBROKE.lon, zoom));
    }
    // Pembroke Hill's own zoom-8 tile, which the map can draw long before the street tiles are in.
    expect(tiles[0]).toEqual(tileAt(PEMBROKE.lat, PEMBROKE.lon, 8));
    expect(new Set(tiles.map((tile) => tile.join('/'))).size).toBe(tiles.length);
  });

  it('keep to a handful, and to what a phone screen shows', () => {
    expect(flightTiles(PEMBROKE, DESKTOP).length).toBeLessThanOrEqual(MAX_FLIGHT_TILES);
    expect(flightTiles({ ...PLAZA, zoom: 12 }, { width: 3840, height: 2160 })).toHaveLength(
      MAX_FLIGHT_TILES,
    );
    const phone = flightTiles(PLAZA, PHONE);
    expect(phone.length).toBeLessThan(flightTiles(PLAZA, DESKTOP).length);
    expect(phone.length).toBeGreaterThanOrEqual(FLIGHT_STEPS.length);
  });

  it('ask for nothing below zoom 7, nor below it on the way', () => {
    expect(flightTiles({ ...PLAZA, zoom: 6.9 }, DESKTOP)).toEqual([]);
    const city = flightTiles({ ...PLAZA, zoom: 9.5 }, DESKTOP);
    expect(city.length).toBeGreaterThan(0);
    expect(city.every(([z]) => z >= OPENFREEMAP_MIN_ZOOM && z <= 9)).toBe(true);
  });

  it('ask for nothing wholly outside the continental US', () => {
    // Out over the Gulf of Maine and into New Brunswick, at the edge of the US box.
    const tiles = flightTiles({ lat: 44.9, lon: -66.2, zoom: 12 }, DESKTOP);
    const east = mercatorXFromLng(-66.95);
    for (const [z, x] of tiles) expect(x / 2 ** z).toBeLessThanOrEqual(east);
  });
});
