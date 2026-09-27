import { describe, expect, it, vi } from 'vitest';

import {
  createDirectory,
  directorySource,
  districtBounds,
  loadDirectory,
  parseMeta,
  parsePoints,
  sameDirectory,
  schoolLocation,
} from '../directory';
import { createDataFiles } from '../files';
import { GENERATED_ON, jsonResponse, testMeta, testPoints } from './builders';
import type { TestSchool } from './builders';

const ROOT = 'https://snow.test/data/';
const SCHOOLS: TestSchool[] = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: 0 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: 0 },
  { id: '290000000001', name: 'Third', lon: -94.5, lat: 39.1, district: 1 },
  { id: 'A1902690', name: 'Fourth', lon: -94.593001, lat: 39.03606, district: -1 },
];
const DISTRICTS = ['0100005', '2900001'];

function directory() {
  const meta = testMeta(SCHOOLS, DISTRICTS);
  const points = parsePoints(testPoints(SCHOOLS, DISTRICTS.length), meta);
  if (points === null) throw new Error('points did not parse');
  return createDirectory(meta, points);
}

describe('meta.json', () => {
  it('reads a well-formed directory', () => {
    const meta = testMeta(SCHOOLS, DISTRICTS);
    expect(parseMeta(JSON.parse(JSON.stringify(meta)))).toEqual(meta);
  });

  it('refuses a file of another version, or whose columns disagree', () => {
    const meta = testMeta(SCHOOLS, DISTRICTS);
    expect(parseMeta({ ...meta, schema_version: 2 })).toBeNull();
    expect(parseMeta({ ...meta, count: 3 })).toBeNull();
    expect(parseMeta({ ...meta, names: meta.names.slice(1) })).toBeNull();
    expect(parseMeta({ ...meta, districts: { ids: DISTRICTS, names: [] } })).toBeNull();
    expect(parseMeta({ ...meta, generated_on: 'yesterday' })).toBeNull();
    expect(parseMeta(null)).toBeNull();
    expect(parseMeta('meta')).toBeNull();
  });
});

describe('points.bin', () => {
  it('places every school to the millionth of a degree, with its district', () => {
    const found = directory();
    expect(found.lngLat[6]).toBeCloseTo(-94.593001, 6);
    expect(found.lngLat[7]).toBeCloseTo(39.03606, 6);
    expect([...found.district]).toEqual([0, 0, 1, -1]);
  });

  it('refuses bytes that are not the same directory', () => {
    const meta = testMeta(SCHOOLS, DISTRICTS);
    const bytes = testPoints(SCHOOLS, DISTRICTS.length);
    expect(parsePoints(bytes.slice(0, 20), meta)).toBeNull();
    expect(parsePoints(testPoints(SCHOOLS.slice(1), DISTRICTS.length), meta)).toBeNull();
    expect(parsePoints(testPoints(SCHOOLS, 5), meta)).toBeNull();
    const wrongMagic = bytes.slice(0);
    new DataView(wrongMagic).setUint8(0, 0);
    expect(parsePoints(wrongMagic, meta)).toBeNull();
    const badDistrict = bytes.slice(0);
    new DataView(badDistrict).setUint32(16 + 8, 9, true);
    expect(parsePoints(badDistrict, meta)).toBeNull();
  });
});

describe('lookups', () => {
  it('finds schools and districts by id, and says so when there is none', () => {
    const found = directory();
    expect(found.schoolIndex('A1902690')).toBe(3);
    expect(found.schoolIndex('999999999999')).toBe(-1);
    expect(found.districtIndex('2900001')).toBe(1);
    expect(schoolLocation(found, 'A1902690')).toEqual({ lon: -94.593001, lat: 39.03606 });
    expect(schoolLocation(found, 'Z9999999')).toBeNull();
  });

  it('bounds a district by its schools', () => {
    const found = directory();
    const bounds = districtBounds(found, '0100005');
    expect(bounds?.map((value) => Math.round(value * 10) / 10)).toEqual([-86.8, 33.5, -86.6, 33.7]);
    expect(districtBounds(found, '0999999')).toBeNull();
  });

  it('matches a file stamp to the loaded directory', () => {
    const found = directory();
    const stamp = { generated_on: GENERATED_ON, schools: 4, districts: 2 };
    expect(sameDirectory(found, stamp)).toBe(true);
    expect(sameDirectory(found, { ...stamp, generated_on: '2026-02-01' })).toBe(false);
    expect(sameDirectory(found, { ...stamp, schools: 5 })).toBe(false);
  });
});

function serve(meta: unknown, points: ArrayBuffer) {
  return vi.fn((input: string) =>
    Promise.resolve(
      input.endsWith('meta.json') ? jsonResponse(meta) : new Response(new Uint8Array(points)),
    ),
  );
}

describe('loading', () => {
  it('asks for nothing when the build ships no directory', async () => {
    const fetchImpl = vi.fn<(input: string) => Promise<Response>>();
    const files = createDataFiles(['schools/meta.json'], ROOT);
    expect(await loadDirectory(files, {}, fetchImpl)).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('loads both files together', async () => {
    const meta = testMeta(SCHOOLS, DISTRICTS);
    const files = createDataFiles(['schools/meta.json', 'schools/points.bin'], ROOT);
    const loaded = await loadDirectory(files, {}, serve(meta, testPoints(SCHOOLS, 2)));
    expect(loaded?.count).toBe(4);
  });

  it('drops a cached directory older than a file names, once, and loads it again', async () => {
    const files = createDataFiles(['schools/meta.json', 'schools/points.bin'], ROOT);
    const old = testMeta(SCHOOLS, DISTRICTS);
    const fresh = { ...old, generated_on: '2026-02-01' };
    let current: unknown = old;
    const fetchImpl = vi.fn((input: string) =>
      Promise.resolve(
        input.endsWith('meta.json')
          ? jsonResponse(current)
          : new Response(new Uint8Array(testPoints(SCHOOLS, 2))),
      ),
    );
    const evict = vi.fn<(urls: readonly string[]) => Promise<void>>(() => {
      current = fresh;
      return Promise.resolve();
    });
    const source = directorySource(files, { fetch: fetchImpl, evict });
    expect((await source.get())?.meta.generated_on).toBe(GENERATED_ON);
    const stamp = { generated_on: '2026-02-01', schools: 4, districts: 2 };
    expect((await source.get(stamp))?.meta.generated_on).toBe('2026-02-01');
    expect(evict).toHaveBeenCalledWith([`${ROOT}schools/meta.json`, `${ROOT}schools/points.bin`]);
    // A stamp naming a directory that never arrives: no second eviction, nothing read with it.
    expect(await source.get({ ...stamp, generated_on: '2026-03-01' })).toBeNull();
    expect(evict).toHaveBeenCalledTimes(1);
  });
});
