// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { IndexFormatError, loadIndex } from '../decode';
import { RecordError, cleanText, encodeIndex, placeLength, validateRecord } from '../encode';
import { ByteReader, ByteWriter, HEADER_BYTES, quantizeWeight, unzigzag, zigzag } from '../format';
import type { SearchRecord } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

function allRecords(bytes: Uint8Array) {
  const index = loadIndex(bytes);
  const out = [];
  for (let f = 0; f < index.recordCount; f++) out.push(index.record(f));
  return out;
}

describe('byte format', () => {
  it('round-trips varints and zigzag', () => {
    const w = new ByteWriter();
    const values = [0, 1, 127, 128, 16383, 16384, 2 ** 31, 2 ** 32 - 1];
    for (const v of values) w.varint(v);
    const r = new ByteReader(w.finish());
    for (const v of values) expect(r.varint()).toBe(v);
    expect(r.atEnd()).toBe(true);
    for (const v of [0, 1, -1, 123456, -123456, 2 ** 30, -(2 ** 30)]) {
      expect(unzigzag(zigzag(v))).toBe(v);
    }
  });

  it('refuses out-of-range varints and short reads', () => {
    expect(() => {
      new ByteWriter().varint(-1);
    }).toThrow(RangeError);
    expect(() => {
      new ByteWriter().varint(2 ** 32);
    }).toThrow(RangeError);
    expect(() => new ByteReader(new Uint8Array([0x80])).varint()).toThrow(RangeError);
    expect(() => new ByteReader(new Uint8Array([1])).u32()).toThrow(RangeError);
  });

  it('quantizes weights in order', () => {
    expect(quantizeWeight(0)).toBe(0);
    expect(quantizeWeight(-5)).toBe(0);
    expect(quantizeWeight(Number.NaN)).toBe(0);
    let prev = 0;
    for (const w of [1, 2, 10, 100, 450, 1000, 1e5, 1e7]) {
      const q = quantizeWeight(w);
      expect(q).toBeGreaterThan(prev);
      prev = q;
    }
    expect(quantizeWeight(1e300)).toBe(4095);
  });
});

describe('records', () => {
  it('cleans text', () => {
    expect(cleanText('  Lancaster\n\tHigh   School ')).toBe('Lancaster High School');
    expect(cleanText('Café')).toBe('Café');
  });

  it('accepts a valid record', () => {
    const r = validateRecord(
      {
        kind: 'school',
        id: 'SYN1',
        name: ' A  B ',
        sub: 'X, PA',
        state: 'PA',
        lat: 1,
        lon: 2,
        weight: 3,
      },
      'test:1',
    );
    expect(r.name).toBe('A B');
  });

  it.each([
    [null, 'expected a JSON object'],
    [[], 'expected a JSON object'],
    [{ kind: 'planet' }, 'kind must be'],
    [
      { kind: 'city', id: '', name: 'A', sub: '', state: 'PA', lat: 0, lon: 0, weight: 0 },
      'id must be',
    ],
    [
      { kind: 'city', id: 'a b', name: 'A', sub: '', state: 'PA', lat: 0, lon: 0, weight: 0 },
      'id must be',
    ],
    [
      { kind: 'city', id: '1', name: '🙂', sub: '', state: 'PA', lat: 0, lon: 0, weight: 0 },
      'no letters',
    ],
    [{ kind: 'city', id: '1', name: 'A', sub: '', state: 'XX', lat: 0, lon: 0, weight: 0 }, 'USPS'],
    [{ kind: 'city', id: '1', name: 'A', sub: '', state: 'PA', lat: 91, lon: 0, weight: 0 }, 'lat'],
    [
      { kind: 'city', id: '1', name: 'A', sub: '', state: 'PA', lat: 0, lon: 0, weight: -1 },
      'weight',
    ],
    [
      {
        kind: 'city',
        id: '1',
        name: 'A',
        sub: '',
        state: 'PA',
        lat: 0,
        lon: 0,
        weight: 0,
        extra: 1,
      },
      'unknown field',
    ],
  ])('refuses %j', (value, message) => {
    expect(() => validateRecord(value, 'test:1')).toThrow(RecordError);
    expect(() => validateRecord(value, 'test:1')).toThrow(message);
  });

  it.each([
    ['Lancaster, PA', 9],
    ['Lancaster, Pennsylvania', 9],
    ['Washington, DC', 10],
    ['Pennsylvania', 0],
    ['New York, Pennsylvania', 8],
    ['Winston-Salem, NC', 13],
    ['Somewhere', 9],
    ['', 0],
  ])('the place part of %j is %i long', (sub, len) => {
    expect(placeLength(sub)).toBe(len);
  });
});

describe('index round trip', () => {
  const { bytes, stats } = encodeIndex(SYNTHETIC_RECORDS);

  it('gives back every record', () => {
    const back = allRecords(bytes);
    expect(back).toHaveLength(SYNTHETIC_RECORDS.length);
    for (const r of SYNTHETIC_RECORDS) {
      const got = back.find((b) => b.kind === r.kind && b.id === r.id);
      expect(got, r.id).toBeDefined();
      expect(got?.name).toBe(r.name);
      expect(got?.sub).toBe(r.sub);
      expect(got?.state).toBe(r.state);
      expect(Math.abs((got?.lat ?? 0) - r.lat)).toBeLessThanOrEqual(0.00005 + 1e-9);
      expect(Math.abs((got?.lon ?? 0) - r.lon)).toBeLessThanOrEqual(0.00005 + 1e-9);
    }
  });

  it('reports what it holds', () => {
    expect(stats.records).toBe(SYNTHETIC_RECORDS.length);
    expect(stats.byKind.zip).toBe(6);
    expect(stats.tokens).toBeGreaterThan(50);
  });

  it('is byte-identical for the same records in any order', () => {
    const shuffled = [...SYNTHETIC_RECORDS].reverse();
    expect(encodeIndex(shuffled).bytes).toEqual(bytes);
  });

  it('refuses duplicate ids within a kind', () => {
    const dup = SYNTHETIC_RECORDS[0];
    if (!dup) throw new Error('empty fixture');
    expect(() => encodeIndex([...SYNTHETIC_RECORDS, dup])).toThrow('duplicate id');
  });

  it('round-trips unusual ids and names', () => {
    const records: SearchRecord[] = [
      {
        kind: 'school',
        id: '010000500870',
        name: 'A',
        sub: 'X, AL',
        state: 'AL',
        lat: 0,
        lon: 0,
        weight: 1,
      },
      {
        kind: 'school',
        id: '010000500871',
        name: 'B',
        sub: 'X, AL',
        state: 'AL',
        lat: 0,
        lon: 0,
        weight: 1,
      },
      {
        kind: 'school',
        id: '010000500879',
        name: 'C',
        sub: 'X, AL',
        state: 'AL',
        lat: 0,
        lon: 0,
        weight: 1,
      },
      {
        kind: 'school',
        id: 'A0100026',
        name: 'D',
        sub: 'Y, AL',
        state: 'AL',
        lat: 0,
        lon: 0,
        weight: 1,
      },
      {
        kind: 'school',
        id: 'A0100027',
        name: 'É 学校 🏫 e',
        sub: 'Ÿ, AL',
        state: 'AL',
        lat: 0,
        lon: 0,
        weight: 1,
      },
      {
        kind: 'district',
        id: '0100005',
        name: 'F',
        sub: '',
        state: 'AL',
        lat: -45.12345,
        lon: 170.5,
        weight: 0,
      },
      {
        kind: 'zip',
        id: '00501',
        name: '00501',
        sub: 'New York',
        state: 'NY',
        lat: 40.8,
        lon: -73.0,
        weight: 0,
      },
    ];
    for (let i = 0; i < 100; i++) {
      records.push({
        kind: 'school',
        id: `9${String(1000 + i * 37).padStart(11, '0')}`,
        name: `Name ${String(i)}`,
        sub: 'Z, AK',
        state: 'AK',
        lat: 60 + i / 1000,
        lon: -150 - i / 1000,
        weight: i,
      });
    }
    const back = allRecords(encodeIndex(records).bytes);
    for (const r of records) {
      const got = back.find((b) => b.kind === r.kind && b.id === r.id);
      expect(got?.name, r.id).toBe(r.name);
      // Coordinates keep 4 decimals: off by at most half a unit.
      expect(Math.abs((got?.lat ?? 0) - r.lat)).toBeLessThanOrEqual(0.00005 + 1e-9);
      expect(Math.abs((got?.lon ?? 0) - r.lon)).toBeLessThanOrEqual(0.00005 + 1e-9);
    }
  });
});

describe('loading bad files', () => {
  const { bytes } = encodeIndex(SYNTHETIC_RECORDS);

  it('refuses a truncated file', () => {
    expect(() => loadIndex(bytes.subarray(0, 20))).toThrow(IndexFormatError);
    expect(() => loadIndex(bytes.subarray(0, bytes.length - 10))).toThrow(IndexFormatError);
  });

  it('refuses a file that is not an index', () => {
    const junk = new Uint8Array(bytes.length);
    expect(() => loadIndex(junk)).toThrow('not a search index file');
  });

  it('refuses another format or tokenizer version', () => {
    const other = bytes.slice();
    other[4] = 99;
    expect(() => loadIndex(other)).toThrow('format 99');
    const tokenizer = bytes.slice();
    tokenizer[6] = 99;
    expect(() => loadIndex(tokenizer)).toThrow('tokenizer 99');
  });

  it('refuses sections that point outside the file', () => {
    const broken = bytes.slice();
    new DataView(broken.buffer).setUint32(HEADER_BYTES + 4, 1e9, true);
    expect(() => loadIndex(broken)).toThrow('out of bounds');
  });

  it('refuses a dictionary that lacks a name token', () => {
    const broken = bytes.slice();
    const view = new DataView(broken.buffer);
    // Blank the first dictionary suffix's first byte so its token changes.
    const suffixAt = view.getUint32(HEADER_BYTES + 9 * 8, true);
    broken[suffixAt] = 0x7a;
    expect(() => loadIndex(broken)).toThrow(IndexFormatError);
  });
});
