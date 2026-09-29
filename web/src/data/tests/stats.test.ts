import { describe, expect, it } from 'vitest';

import { parseSeasonStats, parseTrackRecord } from '../stats';

/** A season file in the published shape, made up for these tests. */
function season(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: 1,
    generated_at: '2026-01-13T12:00:00Z',
    season: '2025-2026',
    through: '2026-01-13',
    days: [
      ['2026-01-05', 10, 4, 0, 1],
      ['2026-01-12', 30, 6, 2, 0],
    ],
    states: [
      ['IA', 15, 4, 0, 1],
      ['MO', 25, 6, 2, 0],
    ],
    schools: 41,
    districts: 9,
    ...overrides,
  };
}

/** Bins from 0 to 100 in tens, from [forecasts, outcomes] pairs. */
function calibration(pairs: readonly (readonly [number, number])[]): Record<string, unknown> {
  const bins = pairs.map(([forecasts, outcomes], n) => [n * 10, (n + 1) * 10, forecasts, outcomes]);
  return {
    forecasts: pairs.reduce((sum, [forecasts]) => sum + forecasts, 0),
    outcomes: pairs.reduce((sum, [, outcomes]) => sum + outcomes, 0),
    bins,
  };
}

const NONE = calibration(Array.from({ length: 10 }, () => [0, 0] as const));
const SCORED = calibration([
  [40, 1],
  [12, 2],
  [0, 0],
  [0, 0],
  [5, 2],
  [0, 0],
  [0, 0],
  [3, 2],
  [0, 0],
  [4, 4],
]);

/** A track record in the published shape, made up for these tests. */
function record(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: 1,
    generated_at: '2026-01-13T12:00:00Z',
    first_day: '2025-12-01',
    last_day: '2026-01-13',
    leads: [
      { lead_days: 0, no_school: SCORED, delay: NONE },
      { lead_days: 1, no_school: SCORED, delay: SCORED },
    ],
    ...overrides,
  };
}

describe('parseSeasonStats', () => {
  it('reads a season whose days and states add up', () => {
    const read = parseSeasonStats(season());
    expect(read?.season).toBe('2025-2026');
    expect(read?.days).toHaveLength(2);
    expect(read?.schools).toBe(41);
  });

  it('reads a season with nothing counted yet', () => {
    const read = parseSeasonStats(season({ days: [], states: [], schools: 0, districts: 0 }));
    expect(read?.days).toEqual([]);
  });

  it.each([
    ['another version', { schema_version: 2 }],
    ['no generated_at', { generated_at: '2026-01-13' }],
    ['a season that is not a school year', { season: '2025-2027' }],
    ['a last day outside the season', { through: '2026-07-01' }],
    ['a last day that is no day', { through: '2026-02-30' }],
    [
      'a day after the last day counted',
      {
        through: '2026-01-06',
        days: [
          ['2026-01-05', 10, 4, 0, 1],
          ['2026-01-12', 30, 6, 2, 0],
        ],
      },
    ],
    [
      'days out of order',
      {
        days: [
          ['2026-01-12', 30, 6, 2, 0],
          ['2026-01-05', 10, 4, 0, 1],
        ],
      },
    ],
    [
      'a day listed with no school',
      {
        days: [
          ['2026-01-05', 0, 0, 0, 0],
          ['2026-01-12', 40, 10, 2, 1],
        ],
      },
    ],
    [
      'states out of order',
      {
        states: [
          ['MO', 25, 6, 2, 0],
          ['IA', 15, 4, 0, 1],
        ],
      },
    ],
    [
      'states that do not add up to the days',
      {
        states: [
          ['IA', 15, 4, 0, 1],
          ['MO', 25, 6, 2, 1],
        ],
      },
    ],
    [
      'a state that is no state code',
      {
        states: [
          ['Iowa', 15, 4, 0, 1],
          ['MO', 25, 6, 2, 0],
        ],
      },
    ],
    ['more schools than school-days', { schools: 60 }],
    ['schools without school-days', { days: [], states: [], schools: 3, districts: 0 }],
    ['more districts than schools', { districts: 42 }],
    ['a count that is not whole', { schools: 4.5 }],
    ['a row of the wrong length', { days: [['2026-01-05', 10, 4, 0]] }],
  ])('refuses %s', (_what, overrides) => {
    expect(parseSeasonStats(season(overrides))).toBeNull();
  });

  it('refuses anything that is not a season file', () => {
    for (const value of [null, 'season', 3, [], {}]) expect(parseSeasonStats(value)).toBeNull();
  });
});

describe('parseTrackRecord', () => {
  it('reads a scored record', () => {
    const read = parseTrackRecord(record());
    expect(read?.first_day).toBe('2025-12-01');
    expect(read?.leads.map((lead) => lead.lead_days)).toEqual([0, 1]);
    expect(read?.leads[0]?.no_school.forecasts).toBe(64);
  });

  it('reads a record with no day scored yet', () => {
    const read = parseTrackRecord(
      record({
        first_day: null,
        last_day: null,
        leads: [{ lead_days: 0, no_school: NONE, delay: NONE }],
      }),
    );
    expect(read?.first_day).toBeNull();
  });

  const gap = { ...SCORED, bins: (SCORED.bins as number[][]).filter((_, n) => n !== 3) };
  const past = { ...SCORED, forecasts: 65 };
  const tooMany = calibration([[1, 2], ...Array.from({ length: 9 }, () => [0, 0] as const)]);

  it.each([
    ['another version', { schema_version: 2 }],
    ['days scored without a span', { first_day: null, last_day: null }],
    ['a span with nothing scored', { leads: [{ lead_days: 0, no_school: NONE, delay: NONE }] }],
    ['one end of a span', { last_day: null }],
    ['a span that runs backwards', { first_day: '2026-02-01' }],
    ['a first day that is no day', { first_day: '2025-11-31' }],
    [
      'leads out of order',
      {
        leads: [
          { lead_days: 1, no_school: SCORED, delay: NONE },
          { lead_days: 0, no_school: SCORED, delay: NONE },
        ],
      },
    ],
    [
      'a lead given twice',
      {
        leads: [
          { lead_days: 0, no_school: SCORED, delay: NONE },
          { lead_days: 0, no_school: SCORED, delay: NONE },
        ],
      },
    ],
    ['a lead too far ahead', { leads: [{ lead_days: 3, no_school: SCORED, delay: NONE }] }],
    ['bins with a gap', { leads: [{ lead_days: 0, no_school: gap, delay: NONE }] }],
    [
      'a total that is not the bins’ sum',
      { leads: [{ lead_days: 0, no_school: past, delay: NONE }] },
    ],
    [
      'more outcomes than forecasts',
      { leads: [{ lead_days: 0, no_school: tooMany, delay: NONE }] },
    ],
    ['a lead without its delay record', { leads: [{ lead_days: 0, no_school: SCORED }] }],
  ])('refuses %s', (_what, overrides) => {
    expect(parseTrackRecord(record(overrides))).toBeNull();
  });

  it('refuses anything that is not a track record', () => {
    for (const value of [null, 'record', 3, [], {}]) expect(parseTrackRecord(value)).toBeNull();
  });
});
