/** Best time to fly and a flight's legs, at set clocks (SYNTHETIC files). */
import { describe, expect, it } from 'vitest';

import {
  BLOCK_KEYS,
  dayName,
  dayWords,
  safestChance,
  sameChance,
  faaWait,
  usualDaysFact,
} from '../../../copy-flights';
import type {
  FlightsAirportLive,
  FlightsProgramNow,
  FlightsUsualFlight,
} from '../../../types/generated';
import { bestTime, faaHolds, flightLegs, holdsOn, routeGrid, rowForDay } from '../schedule';
import { levelOf, wholePercent } from '../chance';
import { FlightsProgram } from '../../../types/generated';
import { readLive } from '../data';
import { airportLive, liveFile } from './fixtures';

const MCI = 'America/Chicago';
const LAX = 'America/Los_Angeles';
const ALL_DAYS = 0b1111111;

function usual(
  number: number,
  leaves: number,
  lands: number,
  weekdays = ALL_DAYS,
  to = 'LAX',
): FlightsUsualFlight {
  return {
    carrier: 'WN',
    number,
    to_airport: to,
    leaves,
    lands,
    weekdays,
    days: 20,
    cancelled: 0,
    late: 0,
  };
}

const FLIGHTS = [usual(1, 446, 560), usual(2, 600, 720), usual(3, 800, 900), usual(4, 1100, 1200)];
const ALL_USUAL: [number, number, number] = [0b11111, 0b11111, 0b11111];

/** Jan 5, 2026, 8:00 am CST: the early block runs to 9, and the 7:26 flight has left. */
const EIGHT_AM = Date.parse('2026-01-05T14:00:00Z');

describe('Best time to fly', () => {
  it('leaves out flights that have left and blocks that have ended', () => {
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [0, 10, 20, 30, 40],
        [50, 50, 50, 50, 50],
        [50, 50, 50, 50, 50],
      ],
    });
    const to = airportLive('LAX', '2026-01-05', {
      arr_canc: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const grid = routeGrid(
      FLIGHTS,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      EIGHT_AM,
    );
    // The early block still runs, but its one flight (7:26) has left: over, never ranked.
    expect(grid[0]?.cells[0]?.state).toBe('over');
    expect(grid[0]?.cells[0]?.flights).toEqual([]);
    expect(grid[0]?.cells[1]?.state).toBe('value');
    const best = bestTime(grid);
    expect(best.kind).toBe('safest');
    if (best.kind !== 'safest') return;
    expect(best.pick).toEqual({ index: 0, date: '2026-01-05', block: 1 });
    expect(best.best.chance.cancel).toBe(10);
    expect(
      safestChance(
        { day: best.pick.date, block: BLOCK_KEYS[best.pick.block] ?? 'early' },
        '2026-01-05',
      ),
    ).toBe('Chance of a cancel today, 9 am to noon. It is the safest time to fly.');
    // At 5 pm the day's blocks before evening are over.
    const late = routeGrid(
      FLIGHTS,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T23:00:00Z'),
    );
    expect(late[0]?.cells.slice(0, 3).map((cell) => cell.state)).toEqual(['over', 'over', 'over']);
  });

  it('ranks by the level rule: a high late chance loses to a low one at the same cancel', () => {
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [10, 10, 10, 10, 10],
        [10, 10, 10, 10, 10],
        [10, 10, 10, 10, 10],
      ],
      dep_late: [
        [300, 300, 60, 300, 300],
        [300, 300, 300, 300, 300],
        [300, 300, 300, 300, 300],
      ],
    });
    const to = airportLive('LAX', '2026-01-05', {
      arr_canc: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
      arr_late: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const grid = routeGrid(
      FLIGHTS,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T10:00:00Z'),
    );
    const best = bestTime(grid);
    expect(best.kind === 'safest' && BLOCK_KEYS[best.pick.block]).toBe('afternoon');
    // Every other cell shows the same 1%: nothing lower is passed over.
    expect(best.kind === 'safest' && best.passed).toBeNull();
  });

  it('names a lower cancel chance passed over for its late chance (TRAV-R11-S1)', () => {
    // Today's evening shows 3% with a 26% late chance (Some risk); tomorrow shows 4% and none.
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [40, 40, 40, 30, 40],
        [40, 40, 40, 40, 40],
        [40, 40, 40, 40, 40],
      ],
      dep_late: [
        [0, 0, 0, 260, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const to = airportLive('LAX', '2026-01-05', {
      arr_canc: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
      arr_late: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const grid = routeGrid(
      FLIGHTS,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T10:00:00Z'),
    );
    const best = bestTime(grid);
    expect(best.kind).toBe('safest');
    if (best.kind !== 'safest') return;
    expect(best.best.chance.cancel).toBe(40);
    expect(best.passed).toMatchObject({ index: 0, block: 3 });
    expect(best.passed?.best.chance).toMatchObject({ cancel: 30, late: 260 });
  });

  it('names no safest time when the lowest ties or is the usual rate', () => {
    const flat = airportLive('MCI', '2026-01-05');
    const to = airportLive('LAX', '2026-01-05', {
      arr_canc: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
      arr_late: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const tie = routeGrid(
      [usual(2, 600, 720), usual(5, 610, 730, 0b0000010)],
      {
        entry: airportLive('MCI', '2026-01-05', {
          dep_canc: [
            [10, 10, 10, 10, 10],
            [10, 10, 10, 10, 10],
            [10, 10, 10, 10, 10],
          ],
          dep_late: [
            [40, 40, 40, 40, 40],
            [40, 40, 40, 40, 40],
            [40, 40, 40, 40, 40],
          ],
        }),
        zone: MCI,
      },
      { entry: to, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T10:00:00Z'),
    );
    const said = bestTime(tie);
    expect(said.kind).toBe('tie');
    // The line says the number every time shows (LR-F14.2).
    if (said.kind === 'tie') expect(sameChance(said.best.chance.cancel ?? 0)).toContain(': 1%.');
    const usualFrom = airportLive('MCI', '2026-01-05', {
      usual: [ALL_USUAL, ALL_USUAL, ALL_USUAL, ALL_USUAL],
    });
    const allUsual = routeGrid(
      FLIGHTS,
      { entry: usualFrom, zone: MCI },
      { entry: flat, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T10:00:00Z'),
    );
    const whole = bestTime(allUsual);
    expect(whole.kind).toBe('usual');
    // Only MCI's values are usual, LAX's the forecast's: never said as only the usual rate. The
    // cancel number is MCI's usual rate and LAX's forecast: usual in part.
    if (whole.kind === 'usual') expect(whole.cancelShare).toBe('part');
    const usualTo = airportLive('LAX', '2026-01-05', {
      usual: [ALL_USUAL, ALL_USUAL, ALL_USUAL, ALL_USUAL],
    });
    const both = bestTime(
      routeGrid(
        FLIGHTS,
        { entry: usualFrom, zone: MCI },
        { entry: usualTo, zone: LAX },
        '2026-01-05',
        Date.parse('2026-01-05T10:00:00Z'),
      ),
    );
    expect(both).toEqual({ kind: 'usual', cancelShare: 'all', lateShare: 'all' });
  });

  const ZERO = airportLive('LAX', '2026-01-05', {
    arr_canc: [
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
    arr_late: [
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
  });
  const DAY = [usual(2, 600, 720), usual(3, 800, 900), usual(4, 1100, 1200)];

  type Rows = FlightsAirportLive['dep_canc'];
  /** Every forecast cell's shown numbers: its whole cancel and late percent. */
  const shownNumbers = (grid: ReturnType<typeof routeGrid>): Set<string> =>
    new Set(
      grid.flatMap((row) =>
        row.cells.flatMap((cell) =>
          cell.best === null || cell.best.chance.usual
            ? []
            : [
                `${String(Math.round((cell.best.chance.cancel ?? 0) / 10))}/${String(Math.round((cell.best.chance.late ?? 0) / 10))}`,
              ],
        ),
      ),
    );

  const gridOf = (canc: Rows, late?: Rows): ReturnType<typeof routeGrid> =>
    routeGrid(
      DAY,
      {
        entry: airportLive('MCI', '2026-01-05', {
          dep_canc: canc,
          dep_late: late ?? [
            [0, 60, 60, 60, 0],
            [0, 60, 60, 60, 0],
            [0, 60, 60, 60, 0],
          ],
        }),
        zone: MCI,
      },
      { entry: ZERO, zone: LAX },
      '2026-01-05',
      EIGHT_AM,
    );

  it('names the earliest of the lowest cells, never a tie of every time', () => {
    // The critic's grid: today 36% and 29%, tomorrow 61%, 38% and 16%, Wednesday 5%, 4%, 4%.
    const grid = gridOf([
      [0, 360, 290, 290, 0],
      [0, 610, 380, 160, 0],
      [0, 50, 40, 40, 0],
    ]);
    const best = bestTime(grid);
    expect(best.kind).toBe('safest');
    if (best.kind !== 'safest') return;
    expect([best.pick.index, BLOCK_KEYS[best.pick.block]]).toEqual([2, 'afternoon']);
    expect(
      safestChance(
        { day: best.pick.date, block: BLOCK_KEYS[best.pick.block] ?? 'early' },
        '2026-01-05',
      ),
    ).toBe('Chance of a cancel Wednesday, noon to 5 pm. It is the safest time to fly.');
  });

  it('names the lowest cell even one point under the next: 2% next to 3% (LR-F14.2)', () => {
    const best = bestTime(
      gridOf([
        [0, 30, 30, 30, 0],
        [0, 30, 20, 30, 0],
        [0, 30, 30, 20, 0],
      ]),
    );
    expect(best.kind).toBe('safest');
    if (best.kind !== 'safest') return;
    // The earliest 2%: tomorrow afternoon.
    expect([best.pick.index, BLOCK_KEYS[best.pick.block]]).toEqual([1, 'afternoon']);
    expect(best.best.chance.cancel).toBe(20);
    // The critic's near-tie (5%, 4%, 4%, 5%, 4%): the earliest 4%.
    const near = bestTime(
      gridOf([
        [0, 50, 50, 50, 0],
        [0, 40, 40, 50, 0],
        [0, 40, 50, 50, 0],
      ]),
    );
    expect(near.kind === 'safest' && [near.pick.index, BLOCK_KEYS[near.pick.block]]).toEqual([
      1,
      'morning',
    ]);
  });

  it('says every time is the same only when every cell shows the same numbers', () => {
    const flat = gridOf([
      [0, 40, 40, 40, 0],
      [0, 40, 40, 40, 0],
      [0, 40, 40, 40, 0],
    ]);
    const best = bestTime(flat);
    expect(best.kind).toBe('tie');
    expect(shownNumbers(flat).size).toBe(1);
    if (best.kind === 'tie')
      expect(sameChance(best.best.chance.cancel ?? 0)).toBe(
        'Every time shows the same chance: 4%.',
      );
    // The same cancel chance but one late chance a point higher: the numbers differ, so no tie.
    const late = bestTime(
      gridOf(
        [
          [0, 40, 40, 40, 0],
          [0, 40, 40, 40, 0],
          [0, 40, 40, 40, 0],
        ],
        [
          [0, 70, 60, 60, 0],
          [0, 60, 60, 60, 0],
          [0, 60, 60, 60, 0],
        ],
      ),
    );
    expect(late.kind === 'safest' && [late.pick.index, BLOCK_KEYS[late.pick.block]]).toEqual([
      0,
      'afternoon',
    ]);
  });

  it('never says the same while two cells show different numbers', () => {
    // Every grid of 1% to 3% cells by a fixed walk: a tie only when every shown cell is one number.
    let seed = 7;
    const next = (): number => {
      seed = (seed * 48271) % 2147483647;
      return seed;
    };
    for (let i = 0; i < 200; i += 1) {
      const cell = (): number => 10 * (1 + (next() % 3));
      const row = (): Rows[0] => [0, cell(), cell(), cell(), 0];
      const canc: Rows = [row(), row(), row()];
      const grid = gridOf(canc);
      const best = bestTime(grid);
      expect(best.kind === 'tie').toBe(shownNumbers(grid).size === 1);
      if (best.kind === 'safest') {
        const lowest = Math.min(
          ...grid.flatMap((r) =>
            r.cells.flatMap((c) => (c.best === null ? [] : [c.best.chance.cancel ?? 0])),
          ),
        );
        expect(best.best.chance.cancel).toBe(lowest);
      }
    }
  });

  it('ranks forecast cells among themselves and names the days with only the usual rate', () => {
    // Forecast risk on today and tomorrow; Wednesday only the usual rate, 2%.
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [0, 360, 360, 360, 0],
        [0, 510, 510, 510, 0],
        [0, 20, 20, 20, 0],
      ],
      usual: [
        [0, 0, 0b11111],
        [0, 0, 0b11111],
        [0, 0, 0],
        [0, 0, 0],
      ],
    });
    const grid = routeGrid(
      DAY,
      { entry: from, zone: MCI },
      { entry: ZERO, zone: LAX },
      '2026-01-05',
      EIGHT_AM,
    );
    const best = bestTime(grid);
    expect(best.kind).toBe('safest');
    if (best.kind !== 'safest') return;
    // The lowest forecast cells are today's; Wednesday's usual 2% is never ranked above them.
    expect(best.pick.index).toBe(0);
    expect(best.best.chance.usual).toBe(false);
    expect(best.usualDays).toEqual(['2026-01-07']);
    // Wednesday's cells are the usual rate at MCI only, LAX's the forecast's: usual in part.
    expect(usualDaysFact(best.usualDays, '2026-01-05')).toEqual({
      label: 'Wednesday',
      value: 'Usual rate in them, not ranked',
    });
  });

  it('puts a flight that leaves after midnight in the night before it, on its own weekday', () => {
    const from = airportLive('MCI', '2026-01-05');
    // 12:30 am, Tuesdays only: Jan 6, 2026 is a Tuesday, so it is in Monday's night.
    const redEye = usual(9, 30, 200, 0b0000010);
    const grid = routeGrid(
      [redEye],
      { entry: from, zone: MCI },
      { entry: ZERO, zone: LAX },
      '2026-01-05',
      EIGHT_AM,
    );
    expect(grid[0]?.cells[4]?.state).toBe('value');
    expect(grid[0]?.cells[4]?.flights[0]?.day).toBe('2026-01-06');
    // Not in Tuesday's night: that one leaves on Wednesday, which it does not fly.
    expect(grid[1]?.cells[4]?.state).toBe('none');
    expect(grid[0]?.cells[0]?.state).toBe('none');
  });

  it('tells a block with no forecast from one with no usual flights', () => {
    const from = airportLive('MCI', '2026-01-05');
    // LAX's file holds Jan 4 to 6 (its night before): a flight landing on Jan 7 has no value.
    const to = airportLive('LAX', '2026-01-04');
    const grid = routeGrid(
      [usual(2, 600, 720)],
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      Date.parse('2026-01-05T10:00:00Z'),
    );
    expect(grid[2]?.cells[1]?.state).toBe('noForecast');
    expect(grid[2]?.cells[3]?.state).toBe('none');
  });
});

describe('Best time to fly under a live FAA hold (LR-F14.3)', () => {
  const made = '2026-01-05T13:55:00Z';
  const latest = { schema_version: 1, generated_at: made, slot: 'slot-0', stamp: '20260105T1355Z' };
  const STOP: FlightsProgramNow = { program: 0, why: 1, minutes: null, until: null };
  /** Today 2%, tomorrow 51%, Wednesday 51%: the critic's grid, with a stop at MCI. */
  const ROWS: FlightsAirportLive['dep_canc'] = [
    [0, 20, 20, 20, 0],
    [0, 510, 510, 510, 0],
    [0, 510, 510, 510, 0],
  ];
  const FLAT_LATE: FlightsAirportLive['dep_late'] = [
    [60, 60, 60, 60, 60],
    [60, 60, 60, 60, 60],
    [60, 60, 60, 60, 60],
  ];
  const DAY = [usual(2, 600, 720), usual(3, 800, 900), usual(4, 1100, 1200)];
  const ZERO = airportLive('LAX', '2026-01-05', {
    arr_canc: [
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
    arr_late: [
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
  });

  function said(
    programs: readonly FlightsProgramNow[],
    now: number,
    rows = ROWS,
    toPrograms: readonly FlightsProgramNow[] = [],
  ): ReturnType<typeof bestTime> {
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: rows,
      dep_late: FLAT_LATE,
      programs: [...programs],
    });
    const to = { ...ZERO, programs: [...toPrograms] };
    const read = readLive(latest, liveFile([from, to], made, latest.stamp));
    if (read === null) throw new Error('no read');
    const grid = routeGrid(
      DAY,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      now,
    );
    const holds = faaHolds(
      read,
      [
        { code: 'MCI', entry: from },
        { code: 'LAX', entry: to },
      ],
      MCI,
      now,
    );
    return bestTime(grid, { holds, zone: MCI });
  }

  it('names tomorrow when a stop with no end covers today, even at a higher chance', () => {
    const best = said([STOP], EIGHT_AM);
    // Every time left unheld shows 5%: the same, said without the held ones (LR-F15.1).
    expect(best.kind).toBe('tie');
    if (best.kind !== 'tie') return;
    expect(best.pick.index).toBe(1);
    expect(best.best.chance.cancel).toBe(510);
    expect(best.held).toBe(true);
    // Why today is not named (LR-F15.3a): the stop covers every time left today.
    expect(best.todayHeld).toMatchObject({ holds: [{ code: 'MCI', program: 0 }], all: true });
    const stepped = said([STOP], EIGHT_AM, [
      [0, 20, 20, 20, 0],
      [0, 510, 400, 510, 0],
      [0, 510, 510, 510, 0],
    ]);
    expect(stepped).toMatchObject({ kind: 'safest', pick: { index: 1, block: 2 }, held: true });
  });

  it('says no held line when the pick is today, and part of today when the hold ends in it', () => {
    // A stop to 10:30 am holds the morning only; tomorrow's 1% is the lowest.
    const rows: FlightsAirportLive['dep_canc'] = [
      [0, 20, 30, 30, 0],
      [0, 10, 20, 20, 0],
      [0, 20, 20, 20, 0],
    ];
    const part = said([{ ...STOP, until: '2026-01-05T16:30:00Z' }], EIGHT_AM, rows);
    expect(part).toMatchObject({ kind: 'safest', pick: { index: 1, block: 1 } });
    expect(part.kind === 'safest' && part.todayHeld).toMatchObject({ all: false });
    // No hold: no held line.
    const none = said([], EIGHT_AM, rows);
    expect(none.kind === 'safest' && none.todayHeld).toBeNull();
    // The pick today, after the hold: no held line either.
    const today = said([{ ...STOP, until: '2026-01-05T16:30:00Z' }], EIGHT_AM, [
      [0, 20, 10, 30, 0],
      [0, 20, 20, 20, 0],
      [0, 20, 20, 20, 0],
    ]);
    expect(today).toMatchObject({ kind: 'safest', pick: { index: 0, block: 2 }, todayHeld: null });
  });

  it('names a time after a stop set to end, never one it covers', () => {
    // A stop to 10:30 am: the morning block starts before it ends; the afternoon is clear.
    const best = said([{ ...STOP, until: '2026-01-05T16:30:00Z' }], EIGHT_AM);
    expect(best.kind === 'safest' && [best.pick.index, BLOCK_KEYS[best.pick.block]]).toEqual([
      0,
      'afternoon',
    ]);
  });

  it('holds for a ground delay or a closed airport at either end, but not a late departure', () => {
    const delay = { ...STOP, program: 1 as const, minutes: 90 };
    expect(said([], EIGHT_AM, ROWS, [delay])).toMatchObject({ pick: { index: 1 } });
    expect(said([{ ...STOP, program: 4 }], EIGHT_AM)).toMatchObject({ pick: { index: 1 } });
    expect(said([{ ...STOP, program: 2, minutes: 45 }], EIGHT_AM)).toMatchObject({
      kind: 'safest',
      pick: { index: 0, block: 1 },
    });
  });

  it('points to the FAA when the hold covers every time with a forecast', () => {
    const best = said([{ ...STOP, until: '2026-01-09T00:00:00Z' }], EIGHT_AM);
    expect(best).toEqual({
      kind: 'faa',
      holds: [{ code: 'MCI', program: 0, ends: Date.parse('2026-01-09T00:00:00Z'), ended: false }],
    });
    if (best.kind === 'faa')
      expect(faaWait(best.holds.map((hold) => ({ ...hold, endedAt: null })))).toBe(
        'The FAA has a ground stop at MCI now. Check back when it ends.',
      );
    // A stop at the far end alone still holds the flights there.
    expect(said([], EIGHT_AM, ROWS, [{ ...STOP, until: '2026-01-09T00:00:00Z' }])).toMatchObject({
      kind: 'faa',
      holds: [{ code: 'LAX' }],
    });
  });

  it('names every hold behind the FAA answer, at both ends and two at one (TRAV-R13-S3)', () => {
    const until = '2026-01-09T00:00:00Z';
    const best = said(
      [
        { ...STOP, until },
        { program: 1, why: 1, minutes: 60, until },
      ],
      EIGHT_AM,
      ROWS,
      [{ program: 1, why: 1, minutes: 45, until }],
    );
    expect(best.kind).toBe('faa');
    if (best.kind !== 'faa') return;
    expect(best.holds.map((hold) => [hold.code, hold.program])).toEqual([
      ['MCI', 0],
      ['MCI', 1],
      ['LAX', 1],
    ]);
    expect(faaWait(best.holds.map((hold) => ({ ...hold, endedAt: null })))).toBe(
      'FAA holds cover every time now. Check back when they end.',
    );
  });

  it('never holds a time from an FAA read past its 30 minutes, or one after a stop’s end', () => {
    // 40 minutes after the read: the live file is still fresh, its FAA part is not.
    const old = said([STOP], Date.parse(made) + 40 * 60_000);
    expect(old).toMatchObject({ kind: 'safest', pick: { index: 0 } });
    const ended = said([{ ...STOP, until: '2026-01-05T13:59:00Z' }], EIGHT_AM);
    expect(ended).toMatchObject({ kind: 'safest', pick: { index: 0, block: 1 } });
  });

  it('never calls a flat grid a tie while a hold covers part of it', () => {
    const flat: FlightsAirportLive['dep_canc'] = [
      [0, 20, 20, 20, 0],
      [0, 20, 20, 20, 0],
      [0, 20, 20, 20, 0],
    ];
    expect(said([], EIGHT_AM, flat)).toMatchObject({ kind: 'tie', held: false });
    // The times left unheld all show 2%: the same, said as leaving the held times out.
    const tie = said([STOP], EIGHT_AM, flat);
    expect(tie).toMatchObject({ kind: 'tie', held: true, pick: { index: 1, block: 1 } });
    // The stop behind it is in force: the line leaves out times with an FAA hold.
    expect(tie.kind === 'tie' && tie.heldBy.map((hold) => hold.ended)).toEqual([false]);
  });

  it('keeps holding the times a stop past its stated end covered, while the read is live (TRAV-R10-B3)', () => {
    // MCI's stop was set to end at 9:10 am; the read is 20 minutes old and it is 9:15 am now.
    const read = Date.parse('2026-01-05T15:15:00Z');
    const stop = { ...STOP, until: '2026-01-05T15:10:00Z' };
    const rows: FlightsAirportLive['dep_canc'] = [
      [0, 10, 30, 30, 0],
      [0, 20, 20, 20, 0],
      [0, 20, 20, 20, 0],
    ];
    const lateRead = { ...latest, generated_at: '2026-01-05T14:55:00Z' };
    const from = airportLive('MCI', '2026-01-05', {
      dep_canc: rows,
      dep_late: FLAT_LATE,
      programs: [stop],
    });
    const live = readLive(lateRead, liveFile([from, ZERO], '2026-01-05T14:55:00Z', latest.stamp));
    if (live === null) throw new Error('no read');
    const holds = faaHolds(live, [{ code: 'MCI', entry: from }], MCI, read);
    expect(holds).toEqual([{ code: 'MCI', program: 0, ends: Date.parse(stop.until), ended: true }]);
    const grid = routeGrid(
      DAY,
      { entry: from, zone: MCI },
      { entry: ZERO, zone: LAX },
      '2026-01-05',
      read,
    );
    // The morning, which began inside the stop, is never named; the afternoon after it may be.
    const best = bestTime(grid, { holds, zone: MCI });
    expect(best).toMatchObject({ kind: 'safest', pick: { index: 1, block: 1 } });
    // The hold behind today's line and the held times is the one past its end (TRAV-R11-B1).
    expect(best.kind === 'safest' && best.todayHeld?.holds.map((hold) => hold.ended)).toEqual([
      true,
    ]);
    expect(best.kind === 'safest' && best.heldBy.map((hold) => hold.ended)).toEqual([true]);
    // Every time it covered held: the FAA line says it was set to end, never that it is in place.
    expect(faaWait([{ program: 0, code: 'MCI', endedAt: '9:10 am' }])).not.toMatch(/\bnow\b/);
  });
});

describe('Best time to fly from the shown numbers only (LR-F15.1)', () => {
  /** Jan 5, 2026, 4 am CST: before the first block of the day, so every cell is left. */
  const BEFORE_DAWN = Date.parse('2026-01-05T10:00:00Z');
  /** A grid of three days of one flight per block, from cancel and late rows (per mille). */
  function shown(
    cancel: FlightsAirportLive['dep_canc'],
    late: FlightsAirportLive['dep_late'],
  ): { grid: ReturnType<typeof routeGrid>; best: ReturnType<typeof bestTime> } {
    const flights = [
      usual(1, 330, 450),
      usual(2, 600, 720),
      usual(3, 800, 900),
      usual(4, 1100, 1200),
      usual(5, 1300, 1400),
    ];
    const from = airportLive('MCI', '2026-01-05', { dep_canc: cancel, dep_late: late });
    const to = airportLive('LAX', '2026-01-05', {
      arr_canc: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
      arr_late: [
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
      ],
    });
    const grid = routeGrid(
      flights,
      { entry: from, zone: MCI },
      { entry: to, zone: LAX },
      '2026-01-05',
      BEFORE_DAWN,
    );
    return { grid, best: bestTime(grid) };
  }
  const row = (a: number, b: number): [number, number, number, number, number] => [a, a, a, a, b];
  const FLAT: FlightsAirportLive['dep_late'] = [row(0, 0), row(0, 0), row(0, 0)];

  it('ranks by the level, then the cancel, then the late chance shown, at every line (LR-F16.1)', () => {
    // Today's evening (block 3) against tomorrow's early time (block 0); every other time 9%
    // cancel and 0% late (Some risk), so the two compared are the only Low risk candidates.
    const nine = (): [number, number, number, number, number] => [90, 90, 90, 90, 90];
    function two(
      today: readonly [number, number],
      tomorrow: readonly [number, number],
    ): ReturnType<typeof bestTime> {
      const [c0, c1, c2] = [nine(), nine(), nine()];
      const [l0, l1, l2] = [row(0, 0), row(0, 0), row(0, 0)];
      c0[3] = today[0];
      l0[3] = today[1];
      c1[0] = tomorrow[0];
      l1[0] = tomorrow[1];
      const cancel = [c0, c1, c2];
      const late = [l0, l1, l2];
      return shown(
        cancel as unknown as FlightsAirportLive['dep_canc'],
        late as unknown as FlightsAirportLive['dep_late'],
      ).best;
    }
    // The critic's grid: 4% with 24% late (Low risk) is named over 3% with 25% late (Some risk),
    // and the line under it says why with both times' numbers.
    const near = two([40, 240], [30, 250]);
    expect(near).toMatchObject({ kind: 'safest', pick: { index: 0, block: 3 } });
    expect(near.kind === 'safest' && near.passed).toMatchObject({ index: 1, block: 0 });
    // One per mille under each line rounds to the shown number below it: the same rank.
    expect(two([40, 244], [30, 245]).kind === 'safest' && two([40, 244], [30, 245])).toMatchObject({
      pick: { index: 0, block: 3 },
    });
    expect(two([40, 245], [30, 244])).toMatchObject({ pick: { index: 1, block: 0 }, passed: null });
    // With the late chance on the same side of its line, the lower cancel chance wins.
    expect(two([40, 240], [30, 240])).toMatchObject({ pick: { index: 1, block: 0 }, passed: null });
    // Both Some risk from the late chance: the lower cancel chance wins at the same level.
    expect(two([30, 250], [40, 260])).toMatchObject({ pick: { index: 0, block: 3 }, passed: null });
    // The cancel lines: 4% (Low) over 5% (Some), 14% (Some) over 15% (High), either way round.
    expect(two([40, 0], [50, 0])).toMatchObject({ pick: { index: 0, block: 3 }, passed: null });
    expect(two([50, 0], [40, 0])).toMatchObject({ pick: { index: 1, block: 0 }, passed: null });
    expect(two([44, 0], [45, 0])).toMatchObject({ pick: { index: 0, block: 3 } });
    expect(two([45, 0], [44, 0])).toMatchObject({ pick: { index: 1, block: 0 } });
    // At the same level, the late chance breaks a tie in the cancel chance.
    expect(two([30, 100], [30, 90])).toMatchObject({ pick: { index: 1, block: 0 }, passed: null });
    expect(two([30, 90], [30, 100])).toMatchObject({ pick: { index: 0, block: 3 }, passed: null });
    // Equal shown numbers: the earliest, as a tie only when every open time shows them.
    expect(two([30, 90], [30, 90])).toMatchObject({ kind: 'safest', pick: { index: 0, block: 3 } });
  });

  it('picks the least (level, cancel, late, time) and says a passed lower cancel exactly (LR-F16.3)', () => {
    let seed = 11;
    const next = (): number => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const near = [0, 4, 5, 6, 20, 30, 40, 44, 45, 46, 49, 50, 51, 144, 145, 146, 151, 300];
    const nearLate = [0, 60, 100, 240, 244, 245, 246, 249, 250, 251, 400];
    const choose = (list: readonly number[]): number => list[Math.floor(next() * list.length)] ?? 0;
    const rand = (list: readonly number[]): FlightsAirportLive['dep_canc'] =>
      [0, 1, 2].map(() =>
        [0, 1, 2, 3, 4].map(() => choose(list)),
      ) as unknown as FlightsAirportLive['dep_canc'];
    const RANKS = { low: 0, delay: 1, cancel: 2 } as const;
    for (let trial = 0; trial < 400; trial += 1) {
      const { grid } = shown(rand(near), rand(nearLate));
      // A hold on some trials, set to end at a random time of the three days (SYNTHETIC).
      const ends = BEFORE_DAWN + Math.floor(next() * 3 * 24) * 3_600_000;
      const holds =
        next() < 0.4
          ? [{ code: 'MCI', program: FlightsProgram.ground_stop, ends, ended: next() < 0.5 }]
          : [];
      const best = bestTime(grid, { holds, zone: MCI });
      const cells = grid.flatMap((d) =>
        d.cells.flatMap((c, block) =>
          c.best === null ? [] : [{ index: d.index, date: d.date, block, best: c.best }],
        ),
      );
      const open = cells.filter((c) => holdsOn(c.date, c.block, { holds, zone: MCI }).length === 0);
      const key = (c: (typeof cells)[number]): number[] => {
        const cancel = c.best.chance.cancel ?? 0;
        const late = c.best.chance.late ?? 0;
        return [
          RANKS[levelOf(cancel, late)],
          wholePercent(cancel),
          wholePercent(late),
          c.index * 5 + c.block,
        ];
      };
      const less = (a: number[], b: number[]): boolean => {
        for (let i = 0; i < a.length; i += 1)
          if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0);
        return false;
      };
      if (open.length === 0) {
        expect(best.kind).toBe('faa');
        continue;
      }
      const least = open.reduce((a, b) => (less(key(b), key(a)) ? b : a));
      if (best.kind !== 'safest' && best.kind !== 'tie') throw new Error(best.kind);
      expect([best.pick.index, best.pick.block]).toEqual([least.index, least.block]);
      // The passed-over line exactly when an open time shows a lower cancel chance, and true.
      const cancelOf = (c: { best: { chance: { cancel: number | null } } }): number =>
        wholePercent(c.best.chance.cancel ?? 0);
      const lower = open.filter((c) => cancelOf(c) < cancelOf(least));
      expect(best.kind === 'safest' && best.passed !== null).toBe(lower.length > 0);
      if (best.kind !== 'safest' || best.passed === null) continue;
      const passed = best.passed;
      const lowest = lower.reduce((a, b) => (cancelOf(b) < cancelOf(a) ? b : a));
      expect([passed.index, passed.block]).toEqual([lowest.index, lowest.block]);
      const [pl, pc, pt] = key({ ...passed, date: passed.date });
      const [kl, kc, kt] = key(least);
      // Its level is higher, which only its higher late chance can make: the line's reason holds.
      expect((pl ?? 0) > (kl ?? 0) && (pc ?? 0) < (kc ?? 0) && (pt ?? 0) > (kt ?? 0)).toBe(true);
      expect(levelOf(0, passed.best.chance.late ?? 0)).toBe('delay');
    }
  });

  it('calls two cells that show the same numbers the same, at every level line', () => {
    for (const [a, b] of [
      [48, 52],
      [49, 51],
      [148, 152],
      [149, 151],
    ] as const) {
      const { grid, best } = shown([row(b, b), row(a, a), row(a, a)], FLAT);
      expect([a, b, best.kind]).toEqual([a, b, 'tie']);
      const levels = new Set(grid.flatMap((d) => d.cells.map((c) => c.best?.chance.level)));
      expect([a, b, levels.size]).toEqual([a, b, 1]);
    }
    // Late 249 and 251 both show 25%; 2% cancel everywhere.
    const late = shown(
      [row(20, 20), row(20, 20), row(20, 20)],
      [row(251, 251), row(249, 249), row(249, 249)],
    );
    expect(late.best.kind).toBe('tie');
    // One shown point lower is lower: 4% (44) next to 5% (45), later in the grid.
    const lower = shown([row(45, 45), row(45, 45), row(45, 44)], FLAT);
    expect(lower.best).toMatchObject({ kind: 'safest', pick: { index: 2, block: 4 } });
    expect(
      lower.best.kind === 'safest' &&
        safestChance({ day: '2026-01-07', block: 'night' }, '2026-01-05'),
    ).toContain('safest');
  });

  it('never ranks or colors two cells apart that show the same numbers, on any grid', () => {
    // A seeded walk over grids near every level line (SYNTHETIC values).
    let seed = 7;
    const next = (): number => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const near = [0, 4, 5, 6, 44, 45, 46, 48, 49, 50, 51, 52, 144, 145, 146, 149, 150, 151, 300];
    const nearLate = [0, 60, 240, 244, 245, 246, 249, 250, 251, 400];
    const pick = (list: readonly number[]): number => list[Math.floor(next() * list.length)] ?? 0;
    const rand = (list: readonly number[]): FlightsAirportLive['dep_canc'] =>
      [0, 1, 2].map(() =>
        [0, 1, 2, 3, 4].map(() => pick(list)),
      ) as unknown as FlightsAirportLive['dep_canc'];
    for (let trial = 0; trial < 400; trial += 1) {
      const { grid, best } = shown(rand(near), rand(nearLate));
      const cells = grid.flatMap((d) =>
        d.cells.flatMap((c, block) =>
          c.best === null ? [] : [{ index: d.index, block, best: c.best }],
        ),
      );
      const key = (c: (typeof cells)[number]): string =>
        `${String(Math.round((c.best.chance.cancel ?? 0) / 10))}/${String(Math.round((c.best.chance.late ?? 0) / 10))}`;
      for (const a of cells)
        for (const b of cells)
          if (key(a) === key(b)) expect(a.best.chance.level).toBe(b.best.chance.level);
      if (best.kind !== 'safest' && best.kind !== 'tie') continue;
      const named = cells.find((c) => c.index === best.pick.index && c.block === best.pick.block);
      if (named === undefined) throw new Error('named cell missing');
      // No earlier cell shows the same numbers as the one named.
      const earlier = cells.filter((c) => c.index * 5 + c.block < named.index * 5 + named.block);
      expect(earlier.some((c) => key(c) === key(named))).toBe(false);
      // A tie exactly when every cell shows the same numbers.
      expect(best.kind === 'tie').toBe(
        cells.length > 1 && cells.every((c) => key(c) === key(named)),
      );
    }
  });
});

describe('a flight’s legs', () => {
  // WN 2510 from MCI: 6:30 am Monday, Thursday and Friday, 7:00 am Tuesday and Wednesday and
  // 7:40 am Sunday, as BTS lists one number once per set of weekdays with its own times.
  const rows = [
    usual(2510, 390, 475, 0b0011001),
    usual(2510, 420, 505, 0b0000110),
    usual(2510, 460, 540, 0b1000000),
  ];

  it('is one leg per place it lands, with the row for the day shown', () => {
    expect(flightLegs(rows)).toEqual(['LAX']);
    // Tuesday Jan 6, 2026: the 7:00 am row.
    expect(rowForDay(rows, 'LAX', '2026-01-06')?.leaves).toBe(420);
    // Monday Jan 5: the 6:30 am row.
    expect(rowForDay(rows, 'LAX', '2026-01-05')?.leaves).toBe(390);
    // Sunday Jan 11: the 7:40 am row.
    expect(rowForDay(rows, 'LAX', '2026-01-11')?.leaves).toBe(460);
    expect(flightLegs([...rows, usual(2510, 700, 800, ALL_DAYS, 'PHX')])).toEqual(['LAX', 'PHX']);
  });
});

describe('the day words', () => {
  it('name days from the local date now, and an old file’s days by their dates', () => {
    expect(dayName('2026-01-05', '2026-01-05')).toBe('Today');
    expect(dayName('2026-01-06', '2026-01-05')).toBe('Tomorrow');
    expect(dayName('2026-01-07', '2026-01-05')).toBe('Wednesday');
    // 2 am: the night before is the file's first day, named by its date, never as today.
    expect(dayName('2026-01-04', '2026-01-05')).toBe('Sun, Jan 4');
    // A file from yesterday: no today or tomorrow at all.
    expect(dayName('2026-01-05', '2026-01-05', true)).toBe('Mon, Jan 5');
    expect(dayWords('2026-01-07', '2026-01-05')).toBe('on Wednesday');
    expect(dayWords('2026-01-04', '2026-01-05')).toBe('on Sun, Jan 4');
  });
});
