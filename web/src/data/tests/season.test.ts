import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDataFiles, withLiveRoot } from '../files';
import {
  SEASON_GRACE_MS,
  SEASON_PATH,
  SEASON_READ_MS,
  lastDayOver,
  parseSeason,
  readSeason,
  schoolSeason,
} from '../season';
import type { SeasonFile } from '../../types/generated';
import { jsonResponse } from './builders';

/** A made-up season file for these tests: schools 1, 4 and 5 of a 6-school directory. */
const STAMP = { generated_on: '2026-10-14', schools: 6, districts: 2 };
const FILE: SeasonFile = {
  schema_version: 1,
  season: '2026-2027',
  since: '2026-10-27',
  through: '2026-11-17',
  directory: STAMP,
  content_sha256: '5'.repeat(64),
  gaps: [1, 2, 0],
  closed: [2, 0, 1],
  delayed: [1, 0, 0],
  remote: [0, 3, 0],
  early_dismissal: [0, 1, 0],
};
/** Noon in Kansas City on Nov 18: Nov 17 is the last day over everywhere. */
const NOON = new Date('2026-11-18T18:00:00Z');

function changed(fields: Record<string, unknown>): unknown {
  return { ...FILE, ...fields };
}

describe('parseSeason', () => {
  it('takes the file as the pipeline writes it', () => {
    expect(parseSeason(FILE)).toBe(FILE);
    expect(parseSeason({ ...FILE, content_sha256: null, ...emptyRows() })).not.toBeNull();
  });

  it.each([
    ['another version', { schema_version: 2 }],
    ['a season that is not two years', { season: '2026-2028' }],
    ['a first day before the school year', { since: '2026-06-30' }],
    ['a first day after the last', { since: '2026-11-18' }],
    ['a last day past the school year', { through: '2027-07-01' }],
    ['a day that is not a date', { through: '2026-11-31' }],
    ['a digest that is not one', { content_sha256: 'abc' }],
    ['an emptied file with rows', { content_sha256: null }],
    ['a column of another length', { remote: [0, 3] }],
    ['a school past the directory', { gaps: [1, 2, 1] }],
    ['a row with no day', { closed: [2, 0, 0] }],
    ['more days than the stretch counted', { through: '2026-10-28', closed: [2, 0, 1] }],
    ['a count that is not whole', { delayed: [1.5, 0, 0] }],
    ['a stamp that is not one', { directory: { generated_on: 'x', schools: 6, districts: 2 } }],
  ])('refuses %s', (_, fields) => {
    expect(parseSeason(changed(fields))).toBeNull();
  });

  it('refuses what is not an object', () => {
    for (const value of [null, 3, 'season', []]) expect(parseSeason(value)).toBeNull();
  });
});

function emptyRows(): Partial<SeasonFile> {
  return { gaps: [], closed: [], delayed: [], remote: [], early_dismissal: [] };
}

describe('lastDayOver', () => {
  it('is the day before the far west’s today', () => {
    expect(lastDayOver(new Date('2026-11-18T07:59:00Z'))).toBe('2026-11-16');
    expect(lastDayOver(new Date('2026-11-18T08:00:00Z'))).toBe('2026-11-17');
    expect(lastDayOver(new Date('2027-01-01T09:00:00Z'))).toBe('2026-12-31');
  });
});

describe('schoolSeason', () => {
  it('gives a listed school’s days and when counting began', () => {
    expect(schoolSeason(FILE, 1, STAMP, NOON)).toEqual({
      days: { closed: 2, delayed: 1, remote: 0, earlyDismissal: 0 },
      since: '2026-10-27',
    });
    expect(schoolSeason(FILE, 4, STAMP, NOON)?.days).toEqual({
      closed: 0,
      delayed: 0,
      remote: 3,
      earlyDismissal: 1,
    });
    expect(schoolSeason(FILE, 5, STAMP, NOON)?.days.closed).toBe(1);
  });

  it('names no first day when counting began with the school year', () => {
    const whole = { ...FILE, since: '2026-07-01' };
    expect(schoolSeason(whole, 1, STAMP, NOON)?.since).toBeNull();
  });

  it('says nothing of a school it does not list', () => {
    for (const school of [0, 2, 3, 6]) expect(schoolSeason(FILE, school, STAMP, NOON)).toBeNull();
  });

  it('says nothing for another directory, or an emptied file', () => {
    const other = { ...STAMP, generated_on: '2026-11-01' };
    expect(schoolSeason(FILE, 1, other, NOON)).toBeNull();
    expect(schoolSeason(FILE, 1, { ...STAMP, schools: 7 }, NOON)).toBeNull();
    expect(schoolSeason({ ...FILE, content_sha256: null }, 1, STAMP, NOON)).toBeNull();
  });

  it('says nothing once its last day counted is behind, past an hour of grace', () => {
    // Nov 18 is over everywhere at 08:00 UTC on Nov 19: the file counting through Nov 17 stands
    // for the hour the pass has to count it, and no longer.
    const due = Date.parse('2026-11-19T08:00:00Z');
    expect(schoolSeason(FILE, 1, STAMP, new Date(due - 1))).not.toBeNull();
    expect(schoolSeason(FILE, 1, STAMP, new Date(due + SEASON_GRACE_MS - 1))).not.toBeNull();
    expect(schoolSeason(FILE, 1, STAMP, new Date(due + SEASON_GRACE_MS))).toBeNull();
    expect(schoolSeason(FILE, 1, STAMP, new Date(Number.NaN))).toBeNull();
  });
});

describe('readSeason', () => {
  const ROOT = 'https://snow.test/data/';
  const LIVE = 'https://live.snow.test/v1/';

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('asks for nothing where the build has no season file', async () => {
    const fetchImpl = vi.spyOn(globalThis, 'fetch');
    expect(await readSeason(createDataFiles(['live/closings.json'], ROOT))).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('reads it from the live root beside the closings, once for every panel in a while', async () => {
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(FILE)));
    const files = withLiveRoot(createDataFiles([], ROOT), LIVE);
    let now = 1_000_000;
    expect(await readSeason(files, () => now)).toEqual(FILE);
    now += SEASON_READ_MS - 1;
    expect(await readSeason(files, () => now)).toEqual(FILE);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0]?.[0]).toBe(`${LIVE}${SEASON_PATH}`);
    now += 1;
    await readSeason(files, () => now);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('gives null for a file that is missing or does not check', async () => {
    const answers = [new Response(null, { status: 404 }), jsonResponse({ schema_version: 1 })];
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(answers.shift() ?? jsonResponse(null)),
    );
    expect(await readSeason(createDataFiles([SEASON_PATH], ROOT))).toBeNull();
    expect(await readSeason(createDataFiles([SEASON_PATH], ROOT))).toBeNull();
  });
});
