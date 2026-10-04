import { describe, expect, it, vi } from 'vitest';

import {
  AREAS_INDEX_PATH,
  AREA_MIN_SCHOOLS,
  AREA_NEAR_METRES,
  AREA_OWN_METRES,
  areasShardPath,
  isAreaRow,
  isAreaShard,
  zipShardOf,
} from '../areas-format';
import type { AreaRow } from '../areas-format';
import { areaOf, createAreaSource, parseAreaIndex, parseAreaShard } from '../areas';
import { createDataFiles } from '../files';
import { jsonResponse } from './builders';

const ROOT = 'https://snow.test/data/';
const STAMP = { generated_on: '2026-01-05', schools: 9, districts: 1 };

/** Made up for these tests, in the format's shape. */
const FULL: AreaRow = [
  '64111',
  -94.5939,
  39.0571,
  ['MO'],
  [
    [0, '290000100001', 268, -94.59, 39.06],
    [1, '290000100002', 276, -94.592, 39.058],
    [2, '290000100003', 276, -94.596, 39.055],
    [3, '290000100004', 645, -94.6, 39.05],
    [4, '290000100005', 900, -94.61, 39.05],
    [5, 'A0000001', 1204, -94.58, 39.05],
    [6, 'A0000002', 2400, -94.57, 39.04],
  ],
  [],
];
const SPARSE: AreaRow = [
  '64112',
  -94.5953,
  39.036,
  ['MO'],
  [
    [7, 'A1902690', 194, -94.593, 39.036],
    [8, 'A0000003', 609, -94.6, 39.03],
  ],
  [
    [0, '290000100001', 1252, -94.59, 39.06],
    [1, '290000100002', 1723, -94.592, 39.058],
  ],
];

function shard(areas: readonly unknown[], directory = STAMP): unknown {
  const first = (areas[0] as AreaRow | undefined)?.[0] ?? '00000';
  return { schema_version: 1, directory, first, areas };
}

describe('the area format', () => {
  it('names its files as the build lists them: the index by name, the shards through it', () => {
    expect(AREAS_INDEX_PATH).toBe('schools/areas/index.json');
    expect(areasShardPath(12)).toBe('schools/areas/12.json');
    expect(isAreaShard('schools/areas/12.0123456789.json')).toBe(true);
    expect(isAreaShard('schools/areas/12.json')).toBe(true);
    expect(isAreaShard('schools/areas/index.0123456789.json')).toBe(false);
    expect(isAreaShard('schools/details/12.0123456789.json')).toBe(false);
  });

  it('takes in others within two miles when a ZIP code has fewer than six schools', () => {
    expect(AREA_MIN_SCHOOLS).toBe(6);
    expect(AREA_NEAR_METRES).toBeCloseTo(3218.688, 3);
    expect(AREA_OWN_METRES).toBeCloseTo(40_233.6, 1);
  });

  it('checks every column of an area', () => {
    expect(isAreaRow(FULL)).toBe(true);
    expect(isAreaRow(SPARSE)).toBe(true);
    const broken = (at: number, value: unknown, row: AreaRow = SPARSE): unknown[] => {
      const copy: unknown[] = [...row];
      copy[at] = value;
      return copy;
    };
    expect(isAreaRow(broken(0, '6411'))).toBe(false);
    expect(isAreaRow(broken(1, -200))).toBe(false);
    expect(isAreaRow(broken(2, Number.NaN))).toBe(false);
    expect(isAreaRow(broken(3, []))).toBe(false);
    expect(isAreaRow(broken(3, ['Missouri']))).toBe(false);
    // Nearest first, ties by position.
    expect(isAreaRow(broken(4, [...SPARSE[4]].reverse()))).toBe(false);
    expect(
      isAreaRow(
        broken(4, [
          [8, 'A0000003', 194, -94.6, 39.03],
          [7, 'A1902690', 194, -94.593, 39.036],
        ]),
      ),
    ).toBe(false);
    // A school once, whole metres, an id as the directory writes it.
    expect(isAreaRow(broken(5, [[7, 'A1902690', 1252, -94.59, 39.06]]))).toBe(false);
    expect(isAreaRow(broken(5, [[0, '290000100001', 1252.5, -94.59, 39.06]]))).toBe(false);
    expect(isAreaRow(broken(5, [[0, '29000010000', 1252, -94.59, 39.06]]))).toBe(false);
    // The others within two miles, and only to make up six.
    expect(isAreaRow(broken(5, [[0, '290000100001', 3300, -94.59, 39.06]]))).toBe(false);
    expect(isAreaRow(broken(5, [[9, 'A0000004', 3000, -94.6, 39.0]], FULL))).toBe(false);
    // Its own within 25 miles of its point.
    expect(isAreaRow(broken(4, [[7, 'A1902690', 41_000, -94.593, 39.036]]))).toBe(false);
    expect(isAreaRow(SPARSE.slice(0, 5))).toBe(false);
    expect(isAreaRow(null)).toBe(false);
  });

  it('finds the shard a ZIP code would be in from the first ZIP codes', () => {
    const firsts = ['01001', '20001', '64101', '99901'];
    expect(zipShardOf(firsts, '01001')).toBe(0);
    expect(zipShardOf(firsts, '19999')).toBe(0);
    expect(zipShardOf(firsts, '64112')).toBe(2);
    expect(zipShardOf(firsts, '99999')).toBe(3);
    expect(zipShardOf(firsts, '00501')).toBe(-1);
  });
});

describe('reading the area files', () => {
  const index = {
    schema_version: 1,
    directory: STAMP,
    shards: 1,
    first_zips: ['64111'],
    files: ['0.abcdefabcd.json'],
  };

  it('reads an index and a shard, and refuses what does not match its format', () => {
    expect(parseAreaIndex(index)).toEqual({
      firstZips: ['64111'],
      files: ['0.abcdefabcd.json'],
      directory: STAMP,
    });
    expect(parseAreaIndex({ ...index, files: ['../0.json'] })).toBeNull();
    expect(parseAreaIndex({ ...index, shards: 2 })).toBeNull();
    expect(
      parseAreaIndex({
        ...index,
        shards: 2,
        first_zips: ['64111', '01001'],
        files: ['0.json', '1.json'],
      }),
    ).toBeNull();
    expect(parseAreaIndex({ ...index, schema_version: 2 })).toBeNull();

    expect(parseAreaShard(shard([FULL, SPARSE]))).toEqual({
      first: '64111',
      areas: [FULL, SPARSE],
      directory: STAMP,
    });
    // In order of their codes, from the first it names, every school inside the directory.
    expect(parseAreaShard(shard([SPARSE, FULL]))).toBeNull();
    expect(parseAreaShard({ ...(shard([FULL]) as object), first: '64110' })).toBeNull();
    expect(parseAreaShard(shard([FULL], { ...STAMP, schools: 6 }))).toBeNull();
    expect(parseAreaShard(shard([]))).toBeNull();
  });

  it('turns an area into a record', () => {
    expect(areaOf(SPARSE, STAMP)).toEqual({
      zip: '64112',
      lon: -94.5953,
      lat: 39.036,
      states: ['MO'],
      own: [
        { index: 7, id: 'A1902690', metres: 194, lon: -94.593, lat: 39.036 },
        { index: 8, id: 'A0000003', metres: 609, lon: -94.6, lat: 39.03 },
      ],
      near: [
        { index: 0, id: '290000100001', metres: 1252, lon: -94.59, lat: 39.06 },
        { index: 1, id: '290000100002', metres: 1723, lon: -94.592, lat: 39.058 },
      ],
      directory: STAMP,
    });
  });

  it('reads the index once and each shard once, and finds each ZIP code in its shard', async () => {
    const fetchImpl = vi.fn((url: string) =>
      Promise.resolve(jsonResponse(url.includes('index') ? index : shard([FULL, SPARSE]))),
    );
    const files = createDataFiles(['schools/areas/index.0123456789.json'], ROOT);
    const source = createAreaSource(files, fetchImpl);
    expect(source.shipped).toBe(true);
    expect(await source.get('64112')).toMatchObject({ zip: '64112', states: ['MO'] });
    expect(await source.get('64111')).toMatchObject({ zip: '64111' });
    expect(await source.get('64113')).toBeNull();
    expect(await source.get('00501')).toBeNull();
    expect(await source.get('641')).toBeNull();
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      `${ROOT}schools/areas/index.0123456789.json`,
      `${ROOT}schools/areas/0.abcdefabcd.json`,
    ]);
  });

  it('reads nothing where the build ships no areas, and nothing from a broken shard', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse({})));
    const none = createAreaSource(createDataFiles([], ROOT), fetchImpl);
    expect(none.shipped).toBe(false);
    expect(await none.get('64112')).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();

    const files = createDataFiles(['schools/areas/index.0123456789.json'], ROOT);
    const answers = (body: unknown) =>
      vi.fn((url: string) => Promise.resolve(jsonResponse(url.includes('index') ? index : body)));
    // A shard for another directory than the index's is not read with it.
    const other = { ...STAMP, generated_on: '2026-01-06' };
    expect(await createAreaSource(files, answers(shard([FULL], other))).get('64111')).toBeNull();
    expect(await createAreaSource(files, answers({ areas: 'none' })).get('64111')).toBeNull();
    const failing = createAreaSource(files, () => Promise.reject(new Error('offline')));
    expect(await failing.get('64111')).toBeNull();
  });
});
