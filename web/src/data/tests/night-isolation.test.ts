/**
 * A bad night, or a bug in reading one, never hides a chance (critic 3, B1): the file still
 * parses, the district's chance and the rest of its forecast still read, and so do the other
 * districts. The file is the pipeline's synthetic example (pipeline/tests/schemas/examples) with
 * a night added, as the pipeline writes one; every amount is made up.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, describe, expect, it, vi } from 'vitest';

import * as nightModule from '../night';
import { parsePredictions, schoolOutlook } from '../school-day';

const EXAMPLE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../pipeline/tests/schemas/examples/synthetic-predictions.json',
);
/** 11:00Z on Tuesday 2027-01-12: 5 AM in Chicago, one hour left to 7 AM. */
const NOW = new Date('2027-01-12T11:05:00Z');
const NIGHT = { least: [1.2], low: 1.2, high: 1.9 };

type Json = Record<string, unknown>;
const MISSING = Symbol('missing');

function withNight(night: unknown = NIGHT, nightAt: unknown = '2027-01-12T09:53:00Z'): Json {
  const file = JSON.parse(readFileSync(EXAMPLE, 'utf8')) as Json;
  const districts = file.districts as { days: Json[] }[];
  const first = districts[0]?.days[0];
  if (first === undefined) throw new Error('the example changed');
  first.night = night;
  if (nightAt === MISSING) delete file.night_at;
  else file.night_at = nightAt;
  return file;
}

function outlookOf(value: Json, district: number) {
  const file = parsePredictions(value);
  if (file === null) throw new Error('the file does not parse');
  return schoolOutlook({
    district,
    directory: file.directory,
    shipped: true,
    predictions: file,
    now: NOW,
  });
}

function expectChancesStand(value: Json): void {
  const own = outlookOf(value, 0);
  expect(own?.today).toMatchObject({ state: 'forecast', noSchool: 0.62, day: '2027-01-12' });
  const today = own?.today;
  if (today?.state !== 'forecast') throw new Error('no forecast');
  expect(today.detail?.night).toBeNull();
  expect(today.detail?.why).not.toBeNull();
  expect(today.detail?.previous).not.toBeNull();
  expect(outlookOf(value, 1)?.tomorrow).toMatchObject({ state: 'forecast' });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('a night that does not read', () => {
  it('reads when it is what the contract says', () => {
    const today = outlookOf(withNight(), 0)?.today;
    if (today?.state !== 'forecast') throw new Error('no forecast');
    expect(today.detail?.night?.least).toEqual([1.2]);
  });

  it.each([
    ['least_falls', { least: [1.2, 1.1], low: 1.1, high: 1.9 }],
    ['least_bound', { least: [100], low: 99, high: 99 }],
    ['bars', { least: [0.5, 1.2], low: 1.2, high: 1.9 }],
    ['range', { least: [1.2], low: 1.3, high: 1.9 }],
    ['heavy', { least: [1.2], low: 1.2, high: 1.9, heavy: [0, 1] }],
    ['not an object', 'a night'],
    ['an array', [1, 2, 3]],
  ])('fails %s and leaves every chance standing', (_check, night) => {
    expectChancesStand(withNight(night));
  });

  it.each([
    ['not an instant', 'yesterday'],
    ['a number', 1_768_000_000],
    ['missing', MISSING],
    ['null', null],
    ['too old', '2027-01-12T08:29:00Z'],
    ['after the file', '2027-01-12T11:01:00Z'],
  ])('a night_at that is %s reads as no night, and the file still parses', (_what, nightAt) => {
    const value = withNight(NIGHT, nightAt);
    expect(parsePredictions(value)).not.toBeNull();
    expectChancesStand(value);
  });

  it('leaves every chance standing when reading a night throws', () => {
    vi.spyOn(nightModule, 'nightOf').mockImplementation(() => {
      throw new Error('a bug in the night chart');
    });
    expectChancesStand(withNight());
  });

  it('never makes the whole file unreadable', () => {
    for (const night of [null, {}, { least: 'all of it' }, NIGHT]) {
      expect(parsePredictions(withNight(night, 'nonsense'))).not.toBeNull();
    }
  });
});
