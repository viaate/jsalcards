import { afterEach, describe, expect, it, vi } from 'vitest';

import { seasonFormat } from '../../copy-season';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles, withLiveRoot } from '../../data/files';
import { NO_STATUS } from '../../data/school-day';
import { SEASON_PATH } from '../../data/season';
import { jsonResponse } from '../../data/tests/builders';
import type { SeasonFile } from '../../types/generated';
import { schoolView, watchSchool } from '../school';
import type { SchoolView, ViewInput } from '../school';

/** Made up for these tests: a public school at index 4 of a 6-school directory. */
const STAMP = { generated_on: '2026-10-14', schools: 6, districts: 2 };
const SCHOOL: SchoolRecord = {
  id: '290000199999',
  index: 4,
  name: 'BELLE ELEM.',
  private: false,
  charter: false,
  virtual: false,
  district: { index: 0, id: '2999999', name: 'MARIES CO. R-II' },
  street: null,
  city: 'BELLE',
  state: 'MO',
  zip: null,
  county: null,
  grades: { low: 'KG', high: '04' },
  enrollment: 0,
  phone: null,
  nearby: [],
  directory: STAMP,
};
/** SYNTHETIC: school 4 closed two days and delayed one since Oct 27; school 1 remote once. */
const FILE: SeasonFile = {
  schema_version: 1,
  season: '2026-2027',
  since: '2026-10-27',
  through: '2026-11-17',
  directory: STAMP,
  content_sha256: '5'.repeat(64),
  gaps: [1, 2],
  closed: [0, 2],
  delayed: [0, 1],
  remote: [1, 0],
  early_dismissal: [0, 0],
};
/** Noon in Kansas City on Nov 18: Nov 17 is the last day over everywhere. */
const NOON = new Date('2026-11-18T18:00:00Z');
const LINE = 'This school year, since Oct 27: closed 2 days, delayed 1.';

function input(overrides: Partial<ViewInput> = {}): ViewInput {
  return {
    id: SCHOOL.id,
    hint: null,
    record: SCHOOL,
    settled: true,
    status: NO_STATUS,
    outlook: null,
    now: NOON,
    timeZone: 'America/Chicago',
    season: FILE,
    ...overrides,
  };
}

describe('the school view’s season line', () => {
  it('says the school’s days, and since when they were counted', () => {
    expect(schoolView(input())?.season).toBe(LINE);
    expect(LINE).toBe(
      seasonFormat.line({ closed: 2, delayed: 1, remote: 0, earlyDismissal: 0 }, '2026-10-27'),
    );
    const whole = { ...FILE, since: '2026-07-01' };
    expect(schoolView(input({ season: whole }))?.season).toBe(
      'This school year: closed 2 days, delayed 1.',
    );
  });

  it('says nothing for a school with no day counted', () => {
    const other = { ...SCHOOL, index: 3 };
    expect(schoolView(input({ record: other }))?.season).toBeNull();
  });

  it('says nothing without a file, from a stale one, or from another directory’s', () => {
    expect(schoolView(input({ season: null }))?.season).toBeNull();
    const none: ViewInput = { ...input() };
    delete (none as { season?: unknown }).season;
    expect(schoolView(none)?.season).toBeNull();
    const stale = new Date('2026-11-19T09:00:00Z');
    expect(schoolView(input({ now: stale }))?.season).toBeNull();
    const elsewhere = { ...FILE, directory: { ...STAMP, generated_on: '2026-11-01' } };
    expect(schoolView(input({ season: elsewhere }))?.season).toBeNull();
    const blank = {
      ...FILE,
      content_sha256: null,
      gaps: [],
      closed: [],
      delayed: [],
      remote: [],
      early_dismissal: [],
    };
    expect(schoolView(input({ season: blank }))?.season).toBeNull();
  });

  it('says nothing on a past day: the season so far is not that day’s', () => {
    const replay = { day: '2026-11-03', lookup: { status: () => null } } as unknown as NonNullable<
      ViewInput['replay']
    >;
    expect(schoolView(input({ replay }))?.season).toBeNull();
  });
});

describe('a watched school’s season line', () => {
  const ROOT = 'https://snow.test/data/';
  const LIVE = 'https://live.snow.test/v1/';
  const details: DetailsSource = { get: vi.fn(() => Promise.resolve(SCHOOL)) };

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function urlOf(input: string | URL | Request): string {
    return input instanceof Request ? input.url : input.toString();
  }

  async function watch(
    seasons: boolean,
    answer: (url: string) => Response,
  ): Promise<{
    views: (SchoolView | null)[];
    asked: string[];
  }> {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const asked: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      asked.push(urlOf(url));
      return Promise.resolve(answer(urlOf(url)));
    });
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files: withLiveRoot(createDataFiles(['schools/details/index.0123456789.json'], ROOT), LIVE),
      details,
      id: SCHOOL.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
      seasons,
    });
    await vi.advanceTimersByTimeAsync(50);
    stop();
    return { views, asked };
  }

  it('reads the season file from the live root as the panel opens, and shows the line', async () => {
    const { views, asked } = await watch(true, (url) =>
      url.endsWith(SEASON_PATH) ? jsonResponse(FILE) : new Response(null, { status: 404 }),
    );
    expect(asked).toContain(`${LIVE}${SEASON_PATH}`);
    expect(views.at(-1)?.season).toBe(LINE);
  });

  it('shows no line when the file is missing or does not check', async () => {
    const missing = await watch(true, () => new Response(null, { status: 404 }));
    expect(missing.views.at(-1)?.season ?? null).toBeNull();
    vi.restoreAllMocks();
    const bad = await watch(true, (url) =>
      url.endsWith(SEASON_PATH)
        ? jsonResponse({ ...FILE, closed: [0, 30] })
        : new Response(null, { status: 404 }),
    );
    expect(bad.views.at(-1)?.season ?? null).toBeNull();
  });

  it('asks for no season file unless the page’s panel wants one', async () => {
    const { asked } = await watch(false, () => new Response(null, { status: 404 }));
    expect(asked.some((url) => url.endsWith(SEASON_PATH))).toBe(false);
  });
});
