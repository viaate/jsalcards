// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
  SCHOOL_DOTS_FROM,
  SCHOOL_DOT_OPACITY,
  SCHOOL_DOT_RADIUS,
  SCHOOL_DOT_SOFTNESS,
  SCHOOL_DUST_FROM,
  SCHOOL_DUST_UNTIL,
  dotAt,
} from '../dots';

/** Zooms from the national view on a laptop to the last the curves name, a tenth apart. */
const ZOOMS = Array.from({ length: 131 }, (_, i) => 4 + i / 10);

/** A dot's light: its area times its opacity. */
const light = (zoom: number): number =>
  Math.PI * dotAt(SCHOOL_DOT_RADIUS, zoom) ** 2 * dotAt(SCHOOL_DOT_OPACITY, zoom);

describe("a school's dot by zoom", () => {
  it('is none at the national view, and a speck from there in', () => {
    // The national view on a laptop is about zoom 4; on a wide screen about 5.
    expect(SCHOOL_DUST_FROM).toBe(5);
    for (const zoom of [3, 4, 4.5, SCHOOL_DUST_FROM]) {
      expect(dotAt(SCHOOL_DOT_OPACITY, zoom), String(zoom)).toBe(0);
    }
    for (const zoom of [5.25, 6, 7, 8, 9]) {
      expect(dotAt(SCHOOL_DOT_OPACITY, zoom), String(zoom)).toBeGreaterThan(0);
    }
  });

  it('shrinks and dims at every step out, with no step where it vanishes or jumps', () => {
    for (let i = 1; i < ZOOMS.length; i++) {
      const [zoom, previous] = [ZOOMS[i] ?? 0, ZOOMS[i - 1] ?? 0];
      if (zoom <= SCHOOL_DUST_FROM) continue;
      const where = String(zoom);
      expect(dotAt(SCHOOL_DOT_RADIUS, zoom), where).toBeGreaterThan(
        dotAt(SCHOOL_DOT_RADIUS, previous),
      );
      expect(dotAt(SCHOOL_DOT_OPACITY, zoom), where).toBeGreaterThanOrEqual(
        dotAt(SCHOOL_DOT_OPACITY, previous),
      );
      // A tenth of a zoom out never takes more than a third of a dot's light across a state and a
      // metro, where the dust and the tiles' dots hand over: a steady fade, never a cut.
      if (zoom > SCHOOL_DUST_FROM + 0.5 && zoom <= SCHOOL_DUST_UNTIL) {
        expect(light(previous) / light(zoom), where).toBeGreaterThan(2 / 3);
      }
    }
  });

  it('is whole across a metro and a faint speck across a state', () => {
    expect(dotAt(SCHOOL_DOT_OPACITY, SCHOOL_DOTS_FROM)).toBe(1);
    expect(dotAt(SCHOOL_DOT_OPACITY, 9)).toBeLessThan(0.75);
    // A whole state on a laptop: under a pixel's radius, and a quarter of the metro's light.
    for (const zoom of [6, 6.5]) {
      expect(dotAt(SCHOOL_DOT_RADIUS, zoom), String(zoom)).toBeLessThan(1);
      expect(dotAt(SCHOOL_DOT_OPACITY, zoom), String(zoom)).toBeLessThanOrEqual(0.33);
    }
  });

  it('is soft-edged as dust and edged as the tiles draw it from their first zoom', () => {
    expect(dotAt(SCHOOL_DOT_SOFTNESS, 6)).toBe(1);
    expect(dotAt(SCHOOL_DOT_SOFTNESS, 9)).toBe(0);
    expect(dotAt(SCHOOL_DOT_SOFTNESS, SCHOOL_DUST_UNTIL)).toBe(0);
  });

  it('reads its curves as MapLibre does, holding the ends', () => {
    const stops = [
      [1, 10],
      [3, 30],
    ] as const;
    expect(dotAt(stops, 0)).toBe(10);
    expect(dotAt(stops, 2)).toBe(20);
    expect(dotAt(stops, 5)).toBe(30);
    expect(dotAt([], 5)).toBe(0);
  });
});
