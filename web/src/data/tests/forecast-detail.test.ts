import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { forecastDetail, neighborsOf, NO_DETAIL } from '../forecast-detail';
import { parsePredictions } from '../school-day';

/** The pipeline's own synthetic predictions file (pipeline/tests/schemas/examples). */
const EXAMPLE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../pipeline/tests/schemas/examples/synthetic-predictions.json',
);
const at = (iso: string): Date => new Date(iso);
const GENERATED = at('2027-01-12T11:00:00Z');

type Json = Record<string, unknown>;

function example(): Json {
  return JSON.parse(readFileSync(EXAMPLE, 'utf8')) as Json;
}

/** The example's night-before forecast (district 0, the first day), a fresh copy. */
function night(): Json {
  const districts = example().districts as { days: Json[] }[];
  return districts[0]?.days[0] ?? {};
}

function morning(): Json {
  const districts = example().districts as { days: Json[] }[];
  return districts[0]?.days[1] ?? {};
}

const read = (value: Json, day = '2027-01-12') => forecastDetail(value, day, 2, GENERATED);

describe('a forecast’s chance section parts', () => {
  it('reads every part of what the pipeline writes', () => {
    expect(parsePredictions(example())).not.toBeNull();
    expect(read(night())).toEqual({
      previous: { noSchool: 0.41, at: at('2027-01-11T23:00:00Z') },
      announcesAt: at('2027-01-12T11:30:00Z'),
      busesAt: at('2027-01-12T13:00:00Z'),
      hours: {
        kind: 'snow_total',
        start: at('2027-01-12T03:00:00Z'),
        values: [0, 0, 0.2, 0.6, 1.1, 1.8, 3.3, 4.8, 6.3, 7.1, 7.5],
        range: { low: 6, high: 9 },
        heavy: { first: 6, last: 8 },
      },
      why: {
        base: { kind: 'alert', points: 30, alert: 'winter_storm_warning' },
        reasons: [
          { kind: 'snow_total', points: 14, low: 6, high: 9, overnight: true },
          { kind: 'neighbors', points: 9, districts: [1], status: 0 },
          {
            kind: 'timing',
            points: 7,
            start: at('2027-01-12T08:00:00Z'),
            end: at('2027-01-12T11:00:00Z'),
          },
          { kind: 'wind_chill', points: 5, feelsLike: -4 },
          { kind: 'snow_stops', points: -3, at: at('2027-01-12T13:00:00Z') },
        ],
      },
      record: {
        proves: 'snow_total',
        inches: 6,
        days: [
          { day: '2024-01-09', inches: 8, status: 0 },
          { day: '2025-01-06', inches: 10, status: 0 },
          { day: '2025-01-10', inches: 6, status: 0 },
          { day: '2025-02-05', inches: 6, status: 1 },
          { day: '2025-02-18', inches: 7, status: 0 },
        ],
      },
      events: [{ kind: 'snow_started', at: at('2027-01-12T05:00:00Z') }],
    });
    const next = read(morning(), '2027-01-13');
    expect(next.hours).toMatchObject({ kind: 'wind_chill', range: null, heavy: null });
    expect(next.why?.base).toEqual({ kind: 'day_after', points: 25 });
    expect(next.why?.reasons.map((reason) => reason.kind)).toEqual([
      'snow_stops',
      'cold',
      'sun',
      'icy_roads',
    ]);
    expect(next.record).toMatchObject({ proves: 'base', inches: null });
    expect(neighborsOf([1], 0, 2)).toEqual([1]);
  });

  it('reads a forecast from before the section as having none of it', () => {
    expect(read({ state: 'forecast', p_no_school: 0.3, p_delay: 0.1, reasons: [0] })).toEqual(
      NO_DETAIL,
    );
    expect(read(null as unknown as Json)).toEqual(NO_DETAIL);
  });

  it('leaves out only the part that is not what the schema says', () => {
    const cases: [string, (forecast: Json) => void, keyof typeof NO_DETAIL][] = [
      ['a chance over 1', (f) => ((f.previous as Json).p_no_school = 1.2), 'previous'],
      [
        'a run after this one',
        (f) => ((f.previous as Json).at = '2027-01-12T11:00:00Z'),
        'previous',
      ],
      [
        'a time that is not UTC',
        (f) => (f.announces_at = '2027-01-12T05:30:00-06:00'),
        'announcesAt',
      ],
      ['hours off the hour', (f) => ((f.hours as Json).start = '2027-01-12T03:30:00Z'), 'hours'],
      ['hours past the buses', (f) => (f.buses_at = '2027-01-12T12:00:00Z'), 'hours'],
      [
        'snow going down',
        (f) => ((f.hours as Json).values = [0, 1, 0.5, 1, 1, 1, 1, 1, 1, 1, 1]),
        'hours',
      ],
      [
        'a value in hundredths',
        (f) => ((f.hours as { values: number[] }).values[3] = 0.65),
        'hours',
      ],
      ['a range without the total', (f) => ((f.hours as Json).low = 8), 'hours'],
      ['half a range', (f) => ((f.hours as Json).high = null), 'hours'],
      [
        'heavy hours past the end',
        (f) => ((f.hours as Json).heavy = { first: 9, last: 11 }),
        'hours',
      ],
      [
        'heavy hours from the first',
        (f) => ((f.hours as Json).heavy = { first: 0, last: 2 }),
        'hours',
      ],
      [
        'a kind of chart there is no drawing for',
        (f) => ((f.hours as Json).kind = 'rain'),
        'hours',
      ],
      [
        'a reason of an unknown kind',
        (f) => (reasons(f)[3] = { kind: 'gossip', points: 5 }),
        'why',
      ],
      [
        'a reason without its numbers',
        (f) => (reasons(f)[3] = { kind: 'wind_chill', points: 5 }),
        'why',
      ],
      ['a reason of no points', (f) => ((reasons(f)[4] as Json).points = 0), 'why'],
      ['a reason twice', (f) => reasons(f).push(reasons(f)[3]), 'why'],
      ['a base over 100', (f) => (((f.why as Json).base as Json).points = 101), 'why'],
      [
        'an alert there are no words for',
        (f) => (((f.why as Json).base as Json).alert = 'fog'),
        'why',
      ],
      ['a neighbor not in the directory', (f) => ((reasons(f)[1] as Json).districts = [7]), 'why'],
      [
        'a timing that ends first',
        (f) => ((reasons(f)[2] as Json).end = '2027-01-12T07:00:00Z'),
        'why',
      ],
      ['record days out of order', (f) => days(f).reverse(), 'record'],
      [
        'a record day not before the day',
        (f) => ((days(f)[4] as Json).day = '2027-01-12'),
        'record',
      ],
      ['a storm smaller than counted', (f) => ((days(f)[2] as Json).inches = 5), 'record'],
      [
        'a record of storms without its inches',
        (f) => ((f.record as Json).inches = null),
        'record',
      ],
      ['a status there is no dot for', (f) => ((days(f)[0] as Json).status = 9), 'record'],
      [
        'a record under a line there is none of',
        (f) => ((f.record as Json).proves = 'gossip'),
        'record',
      ],
    ];
    for (const [what, change, part] of cases) {
      const forecast = night();
      change(forecast);
      const detail = read(forecast);
      expect(detail[part], what).toBeNull();
      // Everything else still reads.
      for (const key of Object.keys(NO_DETAIL) as (keyof typeof NO_DETAIL)[]) {
        if (key !== part) expect(detail[key], `${what}: ${key}`).not.toBeNull();
      }
      expect(detail.events, what).toHaveLength(1);
    }
  });

  it('keeps only the weather that already happened, in time order', () => {
    const forecast = night();
    forecast.events = [
      { kind: 'snow_started', at: '2027-01-12T05:00:00Z' },
      { kind: 'snow_stopped', at: '2027-01-12T04:00:00Z', inches: 1 },
      { kind: 'snow_stopped', at: '2027-01-12T10:00:00Z' },
      { kind: 'snow_stopped', at: '2027-01-12T10:30:00Z', inches: 2.5 },
      { kind: 'snow_stopped', at: '2027-01-12T12:00:00Z', inches: 3 },
      { kind: 'rain', at: '2027-01-12T06:00:00Z' },
    ];
    expect(read(forecast).events).toEqual([
      { kind: 'snow_started', at: at('2027-01-12T05:00:00Z') },
      { kind: 'snow_stopped', at: at('2027-01-12T10:30:00Z'), inches: 2.5 },
    ]);
  });

  it('reads a district’s neighbors as other districts in the directory, once each', () => {
    expect(neighborsOf([3, 1, 1, 0, 9, -1, 2.5, '4'], 0, 5)).toEqual([3, 1]);
    expect(neighborsOf(undefined, 0, 5)).toEqual([]);
    expect(neighborsOf('1,2', 0, 5)).toEqual([]);
  });
});

function reasons(forecast: Json): unknown[] {
  return (forecast.why as { reasons: unknown[] }).reasons;
}

function days(forecast: Json): unknown[] {
  return (forecast.record as { days: unknown[] }).days;
}
