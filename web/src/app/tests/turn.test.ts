/**
 * The minute a school's day turns under way (chance.ts nextTurn, latestZone, data/live.ts
 * turnTimer): an open panel shows the next day's chance, and "Open today", at that minute,
 * not at its next read of the live files. Made-up schools and files, in the files' shapes.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { copy } from '../../copy';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles } from '../../data/files';
import { turnTimer } from '../../data/live';
import type { Outlook } from '../../data/school-day';
import { jsonResponse, testClosings, testMeta } from '../../data/tests/builders';
import { STATES } from '../../search/states';
import { latestZone, nextTurn } from '../chance';
import { watchSchool } from '../school';
import type { SchoolView } from '../school';

const WAIT = { timeout: 4_000 };

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the clock a school keeps without the file’s zone', () => {
  it('is the latest any part of its state keeps', () => {
    const latest: Record<string, string> = {
      NY: 'America/New_York',
      GA: 'America/New_York',
      DC: 'America/New_York',
      FL: 'America/Chicago',
      IN: 'America/Chicago',
      KY: 'America/Chicago',
      MI: 'America/Chicago',
      TN: 'America/Chicago',
      MO: 'America/Chicago',
      TX: 'America/Denver',
      KS: 'America/Denver',
      ND: 'America/Denver',
      CO: 'America/Denver',
      AZ: 'America/Phoenix',
      ID: 'America/Los_Angeles',
      OR: 'America/Los_Angeles',
      WA: 'America/Los_Angeles',
      AK: 'America/Adak',
      HI: 'Pacific/Honolulu',
      AS: 'Pacific/Pago_Pago',
      GU: 'Pacific/Guam',
      MP: 'Pacific/Saipan',
      PR: 'America/Puerto_Rico',
      VI: 'America/St_Thomas',
      // A state not known: the latest of any US clock.
      '': 'Pacific/Pago_Pago',
    };
    for (const [state, zone] of Object.entries(latest)) expect(latestZone(state)).toBe(zone);
    // Every state and territory the search knows is in the table, with a clock this browser
    // reads (only American Samoa keeps the clock a state not known is given).
    expect(STATES.length).toBeGreaterThan(50);
    for (const [state] of STATES) {
      expect(() => new Intl.DateTimeFormat('en-US', { timeZone: latestZone(state) })).not.toThrow();
      if (state !== 'AS') expect(latestZone(state), state).not.toBe(latestZone(''));
    }
  });
});

describe('the next turn of a school’s day', () => {
  const pacific: Outlook = {
    today: { state: 'no_threat' },
    tomorrow: null,
    neighbors: [],
    timeZone: 'America/Los_Angeles',
  };

  it('is 7:30 AM on its clock today, then tomorrow', () => {
    // 6 AM in Seattle on Wednesday Oct 28: 7:30 AM PDT is 14:30 UTC.
    expect(nextTurn(pacific, 'America/Chicago', new Date('2026-10-28T13:00:00Z'))).toEqual(
      new Date('2026-10-28T14:30:00Z'),
    );
    expect(nextTurn(pacific, 'America/Chicago', new Date('2026-10-28T14:30:00Z'))).toEqual(
      new Date('2026-10-29T14:30:00Z'),
    );
    // Without an outlook: the zone given.
    expect(nextTurn(null, 'Pacific/Honolulu', new Date('2026-10-28T13:00:00Z'))).toEqual(
      new Date('2026-10-28T17:30:00Z'),
    );
  });

  it('is 7:30 AM on both days the clocks change', () => {
    // Sunday Nov 1 2026, the clocks go back: 7:30 AM PST is 15:30 UTC.
    expect(nextTurn(null, 'America/Los_Angeles', new Date('2026-11-01T10:00:00Z'))).toEqual(
      new Date('2026-11-01T15:30:00Z'),
    );
    // Sunday Mar 14 2027, forward: 7:30 AM CDT is 12:30 UTC.
    expect(nextTurn(null, 'America/Chicago', new Date('2027-03-14T09:00:00Z'))).toEqual(
      new Date('2027-03-14T12:30:00Z'),
    );
  });

  it('is the buses where they run before 7:30', () => {
    const buses: Outlook = {
      today: {
        state: 'forecast',
        noSchool: 0.4,
        delay: 0.1,
        reasons: [],
        day: '2026-10-28',
        detail: { busesAt: new Date('2026-10-28T14:00:00Z') } as never,
      },
      tomorrow: null,
      neighbors: [],
      timeZone: 'America/Los_Angeles',
    };
    expect(nextTurn(buses, 'America/Chicago', new Date('2026-10-28T13:00:00Z'))).toEqual(
      new Date('2026-10-28T14:00:00Z'),
    );
    expect(nextTurn(buses, 'America/Chicago', new Date('2026-10-28T14:00:00Z'))).toEqual(
      new Date('2026-10-29T14:30:00Z'),
    );
  });

  it('is none where no clock can be read', () => {
    expect(nextTurn(null, 'Mars/Base', new Date('2026-10-28T13:00:00Z'))).toBeNull();
  });
});

describe('the turn timer', () => {
  it('runs once at the turn, never twice for it, and not after it stops', () => {
    vi.useFakeTimers();
    const now = new Date('2026-10-28T13:00:00Z');
    vi.setSystemTime(now);
    const run = vi.fn();
    const timer = turnTimer(run);
    const turn = new Date('2026-10-28T14:30:00Z');
    timer.set(turn, now);
    timer.set(turn, now);
    vi.advanceTimersByTime(90 * 60_000 - 1);
    expect(run).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1_000);
    expect(run).toHaveBeenCalledTimes(1);
    // A clock that stands still names the same turn again: it is not waited for twice.
    timer.set(turn, now);
    vi.advanceTimersByTime(3 * 3_600_000);
    expect(run).toHaveBeenCalledTimes(1);
    // A turn far ahead is waited for in parts; a stop cancels it.
    timer.set(new Date('2026-10-29T14:30:00Z'), new Date('2026-10-28T14:30:00Z'));
    timer.stop();
    vi.advanceTimersByTime(48 * 3_600_000);
    expect(run).toHaveBeenCalledTimes(1);
  });
});

describe('an open panel at the turn', () => {
  it('says Open today at 7:30 AM on the school’s clock without waiting for its next read', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    // 7:29 AM in Kansas City, the private school's clock with no file zone (Missouri keeps
    // Central time alone): 7:29 AM CST is 13:29 UTC on Monday Jan 12.
    vi.setSystemTime(new Date('2026-01-12T13:29:00Z'));
    const meta = testMeta([
      { id: '010000500870', name: 'A', lon: 0, lat: 0, district: 0 },
      { id: '010000500871', name: 'B', lon: 0, lat: 0, district: 0 },
      { id: 'ZZ000001', name: 'C', lon: 0, lat: 0, district: -1 },
    ]);
    const stamp = '2026-01-12T13:25:00Z';
    const closings = testClosings(stamp, meta, []);
    const covered = {
      schema_version: 1,
      generated_at: stamp,
      directory: closings.directory,
      ranges: [[0, 3]],
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) =>
      Promise.resolve(
        jsonResponse(
          String(url instanceof Request ? url.url : url).includes('covered') ? covered : closings,
        ),
      ),
    );
    const record: SchoolRecord = {
      id: 'ZZ000001',
      index: 2,
      name: 'THE TEST HILL SCHOOL',
      private: true,
      charter: false,
      virtual: false,
      district: null,
      street: null,
      city: 'KANSAS CITY',
      state: 'MO',
      zip: null,
      county: null,
      grades: { low: 'PK', high: '12' },
      enrollment: 100,
      phone: null,
      nearby: [],
      directory: closings.directory,
    };
    const details: DetailsSource = { get: vi.fn(() => Promise.resolve(record)) };
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files: createDataFiles(
        ['live/closings.json', 'live/covered.json', 'schools/details/index.0123456789.json'],
        'https://snow.test/data/',
      ),
      details,
      id: record.id,
      hint: null,
      onView: (view) => views.push(view),
      timeZone: () => 'America/Chicago',
      // No read again before the turn: the turn alone shows it.
      pollMs: 3_600_000,
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
    }, WAIT);
    expect(views.at(-1)?.status).toEqual([]);
    const before = views.length;
    await vi.advanceTimersByTimeAsync(61_000);
    expect(views.length).toBeGreaterThan(before);
    expect(views.at(-1)?.status.map((line) => line.headline)).toEqual([copy.open.today]);
    stop();
  });
});
