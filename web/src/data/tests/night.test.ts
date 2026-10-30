/**
 * The night chart's reading (data/night.ts): every check of the contract, the age cap on the
 * phone, the first hour's drop and the close. Every amount is made up.
 */

import { describe, expect, it } from 'vitest';

import { nightOf, nightShows, nightUntil } from '../night';
import type { NightContext } from '../night';

const at = (iso: string): Date => new Date(iso);
const MINUTE = 60_000;
/** 9:07 PM Eastern on Monday 2026-01-26: Start 10 PM, End 7 AM Tuesday, 9 hours. */
const GENERATED = at('2026-01-27T02:07:00Z');
const CYCLE = at('2026-01-27T01:00:00Z');
const CONTEXT: NightContext = {
  day: '2026-01-27',
  timeZone: 'America/New_York',
  generatedAt: GENERATED,
  nightAt: CYCLE,
};
const NIGHT = {
  least: [0.1, 0.4, 1.0, 1.8, 2.6, 3.4, 4.0, 4.3, 4.4],
  low: 4,
  high: 6,
  heavy: [2, 5],
};

const read = (value: unknown, context: Partial<NightContext> = {}) =>
  nightOf(value, { ...CONTEXT, ...context });

describe('a night chart', () => {
  it('reads what the pipeline writes', () => {
    const night = read(NIGHT);
    expect(night).not.toBeNull();
    expect(night?.start).toEqual(at('2026-01-27T03:00:00Z'));
    expect(night?.end).toEqual(at('2026-01-27T12:00:00Z'));
    expect(night?.instants).toHaveLength(10);
    expect(night?.least).toEqual(NIGHT.least);
    expect(night?.range).toEqual({ low: 4, high: 6, tenths: false });
    expect(night?.heavy).toEqual({
      first: 2,
      last: 5,
      from: at('2026-01-27T05:00:00Z'),
      to: at('2026-01-27T08:00:00Z'),
    });
    expect(
      read({ ...NIGHT, low: 1.1, high: 1.7, least: NIGHT.least.map(() => 1.1) })?.range,
    ).toEqual({
      low: 1.1,
      high: 1.7,
      tenths: true,
    });
    expect(read({ least: NIGHT.least, low: 4, high: 6 })?.heavy).toBeNull();
  });

  it.each([
    ['a missing night', undefined],
    ['a null night', null],
    ['not an object', 'night'],
    ['least_falls', { ...NIGHT, least: [...NIGHT.least.slice(0, 8), 4.2] }],
    ['least_bound: below 0', { ...NIGHT, least: [-0.1, ...NIGHT.least.slice(1)] }],
    ['least_bound: hundredths', { ...NIGHT, least: [0.15, ...NIGHT.least.slice(1)] }],
    ['least_bound: over 99.9', { least: Array(9).fill(100), low: 99, high: 99 }],
    ['bars: too few', { ...NIGHT, least: NIGHT.least.slice(1), heavy: null }],
    ['bars: too many', { ...NIGHT, least: [0, ...NIGHT.least] }],
    ['range: low over the last bar', { ...NIGHT, low: 5 }],
    ['range: high under the last bar', { ...NIGHT, low: 4, high: 4.3 }],
    ['range: under an inch', { least: Array(9).fill(0.5), low: 0.5, high: 0.9 }],
    ['range: tenths from 2 in', { ...NIGHT, low: 4.4, high: 6 }],
    ['range: over 99', { least: Array(9).fill(99), low: 99, high: 100 }],
    ['heavy: two hours', { ...NIGHT, heavy: [2, 4] }],
    ['heavy: five hours', { ...NIGHT, heavy: [2, 7] }],
    ['heavy: past the bars', { ...NIGHT, heavy: [7, 10] }],
    ['heavy: not a pair', { ...NIGHT, heavy: [2, 5, 6] }],
    ['heavy: not whole', { ...NIGHT, heavy: [2.5, 5.5] }],
  ])('reads no chart for %s', (_what, value) => {
    expect(read(value)).toBeNull();
  });

  it('reads no chart outside its window or day', () => {
    // 6:30 AM: closed.
    expect(
      read(
        { ...NIGHT, least: [4.4], heavy: null },
        { generatedAt: at('2026-01-27T11:30:00Z'), nightAt: at('2026-01-27T10:00:00Z') },
      ),
    ).toBeNull();
    // The next day's night is not this file's.
    expect(read(NIGHT, { day: '2026-01-28' })).toBeNull();
  });

  it('reads no chart without its cycle, or from one too old or after the file', () => {
    expect(read(NIGHT, { nightAt: null })).toBeNull();
    expect(read(NIGHT, { nightAt: new Date(GENERATED.getTime() + MINUTE) })).toBeNull();
    expect(read(NIGHT, { nightAt: new Date(GENERATED.getTime() - 150 * MINUTE) })).not.toBeNull();
    expect(read(NIGHT, { nightAt: new Date(GENERATED.getTime() - 151 * MINUTE) })).toBeNull();
  });

  it('never throws, whatever it is given', () => {
    const hostile = {
      get least(): never {
        throw new Error('a getter that throws');
      },
    };
    expect(read(hostile)).toBeNull();
    expect(read(NIGHT, { timeZone: 'Not/AZone' })).toBeNull();
  });
});

describe('when a night chart shows', () => {
  const night = read(NIGHT);
  if (night === null) throw new Error('the night does not read');

  it('shows while its hourly forecast is at most 195 minutes old', () => {
    const old = read(NIGHT, { nightAt: at('2026-01-27T00:00:00Z') });
    if (old === null) throw new Error('the night does not read');
    expect(nightShows(old, new Date(old.nightAt.getTime() + 194 * MINUTE))).toBe(true);
    expect(nightShows(old, new Date(old.nightAt.getTime() + 196 * MINUTE))).toBe(false);
  });

  it('drops once its first hour is wholly past', () => {
    expect(nightShows(night, new Date(night.start.getTime() + 59 * MINUTE))).toBe(true);
    expect(nightShows(night, new Date(night.start.getTime() + 60 * MINUTE))).toBe(false);
  });

  it('drops at the close, and on another night', () => {
    const late = read(
      { ...NIGHT, least: [4.4], heavy: null },
      { generatedAt: at('2026-01-27T10:30:00Z'), nightAt: at('2026-01-27T09:00:00Z') },
    );
    if (late === null) throw new Error('the late night does not read');
    expect(nightShows(late, at('2026-01-27T10:59:00Z'))).toBe(true);
    expect(nightShows(late, at('2026-01-27T11:00:00Z'))).toBe(false);
  });
});

describe('when a night stops showing (critic r2 S4)', () => {
  it('is the moment nightShows turns false, minute by minute, for every reason it can', () => {
    const cases = [
      // 9:07 PM from the 8 PM cycle: Start's hour past at 11 PM, before the cycle's 195 min.
      read(NIGHT),
      // From a cycle 2 h old: 195 min old at 10:15 PM, before Start's hour is past.
      read(NIGHT, { nightAt: at('2026-01-27T00:07:00Z') }),
      // 5:30 AM from the 4 AM cycle: the close at 6 AM comes first.
      read(
        { ...NIGHT, least: [4.4], heavy: null },
        { generatedAt: at('2026-01-27T10:30:00Z'), nightAt: at('2026-01-27T09:00:00Z') },
      ),
    ];
    const reasons = new Set<number>();
    for (const night of cases) {
      if (night === null) throw new Error('the night does not read');
      const until = nightUntil(night).getTime();
      reasons.add(until);
      const made = night === cases[2] ? at('2026-01-27T10:30:00Z') : GENERATED;
      expect(nightShows(night, new Date(until - 1))).toBe(true);
      expect(nightShows(night, new Date(until))).toBe(false);
      for (let t = made.getTime(); t < until + 90 * MINUTE; t += MINUTE) {
        expect(nightShows(night, new Date(t))).toBe(t < until);
      }
    }
    expect([...reasons].map((t) => new Date(t).toISOString())).toEqual([
      '2026-01-27T04:00:00.000Z',
      '2026-01-27T03:22:00.001Z',
      '2026-01-27T11:00:00.000Z',
    ]);
  });
});
