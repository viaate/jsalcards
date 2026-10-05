import { describe, expect, it, vi } from 'vitest';

import {
  DETAILS_INDEX_PATH,
  GRADE_CODES,
  SCHOOLS_PER_SHARD,
  compareSchoolIds,
  detailsShardPath,
  isDetailRow,
  isDetailShard,
  metresBetween,
  phoneDigits,
  shardOf,
} from '../details-format';
import type { DetailRow } from '../details-format';
import { createDetailsSource, parseShard, parseShardIndex, recordOf } from '../details';
import { createDataFiles } from '../files';
import { jsonResponse } from './builders';

const ROOT = 'https://snow.test/data/';
const STAMP = { generated_on: '2026-01-05', schools: 3, districts: 1 };

/** Made up for these tests, in the format's shape. */
const PUBLIC_ROW: DetailRow = [
  '010000500870',
  'SMITH EL SCH',
  0,
  0,
  '0100005',
  'SOMEWHERE CITY',
  '12 MAIN ST',
  'SOMEWHERE',
  'AL',
  '35950',
  'Test County',
  'KG',
  '05',
  412,
  '2565550100',
  [[1, '010000500871', 'Second Charter', 400, -86.6, 33.7]],
];
const CHARTER_ROW: DetailRow = [
  '010000500871',
  'Second Charter',
  0x02,
  0,
  '0100005',
  'SOMEWHERE CITY',
  null,
  null,
  'AL',
  null,
  null,
  null,
  null,
  null,
  null,
  [],
];
const PRIVATE_ROW: DetailRow = [
  'A1902690',
  'THE TEST SCHOOL - NORTH CAMPUS',
  0x01,
  null,
  null,
  null,
  '400 W 51ST ST',
  'KANSAS CITY',
  'MO',
  '64112',
  'Jackson County',
  'PK',
  '12',
  1174,
  '8165550100',
  [],
];

function shard(rows: readonly DetailRow[], first = 0, directory = STAMP): unknown {
  return { schema_version: 1, directory, first, rows };
}

describe('the detail format', () => {
  it('names each shard and the index by their plain names', () => {
    expect(DETAILS_INDEX_PATH).toBe('schools/details/index.json');
    expect(detailsShardPath(0)).toBe('schools/details/0.json');
    expect(detailsShardPath(107)).toBe('schools/details/107.json');
    expect(SCHOOLS_PER_SHARD).toBe(256);
    // The page reaches the shards through the index; the build lists the index alone.
    expect(isDetailShard('schools/details/12.0123456789.json')).toBe(true);
    expect(isDetailShard('schools/details/12.json')).toBe(true);
    expect(isDetailShard('schools/details/index.0123456789.json')).toBe(false);
    expect(isDetailShard('schools/meta.0123456789.json')).toBe(false);
    expect(GRADE_CODES[0]).toBe('PK');
    expect(GRADE_CODES.at(-1)).toBe('13');
  });

  it('checks every column of a row', () => {
    expect(isDetailRow(PUBLIC_ROW)).toBe(true);
    expect(isDetailRow(CHARTER_ROW)).toBe(true);
    expect(isDetailRow(PRIVATE_ROW)).toBe(true);
    const broken = (at: number, value: unknown): unknown[] => {
      const row: unknown[] = [...PUBLIC_ROW];
      row[at] = value;
      return row;
    };
    expect(isDetailRow(broken(0, '123'))).toBe(false);
    expect(isDetailRow(broken(1, ''))).toBe(false);
    expect(isDetailRow(broken(2, 8))).toBe(false);
    // A district's id and name come with its position.
    expect(isDetailRow(broken(3, null))).toBe(false);
    expect(isDetailRow(broken(4, '12'))).toBe(false);
    expect(isDetailRow(broken(8, 'Alabama'))).toBe(false);
    expect(isDetailRow(broken(9, '3595'))).toBe(false);
    expect(isDetailRow(broken(11, 'T1'))).toBe(false);
    expect(isDetailRow(broken(13, -1))).toBe(false);
    expect(isDetailRow(broken(13, 2.5))).toBe(false);
    expect(isDetailRow(broken(14, '0565550100'))).toBe(false);
    expect(isDetailRow(PUBLIC_ROW.slice(0, 15))).toBe(false);
    // Nearby schools: at most four, each within five miles, with its place.
    const near = [1, '010000500871', 'Second Charter', 400, -86.6, 33.7];
    expect(isDetailRow(broken(15, [near, near, near, near]))).toBe(true);
    expect(isDetailRow(broken(15, [near, near, near, near, near]))).toBe(false);
    expect(
      isDetailRow(broken(15, [[1, '010000500871', 'Second Charter', 9000, -86.6, 33.7]])),
    ).toBe(false);
    expect(isDetailRow(broken(15, [[1, '010000500871', 'Second Charter', 400, -86.6]]))).toBe(
      false,
    );
    expect(isDetailRow(broken(15, null))).toBe(false);
    expect(isDetailRow(null)).toBe(false);
  });

  it('orders ids as the directory does: public schools, then private ones', () => {
    const ids = ['010000500870', '560000100001', 'A1902690', 'K9302494'];
    const shuffled = ['K9302494', '560000100001', 'A1902690', '010000500870'];
    expect(shuffled.sort(compareSchoolIds)).toEqual(ids);
    expect(compareSchoolIds('A1902690', 'A1902690')).toBe(0);
  });

  it('finds the shard an id would be in from the first ids', () => {
    const firsts = ['010000500870', '290000100048', 'A0000001', 'BB100568'];
    expect(shardOf(firsts, '010000500870')).toBe(0);
    expect(shardOf(firsts, '100000000000')).toBe(0);
    expect(shardOf(firsts, '290000100048')).toBe(1);
    expect(shardOf(firsts, '560000100001')).toBe(1);
    expect(shardOf(firsts, 'A1902690')).toBe(2);
    expect(shardOf(firsts, 'K9302494')).toBe(3);
    expect(shardOf(firsts, '000000000001')).toBe(-1);
  });

  it('measures the distance between two places on the Earth', () => {
    expect(metresBetween(-94.593001, 39.03606, -94.593001, 39.03606)).toBe(0);
    // A degree of latitude is about 111 km.
    expect(metresBetween(-94.6, 39, -94.6, 40)).toBeCloseTo(111_195, -1);
    expect(metresBetween(-94.593001, 39.03606, -94.588871, 39.03368)).toBeCloseTo(444, 0);
  });

  it('keeps ten digits of a phone number, and nothing that is not one', () => {
    expect(phoneDigits('(573)859-3326')).toBe('5738593326');
    expect(phoneDigits('8169361230')).toBe('8169361230');
    expect(phoneDigits('1-816-936-1230')).toBe('8169361230');
    expect(phoneDigits('936-1230')).toBeNull();
    expect(phoneDigits('0169361230')).toBeNull();
    expect(phoneDigits(null)).toBeNull();
  });
});

describe('reading the detail files', () => {
  it('reads an index and a shard, and refuses what does not match its format', () => {
    const index = {
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_ids: ['010000500870'],
      files: ['0.abcdefabcd.json'],
    };
    expect(parseShardIndex(index)).toEqual({
      firstIds: ['010000500870'],
      files: ['0.abcdefabcd.json'],
      directory: STAMP,
    });
    expect(parseShardIndex({ ...index, files: ['../0.json'] })).toBeNull();
    expect(parseShardIndex({ ...index, files: [] })).toBeNull();
    expect(parseShardIndex({ ...index, shards: 2 })).toBeNull();
    expect(parseShardIndex({ ...index, schema_version: 2 })).toBeNull();
    expect(
      parseShardIndex({ ...index, directory: { ...STAMP, generated_on: 'Jan 5' } }),
    ).toBeNull();

    const rows = [PUBLIC_ROW, CHARTER_ROW, PRIVATE_ROW];
    expect(parseShard(shard(rows))).toEqual({ first: 0, rows, directory: STAMP });
    // A shard starts at a multiple of the shard size, and stays within the directory.
    expect(parseShard(shard(rows, 3))).toBeNull();
    expect(parseShard(shard(rows, 256, { ...STAMP, schools: 259 }))).toMatchObject({ first: 256 });
    expect(parseShard(shard(rows, 0, { ...STAMP, schools: 2 }))).toBeNull();
    expect(
      parseShard(shard([...rows.slice(0, 2), ['A1902690'] as unknown as DetailRow])),
    ).toBeNull();
    expect(parseShard(shard([]))).toBeNull();
  });

  it('turns a row into a record at its place in the directory', () => {
    expect(recordOf(PUBLIC_ROW, 0, STAMP)).toEqual({
      id: '010000500870',
      index: 0,
      name: 'SMITH EL SCH',
      private: false,
      charter: false,
      virtual: false,
      district: { index: 0, id: '0100005', name: 'SOMEWHERE CITY' },
      street: '12 MAIN ST',
      city: 'SOMEWHERE',
      state: 'AL',
      zip: '35950',
      county: 'Test County',
      grades: { low: 'KG', high: '05' },
      enrollment: 412,
      phone: '2565550100',
      nearby: [
        {
          index: 1,
          id: '010000500871',
          name: 'Second Charter',
          metres: 400,
          lon: -86.6,
          lat: 33.7,
        },
      ],
      directory: STAMP,
    });
    expect(recordOf(CHARTER_ROW, 1, STAMP)).toMatchObject({ charter: true, grades: null });
    expect(recordOf(PRIVATE_ROW, 2, STAMP)).toMatchObject({ private: true, district: null });
  });

  it('reads the index once and each shard once, and finds each school in its shard', async () => {
    const index = {
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_ids: ['010000500870'],
      files: ['0.abcdefabcd.json'],
    };
    const fetchImpl = vi.fn((url: string) =>
      Promise.resolve(
        jsonResponse(url.includes('index') ? index : shard([PUBLIC_ROW, CHARTER_ROW, PRIVATE_ROW])),
      ),
    );
    // The build lists the index alone; the index names the shard's file.
    const files = createDataFiles(['schools/details/index.0123456789.json'], ROOT);
    const source = createDetailsSource(files, fetchImpl);
    expect(await source.get('A1902690')).toMatchObject({ index: 2, city: 'KANSAS CITY' });
    expect(await source.get('010000500871')).toMatchObject({ index: 1, charter: true });
    expect(await source.get('A0000000')).toBeNull();
    expect(await source.get('000000000001')).toBeNull();
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      `${ROOT}schools/details/index.0123456789.json`,
      `${ROOT}schools/details/0.abcdefabcd.json`,
    ]);
  });

  it('reads nothing where the build ships no details, and nothing from a broken shard', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse({})));
    expect(
      await createDetailsSource(createDataFiles([], ROOT), fetchImpl).get('A1902690'),
    ).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();

    const files = createDataFiles(['schools/details/index.0123456789.json'], ROOT);
    const index = {
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_ids: ['010000500870'],
      files: ['0.abcdefabcd.json'],
    };
    const other = { ...STAMP, generated_on: '2026-01-06' };
    const answers = (body: unknown) =>
      vi.fn((url: string) => Promise.resolve(jsonResponse(url.includes('index') ? index : body)));
    // A shard for another directory than the index's is not read with it.
    const stale = createDetailsSource(files, answers(shard([PUBLIC_ROW], 0, other)));
    expect(await stale.get('010000500870')).toBeNull();
    const broken = createDetailsSource(files, answers({ rows: 'none' }));
    expect(await broken.get('010000500870')).toBeNull();
    const failing = createDetailsSource(files, () => Promise.reject(new Error('offline')));
    expect(await failing.get('010000500870')).toBeNull();
  });

  it('asks again for a file that could not be read, and keeps what was read', async () => {
    const index = {
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_ids: ['010000500870'],
      files: ['0.abcdefabcd.json'],
    };
    let offline = 2;
    const fetchImpl = vi.fn((url: string) => {
      if (offline > 0 && (url.includes('index') ? offline === 2 : offline === 1)) {
        offline -= 1;
        return Promise.reject(new Error('offline'));
      }
      return Promise.resolve(
        jsonResponse(url.includes('index') ? index : shard([PUBLIC_ROW, CHARTER_ROW, PRIVATE_ROW])),
      );
    });
    const files = createDataFiles(['schools/details/index.0123456789.json'], ROOT);
    const source = createDetailsSource(files, fetchImpl);
    // The index fails, then the shard, then both are read, and each once more after that.
    expect(await source.get('A1902690')).toBeNull();
    expect(await source.get('A1902690')).toBeNull();
    expect(await source.get('A1902690')).toMatchObject({ index: 2 });
    expect(await source.get('010000500871')).toMatchObject({ index: 1 });
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      `${ROOT}schools/details/index.0123456789.json`,
      `${ROOT}schools/details/index.0123456789.json`,
      `${ROOT}schools/details/0.abcdefabcd.json`,
      `${ROOT}schools/details/0.abcdefabcd.json`,
    ]);
  });
});
