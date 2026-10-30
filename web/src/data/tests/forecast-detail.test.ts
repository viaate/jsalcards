import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { forecastDetail, neighborsOf, NO_DETAIL, WEATHERS } from '../forecast-detail';
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

const read = (value: Json, day = '2027-01-12', neighbors: number[] = [1]) =>
  forecastDetail(value, {
    day,
    districts: 2,
    generatedAt: GENERATED,
    neighbors,
    timeZone: 'America/Chicago',
  });

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
        base: {
          kind: 'alert',
          points: 30,
          alert: 'winter_storm_warning',
          borrowed: false,
          live: false,
        },
        reasons: [
          {
            kind: 'snow_total',
            points: 14,
            low: 6,
            high: 9,
            overnight: true,
            against: 'storms',
            at: null,
          },
          { kind: 'neighbors', points: 9, districts: [1], status: 0 },
          {
            kind: 'timing',
            points: 7,
            start: at('2027-01-12T08:00:00Z'),
            end: at('2027-01-12T11:00:00Z'),
          },
          { kind: 'wind_chill', points: 5, feelsLike: -4, at: null },
          { kind: 'snow_stops', points: -3, at: at('2027-01-12T13:00:00Z') },
        ],
      },
      thin: false,
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
      night: null,
    });
    const next = read(morning(), '2027-01-13');
    expect(next.hours).toMatchObject({ kind: 'wind_chill', range: null, heavy: null });
    expect(next.why?.base).toEqual({ kind: 'day_after', points: 25, live: false });
    expect(next.why?.reasons.map((reason) => reason.kind)).toEqual([
      'snow_stops',
      'cold',
      'sun',
      'icy_roads',
    ]);
    expect(next.record).toMatchObject({ proves: 'base', inches: null });
    expect(neighborsOf([1], 0, 2)).toEqual([1]);
  });

  it('reads a forecast line that states no amount, as only its comparison', () => {
    // A deciding school's forecast leaves the range the line could state: no amount.
    const unstated = night();
    const lines = reasons(unstated) as Json[];
    const [snow, , , chill] = lines;
    if (snow === undefined || chill === undefined) throw new Error('the example changed');
    delete snow.low;
    delete snow.high;
    snow.overnight = false;
    delete chill.feels_like;
    expect(read(unstated).why?.reasons).toMatchObject([
      { kind: 'snow_total', low: null, high: null, overnight: false },
      { kind: 'neighbors' },
      { kind: 'timing' },
      { kind: 'wind_chill', feelsLike: null },
      { kind: 'snow_stops' },
    ]);
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
      ['a certainty', (f) => ((f.previous as Json).p_no_school = 1), 'previous'],
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
        (f) => (reasons(f)[3] = { kind: 'icy_roads', points: 5 }),
        'why',
      ],
      ['a snow line with half its range', (f) => ((reasons(f)[0] as Json).high = null), 'why'],
      [
        'a snow line with no amount said overnight',
        (f) => {
          const line = reasons(f)[0] as Json;
          delete line.low;
          delete line.high;
        },
        'why',
      ],
      [
        'a snow line weighed against days there are no words for',
        (f) => ((reasons(f)[0] as Json).against = 'lake_days'),
        'why',
      ],
      [
        'a forecast line issued at no instant',
        (f) => ((reasons(f)[3] as Json).at = 'last night'),
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
      // Each kind's points on the side its weather pushes.
      [
        'districts next door closing that take away',
        (f) => {
          reasonPoints(f, 1, -9);
        },
        'why',
      ],
      [
        'a wind chill that takes away',
        (f) => {
          reasonPoints(f, 3, -5);
        },
        'why',
      ],
      // Across parts: the timing on the chart's heaviest hours.
      [
        'a timing off the heaviest hours',
        (f) => ((reasons(f)[2] as Json).start = '2027-01-12T07:00:00Z'),
        'why',
      ],
      // The district's times on the day, in its own time zone, the announcement first.
      [
        'an announcement two evenings before',
        (f) => (f.announces_at = '2027-01-11T02:00:00Z'),
        'announcesAt',
      ],
      [
        'an announcement after the buses',
        (f) => (f.announces_at = '2027-01-12T13:30:00Z'),
        'announcesAt',
      ],
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
        // The example has no night (data/tests/night.test.ts reads them).
        if (key !== part && key !== 'night') {
          expect(detail[key], `${what}: ${key}`).not.toBeNull();
        }
      }
      expect(detail.events, what).toHaveLength(1);
    }
  });

  it('refuses a sum whose parts disagree with the rest of the forecast', () => {
    // The districts in the reason are not among the district's neighbors.
    expect(read(night(), '2027-01-12', []).why).toBeNull();
    expect(read(night(), '2027-01-12', [1]).why).not.toBeNull();
    // The next morning: sun only takes away; snow that stopped before the buses only takes away.
    const sunny = morning();
    reasonPoints(sunny, 2, 5);
    expect(read(sunny, '2027-01-13').why).toBeNull();
    const stopped = morning();
    reasonPoints(stopped, 0, 8);
    expect(read(stopped, '2027-01-13').why).toBeNull();
    expect(read(morning(), '2027-01-13').why).not.toBeNull();
    // Buses on another day than the day forecast: no bus time, and no chart that runs to it.
    const tomorrow = night();
    tomorrow.buses_at = '2027-01-13T13:00:00Z';
    expect(read(tomorrow)).toMatchObject({ busesAt: null, hours: null });
    // The evening before, in the district's own time, is its day before.
    const evening = night();
    evening.announces_at = '2027-01-12T02:00:00Z';
    expect(read(evening).announcesAt).toEqual(at('2027-01-12T02:00:00Z'));
  });

  it('reads a base pooled from the districts around a district with a short history', () => {
    const pooled = night();
    (pooled.why as Json).base = {
      kind: 'pooled',
      scope: 'county',
      points: 30,
      alert: null,
      borrowed: false,
      live: false,
    };
    expect(read(pooled).why?.base).toEqual({
      kind: 'pooled',
      scope: 'county',
      points: 30,
      alert: null,
      borrowed: false,
      live: false,
      of: 'districts',
    });
    ((pooled.why as Json).base as Json).scope = 'planet';
    expect(read(pooled).why).toBeNull();
  });

  it('reads a base pooled over private schools, and drops one over anything else', () => {
    const pooled = night();
    (pooled.why as Json).base = {
      kind: 'pooled',
      scope: 'state',
      points: 30,
      of: 'private_schools',
    };
    expect(read(pooled).why?.base).toEqual({
      kind: 'pooled',
      scope: 'state',
      points: 30,
      alert: null,
      borrowed: false,
      live: false,
      of: 'private_schools',
    });
    ((pooled.why as Json).base as Json).of = 'charters';
    expect(read(pooled).why).toBeNull();
  });

  it('reads the weather a base names its days by, and drops one it cannot say', () => {
    const pooled = night();
    (pooled.why as Json).base = {
      kind: 'pooled',
      scope: 'nation',
      points: 74,
      weather: 'advisory',
    };
    expect(read(pooled).why?.base).toEqual({
      kind: 'pooled',
      scope: 'nation',
      points: 74,
      alert: null,
      weather: 'advisory',
      borrowed: false,
      live: false,
      of: 'districts',
    });
    const own = night();
    (own.why as Json).base = { kind: 'similar_days', points: 75, weather: 'cold' };
    expect(read(own).why?.base).toEqual({
      kind: 'similar_days',
      points: 75,
      weather: 'cold',
      borrowed: false,
      live: false,
    });
    ((own.why as Json).base as Json).weather = 'sleet';
    expect(read(own).why).toBeNull();
    // A pooled base names its days by its alert or by its weather, never both.
    ((pooled.why as Json).base as Json).alert = 'winter_storm_warning';
    expect(read(pooled).why).toBeNull();
  });

  it('reads a said open line only as taking points away', () => {
    const said = night();
    (said.why as Json).base = { kind: 'pooled', scope: 'state', points: 38 };
    (said.why as Json).reasons = [{ kind: 'said_open', points: -37 }];
    expect(read(said).why?.reasons).toEqual([{ kind: 'said_open', points: -37 }]);
    ((said.why as Json).reasons as Json[])[0] = { kind: 'said_open', points: 5 };
    expect(read(said).why).toBeNull();
  });

  it('reads which recorded days a base counts, and drops a base that does not say', () => {
    const lent = night();
    (lent.why as Json).base = {
      kind: 'pooled',
      scope: 'nation',
      points: 90,
      alert: 'winter_storm_warning',
      borrowed: true,
      live: false,
    };
    expect(read(lent).why?.base).toMatchObject({ kind: 'pooled', borrowed: true, live: false });
    // A compact file leaves a false flag out: missing reads as not borrowed. A flag that is
    // there but not a boolean could name the wrong days: no why at all.
    for (const kind of ['pooled', 'alert', 'similar_days']) {
      const bare = night();
      (bare.why as Json).base = {
        kind,
        scope: 'nation',
        points: 90,
        alert: 'winter_storm_warning',
      };
      expect(read(bare).why?.base, kind).toMatchObject({ kind, borrowed: false, live: false });
      ((bare.why as Json).base as Json).borrowed = 'yes';
      expect(read(bare).why, kind).toBeNull();
    }
  });

  it('reads whether a base counts the days read live, and drops a base that does not say', () => {
    for (const base of [
      { kind: 'pooled', scope: 'nation', points: 90, alert: null, borrowed: false },
      { kind: 'alert', points: 30, alert: 'winter_storm_warning', borrowed: false },
      { kind: 'similar_days', points: 1, borrowed: true },
      { kind: 'day_after', points: 25 },
    ]) {
      const live = night();
      (live.why as Json).base = { ...base, live: true };
      expect(read(live).why?.base, base.kind).toMatchObject({ kind: base.kind, live: true });
      // A compact file leaves a false flag out: missing reads as the archive's recorded days.
      // A flag that is there but not a boolean could call days read live recorded days: no
      // why at all.
      const bare = night();
      (bare.why as Json).base = { ...base };
      expect(read(bare).why?.base, base.kind).toMatchObject({ kind: base.kind, live: false });
      ((bare.why as Json).base as Json).live = 'yes';
      expect(read(bare).why, base.kind).toBeNull();
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

/** Sets a reason's points, and the base's so the sum still makes the chance. */
function reasonPoints(forecast: Json, index: number, points: number): void {
  const reason = reasons(forecast)[index] as Json;
  const base = (forecast.why as Json).base as Json;
  base.points = (base.points as number) + (reason.points as number) - points;
  reason.points = points;
}

function days(forecast: Json): unknown[] {
  return (forecast.record as { days: unknown[] }).days;
}

describe('the weathers a base names', () => {
  it('are every value of the contract enum, and only those', () => {
    const schema = JSON.parse(
      readFileSync(
        path.resolve(
          path.dirname(fileURLToPath(import.meta.url)),
          '../../../../schemas/predictions.schema.json',
        ),
        'utf8',
      ),
    ) as { $defs: { CountedWeather: { enum: string[] } } };
    expect([...WEATHERS].sort()).toEqual([...schema.$defs.CountedWeather.enum].sort());
  });
});

describe('few local records', () => {
  /** A forecast whose base is the nation's record, as a thin pass writes it. */
  function nation(base: Json): Json {
    return {
      state: 'forecast',
      p_no_school: 0.74,
      p_delay: 0.01,
      reasons: [],
      why: { base: { kind: 'pooled', scope: 'nation', points: 74, ...base } },
    };
  }

  it('reads the flag from a nation base over recorded days', () => {
    const thin = read(nation({ thin: true, weather: 'advisory' }));
    expect(thin.thin).toBe(true);
    // The sum reads as before, with its weather name.
    expect(thin.why?.base).toMatchObject({ kind: 'pooled', scope: 'nation', weather: 'advisory' });
  });

  it('reads no flag where the file does not set it, as an old file does', () => {
    expect(read(nation({})).thin).toBe(false);
    expect(read(nation({ thin: false })).thin).toBe(false);
    expect(read(night()).thin).toBe(false);
    expect(NO_DETAIL.thin).toBe(false);
  });

  it('reads no flag on a base the contract never sets it on, or one that is not true', () => {
    expect(read(nation({ thin: true, scope: 'state' })).thin).toBe(false);
    expect(read(nation({ thin: true, live: true })).thin).toBe(false);
    expect(read(nation({ thin: 'yes' })).thin).toBe(false);
    expect(read(nation({ thin: 1 })).thin).toBe(false);
    const own = { ...night(), why: { base: { kind: 'similar_days', points: 30, thin: true } } };
    expect(read(own).thin).toBe(false);
  });

  it('holds where the sum’s other parts do not read', () => {
    const broken = nation({ thin: true });
    (broken.why as Json).reasons = [{ kind: 'not_a_reason', points: 3 }];
    const found = read(broken);
    expect(found.why).toBeNull();
    expect(found.thin).toBe(true);
  });
});
