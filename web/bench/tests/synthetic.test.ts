import { describe, expect, it } from 'vitest';

import { conusGeometry } from '../basemap';
import { LandMask, SYNTHETIC_SEED, generateSyntheticPoints, mulberry32 } from '../synthetic';

const geometry = conusGeometry();
const mask = new LandMask(geometry.land);

describe('synthetic benchmark points', () => {
  it('are a pure function of the seed', () => {
    const a = generateSyntheticPoints(mask, geometry.counties, 5000);
    const b = generateSyntheticPoints(mask, geometry.counties, 5000);
    expect(a.lngLat).toEqual(b.lngLat);
    expect(a.status).toEqual(b.status);
    const c = generateSyntheticPoints(mask, geometry.counties, 5000, SYNTHETIC_SEED + 1);
    expect(c.lngLat).not.toEqual(a.lngLat);
  });

  it('come in the exact count asked for, on continental US land, with valid statuses', () => {
    const points = generateSyntheticPoints(mask, geometry.counties, 30_000);
    expect(points.status.length).toBe(30_000);
    expect(points.lngLat.length).toBe(60_000);
    for (let i = 0; i < points.status.length; i++) {
      const lng = points.lngLat[i * 2] ?? Number.NaN;
      const lat = points.lngLat[i * 2 + 1] ?? Number.NaN;
      expect(mask.contains(lng, lat)).toBe(true);
      expect(points.status[i]).toBeLessThanOrEqual(4);
    }
    const counts = [0, 0, 0, 0, 0];
    points.status.forEach((s) => {
      counts[s] = (counts[s] ?? 0) + 1;
    });
    for (const count of counts) expect(count).toBeGreaterThan(0);
  });

  it('use a PRNG that repeats for a seed and spreads evenly', () => {
    const a = mulberry32(7);
    const b = mulberry32(7);
    const values = Array.from({ length: 10_000 }, () => a());
    expect(values.slice(0, 5)).toEqual(Array.from({ length: 5 }, () => b()));
    const mean = values.reduce((s, v) => s + v, 0) / values.length;
    expect(mean).toBeGreaterThan(0.48);
    expect(mean).toBeLessThan(0.52);
  });

  it('land mask knows land from sea', () => {
    expect(mask.contains(-98.5, 39.5)).toBe(true); // Kansas
    expect(mask.contains(-70, 35)).toBe(false); // Atlantic
    expect(mask.contains(-87, 44)).toBe(false); // Lake Michigan
    expect(mask.contains(-150, 61)).toBe(false); // Alaska is not continental
  });
});
