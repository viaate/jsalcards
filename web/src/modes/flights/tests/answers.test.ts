/**
 * The words of Flights' answers, each true for what it labels: the night left after midnight,
 * Best time to fly in one bounded sentence, and the FAA's live program said under the number
 * (and gone once the FAA read is old). The files here are SYNTHETIC.
 */
import { describe, expect, it } from 'vitest';

import {
  BLOCK_KEYS,
  airlineAlerts,
  blockChance,
  dayChance,
  faaFact,
  faaEndedFact,
  flightsCopy,
  notFoundAt,
  safestChance,
  sameChance,
  passedFact,
  clockAt,
  valueWords,
  faaWait,
  faaEndedLine,
  programLine,
  heldTodayFact,
  cellHeld,
  regionalNames,
  cellChance,
  cellLabel,
  codesOf,
  faaDayNote,
  liveWait,
  stormFacts,
  lateFact,
  faaOldFact,
  bothFact,
  usualDaysFact,
  usualSomeFact,
  usualAnswer,
  usualFacts,
  usualNoteFor,
  updated,
  notInUsual,
  reasonKind,
  trackNotShown,
  usualChance,
  hubChance,
  skillLine,
} from '../../../copy-flights';
import { dayHero, dayViews, localToday } from '../chance';
import type { UsualShare } from '../chance';
import {
  REGIONAL_AIRLINES,
  faaFacts,
  faaLive,
  faaPrograms,
  programEndClock,
  programEnded,
  readLive,
} from '../data';
import type { FlightsProgramNow } from '../../../types/generated';
import { airportLive, liveFile } from './fixtures';
import { measure } from '../../../app/tests/plain-reading';

const MCI = 'America/Chicago';

/** Rows under an answer as the page shows them, a label and its value: "FAA at MCI | Ground stop now". */
const rows = (facts: readonly { label: string; value: string }[]): string[] =>
  facts.map((fact) => `${fact.label} | ${fact.value}`);
const row = (fact: { label: string; value: string } | null): string =>
  fact === null ? '' : `${fact.label} | ${fact.value}`;

/** A chance resting in part on the usual rate, with a run read and weather (LR-SF1 rows). */
const SHARES = ['all', 'part', 'none'] as const;

describe('the airport headline after midnight', () => {
  // Monday 2 am in Kansas City: the file's first day is Sunday, whose night runs to 5 am.
  const now = Date.parse('2026-01-05T08:00:00Z');
  const entry = airportLive('MCI', '2026-01-04', {
    dep_canc: [
      [30, 120, 220, 40, 90],
      [10, 10, 10, 10, 10],
      [10, 10, 10, 10, 10],
    ],
  });

  it('names what is left, the night until 5 am, never the whole past day', () => {
    const [sunday] = dayViews(entry, MCI, now);
    if (sunday === undefined) throw new Error('no day');
    expect(sunday.blocks.map((block) => block.over)).toEqual([true, true, true, true, false]);
    const hero = dayHero(sunday, null);
    expect(hero?.cancel).toBe(90);
    const today = localToday(MCI, now);
    expect(today).toBe('2026-01-05');
    const line = dayChance(sunday.day, today, hero?.rest ?? false);
    expect(line).toBe('Chance of a cancel from now to 5 am');
    expect(line).not.toContain('Sun');
    expect(blockChance(sunday.day, today, 'night')).toBe(flightsCopy.nightLeft);
  });

  it('still says today and tomorrow as before', () => {
    expect(dayChance('2026-01-05', '2026-01-05', true)).toBe(
      'Chance of a cancel for the rest of today',
    );
    expect(dayChance('2026-01-06', '2026-01-05', false)).toBe('Chance of a cancel tomorrow');
  });
});

describe('Best time to fly in one sentence', () => {
  const today = '2026-01-05';
  const time = (day: string, block: 'early' | 'afternoon' | 'evening') => ({ day, block });

  it('names the one safest time', () => {
    expect(safestChance(time('2026-01-06', 'afternoon'), today)).toBe(
      'Chance of a cancel tomorrow, noon to 5 pm. It is the safest time to fly.',
    );
  });

  it('scopes the claim to the times with a forecast when some are not ranked', () => {
    expect(safestChance(time('2026-01-05', 'afternoon'), today, true)).toBe(
      'Chance of a cancel today, noon to 5 pm. It is the safest time with a forecast.',
    );
  });

  it('says the number when every time shows the same chance (LR-F14.2)', () => {
    expect(sameChance(20)).toBe('Every time shows the same chance: 2%.');
    expect(sameChance(4)).toBe('Every time shows the same chance: under 1%.');
    expect(sameChance(40, true)).toBe('Every time with a forecast shows the same chance: 4%.');
  });

  it('points to the FAA when a live hold covers every time (LR-F14.3)', () => {
    const hold = (program: number, code: string, endedAt: string | null = null) => ({
      program,
      code,
      endedAt,
    });
    expect(faaWait([hold(0, 'MCI')])).toBe(
      'The FAA has a ground stop at MCI now. Check back when it ends.',
    );
    expect(faaWait([hold(1, 'LAX')])).toBe(
      'The FAA has a ground delay at LAX now. Check back when it ends.',
    );
    expect(faaWait([hold(4, 'MCI')])).toBe('MCI is closed now. Check back when it opens.');
    // Two or more together, in short sentences; the FAA rows under it name each (TRAV-R13-S3).
    expect(faaWait([hold(0, 'MCI'), hold(1, 'MCI')])).toBe(
      'FAA holds cover every time now. Check back when they end.',
    );
    expect(faaWait([hold(0, 'MCI'), hold(1, 'MCI'), hold(1, 'LAX')])).toBe(
      'FAA holds cover every time now. Check back when they end.',
    );
    // With one past its stated end, never "now".
    expect(faaWait([hold(0, 'MCI'), hold(1, 'LAX', clockAt('5:00 pm', 'LAX'))])).toBe(
      'FAA holds cover every time. Check back for the next FAA update.',
    );
    expect(faaWait([hold(0, 'MCI', '7:00 pm'), hold(1, 'LAX', '6:00 pm')])).not.toMatch(/\bnow\b/);
    expect(faaWait([])).toBe('');
  });
});

describe('the FAA under the answer', () => {
  const CHI = 'America/Chicago';
  const made = '2026-01-05T12:00:00Z';
  const latest = { schema_version: 1, generated_at: made, slot: 'slot-0', stamp: '20260105T1200Z' };
  const stop: FlightsProgramNow = { program: 0, why: 1, minutes: null, until: null };
  const entry = airportLive('MCI', '2026-01-05', { programs: [stop] });
  const read = readLive(latest, liveFile([entry], made));

  it('says a live ground stop as now, and that the chance shown does not count it', () => {
    if (read === null) throw new Error('no read');
    const at = Date.parse(made) + 5 * 60_000;
    expect(rows(faaFacts(read, entry, 'MCI', CHI, at, true))).toEqual([
      'FAA at MCI | Ground stop now, not counted',
    ]);
    expect(row(faaFact(1, 'LAX', true))).toBe('FAA at LAX | Ground delay now, not counted');
    // On the airport's own panel, its code is never said again.
    expect(rows(faaFacts(read, entry, null, CHI, at, true))).toEqual([
      'FAA | Ground stop now, not counted',
    ]);
  });

  it('says the fact alone under an answer that shows no chance', () => {
    if (read === null) throw new Error('no read');
    const at = Date.parse(made) + 5 * 60_000;
    expect(rows(faaFacts(read, entry, 'MCI', CHI, at))).toEqual(['FAA at MCI | Ground stop now']);
    expect(row(faaFact(1, 'LAX'))).toBe('FAA at LAX | Ground delay now');
    expect(row(faaFact(4, null))).toBe('FAA | Closed now');
    for (let program = 0; program < 6; program += 1)
      expect(row(faaFact(program, 'MCI'))).not.toContain('chance');
  });

  it('calls the FAA now on a later day only while its read is live (TRAV-R7-B1)', () => {
    if (read === null) throw new Error('no read');
    const state = (at: number): 'live' | 'old' => (faaLive(read, at) ? 'live' : 'old');
    const fresh = Date.parse(made) + 5 * 60_000;
    const old = Date.parse(made) + 47 * 60_000;
    expect(faaDayNote(state(fresh), 'flight')).toBe(
      'This is the FAA now, not on the day of this flight.',
    );
    expect(faaDayNote(state(fresh), 'airport')).toBe('This is the FAA now, not on this day.');
    // An hour-old stop is its last status, never now, on both panels.
    for (const where of ['flight', 'airport'] as const) {
      const line = faaDayNote(state(old), where) ?? '';
      expect(line).toContain('last status');
      expect(line).not.toMatch(/\bnow\b/);
      expect(faaDayNote('none', where)).toBeNull();
    }
    expect(flightsCopy.faa.titleOld).not.toMatch(/\bnow\b/);
  });

  it('never says a program past the end the FAA gave it as in place now (TRAV-R10-B3)', () => {
    // A stop set to end at 12:06Z (6:06 am in Kansas City), read at 12:00Z.
    const until = '2026-01-05T12:06:00Z';
    const ending: FlightsProgramNow = { program: 0, why: 1, minutes: null, until };
    const ends = airportLive('MCI', '2026-01-05', { programs: [ending] });
    const endRead = readLive(latest, liveFile([ends], made));
    if (endRead === null) throw new Error('no read');
    const before = Date.parse(until) - 60_000;
    const after = Date.parse(until) + 4 * 60_000;
    expect(rows(faaFacts(endRead, ends, 'MCI', CHI, before))).toEqual([
      'FAA at MCI | Ground stop now',
    ]);
    expect(rows(faaFacts(endRead, ends, 'MCI', CHI, after))).toEqual([
      'FAA at MCI | Ground stop was set to end at 6:06 am',
    ]);
    expect(rows(faaFacts(endRead, ends, null, CHI, after, true))).toEqual([
      'FAA | Ground stop was set to end at 6:06 am',
    ]);
    // At its end to the minute it is past its end.
    expect(programEnded(ending, Date.parse(until))).toBe(true);
    expect(programEnded(ending, before)).toBe(false);
    expect(programLine('Ground stop', null, programEndClock(ending, CHI))).toBe(
      'Ground stop, set to end at 6:06 am',
    );
    expect(faaWait([{ program: 0, code: 'MCI', endedAt: '6:06 am' }])).toBe(
      'The ground stop at MCI was set to end at 6:06 am. Check back for the next FAA update.',
    );
    expect(faaEndedLine(4, 'MCI', '6:06 am')).toBe('MCI was set to open at 6:06 am.');
    expect(row(faaEndedFact(4, 'MCI', '6:06 am'))).toBe('FAA at MCI | Was set to open at 6:06 am');
    expect(row(faaEndedFact(5, null, '6:06 am'))).toBe('FAA | Deicing was set to end at 6:06 am');
    for (let program = 0; program < 6; program += 1) {
      expect(faaEndedLine(program, 'MCI', '6:06 am')).not.toMatch(/\bnow\b/);
      expect(faaEndedLine(program, null, '6:06 am')).not.toMatch(/\bnow\b/);
      expect(row(faaEndedFact(program, 'MCI', '6:06 am'))).not.toMatch(/\bnow\b/);
    }
    // One in force is said before one past its end, whatever their order in the file.
    const delay: FlightsProgramNow = { program: 1, why: 1, minutes: 45, until: null };
    const both = airportLive('MCI', '2026-01-05', { programs: [ending, delay] });
    expect(faaPrograms(endRead, both, after).map((p) => p.program)).toEqual([1, 0]);
    expect(faaPrograms(endRead, both, before).map((p) => p.program)).toEqual([0, 1]);
    // Past the read's limit, nothing at all.
    expect(faaPrograms(endRead, both, Date.parse(made) + 31 * 60_000)).toEqual([]);
    // Each program gets its own line, so none the answer's other lines name is missing
    // (TRAV-R13-S3); one the answer itself names is left out (`named`).
    expect(rows(faaFacts(endRead, both, 'MCI', CHI, after, true))).toEqual([
      'FAA at MCI | Ground delay now, not counted',
      'FAA at MCI | Ground stop was set to end at 6:06 am',
    ]);
    expect(rows(faaFacts(endRead, both, 'MCI', CHI, before))).toEqual([
      'FAA at MCI | Ground stop now',
      'FAA at MCI | Ground delay now',
    ]);
    // A lesser program beside a hold is left to the FAA card: the gravest and each hold only.
    const late: FlightsProgramNow = { program: 2, why: 2, minutes: 30, until: null };
    const lesser = airportLive('MCI', '2026-01-05', { programs: [late, ending] });
    expect(rows(faaFacts(endRead, lesser, 'MCI', CHI, before))).toEqual([
      'FAA at MCI | Ground stop now',
    ]);
    expect(rows(faaFacts(endRead, lesser, 'MCI', CHI, after))).toEqual([
      'FAA at MCI | Departures late now',
      'FAA at MCI | Ground stop was set to end at 6:06 am',
    ]);
    expect(rows(faaFacts(endRead, both, 'MCI', CHI, before, false, false, [0]))).toEqual([
      'FAA at MCI | Ground delay now',
    ]);
    expect(rows(faaFacts(endRead, both, 'LAX', CHI, after, false, true))).toEqual([
      'FAA at LAX | Ground delay now',
      'FAA at LAX | Ground stop was set to end at 6:06 am LAX time',
    ]);
  });

  it('is gone once the FAA read is older than 30 minutes, and with no program', () => {
    if (read === null) throw new Error('no read');
    expect(rows(faaFacts(read, entry, 'MCI', CHI, Date.parse(made) + 31 * 60_000))).toEqual([]);
    const calm = airportLive('MCI', '2026-01-05');
    expect(rows(faaFacts(read, calm, 'MCI', CHI, Date.parse(made)))).toEqual([]);
  });
});

describe('a flight number not found', () => {
  it('says only that we could not find it, never that it does not fly', () => {
    const line = notFoundAt('DL 5489', 'MCI');
    expect(line).toBe('We could not find DL 5489 from MCI in the flights that usually fly.');
    expect(line).not.toMatch(/does not/);
    expect(flightsCopy.flight.notFound).not.toMatch(/does not/);
  });
});

describe('words a traveler reads in passing', () => {
  it('lists the regional airlines by name, leaving out one with no name, never a bare code', () => {
    expect(regionalNames(['OO', 'OH', 'YX', 'ZW'])).toEqual(['SkyWest', 'Republic']);
    for (const name of regionalNames([...REGIONAL_AIRLINES]))
      expect(REGIONAL_AIRLINES.has(name)).toBe(false);
  });

  it('keeps a part of the day in lower case inside a sentence', () => {
    for (const block of ['early', 'morning', 'afternoon', 'evening', 'night'] as const)
      expect(blockChance('2026-01-05', '2026-01-05', block)).toMatch(/today, [a-z0-9]/);
  });

  it('says a grid cell level in words too, never by its color alone (LR-F15.2)', () => {
    expect(cellChance(50, false, 'delay')).toBe('5% chance of a cancel, some risk');
    expect(cellChance(20, false, 'low')).toBe('2% chance of a cancel, low risk');
    expect(cellChance(150, false, 'cancel')).toBe('15% chance of a cancel, high risk');
    // A usual value has no level: the usual mark stands for it.
    expect(cellChance(20, true, null)).toBe('2% chance of a cancel, usual');
    expect(cellChance(20, 'all', null)).toBe('2% chance of a cancel, usual');
    expect(cellChance(90, 'part', null)).toBe('9% chance of a cancel, usual in part');
    expect(cellChance(20, 'none', null)).toBe('2% chance of a cancel');
  });

  it('says why today is not named, and leaves held times out of a tie (LR-F15.3a)', () => {
    expect(row(heldTodayFact([{ program: 0, code: 'MCI', endedAt: null }], true))).toBe(
      'Today | Held by the FAA ground stop at MCI',
    );
    expect(row(heldTodayFact([{ program: 1, code: 'LAX', endedAt: null }], false))).toBe(
      'Part of today | Held by the FAA ground delay at LAX',
    );
    expect(row(heldTodayFact([{ program: 4, code: 'MCI', endedAt: null }], true))).toBe(
      'Today | Held by the closing of MCI',
    );
    expect(sameChance(50, false, true)).toBe(
      'Every time shows the same chance: 5%. It leaves out times with an FAA hold.',
    );
    expect(sameChance(50, true, true)).toBe(
      'Every time with a forecast shows the same chance: 5%. It leaves out times with an FAA hold.',
    );
  });

  it('never says a hold past its stated end holds today or is a hold now (TRAV-R11-B1)', () => {
    // Each is named with its stated end on the FAA rows above (faaFacts): this row says only why.
    expect(row(heldTodayFact([{ program: 0, code: 'MCI', endedAt: '7:00 pm' }], true))).toBe(
      'Today | Not named until the next FAA update',
    );
    expect(
      row(heldTodayFact([{ program: 1, code: 'LAX', endedAt: clockAt('5:00 pm', 'LAX') }], false)),
    ).toBe('Part of today | Not named until the next FAA update');
    const ended = [{ program: 0, code: 'MCI' }];
    expect(sameChance(300, false, true, ended)).toBe(
      'Every time shows the same chance: 30%. It leaves out times before the FAA hold was set to end.',
    );
    expect(sameChance(300, true, true, ended)).toBe(
      'Every time with a forecast shows the same chance: 30%. It leaves out times before the FAA hold was set to end.',
    );
    expect(sameChance(300, false, true, [...ended, { program: 1, code: 'LAX' }])).toBe(
      'Every time shows the same chance: 30%. It leaves out times before the FAA holds were set to end.',
    );
    // Only behind a held tie: with nothing held, no hold is named.
    expect(sameChance(300, false, false, ended)).toBe('Every time shows the same chance: 30%.');
    for (const program of [0, 1, 4]) {
      for (const all of [true, false]) {
        const line = row(
          heldTodayFact([{ program: program, code: 'MCI', endedAt: '7:00 pm' }], all),
        );
        expect(line).not.toMatch(/\bis held\b|\bnow\b/);
      }
      expect(sameChance(300, false, true, [{ program, code: 'MCI' }])).not.toMatch(
        /with an FAA hold/,
      );
    }
  });

  it('gives a lower cancel chance passed over as a row: its time and numbers (LR-F18.2)', () => {
    expect(row(passedFact('2026-01-06', '2026-01-05', 'early', { cancel: 30, late: 250 }))).toBe(
      'Early tomorrow | 3% cancel, 25% delay',
    );
    expect(row(passedFact('2026-01-05', '2026-01-05', 'evening', { cancel: 4, late: 300 }))).toBe(
      'This evening | Under 1% cancel, 30% delay',
    );
    expect(row(passedFact('2026-01-07', '2026-01-05', 'night', { cancel: 30, late: null }))).toBe(
      'Wednesday night | 3% cancel',
    );
  });

  it('names each FAA hold, at most two by name, and says a held cell held (TRAV-R12-S2, S3)', () => {
    const stop = { program: 0, code: 'MCI', endedAt: null };
    const delay = { program: 1, code: 'LAX', endedAt: null };
    const closed = { program: 4, code: 'LAX', endedAt: null };
    // Two in force: the FAA rows name each; the row says they hold it.
    expect(row(heldTodayFact([stop, delay], true))).toBe('Today | Held by FAA holds');
    expect(row(heldTodayFact([stop, delay, closed], false))).toBe(
      'Part of today | Held by FAA holds',
    );
    const stopEnded = { ...stop, endedAt: '7:00 pm' };
    const delayEnded = { ...delay, endedAt: clockAt('5:00 pm', 'LAX') };
    expect(row(heldTodayFact([stopEnded, delayEnded], true))).toBe(
      'Today | Not named until the next FAA update',
    );
    // One in force beside one past its end: the one in force, by name.
    expect(row(heldTodayFact([stop, delayEnded], true))).toBe(
      'Today | Held by the FAA ground stop at MCI',
    );
    expect(sameChance(300, false, true, [stopEnded, delayEnded])).toBe(
      'Every time shows the same chance: 30%. It leaves out times before the FAA holds were set to end.',
    );
    expect(cellHeld([])).toBe('');
    expect(cellHeld([stop])).toBe(', held by the FAA ground stop at MCI');
    // Two or more in a few words: the lines under the answer name each (TRAV-R13-S4).
    expect(cellHeld([stop, delay])).toBe(', held by FAA holds');
    expect(cellHeld([stop, delay, closed])).toBe(', held by FAA holds');
    expect(cellHeld([stopEnded])).toBe(', not named for the FAA ground stop at MCI');
    expect(cellHeld([stop, delayEnded])).toBe(', held by FAA holds');
    expect(cellHeld([stopEnded, delayEnded])).toBe(', not named for FAA holds');
    for (const holds of [[stopEnded], [stopEnded, delayEnded]])
      expect(cellHeld(holds)).not.toMatch(/\bheld\b|\bnow\b/);
    // Short on every cell, however many holds: at most 10 words.
    for (const holds of [
      [stop],
      [stopEnded],
      [delayEnded],
      [stop, delay, closed],
      [stopEnded, delayEnded],
    ])
      expect(cellHeld(holds).split(' ').length).toBeLessThanOrEqual(10);
  });

  it('says a level a cell gets from its late chance, and an airport block’s level (TRAV-R11-S2, S3)', () => {
    expect(cellChance(30, false, 'delay', true)).toBe(
      '3% chance of a cancel, some risk of a long delay',
    );
    expect(cellChance(30, false, 'delay', false)).toBe('3% chance of a cancel, some risk');
    expect(cellChance(30, true, null, true)).toBe('3% chance of a cancel, usual');
    expect(valueWords(300, false, 'cancel')).toBe('30%, high risk');
    expect(valueWords(10, false, 'low')).toBe('1%, low risk');
    expect(valueWords(10, true, 'low')).toBe('1%, usual');
    expect(valueWords(10, false)).toBe('1%');
  });

  it('says what a grid cell measures, and that it is old on an old file', () => {
    expect(cellLabel('Tomorrow', 'morning', cellChance(20, false))).toBe(
      'Tomorrow, Morning: 2% chance of a cancel',
    );
    expect(cellLabel('Sun, Nov 22', 'afternoon', cellChance(360, false), updated(60, true))).toBe(
      `Sun, Nov 22, Afternoon: 36% chance of a cancel. ${updated(60, true)}`,
    );
  });
});

describe('a panel with no live file', () => {
  it('says reading only while the first read is out, and that it failed once it has (TRAV-R7-B2)', () => {
    expect(liveWait(false)).toBe('Reading flight chances');
    expect(liveWait(true)).toBe('We could not read the flight chances just now.');
  });
});

describe('one waiver line for both ends of a trip', () => {
  it('joins the codes, with or when none was found at either', () => {
    expect(codesOf(['MCI'])).toBe('MCI');
    expect(codesOf(['MCI', 'LAX'])).toBe('MCI and LAX');
    expect(codesOf(['MCI', 'LAX'], true)).toBe('MCI or LAX');
  });
});

describe('a past storm day', () => {
  it('says what our chances would have said, never that we said it then (TRAV-R7-S2)', () => {
    expect(rows(stormFacts(150, false, 1))).toEqual([
      'Our chance | 15% for a rough day',
      'Made | The evening before',
      'This day | Kept out when our chances were made',
    ]);
    expect(rows(stormFacts(150, true, 2))).toEqual([
      'Usual rate | 15% for a rough day',
      'This day | From the test year, kept out of our chances',
    ]);
    // The column's head short enough for a phone's narrow column (TRAV-R8-S4).
    expect(flightsCopy.storms.said.length).toBeLessThanOrEqual(12);
  });

  it('gives the waivers card its own title, and the link the airline’s name (TRAV-R8-S3)', () => {
    expect(flightsCopy.waiver.title).toBe('Travel waivers');
    expect(airlineAlerts('Delta')).toBe('Delta travel alerts');
  });
});

describe('every template under an answer, with its longest real values (LR-F17.1, D17)', () => {
  it('keeps each sentence at 16 words or fewer and each line at grade 6 or under', () => {
    const today = '2026-01-05';
    // Wednesday: the longest day name a time can carry; 11:30 pm at the far airport's clock.
    const longDay = '2026-01-07';
    const late = clockAt('11:30 pm', 'LAX');
    const holds = [
      { program: 4, code: 'MCI', endedAt: null },
      { program: 1, code: 'LAX', endedAt: late },
      { program: 0, code: 'ORD', endedAt: null },
    ];
    const lines: string[] = [];
    // A row is a label on the left and its value on the right (LR-F18.2), each read as a short
    // phrase of its own, never one sentence: joined, even LR-F18.2's own example row ("Early
    // tomorrow: 3% cancel, 25% delay.") scores grade 8 on a formula made for prose. A label is at
    // most 5 words and not graded; a value is graded as a phrase. Its figures are read as a short
    // word ("ten"): grade formulas count a bare figure as two syllables, which says nothing of how
    // hard a row of numbers is to read.
    const labels: string[] = [];
    const add = (...facts: { label: string; value: string }[]): void => {
      for (const fact of facts) {
        labels.push(fact.label);
        lines.push(fact.value.replace(/\d+(?::\d+)?%?/g, 'ten'));
      }
    };
    for (const block of BLOCK_KEYS) {
      lines.push(safestChance({ day: longDay, block }, today, true));
      add(passedFact(longDay, today, block, { cancel: 4, late: 999 }));
    }
    for (const n of [1, 2, 3]) {
      lines.push(
        faaWait(holds.slice(0, n)),
        faaWait(holds.slice(0, n).map((h) => ({ ...h, endedAt: late }))),
      );
      for (const all of [true, false]) add(heldTodayFact(holds.slice(0, n), all));
      lines.push(sameChance(4, true, true, holds.slice(0, n)), sameChance(4, true, true));
    }
    for (let program = 0; program < 6; program += 1) {
      const fact = faaFact(program, 'MCI', true);
      if (fact !== null) add(fact);
      add(faaEndedFact(program, 'MCI', late));
    }
    add(
      lateFact(999),
      faaOldFact(47 * 60),
      bothFact(),
      usualDaysFact(['2026-01-07', '2026-01-08', '2026-01-09'], today),
      usualSomeFact(),
      ...SHARES.flatMap((cancel) =>
        [...SHARES, null].flatMap((late) =>
          usualFacts({ cancel, late, run: false, codes: ['MCI', 'LAX'] }),
        ),
      ),
      ...usualFacts({ cancel: 'all', late: 'all', run: false }),
      ...usualFacts({
        cancel: 'part',
        late: 'all',
        run: true,
        reason: 'Freezing rain in the forecast',
        reasonAt: 'LAX',
      }),
      ...notInUsual(5, { days: 60, share: 48, others: 66 }, '2020-01-31'),
      ...notInUsual(1, { days: 1, share: 97, others: 60 }, '2020-01-31', 'LAX'),
      ...notInUsual(3, { days: 9, share: 97, others: 60 }, '2020-01-31'),
      ...notInUsual(4, { days: 9, share: 97, others: 60 }, '2020-01-31'),
      ...notInUsual(2, { days: 9, share: 97, others: 60 }, '2020-01-31'),
      ...notInUsual(3, { days: 0, share: 0, others: 0 }, '2020-01-31'),
      ...stormFacts(4, false, 2),
      ...stormFacts(4, true, 1),
    );
    lines.push(
      trackNotShown('2026-11-22T14:11:13Z'),
      skillLine(0.12, 40, 359),
      flightsCopy.route.allUsual,
      hubChance(90, true, 'afternoon').replace(/\d+%/gu, 'ten'),
      hubChance(90, 'part', 'afternoon').replace(/\d+%/gu, 'ten'),
      usualAnswer(90, true).replace(/\d+%/gu, 'ten'),
    );
    const failed = lines.filter((line) => {
      const { grade, longest } = measure(line, ['MCI', 'LAX', 'ORD', 'FAA']);
      return longest > 16 || (grade ?? 0) > 6;
    });
    expect(failed).toEqual([]);
    expect(labels.filter((label) => label.split(/\s+/u).length > 5)).toEqual([]);
  });
});

describe('the record beside a usual cancel chance (LR-SF1)', () => {
  const JFK_WIND = { days: 60, share: 48, others: 66 };

  it('maps each forecast reason to the record kind it speaks to, and the rest to none', () => {
    // snow, ice, thunder, wind, fog; then cold, hubs and a storm the day before.
    expect([0, 1, 2, 3, 4, 5, 6, 7, 99].map(reasonKind)).toEqual([
      2,
      1,
      3,
      5,
      4,
      null,
      null,
      null,
      null,
    ]);
  });

  it('says past days of the weather here, as past days, with their spread', () => {
    expect(rows(notInUsual(5, JFK_WIND, '2020-01-31'))).toEqual([
      'Windy days here | 60 since 2020',
      'Cancelled here | 5% in the wind',
      'Elsewhere | 7% in the same weather',
    ]);
  });

  it('never says bad days, which count days with any one bad block, not whole days', () => {
    // The record's line as read: its bad_days are there, and never said.
    const line = { ...JFK_WIND, bad_days: 12 };
    const said = rows(notInUsual(5, line, '2020-01-31'));
    expect(said.join(' ')).not.toMatch(/bad|1 in 10|12/iu);
  });

  it('names each kind in the words of the forecast reasons', () => {
    const line = { days: 3, share: 20, others: 30 };
    expect([1, 2, 3, 4, 5].map((kind) => rows(notInUsual(kind, line, '2015-01-01'))[0])).toEqual([
      'Freezing rain days here | 3 since 2015',
      'Snowy days here | 3 since 2015',
      'Thunderstorm days here | 3 since 2015',
      'Foggy days here | 3 since 2015',
      'Windy days here | 3 since 2015',
    ]);
    expect(rows(notInUsual(4, { ...line, days: 1 }, '2015-01-01', 'LAX'))[0]).toBe(
      'Foggy days at LAX | 1 since 2015',
    );
  });

  it('names the airport where the panel is not its own', () => {
    expect(rows(notInUsual(5, JFK_WIND, '2020-01-31', 'JFK'))).toEqual([
      'Windy days at JFK | 60 since 2020',
      'Cancelled at JFK | 5% in the wind',
      'Elsewhere | 7% in the same weather',
    ]);
  });

  it('says nothing with no record, and none for a kind never seen here', () => {
    expect(notInUsual(5, null, '2020-01-31')).toEqual([]);
    expect(notInUsual(0, JFK_WIND, '2020-01-31')).toEqual([]);
    expect(rows(notInUsual(5, { days: 0, share: 0, others: 50 }, '2020-01-31'))).toEqual([
      'Windy days here | None since 2020',
    ]);
  });

  it('rounds as the page does: under 1% below 5 per mille, 1% at 5', () => {
    const at = (share: number, others: number): string[] =>
      rows(notInUsual(5, { days: 10, share, others }, '2020-01-31')).slice(1);
    expect(at(4, 4)).toEqual([
      'Cancelled here | Under 1% in the wind',
      'Elsewhere | Under 1% in the same weather',
    ]);
    expect(at(5, 5)).toEqual([
      'Cancelled here | 1% in the wind',
      'Elsewhere | 1% in the same weather',
    ]);
    expect(at(14, 15)[1]).toBe('Elsewhere | 2% in the same weather');
  });

  it('says which numbers are usual in one row and what they leave out in one more (LR-SF8)', () => {
    const wind = 'Strong wind in the forecast';
    const which = (cancel: UsualShare, late: UsualShare | null): string[] =>
      rows(usualFacts({ cancel, late, run: true }));
    // Every combination: the same two rows, only the value naming which numbers changes.
    const said = SHARES.flatMap((cancel) =>
      [...SHARES, null].map((late) => [cancel, late, which(cancel, late)] as const),
    );
    for (const [cancel, late, shown] of said) {
      if (cancel === 'none' && (late ?? 'none') === 'none') {
        expect(shown).toEqual([]);
        continue;
      }
      expect(shown).toHaveLength(2);
      expect(shown[0]).toMatch(/^Usual rate \| /u);
      expect(shown[1]).toBe('Left out | Weather and the FAA');
    }
    expect(said.map(([cancel, late, shown]) => [cancel, late, shown[0] ?? null])).toEqual([
      ['all', 'all', 'Usual rate | Both chances'],
      ['all', 'part', 'Usual rate | Cancel chance, part of delay'],
      ['all', 'none', 'Usual rate | Cancel chance'],
      ['all', null, 'Usual rate | Cancel chance'],
      ['part', 'all', 'Usual rate | Delay chance, part of cancel'],
      ['part', 'part', 'Usual rate | Part of both chances'],
      ['part', 'none', 'Usual rate | Part of the cancel chance'],
      ['part', null, 'Usual rate | Part of the cancel chance'],
      ['none', 'all', 'Usual rate | Delay chance'],
      ['none', 'part', 'Usual rate | Part of the delay chance'],
      ['none', 'none', null],
      ['none', null, null],
    ]);
    // No half forms: nothing says the weather is left out of one number alone.
    expect(said.flatMap(([, , shown]) => shown).join(' ')).not.toMatch(/in part\b|without/iu);
    // The forecast's weather after the usual rows, never as "Why"; on a flight at its airport.
    expect(rows(usualFacts({ cancel: 'all', late: 'none', run: true, reason: wind }))).toEqual([
      'Usual rate | Cancel chance',
      'Left out | Weather and the FAA',
      'Weather | Strong wind in the forecast',
    ]);
    expect(
      rows(usualFacts({ cancel: 'part', late: 'all', run: true, reason: wind, reasonAt: 'LAX' })),
    ).toEqual([
      'Usual rate | Delay chance, part of cancel',
      'Left out | Weather and the FAA',
      'At LAX | Strong wind in the forecast',
    ]);
    // Nothing usual: no rows, not even the weather (the panel says its reason as "Why").
    expect(usualFacts({ cancel: 'none', late: 'none', run: true, reason: wind })).toEqual([]);
    // No run read: one Forecast row, the airports' form where they are known.
    expect(rows(usualFacts({ cancel: 'all', late: 'all', run: false }))).toEqual([
      'Usual rate | Both chances',
      'Left out | Weather and the FAA',
      'Forecast | None for this day yet',
    ]);
    expect(
      rows(usualFacts({ cancel: 'all', late: 'all', run: false, codes: ['MCI', 'LAX'] })),
    ).toEqual([
      'Usual rate | Both chances',
      'Left out | Weather and the FAA',
      'Forecast | Not ready for MCI and LAX',
    ]);
    expect(usualChance('2026-11-27', null)).toBe('Usual chance of a cancel on a Friday');
    // A day number over the blocks left today keeps its scope.
    expect(usualChance('2026-11-27', null, true)).toBe(
      'Usual chance of a cancel for the rest of today',
    );
    expect(usualChance('2026-11-27', 'evening', true)).toBe(
      'Usual chance of a cancel on a Friday, 5 to 9 pm',
    );
    // A hub whose cancel chance is the usual rate says so on its line.
    expect(hubChance(3, true)).toBe('Usual chance of a cancel today: under 1%');
    expect(hubChance(3, false)).toBe('Chance of a cancel today: under 1%');
    // With no counts, the riskiest time left is named, never said as the whole day.
    expect(hubChance(90, false, 'evening')).toBe('Chance of a cancel this evening: 9%');
    expect(hubChance(90, true, 'early')).toBe('Usual chance of a cancel early today: 9%');
    expect(hubChance(90, 'all')).toBe('Usual chance of a cancel today: 9%');
    expect(hubChance(90, 'none')).toBe('Chance of a cancel today: 9%');
    // In part (one block's usual and another's the forecast's at the same value): said so.
    expect(hubChance(90, 'part')).toBe('Chance of a cancel today, usual in part: 9%');
    // A pill by its cancel number's share.
    expect(usualAnswer(20)).toBe('Usual rate. Cancel chance 2%.');
    expect(usualAnswer(90, true)).toBe('Usual in part. Cancel chance 9%.');
    expect(usualNoteFor(['JFK'])).toBe(
      'Usual means the usual rate for this time of year, in place of our forecast for JFK.',
    );
  });

  it('says a share of the weather’s own hours for every kind, never of whole days', () => {
    const line = { days: 3, share: 20, others: 30 };
    expect([1, 2, 3, 4, 5].map((kind) => notInUsual(kind, line, '2015-01-01')[1]?.value)).toEqual([
      '2% in freezing rain',
      '2% in the snow',
      '2% in thunderstorms',
      '2% in the fog',
      '2% in the wind',
    ]);
  });

  it('says a skill count as the test’s, never as the map’s now', () => {
    expect(skillLine(0.12, 40, 359)).toBe(
      'Beat the usual rate by 12%. Passed the test at 40 of 359 airports.',
    );
    expect(skillLine(-0.02, 3, 351)).toBe(
      'Did not beat the usual rate. Passed the test at 3 of 351 airports.',
    );
  });

  it('dates a track record whose scores are not for the map’s chances', () => {
    expect(trackNotShown('2026-11-22T14:11:13Z')).toBe(
      'These scores are from Nov 22, 2026. They are not for the chances on the map now, so we do not show them.',
    );
  });
});
