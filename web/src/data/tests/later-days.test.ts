/**
 * The later-day rings' selection (data/later-days.ts laterView) and words
 * (copy-later.ts, copy-format.ts statusDated): which days, which schools,
 * the counts, a light today winning over a ring, the menu's filter.
 * Every file here is SYNTHETIC, made up for these tests.
 */
import { describe, expect, it } from 'vitest';

import { format } from '../../copy-format';
import { laterCopy, laterFormat } from '../../copy-later';
import { createDirectory, parsePoints } from '../directory';
import {
  LATER_STATUSES,
  NEAR_REACH,
  NO_LATER,
  laterView,
  nearestLights,
  sameDays,
} from '../later-days';
import type { LaterDay, LitSchools } from '../closings';
import type { LaterRows } from '../live';
import { SHOW_ALL, withKind, withStatus } from '../../state/filter';
import { testMeta, testPoints } from './builders';
import type { TestSchool } from './builders';

const SCHOOLS: TestSchool[] = [
  { id: '2100030100001', name: 'Bath High', lon: -83.7, lat: 38.1, district: 0 },
  { id: '2100030100002', name: 'Bath Middle', lon: -83.71, lat: 38.11, district: 0 },
  { id: '2100030100003', name: 'Bath Elementary', lon: -83.72, lat: 38.12, district: 0 },
  { id: 'A0000009', name: 'Saint Hill', lon: -83.6, lat: 38.2, district: -1, kind: 1 },
  // A metre north of Bath High: at its place, as the panel's "Same place" has it.
  { id: '2100030100005', name: 'Bath Annex', lon: -83.7, lat: 38.10001, district: 0 },
  // 130 m east of Bath High, as the storm's nearest pairs are: a ring there would sit in its glow.
  {
    id: '2100030100006',
    name: 'Bath Primary',
    lon: -83.7 + 130 / (111320 * Math.cos((38.1 * Math.PI) / 180)),
    lat: 38.1,
    district: 0,
  },
];

/** The map's metres to its pixel at zoom 0 at Bath's latitude (512 pixels to the world's width). */
const METRES_PER_PX = (2 * Math.PI * 6378137 * Math.cos((38.1 * Math.PI) / 180)) / 512;
const META = testMeta(SCHOOLS, ['2100030']);
const POINTS = parsePoints(testPoints(SCHOOLS, 1), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);

/** A later day whose every row is a later one, unless the day's whole rows are given. */
function later(
  day: string,
  schools: number[],
  statuses: number[],
  all: { schools: number[]; statuses: number[] } = { schools, statuses },
): LaterDay {
  return { day, schools, statuses, all };
}

/** The map's lights today at these schools, with these statuses (closed where none is given). */
function lights(schools: readonly number[], statuses: readonly number[] = []): LitSchools {
  return {
    lngLat: Float64Array.from(
      schools.flatMap((school) => [
        DIRECTORY.lngLat[school * 2] ?? 0,
        DIRECTORY.lngLat[school * 2 + 1] ?? 0,
      ]),
    ),
    status: Uint8Array.from(schools.map((_, i) => statuses[i] ?? 0)),
    kinds: Uint8Array.from(schools.map((school) => DIRECTORY.kind[school] ?? 0)),
    schools: new Set(schools),
    ids: schools.map((school) => DIRECTORY.meta.ids[school] ?? ''),
    names: schools.map((school) => DIRECTORY.meta.names[school] ?? ''),
    places: DIRECTORY.e6,
  };
}

/** Thursday's rows (High closed, Middle delayed, the private school closed), Friday's (all closed). */
function rows(lit: readonly number[] = []): LaterRows {
  return {
    directory: DIRECTORY,
    lit: lights(lit),
    from: '2026-11-11',
    days: [
      later('2026-11-13', [0, 1, 2, 3], [0, 0, 0, 0]),
      later('2026-11-12', [0, 1, 3], [0, 1, 0]),
    ],
  };
}

describe('the later days on the map', () => {
  it('counts every school with a status each later day, earliest day first', () => {
    expect(laterView(rows(), SHOW_ALL).days).toEqual([
      { day: '2026-11-12', count: 3 },
      { day: '2026-11-13', count: 4 },
    ]);
  });

  it('rings each school once, at its earliest later day, with that day’s status', () => {
    expect(laterView(rows(), SHOW_ALL).marks).toEqual([
      { school: 0, day: '2026-11-12', status: 0, near: Infinity },
      { school: 1, day: '2026-11-12', status: 1, near: Infinity },
      { school: 2, day: '2026-11-13', status: 0, near: Infinity },
      { school: 3, day: '2026-11-12', status: 0, near: Infinity },
    ]);
  });

  it('rings no school the map lights today, and still counts it on its later days', () => {
    const view = laterView(rows([0, 2]), SHOW_ALL);
    expect(view.marks.map((mark) => mark.school)).toEqual([1, 3]);
    expect(view.days).toEqual([
      { day: '2026-11-12', count: 3 },
      { day: '2026-11-13', count: 4 },
    ]);
  });

  it('rings no school at the place of one the map lights today, and still counts it', () => {
    // SYNTHETIC: Bath High lit today; Bath Annex, a metre from it, closed Friday. The glow covers
    // the annex's dot under the High's light, and a ring there would show through that light.
    const shared: LaterRows = {
      ...rows([0]),
      days: [later('2026-11-13', [1, 4], [0, 0], { schools: [0, 1, 4], statuses: [0, 0, 0] })],
    };
    const view = laterView(shared, SHOW_ALL);
    expect(view.marks.map((mark) => mark.school)).toEqual([1]);
    expect(view.days).toEqual([{ day: '2026-11-13', count: 3 }]);
    // With no light today the annex has its ring.
    expect(laterView(rows(), SHOW_ALL).marks.map((mark) => mark.school)).not.toContain(4);
    const unlit = laterView({ ...shared, lit: lights([]) }, SHOW_ALL);
    expect(unlit.marks.map((mark) => mark.school)).toEqual([1, 4]);
  });

  it('tells each ring how near today’s nearest light is, as the map draws it', () => {
    // SYNTHETIC: Bath High lit today; Bath Primary, 130 m east of it, and Bath Middle, 1.4 km
    // north-west, closed Friday, and the private school, 12 km off.
    const near: LaterRows = {
      ...rows([0]),
      days: [later('2026-11-13', [1, 3, 5], [0, 0, 0])],
    };
    const marks = laterView(near, SHOW_ALL).marks;
    expect(marks.map((mark) => mark.school)).toEqual([1, 3, 5]);
    const [middle, saint, primary] = marks;
    expect((primary?.near ?? 0) * METRES_PER_PX).toBeCloseTo(130, 0);
    expect((middle?.near ?? 0) * METRES_PER_PX).toBeGreaterThan(1300);
    expect((middle?.near ?? 0) * METRES_PER_PX).toBeLessThan(1500);
    expect(saint?.near).toBe(Infinity);
    // The days and their counts are the same as with no light near.
    expect(laterView(near, SHOW_ALL).days).toEqual([{ day: '2026-11-13', count: 3 }]);
    // A light the menu shows is near; one it hides is not drawn, so it is not near.
    const closedOnly = withStatus(SHOW_ALL, 0);
    const shown = laterView({ ...near, lit: lights([0], [0]) }, closedOnly);
    expect(shown.marks.find((mark) => mark.school === 5)?.near).toBeCloseTo(primary?.near ?? 0);
    expect(laterView({ ...near, lit: lights([0], [1]) }, closedOnly).marks).toEqual(
      laterView({ ...near, lit: lights([]) }, SHOW_ALL).marks,
    );
  });

  it('finds the nearest light across the squares it looks in, and none past its reach', () => {
    const lngLat = Float64Array.from([-83.7, 38.1, -83.7, 38.1, 0, 0]);
    // A light right at the school, one on the far side of the world.
    expect(nearestLights(lngLat, [1, 2], [0]).get(0)).toBe(0);
    expect(nearestLights(lngLat, [2], [0]).has(0)).toBe(false);
    expect(nearestLights(lngLat, [], [0]).size).toBe(0);
    // Lights on both sides of a square's edge, and one just past NEAR_REACH.
    const edge = NEAR_REACH * 1000;
    const lon = (x: number): number => (x / 512) * 360 - 180;
    const row = Float64Array.from([
      lon(edge - 1e-4),
      0,
      lon(edge + 1e-4),
      0,
      lon(edge + NEAR_REACH * 1.01),
      0,
    ]);
    expect(nearestLights(row, [1], [0]).get(0)).toBeCloseTo(2e-4, 6);
    expect(nearestLights(row, [2], [0]).has(0)).toBe(false);
  });

  it('rings a school at the place of a light the menu hides, as no light is drawn there', () => {
    // SYNTHETIC: the High lit closed, the annex delayed Friday, the menu showing delays alone.
    const shared: LaterRows = {
      ...rows(),
      lit: lights([0], [0]),
      days: [later('2026-11-13', [4], [1])],
    };
    expect(laterView(shared, withStatus(SHOW_ALL, 1)).marks).toEqual([
      { school: 4, day: '2026-11-13', status: 1, near: Infinity },
    ]);
    expect(laterView({ ...shared, lit: lights([0], [1]) }, withStatus(SHOW_ALL, 1)).marks).toEqual(
      [],
    );
  });

  it('follows the menu’s filter: kinds hidden are neither ringed nor counted', () => {
    const publicOnly = withKind(SHOW_ALL, 'private', false);
    const view = laterView(rows(), publicOnly);
    expect(view.marks.map((mark) => mark.school)).toEqual([0, 1, 2]);
    expect(view.days).toEqual([
      { day: '2026-11-12', count: 2 },
      { day: '2026-11-13', count: 3 },
    ]);
  });

  it('rings only the status the menu shows alone, at the first day it has it', () => {
    const delayed = withStatus(SHOW_ALL, 1);
    expect(laterView(rows(), delayed).marks).toEqual([
      { school: 1, day: '2026-11-12', status: 1, near: Infinity },
    ]);
  });

  it('shows nothing with no file shown or no later day', () => {
    expect(laterView(null, SHOW_ALL)).toBe(NO_LATER);
    expect(laterView({ ...rows(), days: [] }, SHOW_ALL)).toBe(NO_LATER);
  });

  it('reads no school past the end of the directory', () => {
    const broken: LaterRows = {
      ...rows(),
      days: [later('2026-11-12', [0, 9], [0, 0])],
    };
    expect(laterView(broken, SHOW_ALL)).toEqual({
      days: [{ day: '2026-11-12', count: 1 }],
      marks: [{ school: 0, day: '2026-11-12', status: 0, near: Infinity }],
      from: '2026-11-11',
    });
  });

  it('counts a later day whole while the map shows two days, where it is lit for some schools', () => {
    // SYNTHETIC: Friday lit for Bath High and Middle (the East's evening), a later day for the
    // rest (the West's afternoon): the key counts all four, and rings only the later ones.
    const twoShown: LaterRows = {
      directory: DIRECTORY,
      lit: lights([0, 1]),
      from: '2026-11-12',
      days: [
        later('2026-11-13', [2, 3], [0, 0], { schools: [0, 1, 2, 3], statuses: [0, 1, 0, 0] }),
      ],
    };
    const view = laterView(twoShown, SHOW_ALL);
    expect(view.days).toEqual([{ day: '2026-11-13', count: 4 }]);
    expect(view.marks.map((mark) => mark.school)).toEqual([2, 3]);
  });

  it('neither counts nor rings a status code the site does not know', () => {
    expect(LATER_STATUSES).toBe(4);
    const odd: LaterRows = {
      ...rows(),
      days: [later('2026-11-12', [0, 1, 2], [0, 4, 9])],
    };
    expect(laterView(odd, SHOW_ALL)).toEqual({
      days: [{ day: '2026-11-12', count: 1 }],
      marks: [{ school: 0, day: '2026-11-12', status: 0, near: Infinity }],
      from: '2026-11-11',
    });
    expect(laterView({ ...rows(), days: [later('2026-11-12', [1], [4])] }, SHOW_ALL)).toBe(
      NO_LATER,
    );
  });

  it('tells two views apart only by their days, counts and map day', () => {
    const a = laterView(rows(), SHOW_ALL);
    expect(sameDays(a, laterView(rows(), SHOW_ALL))).toBe(true);
    expect(sameDays(a, laterView(rows([0, 2]), SHOW_ALL))).toBe(true);
    expect(sameDays(a, laterView(rows(), withKind(SHOW_ALL, 'private', false)))).toBe(false);
    expect(sameDays(a, { ...a, from: '2026-11-12' })).toBe(false);
    expect(sameDays(a, NO_LATER)).toBe(false);
    expect(sameDays(NO_LATER, NO_LATER)).toBe(true);
  });
});

describe('the later days’ words', () => {
  it('names the key line and each day with its count', () => {
    expect(laterCopy.title).toBe('Later days');
    expect(laterFormat.day('2026-11-13', '2026-11-12')).toBe('Fri:');
    expect(laterFormat.count(1204)).toBe('1,204');
    expect(
      laterFormat.label(
        [
          { day: '2026-11-12', count: 10 },
          { day: '2026-11-13', count: 8 },
        ],
        '2026-11-11',
      ),
    ).toBe('Later days: Thursday, 10 schools; Friday, 8 schools');
  });

  it('dates a later day six days or more after the map’s day, so its weekday is not the map’s', () => {
    expect(laterFormat.day('2026-11-17', '2026-11-12')).toBe('Tue:');
    expect(laterFormat.day('2026-11-18', '2026-11-12')).toBe('Wed, Nov 18:');
    expect(laterFormat.day('2026-11-19', '2026-11-12')).toBe('Thu, Nov 19:');
    expect(laterFormat.day('2026-11-13')).toBe('Fri, Nov 13:');
    expect(
      laterFormat.label(
        [
          { day: '2026-11-13', count: 2 },
          { day: '2026-11-19', count: 4 },
        ],
        '2026-11-12',
      ),
    ).toBe('Later days: Friday, 2 schools; Thursday, Nov 19, 4 schools');
  });

  it('never sets a count right after a weekday, where it would read as a date', () => {
    // SYNTHETIC: 13 schools on Friday, Nov 13.
    const shown = `${laterFormat.day('2026-11-13', '2026-11-12')} ${laterFormat.count(13)}`;
    expect(shown).toBe('Fri: 13');
    expect(shown).not.toMatch(/^Fri 13/u);
    expect(laterFormat.label([{ day: '2026-11-13', count: 13 }], '2026-11-12')).toBe(
      'Later days: Friday, 13 schools',
    );
    expect(laterFormat.label([{ day: '2026-11-13', count: 1 }], '2026-11-12')).toBe(
      'Later days: Friday, 1 school',
    );
  });

  it('refuses a day with no school and a line with no day', () => {
    expect(() => laterFormat.count(0)).toThrow(RangeError);
    expect(() => laterFormat.label([])).toThrow(RangeError);
  });

  it('dates a later day’s status line in the site’s words', () => {
    expect(format.statusDated('closed', '2026-11-13')).toBe('Closed Fri, Nov 13');
    expect(format.statusDated('delayed', '2026-11-16')).toBe('Delayed start Mon, Nov 16');
    expect(format.statusDated('remote', '2026-11-16')).toBe('Remote learning Mon, Nov 16');
    expect(format.statusDated('earlyDismissal', '2026-11-16')).toBe('Early dismissal Mon, Nov 16');
  });
});
