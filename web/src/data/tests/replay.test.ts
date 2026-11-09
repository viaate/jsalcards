import { describe, expect, it } from 'vitest';

import { lightSchools, litRows } from '../closings';
import { createDirectory, parsePoints } from '../directory';
import {
  isPast,
  lightReplay,
  parseReplay,
  parseReplayIndex,
  replayDay,
  replayLookup,
  shownReplays,
} from '../replay';
import {
  testClosings,
  testDay,
  testMeta,
  testPoints,
  testReplay,
  testReplayIndex,
} from './builders';
import type { TestSchool } from './builders';

const SCHOOLS: TestSchool[] = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: 0 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: 0 },
  { id: '290000000001', name: 'Third', lon: -94.5, lat: 39.1, district: 1 },
  { id: 'A1902690', name: 'Fourth', lon: -94.593001, lat: 39.03606, district: -1, kind: 1 },
];
const META = testMeta(SCHOOLS, ['0100005', '2900001']);
const POINTS = parsePoints(testPoints(SCHOOLS, 2), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);

const DAY = '2026-01-05';
const FILE = testReplay(DAY, META, [
  [0, 0, 0],
  [2, 2, null],
  [3, 1, 1],
]);

/** The file with one field changed. */
function changed(patch: Record<string, unknown>): unknown {
  return { ...FILE, ...patch };
}

describe('parseReplay', () => {
  it('reads a one-day replay as publish writes it', () => {
    expect(parseReplay(JSON.parse(JSON.stringify(FILE)))).toEqual(FILE);
    expect(replayDay(FILE)).toBe(DAY);
  });

  it.each([
    ['not an object', null],
    ['another schema version', changed({ schema_version: 2 })],
    ['a generated_at that is no instant', changed({ generated_at: '2026-01-09 12:00' })],
    ['an id that is no day', changed({ id: '2026-1-5', start: '2026-1-5T12:00:00Z' })],
    ['an id with a suffix', changed({ id: `${DAY}-b` })],
    ['a day that does not exist', changed({ id: '2026-02-30', start: '2026-02-30T12:00:00Z' })],
    ['more than one frame', changed({ frames: 2 })],
    ['frames a few hours apart', changed({ step_minutes: 360 })],
    ['a start that is not noon UTC', changed({ start: `${DAY}T06:00:00Z` })],
    ['a start on another day', changed({ start: '2026-01-06T12:00:00Z' })],
    ['no directory stamp', changed({ directory: null })],
    ['a stamp with no day', changed({ directory: { ...FILE.directory, generated_on: 'x' } })],
    ['rows out of order', changed({ rows: [FILE.rows[1], FILE.rows[0]] })],
    ['a school twice', changed({ rows: [FILE.rows[0], FILE.rows[0]] })],
    ['a row past the last frame', changed({ rows: [[0, 0, 0, 1, null]] })],
    ['a row ending before it starts', changed({ rows: [[0, 0, 1, 0, null]] })],
    ['a status past 3', changed({ rows: [[0, 4, 0, 0, null]] })],
    ['a reason past 7', changed({ rows: [[0, 0, 0, 0, 8]] })],
    ['a short row', changed({ rows: [[0, 0, 0, 0]] })],
    ['a negative school', changed({ rows: [[-1, 0, 0, 0, null]] })],
    ['rows that are not a list', changed({ rows: {} })],
  ])('refuses %s', (_name, value) => {
    expect(parseReplay(value)).toBeNull();
  });
});

describe('parseReplayIndex', () => {
  const INDEX = testReplayIndex([
    { id: '2024-01-16', schools: 3127, states: ['KS', 'MO'] },
    { id: DAY, schools: 3, states: ['AL', 'MO'] },
  ]);

  it('reads the index publish writes, oldest first', () => {
    expect(parseReplayIndex(JSON.parse(JSON.stringify(INDEX)))).toEqual(INDEX);
  });

  it.each([
    ['newest first', { ...INDEX, replays: [...INDEX.replays].reverse() }],
    ['a day twice', { ...INDEX, replays: [INDEX.replays[0], INDEX.replays[0]] }],
    ['a summary of two frames', { ...INDEX, replays: [{ ...INDEX.replays[0], frames: 2 }] }],
    ['states out of order', { ...INDEX, replays: [{ ...INDEX.replays[0], states: ['MO', 'KS'] }] }],
    ['a state that is no code', { ...INDEX, replays: [{ ...INDEX.replays[0], states: ['Mo'] }] }],
    ['no schools', { ...INDEX, replays: [{ ...INDEX.replays[0], schools: 0, peak_schools: 0 }] }],
    ['no generated_at', { ...INDEX, generated_at: null }],
  ])('refuses %s', (_name, value) => {
    expect(parseReplayIndex(value)).toBeNull();
  });

  it('offers only days over everywhere in the US, newest first', () => {
    // 05:00 UTC on Jan 6 is still Jan 5 in Hawaii: Jan 5 is not offered yet.
    expect(shownReplays(INDEX, new Date('2026-01-06T05:00:00Z')).map(({ id }) => id)).toEqual([
      '2024-01-16',
    ]);
    // 11:00 UTC on Jan 6 is Jan 6 in Hawaii too: Jan 5 is over everywhere.
    expect(shownReplays(INDEX, new Date('2026-01-06T11:00:00Z')).map(({ id }) => id)).toEqual([
      DAY,
      '2024-01-16',
    ]);
    expect(isPast(DAY, new Date('2026-01-06T05:00:00Z'))).toBe(false);
    expect(isPast(DAY, new Date('2026-01-06T11:00:00Z'))).toBe(true);
    expect(isPast('2026-01-07', new Date('2026-01-06T11:00:00Z'))).toBe(false);
    expect(shownReplays(INDEX, new Date(Number.NaN))).toEqual([]);
  });
});

describe('lightReplay', () => {
  it('lights each school of the day at its place, with its status, none pulsing in', () => {
    const lit = lightReplay(FILE, DIRECTORY);
    expect([...lit.schools]).toEqual([0, 2, 3]);
    expect([...lit.status]).toEqual([0, 2, 1]);
    expect([...lit.kinds]).toEqual([0, 0, 1]);
    expect(lit.ids).toEqual(['010000500870', '290000000001', 'A1902690']);
    expect(lit.names).toEqual(['First', 'Third', 'Fourth']);
    expect(Array.from(lit.lngLat)).toEqual([-86.8, 33.5, -94.5, 39.1, -94.593001, 39.03606]);
    expect(lit.bornAt).toBeUndefined();
  });

  it('lights nothing for another directory, or a school past its end', () => {
    const stale = { ...FILE, directory: { ...FILE.directory, generated_on: '2025-09-01' } };
    expect(lightReplay(stale, DIRECTORY).status).toHaveLength(0);
    const past = testReplay(DAY, META, [[4, 0, null]]);
    expect(lightReplay(past, DIRECTORY).status).toHaveLength(0);
    expect(replayLookup(stale, DIRECTORY)('010000500870')).toBeNull();
  });

  it("looks up each school's status and reason by id; none for a school it does not light", () => {
    const lookup = replayLookup(FILE, DIRECTORY);
    expect(lookup('010000500870')).toEqual({ status: 0, reason: 0 });
    expect(lookup('290000000001')).toEqual({ status: 2, reason: null });
    expect(lookup('010000500871')).toBeNull();
    expect(lookup('999999999999')).toBeNull();
  });

  it('lights through the same rows as live: lightSchools is litRows of its day', () => {
    const live = testClosings('2026-01-12T12:42:00Z', META, [
      testDay('2026-01-12', [
        [0, 0],
        [3, 3],
      ]),
    ]);
    const options = { now: new Date('2026-01-12T18:00:00Z'), previous: new Set([0]), bornMs: 7 };
    expect(lightSchools(live, DIRECTORY, options)).toEqual(
      litRows(DIRECTORY, Uint32Array.of(0, 3), Uint8Array.of(0, 3), new Set([0]), 7),
    );
  });

  it('parses and lights a day of 5,000 schools reading each row and school a few times', () => {
    const many = Array.from({ length: 5000 }, (_, i) => ({
      id: String(100000000000 + i),
      name: `School ${String(i)}`,
      lon: -100 + i / 1000,
      lat: 40,
      district: -1,
    }));
    // Quick counted in the work done, not in time, so it holds on any runner: each row of the
    // file and each school of the directory read a fixed few times, never once for each other.
    const reads = { rows: 0, ids: 0, names: 0 };
    const counted = <T extends object>(list: T, kind: keyof typeof reads): T =>
      new Proxy(list, {
        get(target, key, receiver) {
          if (typeof key === 'string' && /^\d+$/u.test(key)) reads[kind]++;
          return Reflect.get(target, key, receiver) as unknown;
        },
      });
    const listed = testMeta(many);
    const meta = {
      ...listed,
      ids: counted(listed.ids, 'ids'),
      names: counted(listed.names, 'names'),
    };
    const points = parsePoints(testPoints(many, 0), meta);
    if (points === null) throw new Error('points did not parse');
    const directory = createDirectory(meta, points);
    const text = JSON.stringify(
      testReplay(
        DAY,
        meta,
        many.map((_, i) => [i, (i % 4) as 0 | 1 | 2 | 3, null] as const),
      ),
    );
    const file = JSON.parse(text) as { rows: unknown[] };
    file.rows = counted(file.rows, 'rows');
    reads.ids = 0;
    reads.names = 0;
    const replay = parseReplay(file);
    if (replay === null) throw new Error('replay did not parse');
    const lit = lightReplay(replay, directory);
    replayLookup(replay, directory);
    expect(lit.status).toHaveLength(5000);
    expect(lit.ids.at(-1)).toBe(many.at(-1)?.id);
    expect(lit.names.at(-1)).toBe(many.at(-1)?.name);
    // Read to check it, to light it and to look it up: three times a row, and the last once
    // more; each school's id and name once, to light it.
    expect(reads.rows).toBeGreaterThanOrEqual(5000);
    expect(reads.rows).toBeLessThanOrEqual(3 * 5000 + 1);
    expect(reads.ids).toBeLessThanOrEqual(5000);
    expect(reads.names).toBeLessThanOrEqual(5000);
  });
});
