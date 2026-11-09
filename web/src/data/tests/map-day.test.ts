/**
 * A school's map day (map-day.ts): its today until 3:30 PM on its own clock,
 * its tomorrow from then until its midnight; the turns the page relights at;
 * the zones read from a predictions file; and the days the map shows at once.
 * Every file here is made up for these tests.
 */
import { describe, expect, it } from 'vitest';

import {
  UNREAD_ZONE,
  mapDay,
  nextMapTurn,
  nextTurnOf,
  regionOf,
  shownDays,
  todayEverywhere,
  zoneOf,
  zonesFor,
  zonesOf,
} from '../map-day';
import { parsePredictions } from '../school-day';
import type { PredictionsFile } from '../../types/generated';

const at = (iso: string): Date => new Date(iso);

/**
 * Each zone, and the instants of 3:29 PM, 3:30 PM, 11:59 PM and the next midnight on its clock
 * on Monday Nov 9, 2026 (standard time everywhere that keeps one).
 */
const ZONES: readonly (readonly [string, string, string, string, string])[] = [
  [
    'America/New_York',
    '2026-11-09T20:29:00Z',
    '2026-11-09T20:30:00Z',
    '2026-11-10T04:59:00Z',
    '2026-11-10T05:00:00Z',
  ],
  [
    'America/Chicago',
    '2026-11-09T21:29:00Z',
    '2026-11-09T21:30:00Z',
    '2026-11-10T05:59:00Z',
    '2026-11-10T06:00:00Z',
  ],
  [
    'America/Denver',
    '2026-11-09T22:29:00Z',
    '2026-11-09T22:30:00Z',
    '2026-11-10T06:59:00Z',
    '2026-11-10T07:00:00Z',
  ],
  [
    'America/Phoenix',
    '2026-11-09T22:29:00Z',
    '2026-11-09T22:30:00Z',
    '2026-11-10T06:59:00Z',
    '2026-11-10T07:00:00Z',
  ],
  [
    'America/Los_Angeles',
    '2026-11-09T23:29:00Z',
    '2026-11-09T23:30:00Z',
    '2026-11-10T07:59:00Z',
    '2026-11-10T08:00:00Z',
  ],
  [
    'America/Anchorage',
    '2026-11-10T00:29:00Z',
    '2026-11-10T00:30:00Z',
    '2026-11-10T08:59:00Z',
    '2026-11-10T09:00:00Z',
  ],
  [
    'Pacific/Honolulu',
    '2026-11-10T01:29:00Z',
    '2026-11-10T01:30:00Z',
    '2026-11-10T09:59:00Z',
    '2026-11-10T10:00:00Z',
  ],
];

describe('a school’s map day', () => {
  for (const [zone, before, turn, late, midnight] of ZONES) {
    it(`is its today until 3:30 PM and its tomorrow from then, in ${zone}`, () => {
      // Monday morning there: Monday.
      expect(mapDay(at('2026-11-09T12:00:00Z'), zone)).toBe('2026-11-09');
      expect(mapDay(at(before), zone)).toBe('2026-11-09');
      expect(mapDay(at(turn), zone)).toBe('2026-11-10');
      expect(mapDay(at(late), zone)).toBe('2026-11-10');
      // After midnight that same Tuesday is its today: nothing changes at midnight.
      expect(mapDay(at(midnight), zone)).toBe('2026-11-10');
      expect(nextMapTurn(at(before), zone)?.toISOString()).toBe(new Date(turn).toISOString());
      expect(nextMapTurn(at(turn), zone)?.toISOString()).toBe(new Date(midnight).toISOString());
    });
  }

  it('keeps Arizona’s own clock, an hour behind Denver’s in summer', () => {
    // Tuesday July 14, 2026, 21:45 UTC: 3:45 PM in Denver (MDT), 2:45 PM in Phoenix (MST).
    expect(mapDay(at('2026-07-14T21:45:00Z'), 'America/Denver')).toBe('2026-07-15');
    expect(mapDay(at('2026-07-14T21:45:00Z'), 'America/Phoenix')).toBe('2026-07-14');
    expect(nextMapTurn(at('2026-07-14T21:45:00Z'), 'America/Phoenix')?.toISOString()).toBe(
      '2026-07-14T22:30:00.000Z',
    );
  });

  it('turns at 3:30 PM on the day the clocks go back (Nov 1, 2026)', () => {
    const zone = 'America/New_York';
    // 12:30 AM EDT, before the clocks go back at 2 AM: the turn is 3:30 PM EST.
    expect(nextMapTurn(at('2026-11-01T04:30:00Z'), zone)?.toISOString()).toBe(
      '2026-11-01T20:30:00.000Z',
    );
    expect(mapDay(at('2026-11-01T20:29:00Z'), zone)).toBe('2026-11-01');
    expect(mapDay(at('2026-11-01T20:30:00Z'), zone)).toBe('2026-11-02');
    // The day before, still EDT: 3:30 PM is 19:30 UTC.
    expect(mapDay(at('2026-10-31T19:29:00Z'), zone)).toBe('2026-10-31');
    expect(mapDay(at('2026-10-31T19:30:00Z'), zone)).toBe('2026-11-01');
    expect(nextMapTurn(at('2026-10-31T19:30:00Z'), zone)?.toISOString()).toBe(
      '2026-11-01T04:00:00.000Z',
    );
    // Los Angeles goes back the same night.
    expect(mapDay(at('2026-11-01T23:29:00Z'), 'America/Los_Angeles')).toBe('2026-11-01');
    expect(mapDay(at('2026-11-01T23:30:00Z'), 'America/Los_Angeles')).toBe('2026-11-02');
  });

  it('turns at 3:30 PM on the day the clocks go forward (Mar 14, 2027)', () => {
    const zone = 'America/Chicago';
    // 12:30 AM CST, before the clocks go forward at 2 AM: the turn is 3:30 PM CDT.
    expect(nextMapTurn(at('2027-03-14T06:30:00Z'), zone)?.toISOString()).toBe(
      '2027-03-14T20:30:00.000Z',
    );
    expect(mapDay(at('2027-03-14T20:29:00Z'), zone)).toBe('2027-03-14');
    expect(mapDay(at('2027-03-14T20:30:00Z'), zone)).toBe('2027-03-15');
    // Its midnight is at CDT's offset now.
    expect(nextMapTurn(at('2027-03-14T20:30:00Z'), zone)?.toISOString()).toBe(
      '2027-03-15T05:00:00.000Z',
    );
    // Arizona keeps no daylight time: 3:30 PM is 22:30 UTC either side of it.
    expect(mapDay(at('2027-03-14T22:29:00Z'), 'America/Phoenix')).toBe('2027-03-14');
    expect(mapDay(at('2027-03-14T22:30:00Z'), 'America/Phoenix')).toBe('2027-03-15');
  });

  it('keeps the day that is today everywhere for a school with no zone, and none overnight', () => {
    // 20:45 UTC: past 3:30 PM in the East, and still Monday everywhere: Monday, never a guess.
    expect(mapDay(at('2026-11-09T20:45:00Z'), null)).toBe('2026-11-09');
    expect(mapDay(at('2026-11-09T20:45:00Z'), null)).toBe(
      todayEverywhere(at('2026-11-09T20:45:00Z')),
    );
    expect(mapDay(at('2026-11-10T04:00:00Z'), null)).toBeNull();
    expect(mapDay(at('2026-11-10T07:59:00Z'), null)).toBeNull();
    expect(mapDay(at('2026-11-10T08:00:00Z'), null)).toBe('2026-11-10');
    expect(nextMapTurn(at('2026-11-09T20:45:00Z'), null)?.toISOString()).toBe(
      '2026-11-10T04:00:00.000Z',
    );
    expect(nextMapTurn(at('2026-11-10T04:00:00Z'), null)?.toISOString()).toBe(
      '2026-11-10T08:00:00.000Z',
    );
  });

  it('gives a school whose zone cannot be read the day every clock agrees on, and none between', () => {
    // 3:45 PM in New York, 12:45 PM in Los Angeles: the clocks differ.
    expect(mapDay(at('2026-11-09T20:45:00Z'), UNREAD_ZONE)).toBeNull();
    // 3:30 PM in Los Angeles: Tuesday on every clock's map day, but still Monday everywhere, the
    // day of a school with no zone: none, so neither school's light steps back once read.
    expect(mapDay(at('2026-11-09T23:30:00Z'), UNREAD_ZONE)).toBeNull();
    expect(mapDay(at('2026-11-10T03:59:00Z'), UNREAD_ZONE)).toBeNull();
    expect(mapDay(at('2026-11-10T07:59:00Z'), UNREAD_ZONE)).toBeNull();
    // Tuesday everywhere and on every clock's map day, through 3:29 PM Tuesday in New York.
    expect(mapDay(at('2026-11-10T08:00:00Z'), UNREAD_ZONE)).toBe('2026-11-10');
    expect(mapDay(at('2026-11-10T20:29:00Z'), UNREAD_ZONE)).toBe('2026-11-10');
    expect(mapDay(at('2026-11-10T20:30:00Z'), UNREAD_ZONE)).toBeNull();
    expect(nextMapTurn(at('2026-11-09T20:45:00Z'), UNREAD_ZONE)?.toISOString()).toBe(
      '2026-11-09T21:30:00.000Z',
    );
  });

  it('gives a school whose zone cannot be read only a day that is its map day with a zone or none', () => {
    // Every minute of a fall and a spring clock change day, a summer and a winter weekday: the
    // unread day, where there is one, is the day of a school with no zone and of a school on
    // every contiguous US clock alike, so it is never one the school's own rule would not show.
    const contiguous = [
      'America/New_York',
      'America/Detroit',
      'America/Chicago',
      'America/Denver',
      'America/Boise',
      'America/Phoenix',
      'America/Los_Angeles',
    ];
    let lit = 0;
    for (const start of ['2026-10-31', '2026-11-09', '2027-03-13', '2026-07-15']) {
      const from = Date.parse(`${start}T00:00:00Z`);
      for (let ms = from; ms < from + 3 * 86_400_000; ms += 60_000) {
        const now = new Date(ms);
        const day = mapDay(now, UNREAD_ZONE);
        if (day === null) continue;
        lit += 1;
        expect(mapDay(now, null)).toBe(day);
        for (const zone of contiguous) expect(mapDay(now, zone)).toBe(day);
      }
    }
    // Lit about half of each day all the same: from the West's morning to 3:30 PM in the East.
    expect(lit).toBeGreaterThan(12 * 11 * 60);
    // Some 155,000 readings of a clock: 1.5 s on a CI runner, several on a busy one.
  }, 30_000);

  it('gives no day for a clock this browser cannot read, or an instant that is not one', () => {
    expect(mapDay(at('2026-11-09T20:45:00Z'), 'Not/A_Zone')).toBeNull();
    expect(nextMapTurn(at('2026-11-09T20:45:00Z'), 'Not/A_Zone')).toBeNull();
    expect(mapDay(new Date(Number.NaN), 'America/Chicago')).toBeNull();
    expect(mapDay(new Date(Number.NaN), null)).toBeNull();
  });
});

describe('the days the map shows at once', () => {
  const zones = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Phoenix',
    'America/Los_Angeles',
  ];

  it('shows two days between 3:30 PM in the East and 3:30 PM in the West, the latest first', () => {
    // A weekday at 20:45 UTC: 3:45 PM in New York, 12:45 PM in Los Angeles.
    expect(shownDays(at('2026-11-09T20:45:00Z'), zones)).toEqual([
      { day: '2026-11-10', zones: ['America/New_York'], today: false },
      {
        day: '2026-11-09',
        zones: ['America/Chicago', 'America/Denver', 'America/Phoenix', 'America/Los_Angeles'],
        today: true,
      },
    ]);
    // 3:30 PM in the West: Tuesday everywhere, every clock's tomorrow, and so through midnight in
    // the East, where it is then today.
    expect(shownDays(at('2026-11-09T23:30:00Z'), zones)).toEqual([
      { day: '2026-11-10', zones, today: false },
    ]);
    expect(shownDays(at('2026-11-10T05:30:00Z'), zones)).toEqual([
      { day: '2026-11-10', zones, today: false },
    ]);
    // The morning: one day, today on every clock.
    expect(shownDays(at('2026-11-10T15:00:00Z'), zones)).toEqual([
      { day: '2026-11-10', zones, today: true },
    ]);
  });

  it('waits for the earliest turn of any zone shown', () => {
    expect(nextTurnOf(at('2026-11-09T20:45:00Z'), zones)?.toISOString()).toBe(
      '2026-11-09T21:30:00.000Z',
    );
    expect(nextTurnOf(at('2026-11-09T20:45:00Z'), [...zones, null])?.toISOString()).toBe(
      '2026-11-09T21:30:00.000Z',
    );
    expect(nextTurnOf(at('2026-11-09T20:45:00Z'), [])).toBeNull();
  });

  it('says where each zone keeps its clock, and other for one it does not name', () => {
    expect(zones.map(regionOf)).toEqual(['eastern', 'central', 'mountain', 'arizona', 'pacific']);
    expect(regionOf('America/Anchorage')).toBe('alaska');
    expect(regionOf('Pacific/Honolulu')).toBe('hawaii');
    expect(regionOf('Europe/Paris')).toBe('other');
    expect(regionOf(null)).toBe('other');
  });
});

describe('the zones of a predictions file', () => {
  const stamp = { generated_on: '2026-10-24', schools: 4, districts: 2 };
  const file = parsePredictions({
    schema_version: 1,
    generated_at: '2026-11-09T20:00:00Z',
    directory: stamp,
    days: ['2026-11-09', '2026-11-10'],
    districts: [
      {
        district: 0,
        time_zone: 'America/New_York',
        days: [{ state: 'no_threat' }, { state: 'no_threat' }],
      },
      {
        district: 1,
        time_zone: 'America/Los_Angeles',
        days: [{ state: 'no_threat' }, { state: 'no_threat' }],
      },
    ],
    outlooks: [{ state: 'no_threat' }],
    zones: ['America/Chicago'],
    schools: [{ school: 2, zone: 0, days: [0, 0] }],
  });
  if (file === null) throw new Error('the made-up predictions file did not parse');

  it('gives a school its district’s zone, a private school its own, and none it lacks', () => {
    const zones = zonesOf(file);
    expect(zoneOf(zones, 0, 0)).toBe('America/New_York');
    expect(zoneOf(zones, 1, 1)).toBe('America/Los_Angeles');
    expect(zoneOf(zones, 2, -1)).toBe('America/Chicago');
    expect(zoneOf(zones, 3, -1)).toBeNull();
    expect(zoneOf(zones, 3, 7)).toBeNull();
    expect(zones.names).toEqual(['America/New_York', 'America/Los_Angeles', 'America/Chicago']);
    // Read once per file.
    expect(zonesOf(file)).toBe(zones);
  });

  it('is for its own directory alone', () => {
    const zones = zonesOf(file);
    expect(zonesFor(zones, stamp)).toBe(true);
    expect(zonesFor(zones, { ...stamp, generated_on: '2026-10-14' })).toBe(false);
    expect(zonesFor(zones, { ...stamp, schools: 5 })).toBe(false);
  });

  it('reads no age off the file: a district’s clock does not go stale', () => {
    const old: PredictionsFile = { ...file, generated_at: '2026-11-01T00:00:00Z' };
    expect(zoneOf(zonesOf(old), 0, 0)).toBe('America/New_York');
  });
});
