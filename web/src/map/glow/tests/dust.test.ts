import { describe, expect, it } from 'vitest';

import {
  type DustStyle,
  dustAtZoom,
  dustCover,
  dustGrid,
  dustRuns,
  dustSpriteSize,
  DUST_GRID,
  DUST_FRAG,
} from '../dust';
import { mercatorXFromLng, mercatorYFromLat } from '../mercator';

const STYLE: DustStyle = {
  from: 5,
  until: 10,
  radius: [
    [5, 0.6],
    [9, 1.7],
  ],
  opacity: [
    [5, 0],
    [6, 0.3],
    [9.5, 1],
  ],
  softness: [
    [8, 1],
    [9, 0],
  ],
  color: [1, 1, 1],
};

describe('dust', () => {
  it('is drawn only between its zooms, and not where it has no light', () => {
    expect(dustAtZoom(STYLE, 4)).toBeNull();
    // Nothing at its first zoom, where its opacity is none.
    expect(dustAtZoom(STYLE, 5)).toBeNull();
    expect(dustAtZoom(STYLE, 10)).toBeNull();
    expect(dustAtZoom(STYLE, 12)).toBeNull();
    expect(dustAtZoom(STYLE, 6)).toEqual({
      radius: 0.6 + (1.1 * 1) / 4,
      opacity: 0.3,
      softness: 1,
    });
    const metro = dustAtZoom(STYLE, 9.99);
    expect(metro?.opacity).toBe(1);
    expect(metro?.softness).toBe(0);
  });

  it('edges a speck as MapLibre edges a circle where it is sharp, and softer further out', () => {
    const radius = 3;
    // Sharp: all of it a pixel inside its radius, half at half a pixel inside, none at it.
    expect(dustCover(radius - 1, radius, 0)).toBe(1);
    expect(dustCover(radius - 0.5, radius, 0)).toBeCloseTo(0.5, 6);
    expect(dustCover(radius, radius, 0)).toBe(0);
    // Soft: reaching a pixel past its radius.
    expect(dustCover(radius, radius, 1)).toBeGreaterThan(0.1);
    expect(dustCover(radius + 1, radius, 1)).toBe(0);
    // The shader draws the same edge.
    expect(DUST_FRAG).toContain('smoothstep(u_radius - 1.0, u_radius + u_softness, d)');
  });

  it('keeps a speck under a pixel across in sight wherever it falls between pixels', () => {
    // A speck of 0.6 px centered on a pixel, and on the corner of four.
    const centered = dustCover(0, 0.6, 1);
    const cornered = dustCover(Math.SQRT1_2, 0.6, 1);
    expect(centered).toBeGreaterThan(0.8);
    expect(4 * cornered).toBeGreaterThan(centered);
    // Its sprite reaches its edge and no further: no pixel past it takes any of the speck.
    for (const [radius, softness] of [
      [0.6, 1],
      [1.9, 1],
      [3, 0.5],
      [3, 0],
    ] as const) {
      const half = dustSpriteSize(radius, softness) / 2;
      expect(dustCover(half, radius, softness)).toBe(0);
      expect(dustCover(half - 0.01, radius, softness)).toBeGreaterThan(0);
    }
  });

  it('places each school in Web Mercator, sorted into the cells of a grid row by row', () => {
    // Boston, Kansas City, Pembroke Hill beside it, Los Angeles: north first, then west first.
    const lngLat = new Float64Array([-94.58, 39.1, -71.06, 42.36, -118.24, 34.05, -94.593, 39.036]);
    const grid = dustGrid(lngLat);
    expect(grid.positions).toHaveLength(8);
    expect(Array.from(grid.slotOf)).toEqual([1, 0, 3, 2]);
    const at = (school: number): [number, number] => {
      const slot = grid.slotOf[school] ?? 0;
      return [grid.positions[slot * 2] ?? 0, grid.positions[slot * 2 + 1] ?? 0];
    };
    expect(at(1)[0]).toBeCloseTo(mercatorXFromLng(-71.06), 6);
    expect(at(1)[1]).toBeCloseTo(mercatorYFromLat(42.36), 6);
    expect(at(3)[0]).toBeCloseTo(mercatorXFromLng(-94.593), 6);
    expect(at(3)[1]).toBeCloseTo(mercatorYFromLat(39.036), 6);
    expect(grid.cellStart).toHaveLength(DUST_GRID * DUST_GRID + 1);
    expect(grid.cellStart[DUST_GRID * DUST_GRID]).toBe(4);
  });

  it('draws only the runs of the grid in view', () => {
    const lngLat = new Float64Array([-94.58, 39.1, -71.06, 42.36, -118.24, 34.05, -94.593, 39.036]);
    const grid = dustGrid(lngLat);
    const box = (west: number, north: number, east: number, south: number) =>
      dustRuns(
        grid.cellStart,
        mercatorXFromLng(west),
        mercatorYFromLat(north),
        mercatorXFromLng(east),
        mercatorYFromLat(south),
      );
    const drawn = (runs: [number, number][]): number => runs.reduce((sum, [, n]) => sum + n, 0);
    // Kansas City: its two schools, in one run.
    expect(box(-95.5, 39.6, -94, 38.6)).toEqual([[grid.slotOf[0] ?? 0, 2]]);
    // The whole country: every school.
    expect(drawn(box(-125, 49, -66, 24))).toBe(4);
    // The ocean: none.
    expect(box(-60, 30, -50, 20)).toEqual([]);
  });
});
