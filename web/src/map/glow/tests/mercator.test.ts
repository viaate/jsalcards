import { MercatorCoordinate } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import {
  MAX_MERCATOR_LATITUDE,
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
  splitDouble,
  worldSizePx,
} from '../mercator';

const f32 = Math.fround;

describe('Web Mercator conversion', () => {
  it('maps the world corners and center like MapLibre', () => {
    expect(mercatorXFromLng(-180)).toBe(0);
    expect(mercatorXFromLng(0)).toBe(0.5);
    expect(mercatorXFromLng(180)).toBe(1);
    expect(mercatorYFromLat(0)).toBeCloseTo(0.5, 15);
    expect(mercatorYFromLat(MAX_MERCATOR_LATITUDE)).toBeCloseTo(0, 6);
    expect(mercatorYFromLat(-MAX_MERCATOR_LATITUDE)).toBeCloseTo(1, 6);
  });

  it('clamps latitude to the Mercator limit', () => {
    expect(mercatorYFromLat(89.9)).toBe(mercatorYFromLat(MAX_MERCATOR_LATITUDE));
    expect(mercatorYFromLat(-90)).toBe(mercatorYFromLat(-MAX_MERCATOR_LATITUDE));
  });

  it('agrees with maplibre-gl MercatorCoordinate across the continental US', () => {
    for (const [lng, lat] of [
      [-124.7, 48.4],
      [-96.8, 32.8],
      [-80.2, 25.8],
      [-67.0, 44.8],
      [-104.99, 39.74],
    ] as const) {
      const reference = MercatorCoordinate.fromLngLat([lng, lat]);
      expect(mercatorXFromLng(lng)).toBeCloseTo(reference.x, 14);
      expect(mercatorYFromLat(lat)).toBeCloseTo(reference.y, 14);
    }
  });

  it('round-trips longitude and latitude', () => {
    for (let lng = -125; lng <= -66; lng += 3.7) {
      for (let lat = 24; lat <= 50; lat += 2.3) {
        expect(lngFromMercatorX(mercatorXFromLng(lng))).toBeCloseTo(lng, 10);
        expect(latFromMercatorY(mercatorYFromLat(lat))).toBeCloseTo(lat, 10);
      }
    }
  });
});

describe('hi/lo split for float32 precision', () => {
  it('gives a float32 hi part and a remainder that restores the double', () => {
    for (const value of [0.2777777, 0.3812345678901234, 0.123456789012345, 0.5, 0.99999]) {
      const [hi, lo] = splitDouble(value);
      expect(f32(hi)).toBe(hi);
      expect(f32(lo)).toBe(lo);
      expect(Math.abs(value - (hi + lo))).toBeLessThan(1e-14);
    }
  });

  it('keeps a point within 1/20 px of true at zoom 18 when computed in float32', () => {
    // Mirrors the vertex shader: (hi - origin) + lo, all float32.
    const zoom = 18;
    const world = worldSizePx(zoom);
    const origin = f32(mercatorXFromLng(-87.6298));
    for (let i = 0; i < 200; i++) {
      const x = mercatorXFromLng(-87.6298 + (i - 100) * 1e-5);
      const [hi, lo] = splitDouble(x);
      const split = f32(f32(hi - origin) + lo);
      const naive = f32(f32(x) - origin);
      const exact = x - origin;
      expect(Math.abs(split - exact) * world).toBeLessThan(0.05);
      // A single float32 would be off by whole pixels here, which is why the split exists.
      if (i === 0) expect(Math.abs(naive - exact) * world).toBeGreaterThan(0.05);
    }
  });
});
