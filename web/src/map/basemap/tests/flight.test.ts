// @vitest-environment node
/**
 * A flight into streets is paced by the street tiles on screen: never more
 * than FLIGHT_LEAD zoom levels past the coarsest of them, so no frame on the
 * way in is drawn from tiles too coarse to show a street.
 */
import { describe, expect, it } from 'vitest';

import {
  FLIGHT_DEADLINE_MS,
  FLIGHT_HOLD_MS,
  FLIGHT_LAST_CALL_MS,
  FLIGHT_LEAD,
  FLIGHT_MS_PER_ZOOM,
  FLIGHT_STOP_ZOOM,
  COVER_GRID,
  coverPoints,
  flightCeiling,
  flightEasing,
  holdVerdict,
  pacedProgress,
  progressAt,
  streetTileZoom,
} from '../flight';
import type { LoadedTile, WorldPoint } from '../flight';
import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import { OPENFREEMAP_MIN_ZOOM } from '../openfreemap';

describe('a flight paced by the street tiles', () => {
  it('stops where the street tiles start, the bundled lines still showing', () => {
    expect(FLIGHT_STOP_ZOOM).toBe(OPENFREEMAP_MIN_ZOOM);
  });

  it('waits at its stop until the first street tiles are drawn', () => {
    expect(flightCeiling(null, FLIGHT_STOP_ZOOM)).toBe(FLIGHT_STOP_ZOOM);
    expect(flightCeiling(7, FLIGHT_STOP_ZOOM)).toBe(7 + FLIGHT_LEAD);
    expect(flightCeiling(13, FLIGHT_STOP_ZOOM)).toBe(13 + FLIGHT_LEAD);
    // Tiles drawn at most eight times their size.
    expect(2 ** FLIGHT_LEAD).toBeLessThanOrEqual(8);
  });

  it('goes by the coarsest tiles drawn across the screen, and by none while part of it has none', () => {
    // Denver at the stop: zoom 7 tile 26/48 holds the middle of the screen, 27/47 a corner.
    const denver = { x: mercatorXFromLng(-104.88), y: mercatorYFromLat(39.76) };
    const tile = (z: number, zoom = z): LoadedTile => ({
      z,
      x: Math.floor(denver.x * 2 ** z),
      y: Math.floor(denver.y * 2 ** z),
      zoom,
    });
    expect(tile(7)).toEqual({ z: 7, x: 26, y: 48, zoom: 7 });
    const middle: WorldPoint[] = [denver];
    // Only the corner's tile is in: the middle has nothing drawn, and the flight waits at its stop.
    const corner: LoadedTile = { z: 7, x: 27, y: 47, zoom: 7 };
    expect(streetTileZoom(middle, [corner])).toBeNull();
    expect(flightCeiling(streetTileZoom(middle, [corner]), FLIGHT_STOP_ZOOM)).toBe(
      FLIGHT_STOP_ZOOM,
    );
    // The middle's own tile: drawn from zoom 7.
    expect(streetTileZoom(middle, [corner, tile(7)])).toBe(7);
    // The closest tile at a point is the one drawn there: zoom 10 over zoom 7.
    expect(streetTileZoom(middle, [tile(7), tile(10)])).toBe(10);
    // Across the screen, the coarsest: a point drawn from zoom 7 holds the flight to zoom 10.
    const east = { x: denver.x + 1 / 2 ** 9, y: denver.y };
    expect(streetTileZoom([denver, east], [tile(7), tile(10)])).toBe(7);
    // Past OpenFreeMap's last zoom a tile is drawn scaled: its zoom is the view's (overscaledZ).
    expect(streetTileZoom(middle, [tile(14, 15)])).toBe(15);
    expect(streetTileZoom([], [tile(7)])).toBeNull();
  });

  it('looks at the whole screen, cell by cell', () => {
    const points = coverPoints(1440, 900);
    expect(points).toHaveLength(COVER_GRID.columns * COVER_GRID.rows);
    for (const [x, y] of points) {
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(1440);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(900);
    }
    expect(Math.min(...points.map(([x]) => x))).toBeLessThan(1440 / 8);
    expect(Math.max(...points.map(([x]) => x))).toBeGreaterThan((1440 * 7) / 8);
  });

  it('holds the camera at the tiles’ limit, never moving it back', () => {
    // From the stop to Pembroke Hill: zoom 7 to 15, the ceiling at 10 with zoom 7 tiles drawn.
    const limit = progressAt(7, 15, flightCeiling(7, FLIGHT_STOP_ZOOM));
    expect(limit).toBeCloseTo(3 / 8, 9);
    let shown = 0;
    for (const t of [0, 0.2, 0.4, 0.6, 0.8, 1]) {
      const next = pacedProgress(shown, flightEasing(t), limit);
      expect(next).toBeGreaterThanOrEqual(shown);
      expect(next).toBeLessThanOrEqual(limit);
      shown = next;
    }
    expect(shown).toBeCloseTo(limit, 9);
    // Tiles closer in arrive: it goes on from where it was.
    expect(pacedProgress(shown, flightEasing(0.1), 1)).toBe(shown);
    expect(pacedProgress(shown, flightEasing(0.9), 1)).toBeCloseTo(flightEasing(0.9), 9);
  });

  it('reads the progress of a zoom as MapLibre moves it: evenly', () => {
    expect(progressAt(7, 15, 7)).toBe(0);
    expect(progressAt(7, 15, 11)).toBe(0.5);
    expect(progressAt(7, 15, 16)).toBe(1);
    expect(progressAt(7, 15, 6)).toBe(0);
    // A leg that goes nowhere is done.
    expect(progressAt(15, 15, 15)).toBe(1);
  });

  it('glides in and out, and in a few seconds where the tiles keep up', () => {
    expect(flightEasing(0)).toBe(0);
    expect(flightEasing(0.5)).toBeCloseTo(0.5, 9);
    expect(flightEasing(1)).toBe(1);
    expect(flightEasing(0.1)).toBeLessThan(0.1);
    expect(flightEasing(0.9)).toBeGreaterThan(0.9);
    for (let t = 0; t < 1; t += 0.05) {
      expect(flightEasing(t + 0.05)).toBeGreaterThanOrEqual(flightEasing(t));
    }
    // Zoom 7 to 15 in about three seconds, as MapLibre's own flight took it.
    expect(8 * FLIGHT_MS_PER_ZOOM).toBeGreaterThanOrEqual(2500);
    expect(8 * FLIGHT_MS_PER_ZOOM).toBeLessThanOrEqual(4000);
    // A wait for tiles longer than a slow phone's is given up.
    expect(FLIGHT_HOLD_MS).toBeGreaterThanOrEqual(5000);
  });
});

describe('a flight waiting for street tiles', () => {
  const at = { zoom: 7, ceiling: 7, failed: false, waited: 0 };

  it('glides on once closer tiles are drawn', () => {
    expect(holdVerdict({ ...at, ceiling: 10 })).toBe('glide');
    // Even with some of them failed, or late: the tiles on screen allow it.
    expect(holdVerdict({ ...at, ceiling: 10, failed: true, waited: FLIGHT_HOLD_MS })).toBe('glide');
  });

  it('waits while they are coming', () => {
    expect(holdVerdict(at)).toBe('wait');
    expect(holdVerdict({ ...at, waited: FLIGHT_HOLD_MS - 1 })).toBe('wait');
  });

  it('goes on without them once they failed: it never waits for nothing', () => {
    // At the stop with every street tile failed (the US mask read wrong, the tile host turning
    // the page away): the flight that sat at zoom 7 for good now goes on in.
    expect(holdVerdict({ ...at, failed: true })).toBe('go-on');
  });

  it('goes on without them once its waits add up to FLIGHT_HOLD_MS: it never waits without end', () => {
    expect(holdVerdict({ ...at, waited: FLIGHT_HOLD_MS })).toBe('go-on');
    expect(holdVerdict({ ...at, zoom: 10, ceiling: 10, waited: Number.POSITIVE_INFINITY })).toBe(
      'go-on',
    );
    expect(holdVerdict({ ...at, waited: Number.NaN })).toBe('go-on');
  });

  it('is past its deadline well after a slow flight would have arrived, and put there after', () => {
    // The stop, every wait, and a glide in from the stop, with room to spare.
    expect(FLIGHT_DEADLINE_MS).toBeGreaterThan(3000 + FLIGHT_HOLD_MS + 8 * FLIGHT_MS_PER_ZOOM);
    expect(FLIGHT_LAST_CALL_MS).toBeGreaterThan(FLIGHT_DEADLINE_MS + 8 * FLIGHT_MS_PER_ZOOM);
  });
});
