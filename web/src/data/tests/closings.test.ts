import { describe, expect, it } from 'vitest';

import { SHOW_ALL, withKind, withStatus } from '../../state/filter';
import { Status } from '../../types/generated';
import {
  NOTHING_LIT,
  countShown,
  countStatuses,
  decodeDay,
  filterLit,
  lightSchools,
  parseClosings,
  sameCounts,
  todayEverywhere,
} from '../closings';
import { createDirectory, parsePoints } from '../directory';
import { testClosings, testDay, testMeta, testPoints } from './builders';
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

const NOON = new Date('2026-01-12T18:00:00Z');
const FILE = testClosings('2026-01-12T12:42:00Z', META, [
  testDay('2026-01-12', [
    [0, 0],
    [2, 1],
    [3, 3],
  ]),
  testDay('2026-01-13', [[1, 0]]),
]);

describe('closings.json', () => {
  it('reads a file that matches its schema', () => {
    expect(parseClosings(JSON.parse(JSON.stringify(FILE)))).toEqual(FILE);
    expect(parseClosings({ ...FILE, days: [] })).not.toBeNull();
  });

  it('refuses anything else whole', () => {
    const day = FILE.days[0];
    if (day === undefined) throw new Error('no day');
    const broken: unknown[] = [
      null,
      [],
      { ...FILE, schema_version: 2 },
      { ...FILE, generated_at: '2026-01-12 12:42' },
      { ...FILE, generated_at: '2026-02-30T12:42:00Z' },
      { ...FILE, directory: { generated_on: '2026-01-05', schools: -1, districts: 2 } },
      { ...FILE, days: [...FILE.days].reverse() },
      { ...FILE, days: [day, day] },
      { ...FILE, days: [{ ...day, statuses: [0, 7, 3] }] },
      { ...FILE, days: [{ ...day, statuses: [0, 1] }] },
      { ...FILE, days: [{ ...day, gaps: [0, -1, 0] }] },
      { ...FILE, days: [{ ...day, gaps: [], statuses: [], announced: [], reasons: [] }] },
      { ...FILE, days: [{ ...day, shifts: [] }] },
      { ...FILE, days: [{ ...day, clocks: [1440, null] }] },
      { ...FILE, days: [{ ...day, announced: ['2026-01-12T11:42:00Z', null, null] }] },
      { ...FILE, days: [{ ...day, reasons: [9, null, null] }] },
    ];
    for (const value of broken) expect(parseClosings(value)).toBeNull();
  });

  it('turns gaps back into school positions', () => {
    const day = FILE.days[0];
    if (day === undefined) throw new Error('no day');
    const rows = decodeDay(day);
    expect([...rows.schools]).toEqual([0, 2, 3]);
    expect([...rows.statuses]).toEqual([0, 1, 3]);
  });
});

describe('today, everywhere in the contiguous US', () => {
  it('is one day from 08:00 UTC to 04:00 UTC the next day', () => {
    expect(todayEverywhere(new Date('2026-01-12T08:00:00Z'))).toBe('2026-01-12');
    expect(todayEverywhere(NOON)).toBe('2026-01-12');
    expect(todayEverywhere(new Date('2026-01-13T03:59:59Z'))).toBe('2026-01-12');
  });

  it('is no day while the East has moved on and the West has not', () => {
    expect(todayEverywhere(new Date('2026-01-13T04:00:00Z'))).toBeNull();
    expect(todayEverywhere(new Date('2026-01-13T07:59:59Z'))).toBeNull();
    expect(todayEverywhere(new Date(Number.NaN))).toBeNull();
  });
});

describe('the schools lit today', () => {
  it('are the rows of the day that is today, where the directory puts them', () => {
    const lit = lightSchools(FILE, DIRECTORY, { now: NOON, previous: null, bornMs: 5 });
    expect([...lit.status]).toEqual([0, 1, 3]);
    expect([...lit.lngLat].map((value) => Math.round(value * 1e6) / 1e6)).toEqual([
      -86.8, 33.5, -94.5, 39.1, -94.593001, 39.03606,
    ]);
    expect([...lit.schools]).toEqual([0, 2, 3]);
    // Each with its kind flags: the last is a private school.
    expect([...lit.kinds]).toEqual([0, 0, 1]);
    // Which school each light is, for a tap on it.
    expect(lit.ids).toEqual(['010000500870', '290000000001', 'A1902690']);
    expect(lit.names).toEqual(['First', 'Third', 'Fourth']);
    // A first load shows everything at once.
    expect(lit.bornAt).toBeUndefined();
  });

  it('move on to the next day once it is today everywhere', () => {
    const lit = lightSchools(FILE, DIRECTORY, {
      now: new Date('2026-01-13T15:00:00Z'),
      previous: null,
      bornMs: 5,
    });
    expect([...lit.schools]).toEqual([1]);
  });

  it('pulse only the schools new since the last read', () => {
    const lit = lightSchools(FILE, DIRECTORY, { now: NOON, previous: new Set([0, 3]), bornMs: 42 });
    expect(lit.bornAt === undefined ? null : [...lit.bornAt]).toEqual([Number.NaN, 42, Number.NaN]);
  });

  it('are none overnight, for another directory, or for a broken file', () => {
    const overnight = new Date('2026-01-13T05:00:00Z');
    expect(lightSchools(FILE, DIRECTORY, { now: overnight, previous: null, bornMs: 0 })).toBe(
      NOTHING_LIT,
    );
    const otherDirectory = {
      ...FILE,
      directory: { ...FILE.directory, generated_on: '2026-02-01' },
    };
    expect(lightSchools(otherDirectory, DIRECTORY, { now: NOON, previous: null, bornMs: 0 })).toBe(
      NOTHING_LIT,
    );
    const pastTheEnd = testClosings(FILE.generated_at, META, [testDay('2026-01-12', [[9, 0]])]);
    expect(lightSchools(pastTheEnd, DIRECTORY, { now: NOON, previous: null, bornMs: 0 })).toBe(
      NOTHING_LIT,
    );
    const yesterday = new Date('2026-01-14T12:00:00Z');
    expect(lightSchools(FILE, DIRECTORY, { now: yesterday, previous: null, bornMs: 0 })).toBe(
      NOTHING_LIT,
    );
  });
});

describe('the counts the legend gives', () => {
  it('count the schools lit today in each status, in code order', () => {
    const lit = lightSchools(FILE, DIRECTORY, { now: NOON, previous: null, bornMs: 5 });
    // Rows today: one closed, one delayed, one dismissing early; none remote.
    expect(countStatuses(lit)).toEqual([1, 1, 0, 1]);
    const tomorrow = lightSchools(FILE, DIRECTORY, {
      now: new Date('2026-01-13T15:00:00Z'),
      previous: null,
      bornMs: 5,
    });
    expect(countStatuses(tomorrow)).toEqual([1, 0, 0, 0]);
  });

  it('are none while nothing is lit, so no count is given for lights the map does not show', () => {
    expect(countStatuses(NOTHING_LIT)).toBeNull();
    const overnight = new Date('2026-01-13T05:00:00Z');
    expect(
      countStatuses(lightSchools(FILE, DIRECTORY, { now: overnight, previous: null, bornMs: 0 })),
    ).toBeNull();
    const otherDirectory = {
      ...FILE,
      directory: { ...FILE.directory, generated_on: '2026-02-01' },
    };
    expect(
      countStatuses(
        lightSchools(otherDirectory, DIRECTORY, { now: NOON, previous: null, bornMs: 0 }),
      ),
    ).toBeNull();
  });

  it('are told apart by what they say', () => {
    expect(sameCounts([1, 2, 0, 3], [1, 2, 0, 3])).toBe(true);
    expect(sameCounts([1, 2, 0, 3], [1, 2, 0, 4])).toBe(false);
    expect(sameCounts(null, null)).toBe(true);
    expect(sameCounts(null, [0, 0, 0, 0])).toBe(false);
    expect(sameCounts([0, 0, 0, 0], null)).toBe(false);
  });
});

describe('the lit schools the menu keeps on the map', () => {
  const lit = lightSchools(FILE, DIRECTORY, { now: NOON, previous: new Set([0]), bornMs: 42 });

  it('are all of them, as they are, while it shows everything', () => {
    expect(filterLit(lit, SHOW_ALL, true)).toBe(lit);
    // After a change of filter they light again without a pulse.
    const again = filterLit(lit, SHOW_ALL, false);
    expect(again.bornAt).toBeUndefined();
    expect([...again.schools]).toEqual([0, 2, 3]);
    expect(filterLit(NOTHING_LIT, SHOW_ALL, false)).toBe(NOTHING_LIT);
  });

  it('are those in the one status it shows, each where it was and pulsing as it would', () => {
    const delayed = filterLit(lit, withStatus(SHOW_ALL, Status.delayed), true);
    expect([...delayed.status]).toEqual([1]);
    expect([...delayed.schools]).toEqual([2]);
    expect([...delayed.kinds]).toEqual([0]);
    expect([...delayed.lngLat].map((value) => Math.round(value * 10) / 10)).toEqual([-94.5, 39.1]);
    expect(delayed.bornAt === undefined ? null : [...delayed.bornAt]).toEqual([42]);
    const remote = filterLit(lit, withStatus(SHOW_ALL, Status.remote), true);
    expect([...remote.schools]).toEqual([]);
    expect(remote.status).toHaveLength(0);
  });

  it('are those of the kinds it shows', () => {
    const publicOnly = filterLit(lit, withKind(SHOW_ALL, 'private', false), false);
    expect([...publicOnly.schools]).toEqual([0, 2]);
    expect([...publicOnly.status]).toEqual([0, 1]);
    expect(publicOnly.bornAt).toBeUndefined();
    const privateOnly = filterLit(lit, withKind(SHOW_ALL, 'public', false), false);
    expect([...privateOnly.schools]).toEqual([3]);
    expect([...privateOnly.status]).toEqual([3]);
    const neither = withKind(withKind(SHOW_ALL, 'public', false), 'private', false);
    expect([...filterLit(lit, neither, false).schools]).toEqual([]);
  });

  it('are counted by status whichever status it shows, of the kinds it shows', () => {
    expect(countShown(lit, SHOW_ALL)).toEqual([1, 1, 0, 1]);
    expect(countShown(lit, withStatus(SHOW_ALL, Status.closed))).toEqual([1, 1, 0, 1]);
    expect(countShown(lit, withKind(SHOW_ALL, 'private', false))).toEqual([1, 1, 0, 0]);
    expect(countShown(lit, withKind(SHOW_ALL, 'public', false))).toEqual([0, 0, 0, 1]);
    // None lit, none counted.
    expect(countShown(NOTHING_LIT, withKind(SHOW_ALL, 'public', false))).toBeNull();
  });
});
