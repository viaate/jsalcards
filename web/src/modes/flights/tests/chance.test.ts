/** What the chances say by block, by day and for a flight's two ends (SYNTHETIC files). */
import { describe, expect, it } from 'vitest';

import {
  addDays,
  answerOf,
  blockCounts,
  blockOfMinute,
  blockOver,
  dayHero,
  dayViews,
  either,
  flightChance,
  pillOf,
  instantOf,
  levelOf,
  wholePercent,
  localParts,
  localToday,
  todayView,
  weekdayIndex,
} from '../chance';
import {
  blockChance,
  dayChance,
  heroNumber,
  lateFact,
  percent,
  usualChance,
} from '../../../copy-flights';
import { ROW_LOW, ROW_NONE, airportLive } from './fixtures';

const CHICAGO = 'America/Chicago';
/** Jan 5, 2026, 4 am CST: before the first block of the day. */
const BEFORE_DAWN = Date.parse('2026-01-05T10:00:00Z');

describe('levels', () => {
  it('reads high risk of cancel at 15%, some risk at 5% cancel or 25% late', () => {
    expect(levelOf(0, 0)).toBe('low');
    expect(levelOf(44, 244)).toBe('low');
    expect(levelOf(50, 0)).toBe('delay');
    expect(levelOf(0, 250)).toBe('delay');
    expect(levelOf(150, 0)).toBe('cancel');
  });

  it('takes the level from the whole percent shown, never the raw value (LR-F15.1)', () => {
    // 49 and 51 both show 5%: both are some risk; 44 shows 4%, 45 shows 5%.
    for (const [cancel, late, level] of [
      [49, 0, 'delay'],
      [51, 0, 'delay'],
      [44, 0, 'low'],
      [45, 0, 'delay'],
      [149, 0, 'cancel'],
      [151, 0, 'cancel'],
      [144, 0, 'delay'],
      [145, 0, 'cancel'],
      [0, 249, 'delay'],
      [0, 251, 'delay'],
      [0, 244, 'low'],
      [0, 245, 'delay'],
    ] as const)
      expect([cancel, late, levelOf(cancel, late)]).toEqual([cancel, late, level]);
    // For every value, the level is the shown percent's, and the shown percent is the page's.
    for (let cancel = 0; cancel <= 1000; cancel += 1) {
      expect(percent(cancel)).toBe(
        wholePercent(cancel) < 1 ? 'Under 1%' : `${String(wholePercent(cancel))}%`,
      );
      for (const late of [0, 244, 245, 255])
        expect(levelOf(cancel, late)).toBe(
          levelOf(wholePercent(cancel) * 10, wholePercent(late) * 10),
        );
    }
  });

  it('puts two ends together as at least one of them', () => {
    expect(either(0, 0)).toBe(0);
    expect(either(100, 100)).toBe(190);
    expect(either(1000, 0)).toBe(1000);
  });
});

describe('blocks and days', () => {
  it('gives each minute its block, the small hours to the night before', () => {
    expect(blockOfMinute(300)).toEqual({ block: 0, dayBefore: false });
    expect(blockOfMinute(539)).toEqual({ block: 0, dayBefore: false });
    expect(blockOfMinute(540)).toEqual({ block: 1, dayBefore: false });
    expect(blockOfMinute(720)).toEqual({ block: 2, dayBefore: false });
    expect(blockOfMinute(1020)).toEqual({ block: 3, dayBefore: false });
    expect(blockOfMinute(1260)).toEqual({ block: 4, dayBefore: false });
    expect(blockOfMinute(120)).toEqual({ block: 4, dayBefore: true });
  });

  it('counts dates and weekdays', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
    expect(weekdayIndex('2026-01-05')).toBe(0); // a Monday
    expect(weekdayIndex('2026-01-11')).toBe(6);
  });

  it('turns local times to instants and back, across a zone', () => {
    const at = instantOf('2026-01-05', 300, 'America/Chicago');
    expect(at.toISOString()).toBe('2026-01-05T11:00:00.000Z');
    expect(localParts(at, 'America/Los_Angeles')).toEqual({ day: '2026-01-05', minute: 180 });
    // Across the spring change: 3 am Chicago on Mar 8, 2026 is CDT.
    expect(instantOf('2026-03-08', 180, 'America/Chicago').toISOString()).toBe(
      '2026-03-08T08:00:00.000Z',
    );
  });

  it('gives a level from forecast values only, and the usual rate as itself', () => {
    const entry = airportLive('MCI', '2026-01-05', {
      dep_canc: [[null, null, 60, 160, 20], [10, 12, 15, 20, 18], ROW_NONE],
      usual: [
        [0b11100, 0b11111, 0],
        [0b11100, 0b11111, 0],
        [0, 0, 0],
        [0, 0, 0],
      ],
    });
    // Before the day starts (Jan 5, 4 am CST): nothing over yet.
    const [today, tomorrow, after] = dayViews(entry, CHICAGO, BEFORE_DAWN);
    expect(today?.blocks[0]).toEqual({
      cancel: null,
      late: 40,
      cancelUsual: false,
      lateUsual: false,
      usual: false,
      over: false,
    });
    // The 16% cancel is the usual rate: it never makes "High risk".
    expect(today?.cancel).toBe(160);
    expect(today?.level).toBeNull();
    expect(today?.answer).toBe('usual');
    expect(tomorrow?.answer).toBe('usual');
    expect(tomorrow?.level).toBeNull();
    expect(after?.cancel).toBeNull();
    expect(after?.day).toBe('2026-01-07');
  });

  it('never lets a usual value make a level under a storm, an FAA stop or an alert', () => {
    const entry = airportLive('MCI', '2026-01-05', {
      usual: [
        [0b11111, 0b11111, 0b11111],
        [0b11111, 0b11111, 0b11111],
        [0b11111, 0b11111, 0b11111],
        [0b11111, 0b11111, 0b11111],
      ],
      why: [[0], [0], []],
      programs: [{ program: 0, why: 1, minutes: null, until: null }],
      alerts: [0],
    });
    for (const view of dayViews(entry, CHICAGO, BEFORE_DAWN)) {
      expect(view.level).toBeNull();
      expect(view.answer).toBe('usual');
    }
    expect(answerOf(null, null, true)).toEqual({ level: null, answer: 'usual' });
    // A forecast of risk stands beside usual values; a low forecast does not.
    expect(answerOf(160, 40, true)).toEqual({ level: 'cancel', answer: 'level' });
    expect(answerOf(10, 40, true)).toEqual({ level: null, answer: 'usual' });
    expect(answerOf(10, 40, false)).toEqual({ level: 'low', answer: 'level' });
    expect(answerOf(null, null, false)).toEqual({ level: null, answer: 'none' });
  });

  it('marks blocks over by now at the airport’s own clock, and leaves them out of the answer', () => {
    const entry = airportLive('MCI', '2026-01-05', {
      dep_canc: [[300, 300, 10, 10, 10], ROW_LOW, ROW_LOW],
    });
    // 1 pm CST: early and morning are over; their 30% is never the answer.
    const [today] = dayViews(entry, CHICAGO, Date.parse('2026-01-05T19:00:00Z'));
    expect(today?.blocks.map((block) => block.over)).toEqual([true, true, false, false, false]);
    expect(today?.cancel).toBe(10);
    expect(today?.level).toBe('low');
    expect(blockOver('2026-01-05', 4, CHICAGO, Date.parse('2026-01-06T10:59:00Z'))).toBe(false);
    expect(blockOver('2026-01-05', 4, CHICAGO, Date.parse('2026-01-06T11:00:00Z'))).toBe(true);
  });

  it('finds local today at 2 am, when the file still holds the night before', () => {
    // 2 am CST on Jan 5: the file's own today is Jan 4, whose night runs to 5 am.
    const twoAm = Date.parse('2026-01-05T08:00:00Z');
    const entry = airportLive('MCI', '2026-01-04');
    const views = dayViews(entry, CHICAGO, twoAm);
    expect(views[0]?.blocks.map((block) => block.over)).toEqual([true, true, true, true, false]);
    expect(localToday(CHICAGO, twoAm)).toBe('2026-01-05');
    expect(todayView(views, CHICAGO, twoAm)?.day).toBe('2026-01-05');
  });
});

describe('a flight’s two ends', () => {
  const from = airportLive('MCI', '2026-01-05', {
    dep_canc: [[10, 200, 15, 20, 18], ROW_NONE, ROW_NONE],
  });
  const to = airportLive('LAX', '2026-01-05', {
    arr_canc: [[5, 5, 100, 5, 5], ROW_NONE, ROW_NONE],
  });

  it('takes the departure block at one end and the arrival block on the other clock', () => {
    // Leaves MCI 9:30 am CST (morning), lands LAX 11:15 am PST (morning).
    const chance = flightChance(
      { entry: from, zone: 'America/Chicago' },
      { entry: to, zone: 'America/Los_Angeles' },
      '2026-01-05',
      570,
      675,
    );
    expect(chance.departBlock).toBe(1);
    expect(chance.arriveBlock).toBe(1);
    expect(chance.minutes).toBe(225);
    expect(chance.cancel).toBe(either(200, 5));
    expect(chance.level).toBe('cancel');
  });

  it('moves an overnight landing to the next day, and has no value off the three days', () => {
    // Leaves 11:30 pm, lands 5:10 am the next day: tomorrow has no values here.
    const chance = flightChance(
      { entry: from, zone: 'America/Chicago' },
      { entry: to, zone: 'America/Los_Angeles' },
      '2026-01-05',
      1410,
      310,
    );
    expect(chance.arriveDay).toBe('2026-01-06');
    expect(chance.cancel).toBeNull();
    expect(chance.level).toBeNull();
  });

  it('carries the usual mark from either end', () => {
    const usualTo = airportLive('LAX', '2026-01-05', {
      usual: [
        [0, 0, 0],
        [0, 0, 0],
        [0b00010, 0, 0],
        [0, 0, 0],
      ],
    });
    const chance = flightChance(
      { entry: from, zone: 'America/Chicago' },
      { entry: usualTo, zone: 'America/Los_Angeles' },
      '2026-01-05',
      570,
      675,
    );
    expect(chance.usual).toBe(true);
    // MCI's 20% cancel at 9:30 is a forecast: the risk it shows stands.
    expect(chance.level).toBe('cancel');
  });

  it('gives no level where the forecast end is low and the other end is the usual rate', () => {
    const quiet = airportLive('MCI', '2026-01-05');
    const usualTo = airportLive('LAX', '2026-01-05', {
      usual: [
        [0, 0, 0],
        [0, 0, 0],
        [0b11111, 0b11111, 0b11111],
        [0b11111, 0b11111, 0b11111],
      ],
    });
    const chance = flightChance(
      { entry: quiet, zone: 'America/Chicago' },
      { entry: usualTo, zone: 'America/Los_Angeles' },
      '2026-01-05',
      570,
      675,
    );
    expect(chance.cancel).not.toBeNull();
    expect(chance.level).toBeNull();
    expect(chance.answer).toBe('usual');
  });
});

describe('the answer’s number (LR-F9)', () => {
  const MCI_ZONE = 'America/Chicago';
  /** Jan 5, 2026 (a Monday), 8:00 am CST: no block is over yet. */
  const EIGHT = Date.parse('2026-01-05T14:00:00Z');
  const flight = (leaves: number, weekdays = 0b1111111) => ({ leaves, weekdays });

  it('counts the usual flights still to leave in each block, the small hours in the night before', () => {
    const flights = [
      flight(400), // 6:40 am: early
      flight(450), // 7:30 am: early
      flight(470, 0b1000000), // 7:50 am, but only on Sundays
      flight(600), // 10 am: morning
      flight(1300), // 9:40 pm: night
      flight(30, 0b0000010), // 12:30 am Tuesday: Monday's night
      flight(60, 0b0000001), // 1 am Monday: Sunday's night, never Monday's
    ];
    // 6 am: both early flights still to leave.
    expect(
      blockCounts(flights, '2026-01-05', MCI_ZONE, Date.parse('2026-01-05T12:00:00Z')),
    ).toEqual([2, 1, 0, 0, 2]);
    // At 7 am the 6:40 has left.
    expect(
      blockCounts(flights, '2026-01-05', MCI_ZONE, Date.parse('2026-01-05T13:00:00Z')),
    ).toEqual([1, 1, 0, 0, 2]);
  });

  it('weights the day by the usual flights left, so the number is a departure’s chance', () => {
    const entry = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [100, 20, 20, 20, 20],
        [20, 20, 20, 20, 20],
        [20, 20, 20, 20, 20],
      ],
    });
    const [today] = dayViews(entry, MCI_ZONE, EIGHT);
    if (today === undefined) throw new Error('no day');
    // One flight early at 10%, three later at 2%: (100 + 3 * 20) / 4 = 40, so 4%.
    const hero = dayHero(today, [1, 1, 1, 1, 0]);
    expect(hero).toMatchObject({ cancel: 40, block: null, rest: false, usual: 'none' });
    expect(heroNumber(hero?.cancel ?? 0)).toBe('4');
    expect(dayChance(today.day, '2026-01-05', false)).toBe('Chance of a cancel today');
    // The late chance is weighted the same: (40 + 50 + 60 + 80) / 4 = 57.5, so 58.
    expect(hero?.late).toBe(58);
    expect(lateFact(hero?.late ?? 0)).toEqual({ label: 'Delay of 45+ min', value: '6%' });
  });

  it('names the riskiest block with no counts, and says one shared value for the day', () => {
    const entry = airportLive('MCI', '2026-01-05', {
      dep_canc: [
        [20, 20, 20, 220, 20],
        [20, 20, 20, 20, 20],
        [20, 20, 20, 20, 20],
      ],
      dep_late: [
        [50, 50, 50, 350, 50],
        [50, 50, 50, 50, 50],
        [50, 50, 50, 50, 50],
      ],
    });
    const [today, tomorrow] = dayViews(entry, MCI_ZONE, EIGHT);
    if (today === undefined || tomorrow === undefined) throw new Error('no day');
    const risky = dayHero(today, null);
    expect(risky).toMatchObject({ cancel: 220, late: 350, block: 3 });
    expect(blockChance(today.day, '2026-01-05', 'evening')).toBe(
      'Chance of a cancel today, 5 to 9 pm',
    );
    // A day with no flights left in the counts: the same, never a 0 made up.
    expect(dayHero(today, [0, 0, 0, 0, 0])?.block).toBe(3);
    expect(dayHero(tomorrow, null)).toMatchObject({ cancel: 20, late: 50, block: null });
    expect(heroNumber(4)).toBe('<1');
  });

  it('says the usual rate as itself, and nothing once every block has ended', () => {
    const all: [number, number, number] = [0b11111, 0b11111, 0b11111];
    const entry = airportLive('MCI', '2026-01-05', { usual: [all, all, all, all] });
    const [today] = dayViews(entry, MCI_ZONE, EIGHT);
    if (today === undefined) throw new Error('no day');
    expect(dayHero(today, null)?.usual).toBe('all');
    expect(usualChance('2026-01-11', null)).toBe('Usual chance of a cancel on a Sunday');
    const part = airportLive('MCI', '2026-01-05', {
      usual: [
        [0b00001, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
      ],
    });
    const [mixed] = dayViews(part, MCI_ZONE, EIGHT);
    if (mixed === undefined) throw new Error('no day');
    expect(dayHero(mixed, [1, 1, 1, 1, 1])?.usual).toBe('part');
    // 5:30 am the next day: every block of Jan 5 is over.
    const [over] = dayViews(entry, MCI_ZONE, Date.parse('2026-01-06T11:30:00Z'));
    if (over === undefined) throw new Error('no day');
    expect(dayHero(over, null)).toBeNull();
    // At 6 pm part of today has ended: the rest of today.
    const [evening] = dayViews(entry, MCI_ZONE, Date.parse('2026-01-06T00:00:00Z'));
    expect(evening === undefined ? null : dayHero(evening, null)?.rest).toBe(true);
    expect(dayChance('2026-01-05', '2026-01-05', true)).toBe(
      'Chance of a cancel for the rest of today',
    );
  });
});

describe('the cancel number’s own usual flags (LR-SF1)', () => {
  const ZONE = 'America/New_York';
  /** Jan 5, 2026, 8:00 am EST: no block is over yet. */
  const EIGHT = Date.parse('2026-01-05T13:00:00Z');
  const ALL: [number, number, number] = [0b11111, 0b11111, 0b11111];
  const NONE: [number, number, number] = [0, 0, 0];

  it('says a usual cancel chance as usual beside a forecast late chance', () => {
    // JFK: cancels the usual rate, late the forecast's (its late gate passes, its cancel fails).
    const entry = airportLive('JFK', '2026-01-05', { usual: [ALL, NONE, ALL, NONE] });
    const [today] = dayViews(entry, ZONE, EIGHT);
    if (today === undefined) throw new Error('no day');
    for (const counts of [null, [1, 1, 1, 1, 1]]) {
      const hero = dayHero(today, counts);
      expect(hero?.usual).toBe('part');
      expect(hero?.cancelUsual).toBe('all');
    }
  });

  it('keeps a forecast cancel chance a forecast beside a usual late chance', () => {
    const entry = airportLive('APN', '2026-01-05', { usual: [NONE, ALL, NONE, ALL] });
    const [today] = dayViews(entry, ZONE, EIGHT);
    if (today === undefined) throw new Error('no day');
    const hero = dayHero(today, [1, 1, 1, 1, 1]);
    expect(hero?.usual).toBe('part');
    expect(hero?.cancelUsual).toBe('none');
  });

  it('counts only the blocks the number rests on', () => {
    // The early block's cancel is usual, the rest are forecast: part of the day's number.
    const entry = airportLive('JFK', '2026-01-05', {
      usual: [[0b00001, 0, 0], NONE, NONE, NONE],
    });
    const [today] = dayViews(entry, ZONE, EIGHT);
    if (today === undefined) throw new Error('no day');
    expect(dayHero(today, [1, 1, 1, 1, 1])?.cancelUsual).toBe('part');
    // With no flight early, the number rests on forecast blocks alone.
    expect(dayHero(today, [0, 1, 1, 1, 1])?.cancelUsual).toBe('none');
  });

  it('gives each end of a flight its own cancel flag', () => {
    const jfk = airportLive('JFK', '2026-01-05', { usual: [ALL, NONE, ALL, NONE] });
    const lax = airportLive('LAX', '2026-01-05');
    const out = flightChance(
      { entry: jfk, zone: ZONE },
      { entry: lax, zone: 'America/Los_Angeles' },
      '2026-01-05',
      600,
      840,
    );
    expect(out).toMatchObject({ fromCancelUsual: true, toCancelUsual: false, allUsual: false });
    const back = flightChance(
      { entry: lax, zone: 'America/Los_Angeles' },
      { entry: jfk, zone: ZONE },
      '2026-01-05',
      420,
      900,
    );
    expect(back).toMatchObject({ fromCancelUsual: false, toCancelUsual: true });
    const both = flightChance(
      { entry: jfk, zone: ZONE },
      { entry: airportLive('PHL', '2026-01-05', { usual: [ALL, NONE, ALL, NONE] }), zone: ZONE },
      '2026-01-05',
      600,
      660,
    );
    expect(both).toMatchObject({ fromCancelUsual: true, toCancelUsual: true, allUsual: false });
  });

  it('gives the late number its own usual share', () => {
    const jfk = airportLive('JFK', '2026-01-05', { usual: [ALL, NONE, ALL, NONE] });
    const apn = airportLive('APN', '2026-01-05', { usual: [NONE, ALL, NONE, ALL] });
    for (const [entry, late] of [
      [jfk, 'none'],
      [apn, 'all'],
    ] as const) {
      const [today] = dayViews(entry, ZONE, EIGHT);
      if (today === undefined) throw new Error('no day');
      expect(dayHero(today, [1, 1, 1, 1, 1])?.lateUsual).toBe(late);
      expect(dayHero(today, null)?.lateUsual).toBe(late);
    }
  });

  it('says a route row’s usual cancel chance as usual, never in its forecast late level', () => {
    // A windy day at JFK and PHL: cancels the usual rate, a 30% forecast late chance at both ends.
    const row: [number, number, number, number, number] = [300, 300, 300, 300, 300];
    const late30: [typeof row, typeof row, typeof row] = [row, row, row];
    const windy = (code: string): ReturnType<typeof airportLive> =>
      airportLive(code, '2026-01-05', {
        usual: [ALL, NONE, ALL, NONE],
        dep_late: late30,
        arr_late: late30,
      });
    const chance = flightChance(
      { entry: windy('JFK'), zone: ZONE },
      { entry: windy('PHL'), zone: ZONE },
      '2026-01-05',
      600,
      660,
    );
    // The forecast late chance alone makes a level, which the pill would show as a color.
    expect(chance.level).toBe('delay');
    expect(chance.cancelShare).toBe('all');
    expect(pillOf(chance)).toEqual({ usual: 'all', level: null });
    // A cancel number the usual rate in part has no level color either; only a cancel number
    // wholly the forecast's takes the forecast's level.
    expect(pillOf({ level: 'delay', cancelShare: 'part' })).toEqual({ usual: 'part', level: null });
    expect(pillOf({ level: 'delay', cancelShare: 'none' })).toEqual({
      usual: 'none',
      level: 'delay',
    });
  });

  // The host file's pattern (LR-SF8 rule 5): arr_late usual at every airport, JFK's dep_late the
  // model's, cancels usual at JFK and BOS, the model's elsewhere.
  const lateRows = (n: number): ReturnType<typeof airportLive>['dep_late'] => [
    [n, n, n, n, n],
    [n, n, n, n, n],
    [n, n, n, n, n],
  ];
  const host = (
    code: string,
    cancelsUsual: boolean,
    depLate: number,
    arrLate: number,
  ): ReturnType<typeof airportLive> =>
    airportLive(code, '2026-01-05', {
      dep_late: lateRows(depLate),
      arr_late: lateRows(arrLate),
      usual: [cancelsUsual ? ALL : NONE, cancelsUsual ? ALL : NONE, cancelsUsual ? ALL : NONE, ALL],
    });
  const fly = (
    from: ReturnType<typeof airportLive>,
    to: ReturnType<typeof airportLive>,
  ): ReturnType<typeof flightChance> =>
    flightChance({ entry: from, zone: ZONE }, { entry: to, zone: ZONE }, '2026-01-05', 600, 660);

  it('marks a flight’s delay all usual where the larger end’s late value is usual (JFK to BOS)', () => {
    const jfk = airportLive('JFK', '2026-01-05', {
      dep_late: lateRows(86),
      arr_late: lateRows(80),
      usual: [ALL, NONE, ALL, ALL],
    });
    const bos = host('BOS', true, 70, 91);
    const chance = fly(jfk, bos);
    // 9% is BOS's usual arrival rate over JFK's forecast 86: wholly the usual rate.
    expect(chance.late).toBe(91);
    expect(chance).toMatchObject({ cancelShare: 'all', lateShare: 'all' });
    // The larger value the forecast's and the smaller usual: usual in part.
    const bosLow = host('BOS', true, 70, 50);
    expect(fly(jfk, bosLow)).toMatchObject({ late: 86, lateShare: 'part' });
    // Equal values, one usual: in part, never all.
    expect(fly(jfk, host('BOS', true, 70, 86))).toMatchObject({ late: 86, lateShare: 'part' });
  });

  it('decides the pill by the cancel number’s own values, never by a late flag (PIT to SNA)', () => {
    // Cancels the model's at both ends, the arrival's late value usual: the cancel number is the
    // forecast's, so the pill never says usual.
    const chance = fly(host('PIT', false, 40, 50), host('SNA', false, 40, 50));
    expect(chance.cancelShare).toBe('none');
    expect(chance.lateShare).toBe('all');
    expect(pillOf(chance).usual).toBe('none');
  });

  it('marks a cancel number usual in part where one end’s is (JFK to SEA, windy at JFK)', () => {
    const jfk = airportLive('JFK', '2026-01-05', {
      dep_late: lateRows(300),
      usual: [ALL, NONE, ALL, ALL],
    });
    const chance = fly(jfk, host('SEA', false, 40, 50));
    expect(chance.cancelShare).toBe('part');
    // The forecast's 30% late at JFK makes a level, which the part-usual pill never shows.
    expect(chance.level).toBe('delay');
    expect(pillOf(chance)).toEqual({ usual: 'part', level: null });
    expect(chance.lateShare).toBe('part');
  });
});
