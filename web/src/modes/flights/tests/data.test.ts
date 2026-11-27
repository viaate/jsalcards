/**
 * Reading the flights files: never a stale file shown as current, never the FAA past 30 minutes,
 * never a waiver state past 2 hours or a guess (flights spec D7, waivers spec W2, W8).
 * SYNTHETIC files.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  LIVE_FRESH_MINUTES,
  createFlightsFiles,
  faaLive,
  isStale,
  readAirports,
  readLive,
  readWaivers,
  airportWaivers,
  waiverState,
  trackRecordFits,
} from '../data';
import type { FlightsAirportLive, FlightsTrackRecord } from '../../../types/generated';
import { airportLive, liveFile } from './fixtures';

const MADE = '2026-01-05T12:00:00Z';
const MADE_MS = Date.parse(MADE);
const latest = { schema_version: 1, generated_at: MADE, slot: 'slot-0', stamp: '20260105T1200Z' };

describe('the live file', () => {
  const file = liveFile([airportLive('MCI', '2026-01-05')], MADE);

  it('is current when latest.json names it and it is fresh', () => {
    const read = readLive(latest, file);
    expect(isStale(read, MADE_MS + 10 * 60_000)).toBe(false);
    expect(read?.byCode.get('MCI')?.today).toBe('2026-01-05');
  });

  it('is old past its freshness limit', () => {
    expect(isStale(readLive(latest, file), MADE_MS + (LIVE_FRESH_MINUTES + 1) * 60_000)).toBe(true);
  });

  it('turns old with the clock after a good read, with no new read (no network)', () => {
    // Read fresh at t; asked again at t + 61 min with no read since: old, never current.
    const read = readLive(latest, file);
    expect(isStale(read, MADE_MS + 5 * 60_000)).toBe(false);
    expect(isStale(read, MADE_MS + 66 * 60_000)).toBe(true);
    if (read === null) throw new Error('no read');
    expect(faaLive(read, MADE_MS + 66 * 60_000)).toBe(false);
    expect(isStale(null, MADE_MS)).toBe(true);
  });

  it('is old when its stamp is not the one latest.json names (a cached slot)', () => {
    const older = { ...latest, stamp: '20260105T1220Z' };
    expect(isStale(readLive(older, file), MADE_MS)).toBe(true);
  });

  it('refuses a file of another version and drops an airport that does not read', () => {
    expect(readLive(latest, { ...file, schema_version: 2 })).toBeNull();
    const bad = { ...airportLive('LAX', '2026-01-05'), dep_canc: [[2000, 0, 0, 0, 0]] };
    const read = readLive(latest, { ...file, airports: [...file.airports, bad] });
    expect(read?.byCode.has('LAX')).toBe(false);
    expect(read?.byCode.has('MCI')).toBe(true);
  });

  it('shows the FAA as live only within 30 minutes of its read, on a current file', () => {
    const read = readLive(latest, file);
    if (read === null) throw new Error('no read');
    expect(faaLive(read, MADE_MS + 30 * 60_000)).toBe(true);
    expect(faaLive(read, MADE_MS + 31 * 60_000)).toBe(false);
    const unread = readLive(latest, { ...file, programs_at: null });
    if (unread === null) throw new Error('no read');
    expect(faaLive(unread, MADE_MS)).toBe(false);
  });

  it('reads latest.json and then the slot it names, afresh', async () => {
    const asked: [string, RequestInit | undefined][] = [];
    const fetcher = (url: string, init?: RequestInit): Promise<Response> => {
      asked.push([url, init]);
      const body = url.endsWith('latest.json') ? latest : url.endsWith('slot-0.json') ? file : null;
      return Promise.resolve(
        body === null ? new Response('', { status: 404 }) : Response.json(body),
      );
    };
    const files = createFlightsFiles(
      fetcher,
      'https://live.invalid/v1/',
      'https://site.invalid/flights/airports.json',
    );
    const read = await files.live();
    expect(isStale(read, MADE_MS)).toBe(false);
    expect(asked.map(([url]) => url)).toEqual([
      'https://live.invalid/v1/flights/latest.json',
      'https://live.invalid/v1/flights/live/slot-0.json',
    ]);
    expect(asked.every(([, init]) => init?.cache === 'no-cache')).toBe(true);
  });

  it('reads the site’s own airports, never the host’s', async () => {
    const shipped = {
      schema_version: 1,
      airports: [
        {
          code: 'MCI',
          name: 'K',
          city: 'Kansas City',
          state: 'MO',
          lat: 39,
          lon: -94,
          tz: 'America/Chicago',
          per_day: 1,
        },
      ],
    };
    const fetcher = (url: string): Promise<Response> =>
      Promise.resolve(
        url.startsWith('https://site.invalid/')
          ? Response.json(shipped)
          : new Response('', { status: 404 }),
      );
    const files = createFlightsFiles(
      fetcher,
      'https://live.invalid/v1/',
      'https://site.invalid/flights/airports.json',
    );
    expect((await files.airports())?.map((a) => a.code)).toEqual(['MCI']);
    expect(await files.record('MCI')).toBeNull();
  });
});

describe('the airports the site ships', () => {
  it('match the pipeline’s table, airport for airport', () => {
    const shipped = readAirports(
      JSON.parse(
        readFileSync(path.join(process.cwd(), 'public/flights/airports.json'), 'utf8'),
      ) as unknown,
    );
    const table = JSON.parse(
      readFileSync(path.join(process.cwd(), '../pipeline/data/flights/airports.json'), 'utf8'),
    ) as { code: string; lat: number; lon: number; tz: string; per_day: number }[];
    expect(shipped?.length).toBe(table.length);
    expect(shipped?.map((a) => [a.code, a.lat, a.lon, a.tz, a.perDay])).toEqual(
      table.map((a) => [a.code, a.lat, a.lon, a.tz, a.per_day]),
    );
  });
});

describe('waivers (waivers spec W2)', () => {
  const file = {
    schema_version: 1,
    generated_at: MADE,
    fresh_minutes: 120,
    airlines: [
      {
        code: 'DL',
        name: 'Delta',
        path: '/advisories',
        state: 'checked',
        read_at: MADE,
        reason: null,
      },
      {
        code: 'AA',
        name: 'American',
        path: '/alerts',
        state: 'not_checked',
        read_at: null,
        reason: 'blocked',
      },
    ],
    waivers: [
      {
        airline: 'DL',
        airports: ['MCI'],
        all_airports: false,
        travel_from: '2026-01-05',
        travel_to: '2026-01-06',
        unclear_days: [],
        on_page: true,
        active: true,
        last_seen: new Date(MADE_MS - 10 * 60_000).toISOString().slice(0, 19) + 'Z',
      },
    ],
  };
  const read = readWaivers(file);

  /** The file with DL's one waiver changed by `change`. */
  function withWaiver(change: Record<string, unknown>): ReturnType<typeof readWaivers> {
    return readWaivers({ ...file, waivers: [{ ...file.waivers[0], ...change }] });
  }

  it('says waiver only for the airline, airport and day it covers', () => {
    expect(waiverState(read, 'DL', 'Delta', 'MCI', '2026-01-05', MADE_MS).state).toBe('waiver');
    expect(waiverState(read, 'DL', 'Delta', 'MCI', '2026-01-07', MADE_MS).state).toBe('none_found');
    expect(waiverState(read, 'DL', 'Delta', 'LAX', '2026-01-05', MADE_MS).state).toBe('none_found');
  });

  it('never says none found for a page it could not read, or for an airline it does not list', () => {
    expect(waiverState(read, 'AA', 'American', 'MCI', '2026-01-05', MADE_MS).state).toBe(
      'not_checked',
    );
    expect(waiverState(read, 'WN', 'Southwest', 'MCI', '2026-01-05', MADE_MS).state).toBe(
      'not_checked',
    );
  });

  it('says unclear, never none found, where the page does not plainly say where or when', () => {
    const state = (change: Record<string, unknown>, day = '2026-01-05'): string =>
      waiverState(withWaiver(change), 'DL', 'Delta', 'MCI', day, MADE_MS).state;
    // No airports stated plainly (the waivers lane's airports: null).
    expect(state({ airports: null })).toBe('unclear');
    // A day the page's own times leave unclear.
    expect(state({ unclear_days: ['2026-01-07'] }, '2026-01-07')).toBe('unclear');
    // Travel days that could not be read.
    expect(state({ travel_from: null, travel_to: null })).toBe('unclear');
    expect(state({ travel_to: null })).toBe('unclear');
    // A waiver the airline marks as ended, or one off its page, says nothing.
    expect(state({ active: false })).toBe('none_found');
    expect(state({ on_page: false })).toBe('none_found');
    // A waiver for another airport is still none found here.
    expect(state({ airports: ['DEN'] })).toBe('none_found');
    // One last seen 2 hours ago or more: its source has not been read since.
    expect(
      state({ last_seen: new Date(MADE_MS - 121 * 60_000).toISOString().slice(0, 19) + 'Z' }),
    ).toBe('not_checked');
  });

  it('names every airline at an airport in its own state, and none only for those read', () => {
    const names: Record<string, string> = { DL: 'Delta', AA: 'American', WN: 'Southwest' };
    const lines = airportWaivers(
      read,
      ['DL', 'AA', 'WN'],
      (code) => names[code] ?? code,
      'MCI',
      '2026-01-07',
      MADE_MS,
    );
    expect(lines.found).toEqual([]);
    expect(lines.none).toEqual(['Delta']);
    expect(lines.notChecked).toEqual(['American', 'Southwest']);
    const found = airportWaivers(read, ['DL'], (code) => code, 'MCI', '2026-01-05', MADE_MS);
    expect(found.found.map((line) => line.state)).toEqual(['waiver']);
  });

  it('says not checked for everything once the file or the read is 2 hours old, or missing', () => {
    expect(
      waiverState(read, 'DL', 'Delta', 'MCI', '2026-01-05', MADE_MS + 120 * 60_000).state,
    ).toBe('not_checked');
    expect(waiverState(null, 'DL', 'Delta', 'MCI', '2026-01-05', MADE_MS).state).toBe(
      'not_checked',
    );
  });
});

describe('the track record against the live file (LR-SF2)', () => {
  const ALL: [number, number, number] = [0b11111, 0b11111, 0b11111];
  const NONE: [number, number, number] = [0, 0, 0];
  const record = (
    airports: { code: string; passed: [number, number, number, number, number] }[],
  ): FlightsTrackRecord => ({
    schema_version: 1,
    generated_at: '2026-11-22T14:11:13Z',
    test_first: '2025-10-01',
    test_last: '2026-09-30',
    usual_first: '2024-10-01',
    usual_last: '2025-09-30',
    tests: [],
    airports,
    months: [],
  });
  const ZONES = new Map([['JFK', 'America/New_York']]);
  // The run of Jan 5 00Z is the evening of Jan 4 in New York: days 0, 1, 2 (Jan 5 to 7) are
  // leads 1, 2, 3, bits 1, 2, 4.
  const RUNS = ['2026-01-05T00:00:00Z', '2026-01-05T00:00:00Z', '2026-01-05T00:00:00Z'] as const;
  // JFK's cancels and rough day the usual rate, its late chances the forecast's.
  const jfk = airportLive('JFK', '2026-01-05', {
    usual: [ALL, NONE, ALL, NONE],
    rough_usual: 0b111,
    runs: [...RUNS],
  });

  it('fits where every forecast value the live file shows passed its gate at its lead', () => {
    const live = liveFile([jfk], MADE);
    const gate = record([{ code: 'JFK', passed: [0, 7, 0, 7, 0] }]);
    expect(trackRecordFits(gate, live, ZONES)).toBe(true);
  });

  it('does not fit where the live file shows a forecast the record says passed nowhere', () => {
    // The Nov 22 record: JFK's late chance passed at no lead, while the map shows it.
    const live = liveFile([jfk], MADE);
    expect(trackRecordFits(record([{ code: 'JFK', passed: [0, 0, 0, 7, 0] }]), live, ZONES)).toBe(
      false,
    );
    expect(trackRecordFits(record([]), live, ZONES)).toBe(false);
  });

  it('does not fit where the record passed a target only at a later lead than a day shown', () => {
    // Leads 2 and 3 passed (bits 2, 4), lead 1 not: tomorrow's forecast late chance at day 0 is
    // not covered, so the lead 1 count would contradict the map.
    const live = liveFile([jfk], MADE);
    expect(trackRecordFits(record([{ code: 'JFK', passed: [0, 6, 0, 7, 0] }]), live, ZONES)).toBe(
      false,
    );
    // Only day 0 shows a forecast: lead 1 alone is enough.
    const first = airportLive('JFK', '2026-01-05', {
      usual: [ALL, [0, 0b11111, 0b11111], ALL, [0, 0b11111, 0b11111]],
      rough_usual: 0b111,
      runs: [...RUNS],
    });
    const one = record([{ code: 'JFK', passed: [0, 1, 0, 1, 0] }]);
    expect(trackRecordFits(one, liveFile([first], MADE), ZONES)).toBe(true);
    // An older run moves each day one lead out: day 0 is lead 2 then.
    const older: FlightsAirportLive = { ...first, runs: ['2026-01-04T00:00:00Z', null, null] };
    expect(trackRecordFits(one, liveFile([older], MADE), ZONES)).toBe(false);
    expect(
      trackRecordFits(
        record([{ code: 'JFK', passed: [0, 2, 0, 2, 0] }]),
        liveFile([older], MADE),
        ZONES,
      ),
    ).toBe(true);
  });

  it('asks for every lead where the run or the zone cannot place a day', () => {
    const live = liveFile([{ ...jfk, runs: [null, null, null] }], MADE);
    expect(trackRecordFits(record([{ code: 'JFK', passed: [0, 3, 0, 3, 0] }]), live, ZONES)).toBe(
      false,
    );
    expect(trackRecordFits(record([{ code: 'JFK', passed: [0, 7, 0, 7, 0] }]), live, ZONES)).toBe(
      true,
    );
    const placed = liveFile([jfk], MADE);
    const gate = record([{ code: 'JFK', passed: [0, 1, 0, 7, 0] }]);
    expect(trackRecordFits(gate, placed, new Map())).toBe(false);
  });

  it('reads the rough day by its own bits and leads, and a value missing as no forecast', () => {
    const rough = airportLive('JFK', '2026-01-05', {
      usual: [ALL, ALL, ALL, ALL],
      runs: [...RUNS],
    });
    const gate = record([{ code: 'JFK', passed: [0, 0, 0, 0, 0] }]);
    expect(trackRecordFits(gate, liveFile([rough], MADE), ZONES)).toBe(false);
    expect(
      trackRecordFits(
        record([{ code: 'JFK', passed: [0, 0, 0, 0, 3] }]),
        liveFile([rough], MADE),
        ZONES,
      ),
    ).toBe(false);
    expect(
      trackRecordFits(
        record([{ code: 'JFK', passed: [0, 0, 0, 0, 7] }]),
        liveFile([rough], MADE),
        ZONES,
      ),
    ).toBe(true);
    const none = airportLive('JFK', '2026-01-05', {
      usual: [ALL, ALL, ALL, ALL],
      rough: [null, null, null],
    });
    expect(trackRecordFits(gate, liveFile([none], MADE), ZONES)).toBe(true);
  });
});
