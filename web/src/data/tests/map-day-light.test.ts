/**
 * Each school lit with its own map day's row (closings.ts lightSchools,
 * live.ts startLive): today's before 3:30 PM on its clock, tomorrow's from
 * then, never the other; the switch relit on time without a read, with no
 * pulse for it; a row newly announced still pulsing; and the days named.
 * Every file here is SYNTHETIC, made up for these tests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { lightSchools } from '../closings';
import type { LitSchools } from '../closings';
import { createDirectory, parsePoints } from '../directory';
import type { Directory } from '../directory';
import { createDataFiles } from '../files';
import {
  LIVE_POLL_MS,
  LIVE_READ_TIMEOUT_MS,
  LIVE_SIDE_POLL_MS,
  startLive,
  turnTimer,
} from '../live';
import type { LaterRows, LiveHost, MapDays } from '../live';
import { inContiguous, mapDay, schoolZone, zonesOf } from '../map-day';
import { dayWords } from '../../ui/map-day-host';
import { parsePredictions } from '../school-day';
import type { ClosingsFile } from '../../types/generated';
import { jsonResponse, testClosings, testDay, testMeta, testPoints } from './builders';
import type { TestSchool } from './builders';

const ROOT = 'https://snow.test/data/';
/** An Eastern school, a Pacific one, a private school in Central time, and one with no zone. */
const SCHOOLS: TestSchool[] = [
  { id: '3600000100001', name: 'East', lon: -73.9, lat: 40.7, district: 0 },
  { id: '0600000100001', name: 'West', lon: -118.2, lat: 34.0, district: 1 },
  { id: 'A0000001', name: 'Middle', lon: -94.6, lat: 39.0, district: -1, kind: 1 },
  { id: 'A0000002', name: 'Nowhere', lon: -94.5, lat: 39.1, district: -1, kind: 1 },
];
const META = testMeta(SCHOOLS, ['3600001', '0600001']);
const POINTS = parsePoints(testPoints(SCHOOLS, 2), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
const STAMP = { generated_on: META.generated_on, schools: 4, districts: 2 };

function predictionsJson(stamp = STAMP, generatedAt = '2026-11-09T20:00:00Z'): unknown {
  const calm = [{ state: 'no_threat' }, { state: 'no_threat' }];
  return {
    schema_version: 1,
    generated_at: generatedAt,
    directory: stamp,
    days: ['2026-11-09', '2026-11-10'],
    districts: [
      { district: 0, time_zone: 'America/New_York', days: calm },
      { district: 1, time_zone: 'America/Los_Angeles', days: calm },
    ],
    outlooks: [{ state: 'no_threat' }],
    zones: ['America/Chicago'],
    schools: [{ school: 2, zone: 0, days: [0, 0] }],
  };
}

const PREDICTIONS = parsePredictions(predictionsJson());
if (PREDICTIONS === null) throw new Error('the made-up predictions file did not parse');
const ZONES = zonesOf(PREDICTIONS);

/** Monday Nov 9 (closed everywhere, the West's delayed) and Tuesday (the East's remote). */
const FILE = testClosings('2026-11-09T19:00:00Z', META, [
  testDay('2026-11-09', [
    [0, 0],
    [1, 1],
    [2, 0],
    [3, 0],
  ]),
  testDay('2026-11-10', [
    [0, 2],
    [1, 3],
    [3, 2],
  ]),
]);

function lit(at: string, file: ClosingsFile = FILE): Map<number, number> {
  const shown = lightSchools(file, DIRECTORY, {
    now: new Date(at),
    previous: null,
    bornMs: 0,
    zones: ZONES,
  });
  return new Map([...shown.schools].map((school, row) => [school, shown.status[row] ?? -1]));
}

describe('lighting each school on its own map day', () => {
  it('lights today’s row until 3:29 PM on the school’s clock, and tomorrow’s from 3:30 PM', () => {
    // 3:29 PM in New York: Monday's closing.
    expect(lit('2026-11-09T20:29:00Z').get(0)).toBe(0);
    // 3:30 PM: Tuesday's remote day, never Monday's closing.
    expect(lit('2026-11-09T20:30:00Z').get(0)).toBe(2);
    // 11:59 PM: still Tuesday's; and after midnight, Tuesday is its today.
    expect(lit('2026-11-10T04:59:00Z').get(0)).toBe(2);
    expect(lit('2026-11-10T05:00:00Z').get(0)).toBe(2);
  });

  it('lights the East on tomorrow and the West on today at once (20:45 UTC on a weekday)', () => {
    const shown = lit('2026-11-09T20:45:00Z');
    expect(shown.get(0)).toBe(2);
    expect(shown.get(1)).toBe(1);
    // The private school by its own zone (Central, 2:45 PM): Monday's.
    expect(shown.get(2)).toBe(0);
    // The school with no zone: the day that is today everywhere, Monday.
    expect(shown.get(3)).toBe(0);
    // 3:30 PM in Los Angeles: Tuesday's early dismissal; the Central school has no Tuesday row.
    const later = lit('2026-11-09T23:30:00Z');
    expect(later.get(1)).toBe(3);
    expect(later.has(2)).toBe(false);
  });

  it('lights a school with no zone on the day that is today everywhere, and on none overnight', () => {
    expect(lit('2026-11-09T23:30:00Z').get(3)).toBe(0);
    expect(lit('2026-11-10T05:00:00Z').has(3)).toBe(false);
    expect(lit('2026-11-10T08:00:00Z').get(3)).toBe(2);
  });

  it('lights nothing with zones read against another directory', () => {
    const other = parsePredictions(predictionsJson({ ...STAMP, generated_on: '2026-01-01' }));
    if (other === null) throw new Error('did not parse');
    const shown = lightSchools(FILE, DIRECTORY, {
      now: new Date('2026-11-09T20:45:00Z'),
      previous: null,
      bornMs: 0,
      zones: zonesOf(other),
    });
    expect(shown.schools.size).toBe(0);
  });

  it('lights nothing from a file with a row past the end of the directory on any day', () => {
    const broken = testClosings('2026-11-09T19:00:00Z', META, [
      testDay('2026-11-09', [[0, 0]]),
      testDay('2026-11-10', [[9, 0]]),
    ]);
    expect(lit('2026-11-09T18:00:00Z', broken).size).toBe(0);
  });

  it('pulses only rows the file did not have before, never a row the turn of the day shows', () => {
    const seen = new Map([
      ['2026-11-09', new Set([0, 1, 2, 3])],
      ['2026-11-10', new Set([0, 1])],
    ]);
    const shown = lightSchools(FILE, DIRECTORY, {
      now: new Date('2026-11-10T08:30:00Z'),
      previous: new Set([0, 1]),
      bornMs: 500,
      zones: ZONES,
      seen,
    });
    // East, West and Nowhere on Tuesday: Nowhere's Tuesday row is new.
    expect([...shown.schools]).toEqual([0, 1, 3]);
    expect([...(shown.bornAt ?? [])]).toEqual([Number.NaN, Number.NaN, 500]);
  });
});

class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = 'visible';
}

function fakeHost(): LiveHost & { document: FakeDocument } {
  return {
    document: new FakeDocument(),
    setInterval: (handler, timeout) => setInterval(handler, timeout) as unknown as number,
    clearInterval: (id) => {
      clearInterval(id);
    },
  };
}

interface Run {
  readonly lights: LitSchools[];
  readonly days: (MapDays | null)[];
  readonly shown: (string | null)[];
  /** The later days given, each time (live.ts onLater). */
  readonly later: (LaterRows | null)[];
  readonly reads: () => { closings: number; predictions: number };
  readonly stop: () => void;
  readonly host: LiveHost & { document: FakeDocument };
  file: unknown;
  /** The predictions file to serve, or a promise of it (a read still on its way). */
  predictions: unknown;
  /** The directory a read of it brings: at once, unless replaced. */
  directory: () => Promise<Directory | null>;
}

function run(
  shipped = ['live/closings.json', 'predictions/latest.json'],
  file: unknown = FILE,
  viewer = 'America/New_York',
): Run {
  const lights: LitSchools[] = [];
  const days: (MapDays | null)[] = [];
  const shown: (string | null)[] = [];
  const later: (LaterRows | null)[] = [];
  const counts = { closings: 0, predictions: 0 };
  const host = fakeHost();
  const state: Run = {
    host,
    lights,
    days,
    shown,
    later,
    reads: () => ({ ...counts }),
    stop: () => undefined,
    file,
    predictions: predictionsJson(),
    directory: () => Promise.resolve<Directory | null>(DIRECTORY),
  };
  const live = startLive({
    files: createDataFiles(shipped, ROOT),
    directory: () => state.directory(),
    onLight: (next) => lights.push(next),
    onShown: (at) => shown.push(at),
    onDays: (next) => days.push(next),
    onLater: (next) => later.push(next),
    viewerZone: () => viewer,
    fetch: (url) => {
      if (url.endsWith('predictions/latest.json')) {
        counts.predictions += 1;
        const given = state.predictions;
        // A function: called for each read (one that takes its time, say).
        const served: unknown = typeof given === 'function' ? (given as () => unknown)() : given;
        return served instanceof Promise
          ? served.then((value) => jsonResponse(value))
          : Promise.resolve(jsonResponse(served));
      }
      counts.closings += 1;
      return Promise.resolve(jsonResponse(state.file));
    },
    now: () => new Date(Date.now()),
    clock: () => performance.now(),
    host,
  });
  return Object.assign(state, {
    stop: () => {
      live.stop();
    },
  });
}

const statusOf = (shown: LitSchools | undefined, school: number): number | undefined => {
  if (shown === undefined) return undefined;
  const row = [...shown.schools].indexOf(school);
  return row < 0 ? undefined : shown.status[row];
};

describe('the live map at the turn of a school’s day', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('relights at 3:30 PM on the school’s clock without a read, and the turn pulses nothing', async () => {
    // 3:29:30 PM in New York, between two polls.
    vi.setSystemTime(new Date('2026-11-09T20:29:30Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    expect(statusOf(map.lights.at(-1), 0)).toBe(0);
    const reads = map.reads();
    const lightsBefore = map.lights.length;
    // Half a minute on, 3:30 PM: Tuesday's row, before the next poll reads anything.
    await vi.advanceTimersByTimeAsync(31_000);
    expect(map.reads().closings).toBe(reads.closings);
    expect(map.lights.length).toBe(lightsBefore + 1);
    const turned = map.lights.at(-1);
    expect(statusOf(turned, 0)).toBe(2);
    // Every light it shows was a row of the file before: none pulses.
    expect([...(turned?.bornAt ?? [])].every(Number.isNaN)).toBe(true);
    map.stop();
  });

  it('relights at the turn while the page is hidden, and reads nothing for it', async () => {
    vi.setSystemTime(new Date('2026-11-09T20:25:00Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    expect(statusOf(map.lights.at(-1), 0)).toBe(0);
    map.host.document.visibilityState = 'hidden';
    const reads = map.reads();
    // Five minutes on, hidden: no poll, no read, and at 3:30 PM Tuesday's row all the same.
    await vi.advanceTimersByTimeAsync(5 * LIVE_POLL_MS + 1000);
    expect(map.reads()).toEqual(reads);
    expect(statusOf(map.lights.at(-1), 0)).toBe(2);
    map.stop();
  });

  it('pulses a tomorrow row announced after the turn', async () => {
    vi.setSystemTime(new Date('2026-11-09T21:00:00Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    // 4 PM in New York: East remote on Tuesday; West still on Monday.
    expect(statusOf(map.lights.at(-1), 0)).toBe(2);
    expect(statusOf(map.lights.at(-1), 1)).toBe(1);
    map.file = testClosings('2026-11-09T21:00:30Z', META, [
      ...FILE.days.slice(0, 1),
      testDay('2026-11-10', [
        [0, 0],
        [1, 3],
        [3, 2],
      ]),
    ]);
    // A newer file: the East's Tuesday row is now a closing (a row it had: no pulse). Add one
    // it did not have by giving the Central school a Tuesday row at its own turn.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    const changed = map.lights.at(-1);
    expect(statusOf(changed, 0)).toBe(0);
    expect([...(changed?.bornAt ?? [])].every(Number.isNaN)).toBe(true);
    map.file = testClosings('2026-11-09T21:01:30Z', META, [
      ...FILE.days.slice(0, 1),
      testDay('2026-11-10', [
        [0, 0],
        [1, 3],
        [2, 1],
        [3, 2],
      ]),
    ]);
    // 4:31 PM Central: the Central school is on Tuesday, and its row is new: it pulses.
    vi.setSystemTime(new Date('2026-11-09T22:31:00Z'));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    const added = map.lights.at(-1);
    const row = [...(added?.schools ?? [])].indexOf(2);
    expect(statusOf(added, 2)).toBe(1);
    expect(added?.bornAt?.[row]).not.toBeNaN();
    map.stop();
  });

  it('names Tuesday and Monday and where while the map shows both, and Tuesday alone after', async () => {
    vi.setSystemTime(new Date('2026-11-09T20:45:00Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    expect(map.days.at(-1)).toEqual({
      days: [
        { day: '2026-11-10', zones: ['America/New_York'], today: false },
        { day: '2026-11-09', zones: ['America/Los_Angeles', 'America/Chicago', null], today: true },
      ],
      viewerToday: '2026-11-09',
    });
    // 3:30 PM in Los Angeles: Tuesday everywhere but the school with no zone (Monday still).
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T23:30:00Z') - Date.now() + 1000);
    expect(map.days.at(-1)?.days.map((shown) => shown.day)).toEqual(['2026-11-10', '2026-11-09']);
    // Past 08:00 UTC, the school with no zone is on Tuesday too: one day, not the viewer's today
    // until their own midnight has passed (it has, in New York).
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T08:00:00Z') - Date.now() + 1000);
    expect(map.days.at(-1)).toEqual({
      days: [
        {
          day: '2026-11-10',
          zones: ['America/New_York', 'America/Los_Angeles', 'America/Chicago', null],
          today: true,
        },
      ],
      viewerToday: '2026-11-10',
    });
    map.stop();
  });

  it('reads the predictions file only where the agreed day cannot tell a school’s day, ahead of 3:30 PM in the East, and once', async () => {
    // 1 PM in New York: every contiguous clock on Monday, before 3:30 PM: each school's own map
    // day, and no predictions file asked for.
    vi.setSystemTime(new Date('2026-11-09T18:00:00Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    expect(map.reads().predictions).toBe(0);
    expect([...(map.lights.at(-1)?.schools ?? [])]).toEqual([0, 1, 2, 3]);
    // Five minutes before 3:30 PM in New York (20:30 UTC): read, so the zones are in by then.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:24:00Z') - Date.now());
    expect(map.reads().predictions).toBe(0);
    await vi.advanceTimersByTimeAsync(2 * LIVE_POLL_MS);
    expect(map.reads().predictions).toBe(1);
    // Held for the file's directory, the zones are not read again: a district's zone does not age.
    await vi.advanceTimersByTimeAsync(3 * LIVE_SIDE_POLL_MS);
    expect(map.reads().predictions).toBe(1);
    // 3:30 PM in New York: the East on Tuesday by its zone, the West still on Monday.
    expect(statusOf(map.lights.at(-1), 0)).toBe(2);
    expect(statusOf(map.lights.at(-1), 1)).toBe(1);
    map.stop();
  });

  it('never reads the predictions file for a file that lists no school', async () => {
    vi.setSystemTime(new Date('2026-11-09T18:00:00Z'));
    const map = run(undefined, testClosings('2026-11-09T19:00:00Z', META, []));
    await vi.advanceTimersByTimeAsync(10);
    expect(map.reads().predictions).toBe(0);
    expect(map.shown.at(-1)).toBe('2026-11-09T19:00:00Z');
    map.stop();
  });

  it('lights only the day every clock agrees on while the zones cannot be had, never a guessed day', async () => {
    // 4 PM in New York, 1 PM in Los Angeles, and no zones to tell them apart: nothing lit, for
    // the East is on Tuesday and the West on Monday. No update time stands over a map that
    // cannot show the file's rows, and no day is named.
    vi.setSystemTime(new Date('2026-11-09T21:00:00Z'));
    const map = run();
    map.predictions = { broken: true };
    await vi.advanceTimersByTimeAsync(10);
    expect(map.lights).toEqual([]);
    expect(map.shown.at(-1) ?? null).toBeNull();
    expect(map.days.at(-1) ?? null).toBeNull();
    // 3:30 PM in Los Angeles: Tuesday on every zoned clock, but Monday still everywhere, the day
    // of a school the file may give no zone (Nowhere's Monday closing): still none lit, so no
    // school's light steps back from Tuesday to Monday once the zones are read.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T23:30:00Z') - Date.now() + 1000);
    expect(map.lights).toEqual([]);
    expect(map.shown.at(-1) ?? null).toBeNull();
    expect(map.days.at(-1) ?? null).toBeNull();
    // 04:00 UTC: past midnight in the East, not in the West: no day every clock calls today,
    // so none lit (the school panel names none either), and none named.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T04:00:00Z') - Date.now() + 1000);
    expect(map.lights).toEqual([]);
    expect(map.shown.at(-1) ?? null).toBeNull();
    expect(map.days.at(-1) ?? null).toBeNull();
    // 08:00 UTC: Tuesday everywhere, before 3:30 PM: today's rows again.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T08:00:00Z') - Date.now() + 1000);
    expect([...(map.lights.at(-1)?.schools ?? [])]).toEqual([0, 1, 3]);
    expect(map.days.at(-1)?.days).toEqual([{ day: '2026-11-10', zones: ['*'], today: true }]);
    map.stop();
  });

  it('tells each school’s day by its zone once the file for its directory comes', async () => {
    vi.setSystemTime(new Date('2026-11-09T21:00:00Z'));
    const map = run();
    // A file for another directory: no zone read from it.
    map.predictions = predictionsJson({ ...STAMP, generated_on: '2026-01-01' });
    await vi.advanceTimersByTimeAsync(10);
    expect(map.lights).toEqual([]);
    // The right file comes: each school by its own day, the East on Tuesday, the West on Monday.
    map.predictions = predictionsJson(STAMP, '2026-11-09T21:05:00Z');
    await vi.advanceTimersByTimeAsync(LIVE_SIDE_POLL_MS);
    expect(statusOf(map.lights.at(-1), 0)).toBe(2);
    expect(statusOf(map.lights.at(-1), 1)).toBe(1);
    map.stop();
  });

  for (const hidden of [false, true]) {
    it(`reads a predictions file for another directory less and less often${hidden ? ' while hidden' : ''}, and lights once the right one comes`, async () => {
      // A Monday from 7 AM in New York to the next day's 9 AM: the zones never had, for the file
      // is for another directory all the while (as at a change of directory).
      vi.setSystemTime(new Date('2026-11-09T12:00:00Z'));
      const map = run();
      map.predictions = predictionsJson({ ...STAMP, generated_on: '2026-01-01' });
      await vi.advanceTimersByTimeAsync(10);
      if (hidden) map.host.document.visibilityState = 'hidden';
      // Lit by the day every contiguous clock agrees on, reading nothing for it until the
      // East's 3:30 PM nears.
      expect([...(map.lights.at(-1)?.schools ?? [])]).toEqual([0, 1, 2, 3]);
      expect(map.reads().predictions).toBe(0);
      await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:24:00Z') - Date.now());
      expect(map.reads().predictions).toBe(0);
      // Read from 3:25 PM in New York, then 5, 10, 20 and every 30 minutes at most while the
      // agreed day has none, never every few minutes, and not at all once it has one again.
      await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T08:00:00Z') - Date.now());
      const night = map.reads().predictions;
      expect(night).toBeGreaterThanOrEqual(hidden ? 2 : 20);
      expect(night).toBeLessThanOrEqual(26);
      await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T14:00:00Z') - Date.now());
      expect(map.reads().predictions).toBe(night);
      // Lit all morning by the agreed day: Tuesday's rows.
      expect(statusOf(map.lights.at(-1), 0)).toBe(2);
      // 3:25 PM Tuesday in New York: read again ahead of the turn (a page not seen too) at once,
      // the wait between reads now as long as it has grown; the right file comes, and each
      // school lights by its own zone at the East's turn.
      map.predictions = predictionsJson(STAMP, '2026-11-10T20:00:00Z');
      await vi.advanceTimersByTimeAsync(Date.parse('2026-11-10T20:30:30Z') - Date.now());
      expect(map.reads().predictions).toBe(night + 1);
      expect(statusOf(map.lights.at(-1), 1)).toBe(3);
      map.stop();
      // A day and a half of the page's timers run through: 2 s on a CI runner, more on a busy one.
    }, 30_000);
  }

  it('reads the zones ahead of the East’s 3:30 PM in a page not seen, so the map is never dark at the turn', async () => {
    // 10 AM in New York, the zones not read: lit by the day every contiguous clock agrees on.
    vi.setSystemTime(new Date('2026-11-09T15:00:00Z'));
    const map = run();
    // Each read of the predictions file takes 30 seconds to come.
    map.predictions = () =>
      new Promise((resolve) => {
        setTimeout(() => {
          resolve(predictionsJson());
        }, 30_000);
      });
    await vi.advanceTimersByTimeAsync(10);
    expect(statusOf(map.lights.at(-1), 0)).toBe(0);
    expect(map.reads().predictions).toBe(0);
    // Hidden: no poll runs from now on.
    map.host.document.visibilityState = 'hidden';
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:24:00Z') - Date.now());
    expect(map.reads().predictions).toBe(0);
    // 3:25 PM: read ahead of the turn, and in before it.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:26:00Z') - Date.now());
    expect(map.reads().predictions).toBe(1);
    // 3:30:30 PM: the East on Tuesday by its zone, the West on Monday: no moment dark.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:30:30Z') - Date.now());
    const turned = map.lights.at(-1);
    expect(statusOf(turned, 0)).toBe(2);
    expect(statusOf(turned, 1)).toBe(1);
    expect(map.lights.every((shown) => shown.schools.size > 0)).toBe(true);
    expect(map.shown.at(-1)).toBe('2026-11-09T19:00:00Z');
    map.stop();
  });

  it('lights a school its file gives no zone, from the first read, on the day that is today everywhere', async () => {
    vi.setSystemTime(new Date('2026-11-09T21:00:00Z'));
    const map = run();
    map.predictions = { ...(predictionsJson() as object), districts: [], schools: [] };
    await vi.advanceTimersByTimeAsync(10);
    // No school has a zone: every one by the day that is today everywhere, Monday.
    expect([...(map.lights.at(-1)?.schools ?? [])]).toEqual([0, 1, 2, 3]);
    expect(statusOf(map.lights.at(-1), 0)).toBe(0);
    expect(map.days.at(-1)?.days).toEqual([{ day: '2026-11-09', zones: [null], today: true }]);
    map.stop();
  });

  it('lights at once while the zones are on their way, by the day every clock agrees on, then by them with no pulse', async () => {
    // 3:26 PM in New York: every contiguous clock on Monday, the zones read ahead of 3:30 PM.
    vi.setSystemTime(new Date('2026-11-09T20:26:00Z'));
    let serve: (value: unknown) => void = () => undefined;
    const map = run();
    map.predictions = new Promise((resolve) => {
      serve = resolve;
    });
    await vi.advanceTimersByTimeAsync(10);
    // Lit from the closings file and the directory alone: the predictions file is still coming.
    expect(map.reads().predictions).toBe(1);
    expect(map.lights).toHaveLength(1);
    expect([...(map.lights[0]?.schools ?? [])]).toEqual([0, 1, 2, 3]);
    expect(map.shown.at(-1)).toBe('2026-11-09T19:00:00Z');
    serve(predictionsJson());
    await vi.advanceTimersByTimeAsync(10);
    // The zones come: lit again by them, the same rows, and none pulses.
    expect(map.lights).toHaveLength(2);
    expect([...(map.lights[1]?.schools ?? [])]).toEqual([0, 1, 2, 3]);
    expect([...(map.lights[1]?.bornAt ?? [])].every(Number.isNaN)).toBe(true);
    // 3:30 PM in New York: the East turns to Tuesday by its zone, with no pulse.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:30:00Z') - Date.now() + 1000);
    expect(statusOf(map.lights.at(-1), 0)).toBe(2);
    expect([...(map.lights.at(-1)?.bornAt ?? [])].every(Number.isNaN)).toBe(true);
    map.stop();
  });

  it('a row new in a file whose directory came late still pulses once it lights', async () => {
    vi.setSystemTime(new Date('2026-11-09T15:00:00Z'));
    const map = run(
      undefined,
      testClosings('2026-11-09T15:00:00Z', META, [
        testDay('2026-11-09', [
          [0, 0],
          [1, 1],
        ]),
      ]),
    );
    await vi.advanceTimersByTimeAsync(10);
    expect([...(map.lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
    // A newer file, with the Central school's closing new in it; its directory read runs late.
    map.file = testClosings('2026-11-09T15:00:30Z', META, [
      testDay('2026-11-09', [
        [0, 0],
        [1, 1],
        [2, 0],
      ]),
    ]);
    let slow: Promise<Directory | null> | null = null;
    // The first read of it from now on takes past the limit; a read asked again joins it.
    map.directory = () =>
      (slow ??= new Promise<Directory | null>((resolve) => {
        setTimeout(() => {
          resolve(DIRECTORY);
        }, LIVE_READ_TIMEOUT_MS + 5_000);
      }));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS + LIVE_READ_TIMEOUT_MS + 1_000);
    // Past the read's limit: dark for the file.
    expect(map.lights.at(-1)?.schools.size).toBe(0);
    await vi.advanceTimersByTimeAsync(5_000);
    // The directory came: lit, and the closing new in the file pulses; the two it had do not.
    const lit = map.lights.at(-1);
    expect([...(lit?.schools ?? [])]).toEqual([0, 1, 2]);
    expect(Number.isNaN(lit?.bornAt?.[0])).toBe(true);
    expect(Number.isNaN(lit?.bornAt?.[1])).toBe(true);
    expect(lit?.bornAt?.[2]).not.toBeNaN();
    map.stop();
  });

  it('names the day for a visitor whose browser keeps UTC, already on Tuesday at 7:30 PM in New York', async () => {
    vi.setSystemTime(new Date('2026-11-10T00:30:00Z'));
    // Every school past 3:30 PM on its clock: Tuesday, no clock's today.
    const map = run(
      undefined,
      testClosings('2026-11-10T00:00:00Z', META, [
        testDay('2026-11-10', [
          [0, 2],
          [1, 3],
        ]),
      ]),
      'UTC',
    );
    await vi.advanceTimersByTimeAsync(10);
    const days = map.days.at(-1) ?? null;
    expect(days?.viewerToday).toBe('2026-11-10');
    // Every clock past 3:30 PM: Tuesday, told by the zones (read at once, for the day every
    // contiguous clock agrees on is no day while it is still Monday everywhere).
    expect(days?.days).toEqual([
      {
        day: '2026-11-10',
        zones: ['America/New_York', 'America/Los_Angeles', 'America/Chicago'],
        today: false,
      },
    ]);
    expect(dayWords(days)).toBe('Showing Tuesday');
    map.stop();
  });

  it('runs a turn its timer reached early again once the clock has reached it, and only then marks it run', async () => {
    vi.setSystemTime(new Date('2026-11-09T20:29:00Z'));
    const at = Date.parse('2026-11-09T20:30:00Z');
    let clock = Date.now();
    const runs: number[] = [];
    const timer = turnTimer(
      () => {
        runs.push(clock);
        // As a relight does: the turn its clock still sees ahead is waited for again.
        timer.set(new Date(at), new Date(clock));
      },
      () => clock,
    );
    timer.set(new Date(at), new Date(clock));
    // The timer fires, but the wall clock was set back meanwhile: a minute short of the turn.
    clock = at - 60_000;
    await vi.advanceTimersByTimeAsync(60_000 + 300);
    expect(runs).toEqual([at - 60_000]);
    // Waited for again, and run when the clock is there; then not waited for again.
    clock = at + 300;
    await vi.advanceTimersByTimeAsync(60_000 + 300);
    expect(runs).toEqual([at - 60_000, at + 300]);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(runs).toHaveLength(2);
    timer.stop();
  });

  it('lights every school on the day that is today everywhere in a build without predictions', async () => {
    vi.setSystemTime(new Date('2026-11-09T21:00:00Z'));
    const map = run(['live/closings.json']);
    await vi.advanceTimersByTimeAsync(10);
    expect(map.reads().predictions).toBe(0);
    expect(statusOf(map.lights.at(-1), 0)).toBe(0);
    expect(map.days.at(-1)).toEqual({
      days: [{ day: '2026-11-09', zones: [null], today: true }],
      viewerToday: '2026-11-09',
    });
    map.stop();
  });
});

describe('the day every contiguous US clock agrees on, while the zones cannot be read', () => {
  /** A school in each zone the directory's states keep, at a place in it. */
  const PLACES: readonly [string, number, number][] = [
    ['America/New_York', -73.9, 40.7],
    ['America/Detroit', -83.0, 42.3],
    ['America/Indiana/Indianapolis', -86.2, 39.8],
    ['America/Kentucky/Louisville', -85.8, 38.3],
    ['America/Chicago', -87.6, 41.9],
    ['America/Indiana/Knox', -86.6, 41.3],
    ['America/North_Dakota/Center', -101.3, 47.1],
    ['America/Menominee', -87.6, 45.1],
    ['America/Denver', -105.0, 39.7],
    ['America/Boise', -116.2, 43.6],
    ['America/Phoenix', -112.1, 33.4],
    ['America/Los_Angeles', -118.2, 34.0],
    ['America/Anchorage', -149.9, 61.2],
    ['America/Juneau', -134.4, 58.3],
    ['America/Metlakatla', -131.6, 55.1],
    ['America/Adak', -176.6, 51.9],
    ['Pacific/Honolulu', -157.9, 21.3],
    ['America/Puerto_Rico', -66.1, 18.4],
    ['Pacific/Guam', 144.8, 13.4],
  ];
  /**
   * Every 70 minutes of a year from Nov 1, 2026 (a clock change) through Nov 2027 (two more),
   * so each hour of the day comes round, and every 5 minutes of each change day.
   */
  const YEAR = [
    ...Array.from(
      { length: Math.floor((380 * 24 * 60) / 70) },
      (_, i) => new Date(Date.parse('2026-11-01T00:00:00Z') + i * 70 * 60_000),
    ),
    ...['2026-11-01', '2027-03-14', '2027-11-07'].flatMap((day) =>
      Array.from(
        { length: 12 * 36 },
        (_, i) => new Date(Date.parse(`${day}T00:00:00Z`) + i * 5 * 60_000),
      ),
    ),
  ];

  it('lights a school only on its own map day, and never one outside the contiguous US', () => {
    const lit = new Map<string, number>();
    for (const now of YEAR) {
      // The day is the same for every school it lights: the one the five clocks agree on.
      const day = mapDay(now, schoolZone(undefined, 0, 0, -73.9, 40.7));
      if (day === null) continue;
      for (const [zone, lon, lat] of PLACES) {
        const unread = schoolZone(undefined, 0, 0, lon, lat);
        if (!inContiguous(lon, lat)) {
          expect(unread).not.toBe(schoolZone(undefined, 0, 0, -73.9, 40.7));
          continue;
        }
        lit.set(zone, (lit.get(zone) ?? 0) + 1);
        expect(day, `${zone} ${now.toISOString()}`).toBe(mapDay(now, zone));
      }
    }
    // Outside the contiguous US no school is lit by it at any hour, and it lights no day there.
    for (const [zone, lon, lat] of PLACES) {
      expect(lit.has(zone), zone).toBe(inContiguous(lon, lat));
      if (!inContiguous(lon, lat)) {
        expect(
          YEAR.slice(0, 200).some(
            (now) => mapDay(now, schoolZone(undefined, 0, 0, lon, lat)) !== null,
          ),
        ).toBe(false);
      }
    }
    // Every 70 minutes of a year and every 5 of three clock change days, at each place: 2 s on a
    // CI runner, more on a busy one.
  }, 30_000);
});

/** The later days given last as day → [school, status] pairs, for reading at a glance. */
function laterOf(given: LaterRows | null | undefined): Record<string, [number, number][]> {
  const out: Record<string, [number, number][]> = {};
  for (const { day, schools, statuses } of given?.days ?? []) {
    out[day] = schools.map((school, i) => [school, statuses[i] ?? -1]);
  }
  return out;
}

describe('the rows for later days than each school’s map day (the later-day rings)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('gives each school’s rows after its own map day, and none of its map day’s', async () => {
    // 2 PM in New York on Monday: every school shows Monday, and Tuesday is a later day for all.
    vi.setSystemTime(new Date('2026-11-09T19:00:00Z'));
    const map = run();
    await vi.advanceTimersByTimeAsync(10);
    const given = map.later.at(-1);
    expect(laterOf(given)).toEqual({
      '2026-11-10': [
        [0, 2],
        [1, 3],
        [3, 2],
      ],
    });
    // The lights today go with them: a light wins over a ring at its school.
    expect([...(given?.lit.schools ?? [])]).toEqual([0, 1, 2, 3]);
    // 3:30 PM in New York: Tuesday is the East's map day, its light, and no longer later for it.
    await vi.advanceTimersByTimeAsync(91 * 60_000);
    expect(laterOf(map.later.at(-1))).toEqual({
      '2026-11-10': [
        [1, 3],
        [3, 2],
      ],
    });
    map.stop();
  });

  it('reads the directory for a file that lists only later days, and lights nothing', async () => {
    vi.setSystemTime(new Date('2026-11-09T19:00:00Z'));
    const map = run(
      undefined,
      testClosings('2026-11-09T18:00:00Z', META, [testDay('2026-11-11', [[1, 0]])]),
    );
    await vi.advanceTimersByTimeAsync(10);
    // Shown, with nothing lit: a map with no closing today, and a ring on Wednesday.
    expect(map.shown.at(-1)).toBe('2026-11-09T18:00:00Z');
    expect(map.lights.every((light) => light.schools.size === 0)).toBe(true);
    expect(laterOf(map.later.at(-1))).toEqual({ '2026-11-11': [[1, 0]] });
    map.stop();
  });

  it('gives none while no file is shown, so no ring outlives its file', async () => {
    vi.setSystemTime(new Date('2026-11-09T19:00:00Z'));
    const map = run();
    map.directory = () => Promise.resolve(null);
    await vi.advanceTimersByTimeAsync(10);
    expect(map.later.at(-1)).toBeNull();
    map.stop();
  });
});
