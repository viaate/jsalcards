// @vitest-environment node
/**
 * The street tiles fetched ahead of a flight: the ones the view it ends on is
 * drawn from, and the ones covering the screen where it stops on the way in,
 * and nothing outside the continental US's box or below zoom 7.
 */
import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import { FLIGHT_LEAD, FLIGHT_STOP_ZOOM, flightZooms } from '../flight';
import { OPENFREEMAP_MAX_ZOOM, OPENFREEMAP_MIN_ZOOM } from '../openfreemap';
import {
  MAX_FLIGHT_TILES,
  SLOW_LINK_FLIGHT_TILES,
  flightTileLimit,
  flightTiles,
  slowLink,
} from '../prefetch';
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
    // Street zoom is drawn from OpenFreeMap's deepest tiles, zoom 14; on the way in from the stop
    // at zoom 7, the flight waits where it must on zoom 10 and zoom 13 (flight.ts).
    expect(zooms).toEqual(flightZooms(OPENFREEMAP_MAX_ZOOM));
    expect(zooms).toEqual([10, 13, 14]);
    for (const zoom of zooms) {
      const first = tiles.find(([z]) => z === zoom);
      expect(first).toEqual(tileAt(PEMBROKE.lat, PEMBROKE.lon, zoom));
    }
    // Pembroke Hill's own zoom-10 tile, which the map draws long before the street tiles are in.
    expect(tiles[0]).toEqual(tileAt(PEMBROKE.lat, PEMBROKE.lon, 10));
    expect(new Set(tiles.map((tile) => tile.join('/'))).size).toBe(tiles.length);
  });

  it('cover the screen where the flight stops on the way, as it waits there for them', () => {
    const tiles = flightTiles(PEMBROKE, DESKTOP);
    // The camera stops at zoom 10: 1440 x 900 there is 2.8 by 1.8 zoom-10 tiles, all of them asked
    // for, corners too; at zoom 15.2, the view itself is a corner of one or two.
    const at10 = tiles.filter(([z]) => z === 10);
    expect(at10.length).toBeGreaterThanOrEqual(6);
    const world = 512 * 2 ** 10;
    const cx = mercatorXFromLng(PEMBROKE.lon);
    const cy = mercatorYFromLat(PEMBROKE.lat);
    for (const [dx, dy] of [
      [-1, -1],
      [1, 1],
    ] as const) {
      const x = Math.floor((cx + (dx * DESKTOP.width) / 2 / world) * 2 ** 10);
      const y = Math.floor((cy + (dy * DESKTOP.height) / 2 / world) * 2 ** 10);
      expect(at10).toContainEqual([10, x, y]);
    }
    expect(tiles.filter(([z]) => z === 14).length).toBeLessThanOrEqual(4);
  });

  it('keep to a handful, and to what a phone screen shows', () => {
    expect(flightTiles(PEMBROKE, DESKTOP).length).toBeLessThanOrEqual(MAX_FLIGHT_TILES);
    expect(flightTiles({ ...PLAZA, zoom: 12 }, { width: 3840, height: 2160 })).toHaveLength(
      MAX_FLIGHT_TILES,
    );
    const phone = flightTiles(PLAZA, PHONE);
    expect(phone.length).toBeLessThan(flightTiles(PLAZA, DESKTOP).length);
    expect(phone.length).toBeGreaterThanOrEqual(flightZooms(13).length);
  });

  it('follow the pacing of a flight: FLIGHT_LEAD apart from its stop, and the tiles it ends on', () => {
    expect(flightZooms(FLIGHT_STOP_ZOOM)).toEqual([FLIGHT_STOP_ZOOM]);
    expect(flightZooms(FLIGHT_STOP_ZOOM + FLIGHT_LEAD)).toEqual([FLIGHT_STOP_ZOOM + FLIGHT_LEAD]);
    expect(flightZooms(11)).toEqual([10, 11]);
    expect(flightZooms(12)).toEqual([10, 12]);
    expect(flightZooms(6)).toEqual([]);
    // Paced from a stop closer in, as a cut from the streets makes (index.ts): its own zoom's tiles,
    // then the ones it ends on.
    expect(flightZooms(12, 12)).toEqual([12]);
    expect(flightZooms(14, 12)).toEqual([14]);
    expect(flightZooms(14, 10)).toEqual([13, 14]);
  });

  it('take the tiles of a flight paced from a stop closer in', () => {
    const stop = { ...PEMBROKE, zoom: PEMBROKE.zoom - FLIGHT_LEAD };
    const atStop = flightTiles(stop, DESKTOP, 12);
    expect([...new Set(atStop.map(([z]) => z))]).toEqual([12]);
    expect(atStop[0]).toEqual(tileAt(PEMBROKE.lat, PEMBROKE.lon, 12));
    const atEnd = flightTiles(PEMBROKE, DESKTOP, 12);
    expect([...new Set(atEnd.map(([z]) => z))]).toEqual([14]);
  });

  it('keep to fewer on a link the browser says is slow', () => {
    expect(flightTileLimit(undefined)).toBe(MAX_FLIGHT_TILES);
    expect(flightTileLimit({ effectiveType: '4g', downlink: 10 })).toBe(MAX_FLIGHT_TILES);
    expect(flightTileLimit({ effectiveType: '4g', downlink: 1.6 })).toBe(SLOW_LINK_FLIGHT_TILES);
    expect(flightTileLimit({ effectiveType: '3g' })).toBe(SLOW_LINK_FLIGHT_TILES);
    expect(flightTileLimit({ saveData: true, effectiveType: '4g' })).toBe(SLOW_LINK_FLIGHT_TILES);
    expect(SLOW_LINK_FLIGHT_TILES).toBeLessThan(MAX_FLIGHT_TILES);
    // As Chrome reports a link held to 1.6 Mbit/s: 4G by its type, slow by its speed.
    expect(slowLink({ effectiveType: '4g', downlink: 1.65 })).toBe(true);
    expect(slowLink({ effectiveType: '4g', downlink: 10 })).toBe(false);
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
