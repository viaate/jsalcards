import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import type { Directory } from '../../data/directory';
import { Status, type ClosingsFile, type PredictionsFile } from '../../types/generated';
import {
  dayOptions,
  dayState,
  defaultDays,
  nearestZone,
  offeredDays,
  onTheMap,
  predictionZones,
  readIssues,
  readRuns,
  runState,
  statusZone,
  summarizePredictions,
  type ListedStatus,
  type ListedTarget,
} from '../overview';

describe('runState', () => {
  it('reads a run’s status and conclusion', () => {
    expect(runState({ status: 'completed', conclusion: 'success' })).toBe('success');
    expect(runState({ status: 'completed', conclusion: 'timed_out' })).toBe('failure');
    expect(runState({ status: 'completed', conclusion: 'cancelled' })).toBe('cancelled');
    expect(runState({ status: 'in_progress', conclusion: null })).toBe('running');
    expect(runState({ status: 'queued', conclusion: null })).toBe('queued');
    expect(runState({ status: 'completed', conclusion: 'neutral' })).toBe('other');
  });
});

describe('the GitHub reads', () => {
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}): Response =>
    new Response(JSON.stringify(body), { status, headers });

  it('takes each workflow’s latest run, and says when none ran', async () => {
    const runs = await readRuns((url) =>
      Promise.resolve(
        url.includes('/api.yml/')
          ? json({ workflow_runs: [] })
          : json({
              workflow_runs: [
                {
                  status: 'completed',
                  conclusion: 'failure',
                  updated_at: '2026-10-20T18:00:00Z',
                  html_url: 'https://github.com/o/r/actions/runs/1',
                },
              ],
            }),
      ),
    );
    expect(runs.limited).toBe(false);
    expect(runs.runs.find((r) => r.workflow === 'api')?.state).toBe('never');
    expect(runs.runs.find((r) => r.workflow === 'ci')).toEqual({
      workflow: 'ci',
      state: 'failure',
      at: '2026-10-20T18:00:00Z',
      url: 'https://github.com/o/r/actions/runs/1',
    });
  });

  it('says when GitHub limits the reads, and shows nothing it could not read', async () => {
    const limited = await readRuns(() =>
      Promise.resolve(json({}, 403, { 'x-ratelimit-remaining': '0' })),
    );
    expect(limited.limited).toBe(true);
    expect(limited.runs.every((r) => r.state === null)).toBe(true);
    const down = await readRuns(() => Promise.reject(new Error('offline')));
    expect(down.runs.every((r) => r.state === null)).toBe(true);
  });

  it('lists open issues without pull requests or links off GitHub', async () => {
    const { issues } = await readIssues(() =>
      Promise.resolve(
        json([
          { title: 'Chances went dark', html_url: 'https://github.com/o/r/issues/1' },
          { title: 'A PR', html_url: 'https://github.com/o/r/pull/2', pull_request: {} },
          { title: 'Odd', html_url: 'javascript:alert(1)' },
        ]),
      ),
    );
    expect(issues).toEqual([
      { title: 'Chances went dark', url: 'https://github.com/o/r/issues/1' },
    ]);
  });
});

describe('summarizePredictions', () => {
  it('counts districts at 50% or more and ranks the highest', () => {
    const forecast = (p: number) => ({ state: 'forecast', p_no_school: p });
    const file = {
      generated_at: '2026-10-20T12:00:00Z',
      days: ['2026-10-20', '2026-10-21'],
      districts: [
        { district: 0, days: [forecast(0.7), forecast(0.2)] },
        { district: 1, days: [forecast(0.5), forecast(0.9)] },
        { district: 2, days: [{ state: 'no_threat' }, forecast(0.6)] },
        { district: 3, days: [forecast(0.1), { state: 'no_threat' }] },
      ],
    } as unknown as PredictionsFile;
    const summary = summarizePredictions(file);
    expect(summary.today).toBe(2);
    expect(summary.tomorrow).toBe(2);
    expect(summary.top.map((r) => r.district)).toEqual([0, 1, 3]);
  });
});

describe('the days a manual status lists', () => {
  const days = (now: Date, zone: string): string[][] =>
    dayOptions(now, zone).map((option) => [...option.days]);
  /** The dates of the choice at `at` (0 today, 1 tomorrow, 2 both). */
  const choice = (now: Date, zone: string, at: number): readonly string[] =>
    dayOptions(now, zone)[at]?.days ?? [];

  it('are the school’s today and tomorrow in its own zone, across a change of clocks', () => {
    const now = new Date('2026-11-01T15:00:00Z');
    expect(days(now, 'America/New_York')).toEqual([
      ['2026-11-01'],
      ['2026-11-02'],
      ['2026-11-01', '2026-11-02'],
    ]);
    expect(dayOptions(now, 'America/Chicago').map((option) => option.choice)).toEqual([
      'today',
      'tomorrow',
      'both',
    ]);
    // Late at night in UTC it is still the evening before in Denver.
    const late = new Date('2026-01-15T03:00:00Z');
    expect(days(late, 'America/Denver')[0]).toEqual(['2026-01-14']);
    expect(days(late, 'America/New_York')[2]).toEqual(['2026-01-14', '2026-01-15']);
  });

  it('start as today, and as tomorrow once the school’s day is over', () => {
    // 14:59 and 15:00 in Kansas City (CST, UTC-6).
    expect(defaultDays(new Date('2026-12-01T20:59:00Z'), 'America/Chicago')).toBe('today');
    expect(defaultDays(new Date('2026-12-01T21:00:00Z'), 'America/Chicago')).toBe('tomorrow');
    expect(defaultDays(new Date('2026-12-02T05:59:00Z'), 'America/Chicago')).toBe('tomorrow');
    expect(defaultDays(new Date('2026-12-02T06:00:00Z'), 'America/Chicago')).toBe('today');
  });

  it('are sent as the dates the form showed, even when the school’s midnight passes first', () => {
    const zone = 'America/Chicago';
    // 11:59 PM Tuesday in Kansas City: "Tomorrow (Wed, Oct 21)" is picked.
    const picked = new Date('2026-10-21T04:59:00Z');
    const tomorrow = choice(picked, zone, 1);
    expect(tomorrow).toEqual(['2026-10-21']);
    // Saved at 12:01 AM Wednesday: still Wednesday, now the school's today, never Thursday.
    const saved = new Date('2026-10-21T05:01:00Z');
    expect(offeredDays(tomorrow, saved, zone)).toEqual(['2026-10-21']);
    expect(choice(saved, zone, 0)).toEqual(['2026-10-21']);
    // "Today (Tue)" or "Today and tomorrow (Tue and Wed)" picked before midnight are no
    // longer days the school can be set for: nothing is sent, the admin picks again.
    expect(offeredDays(choice(picked, zone, 0), saved, zone)).toBeNull();
    expect(offeredDays(choice(picked, zone, 2), saved, zone)).toBeNull();
    expect(offeredDays(null, saved, zone)).toBeNull();
    // Within the same day, every choice stands.
    for (const option of dayOptions(saved, zone)) {
      expect(offeredDays(option.days, new Date('2026-10-21T22:00:00Z'), zone)).toEqual([
        ...option.days,
      ]);
    }
  });
});

describe('the zone the admin view names a status’s days in', () => {
  const stamp = { generated_on: '2026-10-14', schools: 120, districts: 12 };
  const golden = JSON.parse(
    readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        '../../../../pipeline/tests/live/golden/borrowed_zones.json',
      ),
      'utf8',
    ),
  ) as {
    lon_e6: number[];
    lat_e6: number[];
    district: number[];
    zones: (string | null)[];
    borrowed: Record<string, string>;
  };
  /** The golden's SYNTHETIC directory, its places read as points.bin's are (microdegrees). */
  const lngLat = new Float64Array(golden.lon_e6.length * 2);
  golden.lon_e6.forEach((lon, i) => {
    lngLat[i * 2] = lon * 1e-6;
    lngLat[i * 2 + 1] = (golden.lat_e6[i] ?? 0) * 1e-6;
  });
  const directory = {
    meta: {
      generated_on: stamp.generated_on,
      count: stamp.schools,
      districts: { ids: golden.zones.map((_, i) => `99${String(i).padStart(5, '0')}`) },
    },
    count: stamp.schools,
    lngLat,
    district: Int32Array.from(golden.district),
  } as unknown as Directory;
  const predictions = {
    directory: stamp,
    districts: golden.zones.flatMap((zone, district) =>
      zone === null ? [] : [{ district, time_zone: zone }],
    ),
  } as unknown as PredictionsFile;

  it('is the overrides pass’s nearest zoned school for a school without a district', () => {
    const zones = predictionZones(directory, predictions) ?? new Map<number, string>();
    const found: Record<string, string> = {};
    golden.district.forEach((district, school) => {
      if (district >= 0 && zones.has(district)) return;
      const zone = nearestZone(directory, zones, school);
      if (zone !== null) found[String(school)] = zone;
    });
    expect(found).toEqual(golden.borrowed);
    // Across a zone line: a private school in Pacific Oregon is not in Denver's day.
    expect(new Set(Object.values(found)).size).toBe(4);
  });

  it('is the district’s, from a predictions file for this directory only', () => {
    expect(statusZone(directory, predictions, 0, 0)).toBe('America/Los_Angeles');
    expect(statusZone(directory, predictions, 10, -1)).toBe('America/New_York');
    const school = Number(Object.keys(golden.borrowed)[0]);
    expect(statusZone(directory, predictions, -1, school)).toBe(golden.borrowed[String(school)]);
    // A district the file gives no zone: none, never another district's.
    expect(statusZone(directory, predictions, 11, -1)).toBeNull();
    // No file, or a file of another directory edition (its positions are other districts).
    expect(statusZone(directory, null, 0, 0)).toBeNull();
    const other = { ...predictions, directory: { ...stamp, generated_on: '2026-09-01' } };
    expect(statusZone(directory, other as PredictionsFile, 0, 0)).toBeNull();
    expect(statusZone(null, predictions, 0, 0)).toBeNull();
    // A school the directory does not hold.
    expect(statusZone(directory, predictions, -1, -1)).toBeNull();
    expect(statusZone(directory, predictions, -1, stamp.schools)).toBeNull();
  });
});

describe('onTheMap', () => {
  const stamp = { generated_on: '2026-09-25', schools: 4, districts: 1 };
  const directory = {
    meta: { generated_on: '2026-09-25', districts: { ids: ['2900000'] } },
    count: 4,
  } as unknown as Directory;
  const SET = '2026-01-12T12:40:00Z';
  /** Schools 1 and 2 on the 12th: a 2-hour delay set by the team, a list's dismissal at 13:00. */
  function file(generatedAt = '2026-01-12T12:50:00Z', manual = [0, 1]): ClosingsFile {
    return {
      schema_version: 1,
      generated_at: generatedAt,
      directory: stamp,
      days: [
        {
          day: '2026-01-12',
          gaps: [1, 0],
          statuses: [1, 3],
          announced: [10, 10],
          reasons: [null, null],
          shifts: [120, null],
          clocks: [null, 780],
          manual,
        },
      ],
    };
  }
  const delayed = { status: 'delayed', minutes: 120, at_local_time: null, set_at: SET } as const;

  it('is true only for the exact row the team set', () => {
    expect(onTheMap(file(), directory, 1, '2026-01-12', delayed)).toBe(true);
    expect(onTheMap(file(), directory, 1, '2026-01-12', { ...delayed, minutes: 90 })).toBe(false);
    expect(onTheMap(file(), directory, 1, '2026-01-13', delayed)).toBe(false);
    expect(onTheMap(file(), directory, 0, '2026-01-12', delayed)).toBe(false);
    const closed = { ...delayed, status: 'closed', minutes: null } as const;
    expect(onTheMap(file(), directory, 1, '2026-01-12', closed)).toBe(false);
    const dismissal = {
      status: 'early_dismissal',
      minutes: null,
      at_local_time: '13:00',
      set_at: SET,
    } as const;
    expect(onTheMap(file(), directory, 2, '2026-01-12', dismissal)).toBe(true);
    // A dismissal time moved to 12:30 waits until the file says 12:30.
    expect(
      onTheMap(file(), directory, 2, '2026-01-12', { ...dismissal, at_local_time: '12:30' }),
    ).toBe(false);
    // The same status from a list is not the team's.
    expect(onTheMap(file('2026-01-12T12:50:00Z', [0]), directory, 2, '2026-01-12', dismissal)).toBe(
      false,
    );
  });

  it('is false with no file, or a file for another directory', () => {
    expect(onTheMap(null, directory, 1, '2026-01-12', delayed)).toBe(false);
    expect(onTheMap(file(), null, 1, '2026-01-12', delayed)).toBe(false);
    const other = { ...file(), directory: { ...stamp, generated_on: '2026-09-01' } };
    expect(onTheMap(other, directory, 1, '2026-01-12', delayed)).toBe(false);
  });

  it('takes an open as on the map once a file published after it holds no row that day', () => {
    const open = { status: 'open', minutes: null, at_local_time: null, set_at: SET } as const;
    expect(onTheMap(file(), directory, 3, '2026-01-12', open)).toBe(true);
    expect(onTheMap(file(), directory, 1, '2026-01-12', open)).toBe(false);
    expect(onTheMap(file('2026-01-12T12:30:00Z'), directory, 3, '2026-01-12', open)).toBe(false);
  });
});

describe('dayState', () => {
  // SYNTHETIC: district 2900000 holds schools 0-2, district 2900001 school 3, none school 4.
  const stamp = { generated_on: '2026-09-25', schools: 5, districts: 3 };
  const ids = ['290000000001', '290000000002', '290000000003', '290000100001', 'A0000001'];
  const districts = ['2900000', '2900001', '2900002'];
  const directory = {
    meta: { generated_on: stamp.generated_on, districts: { ids: districts } },
    count: stamp.schools,
    district: Int32Array.from([0, 0, 0, 1, -1]),
    schoolIndex: (id: string) => ids.indexOf(id),
    districtIndex: (id: string) => districts.indexOf(id),
  } as unknown as Directory;
  const DAY = '2026-01-12';
  /** The day's rows: each school with a status and whether the team set it. */
  function file(rows: [school: number, status: Status, manual: boolean][]): ClosingsFile {
    let last = -1;
    return {
      schema_version: 1,
      generated_at: '2026-01-12T12:50:00Z',
      directory: stamp,
      days: [
        {
          day: DAY,
          gaps: rows.map(([school]) => {
            const gap = school - last - 1;
            last = school;
            return gap;
          }),
          statuses: rows.map(([, status]) => status),
          announced: rows.map(() => 10),
          reasons: rows.map(() => null),
          shifts: [],
          clocks: [],
          manual: rows.flatMap(([, , manual], i) => (manual ? [i] : [])),
        },
      ],
    };
  }
  const base = { minutes: null, at_local_time: null, set_at: '2026-01-12T12:40:00Z' } as const;
  type Item = ListedTarget & ListedStatus;
  const district: Item = {
    ...base,
    scope: 'district',
    id: '2900000',
    status: 'closed',
    days: [DAY],
  };
  const school: Item = {
    ...base,
    scope: 'school',
    id: '290000000001',
    status: 'closed',
    days: [DAY],
  };
  const CLOSED = Status.closed;

  it('is on the map only once every school the district’s status lights shows it', () => {
    const all = file([
      [0, CLOSED, true],
      [1, CLOSED, true],
      [2, CLOSED, true],
    ]);
    expect(dayState(all, directory, district, DAY, [district])).toBe('onMap');
    expect(dayState(file([[0, CLOSED, true]]), directory, district, DAY, [district])).toBe(
      'waiting',
    );
    expect(dayState(null, directory, district, DAY, [district])).toBe('waiting');
    expect(dayState(all, null, district, DAY, [district])).toBe('waiting');
  });

  it('is not read at a school whose own status wins there', () => {
    // School 0's own Closed is on the map; the district's is not yet at schools 1 and 2.
    const first = file([[0, CLOSED, true]]);
    expect(dayState(first, directory, school, DAY, [district, school])).toBe('onMap');
    expect(dayState(first, directory, district, DAY, [district, school])).toBe('waiting');
    // School 0 has its own Open; the district's Closed is on the map at schools 1 and 2.
    const open: Item = { ...school, status: 'open' };
    const rest = file([
      [1, CLOSED, true],
      [2, CLOSED, true],
    ]);
    expect(dayState(rest, directory, district, DAY, [district, open])).toBe('onMap');
    // A school status for another day does not shadow this one.
    const later = { ...open, days: ['2026-01-13'] };
    expect(dayState(rest, directory, district, DAY, [district, later])).toBe('waiting');
  });

  it('says when each of the district’s schools has its own status that day', () => {
    const own = ids.slice(0, 3).map((id) => ({ ...school, id }));
    expect(dayState(file([]), directory, district, DAY, [district, ...own])).toBe('shadowed');
    // A district or school the directory does not hold lights nothing: never on the map.
    const gone = { ...district, id: '2900009' };
    expect(dayState(file([]), directory, gone, DAY, [gone])).toBe('waiting');
    const empty = { ...district, id: '2900002' };
    expect(dayState(file([]), directory, empty, DAY, [empty])).toBe('waiting');
    const stray = { ...school, id: '999999999999' };
    expect(dayState(file([]), directory, stray, DAY, [stray])).toBe('waiting');
  });
});
