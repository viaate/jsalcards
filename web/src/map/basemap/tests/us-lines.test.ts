// @vitest-environment node
/**
 * The bundled continental US file (scripts/build-geo.mjs): the land, the
 * state lines, the national city names and the state names, as the map reads
 * them.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { splitUsLines } from '../style';
import type { UsLinesData } from '../style';
import { US_BOUNDS, US_LINES_FILE } from '../us-geo';

interface Feature {
  properties: { kind: string; name?: string; rank?: number; label?: string; fit?: number };
  geometry: { type: string; coordinates: unknown };
}

const WEB = new URL('../../../../', import.meta.url);
const DATA = JSON.parse(
  readFileSync(fileURLToPath(new URL(`public/${US_LINES_FILE}`, WEB)), 'utf8'),
) as { type: string; features: Feature[] };
const COMMITTED = (
  JSON.parse(readFileSync(fileURLToPath(new URL('scripts/national-cities.json', WEB)), 'utf8')) as {
    cities: { name: string; state: string; lon: number; lat: number }[];
  }
).cities;

const LAND = DATA.features.filter((feature) => feature.properties.kind === 'land');
const RINGS = LAND.flatMap((feature) => (feature.geometry.coordinates as number[][][][]).flat());
const CITIES = DATA.features.filter((feature) => feature.properties.kind === 'city');
const STATES = DATA.features.filter((feature) => feature.properties.kind === 'state-name');

/** Inside an odd number of the land's rings. */
function onLand([lon, lat]: readonly [number, number]): boolean {
  let inside = false;
  for (const ring of RINGS) {
    for (let i = 1; i < ring.length; i++) {
      const [x0 = 0, y0 = 0] = ring[i - 1] ?? [];
      const [x1 = 0, y1 = 0] = ring[i] ?? [];
      if (y0 < lat === y1 < lat) continue;
      if (lon < x0 + ((lat - y0) / (y1 - y0)) * (x1 - x0)) inside = !inside;
    }
  }
  return inside;
}

describe('the bundled continental US file', () => {
  it('holds the land, the state lines, the city names and the state names, nothing else', () => {
    const kinds = new Set(DATA.features.map((feature) => feature.properties.kind));
    expect([...kinds].sort()).toEqual(['city', 'land', 'state', 'state-name']);
    expect(LAND).toHaveLength(1);
    expect(LAND[0]?.geometry.type).toBe('MultiPolygon');
    // Every ring is closed, so its edge draws as the outline all the way round.
    for (const ring of RINGS) {
      expect(ring.length).toBeGreaterThanOrEqual(4);
      expect(ring[0]).toEqual(ring.at(-1));
    }
  });

  it('keeps the land inside the bounds the map is fitted to', () => {
    const [west, south, east, north] = US_BOUNDS;
    for (const ring of RINGS) {
      for (const [lon = NaN, lat = NaN] of ring) {
        expect(lon).toBeGreaterThanOrEqual(west);
        expect(lon).toBeLessThanOrEqual(east);
        expect(lat).toBeGreaterThanOrEqual(south);
        expect(lat).toBeLessThanOrEqual(north);
      }
    }
  });

  it('names the committed cities, in rank order, each once, each on the land', () => {
    expect(CITIES.length).toBe(COMMITTED.length);
    expect(CITIES.length).toBeGreaterThan(200);
    CITIES.forEach((feature, rank) => {
      const committed = COMMITTED[rank];
      expect(feature.properties.rank).toBe(rank);
      expect(feature.properties.name).toBe(committed?.name);
      expect(feature.geometry).toEqual({
        type: 'Point',
        coordinates: [committed?.lon, committed?.lat],
      });
      expect(onLand(feature.geometry.coordinates as [number, number]), committed?.name).toBe(true);
    });
    const keys = COMMITTED.map((city) => `${city.name}, ${city.state}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('names cities as people know them, without the Census legal forms', () => {
    for (const { name } of COMMITTED) {
      expect(name).not.toMatch(/\(balance\)|government| County$| city$|[-/]Davidson|Jefferson/);
      expect(name.trim()).toBe(name);
    }
    const names = COMMITTED.map((city) => city.name);
    for (const city of ['Indianapolis', 'Nashville', 'Louisville', 'Lexington', 'Augusta']) {
      expect(names).toContain(city);
    }
    // Incorporated as "Boise City", known as Boise.
    expect(names).toContain('Boise');
    expect(names).not.toContain('Boise City');
  });

  it('ranks the largest urban areas and the capital first', () => {
    const rank = (name: string, state: string): number =>
      COMMITTED.findIndex((city) => city.name === name && city.state === state);
    expect(rank('New York', 'NY')).toBe(0);
    expect(rank('Washington', 'DC')).toBe(1);
    for (const [name, state] of [
      ['Los Angeles', 'CA'],
      ['Chicago', 'IL'],
      ['Houston', 'TX'],
      ['San Francisco', 'CA'],
      ['Atlanta', 'GA'],
      ['Boston', 'MA'],
      ['Seattle', 'WA'],
      ['Denver', 'CO'],
      ['Miami', 'FL'],
    ] as const) {
      const at = rank(name, state);
      expect(at, name).toBeGreaterThanOrEqual(0);
      expect(at, name).toBeLessThan(25);
    }
    // San Francisco's Census point is out at sea: its name is on the peninsula.
    const sf = COMMITTED.find((city) => city.name === 'San Francisco');
    expect(sf?.lon).toBeGreaterThan(-122.52);
    expect(sf?.lon).toBeLessThan(-122.35);
  });

  it('names each of the 48 states once, on its land, as the Census names it', () => {
    const names = STATES.map((feature) => feature.properties.name ?? '');
    expect(names).toHaveLength(48);
    expect(new Set(names).size).toBe(48);
    for (const state of ['Texas', 'California', 'Maine', 'Florida', 'Rhode Island', 'Maryland']) {
      expect(names).toContain(state);
    }
    for (const outside of ['Alaska', 'Hawaii', 'Puerto Rico', 'District of Columbia']) {
      expect(names).not.toContain(outside);
    }
    for (const { properties, geometry } of STATES) {
      const { name = '', label = '', fit = NaN } = properties;
      expect(geometry.type, name).toBe('Point');
      expect(onLand(geometry.coordinates as [number, number]), name).toBe(true);
      // Set as named, on one line, or on two broken at a space.
      expect(label.replace('\n', ' '), name).toBe(name);
      expect(label.split('\n').length, name).toBeLessThanOrEqual(2);
      expect(fit, name).toBeGreaterThan(0);
    }
  });

  it("sets the largest states' names largest and the smallest states' smallest", () => {
    const fit = (state: string): number =>
      STATES.find((feature) => feature.properties.name === state)?.properties.fit ?? NaN;
    expect(fit('Texas')).toBeGreaterThan(fit('Kansas'));
    expect(fit('Kansas')).toBeGreaterThan(fit('Pennsylvania'));
    expect(fit('Pennsylvania')).toBeGreaterThan(fit('Connecticut'));
    expect(fit('Connecticut')).toBeGreaterThan(fit('Rhode Island'));
    // Two lines where that sets a two-word name larger: the Dakotas, not New York.
    const label = (state: string): string | undefined =>
      STATES.find((feature) => feature.properties.name === state)?.properties.label;
    expect(label('North Dakota')).toBe('North\nDakota');
    expect(label('New York')).toBe('New York');
  });

  it('splits into the land and lines and a source of the names alone', () => {
    const [geometry, names] = splitUsLines(DATA as unknown as UsLinesData);
    expect(typeof geometry).toBe('object');
    expect((names as UsLinesData).features).toHaveLength(CITIES.length + STATES.length);
    expect((geometry as UsLinesData).features).toHaveLength(
      DATA.features.length - CITIES.length - STATES.length,
    );
  });
});
