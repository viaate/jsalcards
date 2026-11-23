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
  usualFacts,
  updated,
} from '../../../copy-flights';
import { dayHero, dayViews, localToday } from '../chance';
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
      'FAA at MCI | Ground stop now, not in this chance',
    ]);
    expect(row(faaFact(1, 'LAX', true))).toBe('FAA at LAX | Ground delay now, not in this chance');
    // On the airport's own panel, its code is never said again.
    expect(rows(faaFacts(read, entry, null, CHI, at, true))).toEqual([
      'FAA | Ground stop now, not in this chance',
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
      'FAA at MCI | Ground delay now, not in this chance',
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
      ...usualFacts(false, true, ['MCI', 'LAX']),
      ...usualFacts(true, true),
      ...stormFacts(4, false, 2),
      ...stormFacts(4, true, 1),
    );
    const failed = lines.filter((line) => {
      const { grade, longest } = measure(line, ['MCI', 'LAX', 'ORD', 'FAA']);
      return longest > 16 || (grade ?? 0) > 6;
    });
    expect(failed).toEqual([]);
    expect(labels.filter((label) => label.split(/\s+/u).length > 5)).toEqual([]);
  });
});
