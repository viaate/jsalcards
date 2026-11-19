// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { chanceFormat } from '../../copy-chance';
import type { Zones } from '../../copy-chance';
import { NO_DETAIL } from '../../data/forecast-detail';
import type { ForecastDetail, ReasonDetail, WhyDetail } from '../../data/forecast-detail';
import type { StandingFile } from '../../types/generated';
import { amountOf, pickOf, stepsView, tails, verdictOf } from '../steps';
import type { PlainWhyView, StepsInput, StepsSource } from '../steps';
import { bannedIn, measure } from './plain-reading';

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../scripts/check-copy.mjs',
);
const { problems } = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string, file?: string) => string[];
};

const NAMES = ['Tahoe-Truckee', 'Creekside Charter', 'Lake Tahoe School'];
/** The copy rules' problems with a text, a name read as "the district" (a name keeps its case). */
function rules(text: string): string[] {
  let plainText = text;
  for (const name of NAMES) plainText = plainText.replaceAll(name, 'the district');
  return problems(plainText.replace(/^the district/, 'The district'), 'src/copy-chance.ts');
}

// A made-up standing file for two districts and one private school, in the shape the pipeline
// writes (pipeline/snowlight/predict/standing.py). Every number is synthetic.
const LEVEL = { prior: 45, fit: 45, now: 45, storms: 0, q: 0.11, alpha: -0.28, tau: 1.5 };
const FILE: StandingFile = {
  schema_version: 1,
  generated_at: '2026-11-18T20:07:00Z',
  directory: { generated_on: '2026-10-24', schools: 3, districts: 2 },
  stamp: '7c4cc6e710a6',
  ref: { advisory: 4, warning: 1.4, cold: 0.3 },
  nodes: 20,
  winters: [2015, 2024],
  climate_winters: [2018, 2025],
  record_winters: [2015, 2025],
  climate_window: 'whole',
  levels: { advisory: { ...LEVEL, now: 10, prior: 10, fit: 10 }, warning: LEVEL, cold: LEVEL },
  region_delta: { advisory: [], warning: [], cold: [] },
  winter: [
    [5.7, 11.2, 0.3],
    [0, 0, 0],
  ],
  // District 0: several schools; district 1: one school, its county's middle.
  flags: [0, 1 | 4],
  usual: { advisory: [91, 120], warning: [562, 177] },
  alone: { advisory: [80, null], warning: [null, null] },
  own: { advisory: [34, 0], warning: [80, 0] },
  region: { advisory: [], warning: [], cold: [] },
  held: { advisory: [], warning: [], cold: [] },
  record: { advisory: [], warning: [[0, 3, 1, 5]], cold: [] },
  record_sum: { advisory: [495, 93, 667], warning: [1027, 10, 1071], cold: [24, 6, 32] },
  private: {
    rows: [[[5, 0, 0], 0, 0]],
    of: [0],
    record: { advisory: [], warning: [], cold: [] },
    record_sum: { advisory: [226, 0, 248], warning: [231, 0, 237], cold: [4, 0, 4] },
    held: { advisory: [], warning: [], cold: [] },
  },
} as unknown as StandingFile;

const ZONES: Zones = { school: 'America/Los_Angeles', viewer: 'America/Los_Angeles' };
const NBSP = ' ';

function detail(why: WhyDetail): ForecastDetail {
  return { ...NO_DETAIL, why };
}

function classDay(
  points: number,
  reasons: readonly ReasonDetail[],
  read: WhyDetail['read'],
  options: { of?: 'districts' | 'private_schools'; alert?: string; standing?: string } = {},
): WhyDetail {
  return {
    base: {
      kind: 'class',
      points,
      alert: options.alert ?? 'winter_storm_warning',
      standing: options.standing ?? 'usual',
      of: options.of ?? 'districts',
      borrowed: false,
      live: false,
    },
    reasons,
    read,
  } as unknown as WhyDetail;
}

function input(why: WhyDetail, chance: number, source: Partial<StepsSource> = {}): StepsInput {
  return {
    detail: detail(why),
    chance,
    day: '2026-11-19',
    district: 'Tahoe-Truckee',
    zones: ZONES,
    source: { file: FILE, unit: { kind: 'district', index: 0 }, forecastCheck: [], ...source },
    lines: why.reasons.map(() => null),
  };
}

/** Every string a view shows, folds open. */
function strings(view: PlainWhyView): string[] {
  return [
    view.title,
    ...(view.headline === null ? [] : [view.headline]),
    view.habit.title,
    view.habit.text,
    ...view.rows.flatMap((row) => [
      row.number,
      row.text,
      ...(row.parts ?? []).flatMap((part) => [part.label, part.number]),
    ]),
    ...(view.total === null ? [] : [view.total.label, view.total.text]),
  ];
}

/** Every string passes the reading test, the banned words and the house style. */
function readsPlain(view: PlainWhyView): void {
  for (const text of strings(view)) {
    const { grade, longest } = measure(text, NAMES);
    expect([text, grade === null || grade <= 6]).toEqual([text, true]);
    expect([text, longest]).toEqual([text, Math.min(longest, 15)]);
    expect([text, bannedIn(text)]).toEqual([text, []]);
    expect([text, rules(text)]).toEqual([text, []]);
  }
}

const WAIT = { fc: 0, snow: null, feels: null, ice: null, held: null } as const;
const snow = (points: number) =>
  ({
    kind: 'snow_total',
    points,
    low: null,
    high: null,
    against: 'here',
  }) as unknown as ReasonDetail;
const ice = (points: number) =>
  ({ kind: 'ice', points, inches: 0.12, at: null }) as unknown as ReasonDetail;
const cold = (points: number, feels: number) =>
  ({ kind: 'wind_chill', points, feelsLike: feels, at: null }) as unknown as ReasonDetail;

describe('the why in plain words', () => {
  it('reads a Tahoe-Truckee storm warning day: headline, habit, three rows and the total', () => {
    const read = { fc: null, snow: 4.7, feels: 12, ice: null, held: 'low' } as const;
    const view = stepsView(input(classDay(30, [snow(-9), cold(1, 12)], read), 0.22));
    expect(view).not.toBeNull();
    if (view === null) return;
    expect(view.title).toBe('Why 22%');
    expect(view.headline).toBe(
      'Tahoe-Truckee gets more storm warnings than a typical district. Places like that close less often on each one.',
    );
    expect(view.habit.title).toBe('Does Tahoe-Truckee close easily or hold out?');
    expect(view.habit.text).toBe(
      'It tends to hold out. It closes on storm warning days less often than other districts do. Our past closing lists show it on 5 storm warning days. It closed on 3, started late on 1 and stayed open on 1. Other districts closed on more than 19 in 20 of theirs. Its habit did not change today’s chance.',
    );
    expect(view.rows.map((row) => [row.key, row.number, row.parts])).toEqual([
      ['start', '45%', null],
      ['place', '−15', null],
      ['snow', '−8', null],
    ]);
    expect(view.rows[0]?.text).toBe(
      'A winter storm warning is out for Thursday. Days like that start at 45%.',
    );
    expect(view.rows[1]?.text).toBe(
      'In a winter, Tahoe-Truckee has about 11 school days with a storm warning. A typical district in the US that gets them has about 1.4 of those days. Districts with more of them close less often on each one. So the chance goes down. This is about how often storms come, not what Tahoe-Truckee did on them.',
    );
    expect(view.rows[2]?.text).toBe(
      `The forecast shows at least 4.7 inches of snow by 10${NBSP}AM. Half of Tahoe-Truckee’s schools get at least this much. About 5.6 inches is usual here on days like this. This forecast has less, so the chance goes down. At 7 AM it will feel like 12 degrees or colder. The chance cannot go lower here, so the cold does not change it.`,
    );
    expect(view.total).toEqual({ label: '= 22%', text: 'Add these up and you get 22%.' });
    readsPlain(view);
  });

  it('waits for the 9 PM forecast in one row, and says it on the evening before', () => {
    const view = stepsView(input(classDay(30, [], WAIT), 0.3));
    expect(view?.rows.at(-1)).toEqual({
      key: 'forecast',
      number: '0',
      text: 'The forecast is not in this chance yet. We add it at 9 PM Wednesday.',
      parts: null,
    });
    if (view !== null) readsPlain(view);
  });

  it('says the charter-only district and the private school by their county', () => {
    const charter = stepsView({
      ...input(classDay(57, [], WAIT), 0.57, { unit: { kind: 'district', index: 1 } }),
      district: 'Creekside Charter',
    });
    expect(charter?.rows[1]?.number).toBe('+12');
    expect(charter?.rows[1]?.text).toMatch(
      /^Creekside Charter has only charter or online schools\. So we use the districts in its county\. A typical district there has almost no school days with a storm warning\./u,
    );
    expect(charter?.headline).toBe(
      'A typical district in this school’s county gets few storm warnings. Places like that close more on each one.',
    );
    const school = stepsView({
      ...input(classDay(57, [], null, { of: 'private_schools' }), 0.57, {
        unit: { kind: 'school', index: 0 },
      }),
      district: 'Lake Tahoe School',
    });
    expect(school?.habit.title).toBe('Does this school close easily or hold out?');
    expect(school?.habit.text).toBe(
      'We do not know yet. Our past closing lists do not show what it did on a storm warning day. So its habit did not change today’s chance.',
    );
    expect(school?.rows[1]?.text).toMatch(
      /^For a private school, we use the districts in its county\./u,
    );
    expect(school?.rows[1]?.text).toMatch(/not what this school did on them\.$/u);
    expect(school?.rows.at(-1)?.text).toBe(
      'The forecast does not change a private school’s chance.',
    );
    for (const view of [charter, school]) if (view !== null) readsPlain(view);
  });

  it('falls back to the predictions file alone, and still adds up', () => {
    const read = { fc: null, snow: 8.2, feels: null, ice: null, held: null } as const;
    const view = stepsView({
      ...input(classDay(31, [snow(32)], read, { standing: 'more' }), 0.63),
      source: null,
    });
    expect(view?.rows.map((row) => row.number)).toEqual(['31%', '+32']);
    expect(view?.rows[0]?.text).toBe(
      'A winter storm warning is out for Thursday. For Tahoe-Truckee, days like that start at 31%. Tahoe-Truckee gets more storm warnings than a typical district. Places like that close less often on each one.',
    );
    expect(view?.habit.text).toBe(
      'We cannot show its habit right now. Its habit did not change today’s chance.',
    );
    expect(view?.headline).toBe(
      'The forecast has more snow than usual here, so the chance goes up.',
    );
    if (view !== null) readsPlain(view);
  });

  it('shows an ordinary day as one row equal to the chance, and its habit did not change it', () => {
    const calm = {
      base: { kind: 'similar_days', points: 1, borrowed: false, live: false },
      reasons: [],
    } as unknown as WhyDetail;
    const view = stepsView(input(calm, 0.01));
    expect(view?.rows).toEqual([
      {
        key: 'start',
        number: '1%',
        text: 'This chance comes from Tahoe-Truckee’s own past days like this. Those are days with no winter warning or advisory. Fewer than 1 in 20 of them had no school.',
        parts: null,
      },
    ]);
    expect(view?.total).toBeNull();
    expect(view?.headline).toBe(
      'No winter warning or advisory is out. Schools almost never close on days like this.',
    );
    expect(view?.habit.text).toMatch(
      /Today’s chance does not come from storm warning days, so this did not change it\.$/u,
    );
    if (view !== null) readsPlain(view);
  });

  it('shows no why where the published parts do not add to the chance', () => {
    expect(stepsView(input(classDay(30, [], WAIT), 0.31))).toBeNull();
    // A line it cannot say and no fallback.
    const timing = [{ kind: 'timing', points: 4 }] as unknown as ReasonDetail[];
    expect(stepsView(input(classDay(30, timing, { ...WAIT, fc: 6 }), 0.34))).toBeNull();
  });

  it('keeps today’s sentence for a bus hour timing day’s lines', () => {
    const view = stepsView({
      ...input(classDay(30, [snow(12), cold(2, 10)], { ...WAIT, fc: 6 }), 0.44),
      lines: ['Today’s snow sentence.', 'Today’s cold sentence.'],
    });
    expect(view?.rows.map((row) => [row.number, row.text]).slice(2)).toEqual([
      ['+12', 'Today’s snow sentence.'],
      ['+2', 'Today’s cold sentence.'],
    ]);
  });
});

describe('the habit', () => {
  /** A unit's record against others in the lists at `p` (1,000 other days). */
  const against = (closed: number, of: number, p: number) =>
    verdictOf({ closed, of }, { closed: Math.round(1000 * p) + closed, of: 1000 + of });

  it('judges a district only on 5 days or more, against the other districts', () => {
    expect(against(4, 4, 0.96)).toBeNull();
    expect(against(5, 5, 0.96)).toBe('like');
    expect(against(3, 6, 0.96)).toBe('hold');
    expect(against(12, 12, 0.74)).toBe('close');
    expect(tails(5, 5, 0.96).high).toBeCloseTo(0.96 ** 5, 10);
  });

  it('says a planted verdict in the box, then that it did not change today', () => {
    const file = {
      ...FILE,
      record: { advisory: [[0, 12, 0, 12]], warning: [], cold: [] },
      record_sum: { advisory: [752, 0, 1012], warning: [1027, 10, 1071], cold: [24, 6, 32] },
    } as unknown as StandingFile;
    const read = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
    const advisory = classDay(10, [], read, { alert: 'winter_weather_advisory' });
    const view = stepsView({ ...input(advisory, 0.1, { file }), district: 'Tahoe-Truckee' });
    expect(view?.habit.text).toBe(
      'It tends to close easily. It closes on winter advisory days more often than other districts do. Our past closing lists show it on 12 winter advisory days. It closed on all 12. Other districts closed on more than 7 in 10 of theirs. Its habit did not change today’s chance.',
    );
  });
});

describe('the habit, true to what it measures and to the base', () => {
  const { habit } = chanceFormat.plain;

  it('says a late-heavy record closes less often, never that it stays open, beside the others', () => {
    // A planted advisory record: 6 days, closed on 2, late on 4, open on none, against others
    // that closed on about 74 in 100 of theirs: P(X <= 2 | 6, 0.742) is about 0.042, so "hold".
    const file = {
      ...FILE,
      record: { advisory: [[0, 2, 4, 6]], warning: [], cold: [] },
      record_sum: { advisory: [744, 93, 1006], warning: [1027, 10, 1071], cold: [24, 6, 32] },
    } as unknown as StandingFile;
    expect(verdictOf({ closed: 2, of: 6 }, { closed: 744, of: 1006 })).toBe('hold');
    const read = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
    const advisory = classDay(10, [], read, { alert: 'winter_weather_advisory' });
    const view = stepsView(input(advisory, 0.1, { file }));
    expect(view?.habit.text).toBe(
      'It tends to hold out. It closes on winter advisory days less often than other districts do. Our past closing lists show it on 6 winter advisory days. It closed on 2 and started late on 4. Other districts closed on more than 7 in 10 of theirs. Its habit did not change today’s chance.',
    );
    if (view !== null) readsPlain(view);
  });

  it('words a verdict only as the closings it counts', () => {
    for (const k of ['warning', 'advisory', 'cold'] as const) {
      for (const peers of ['districts', 'private schools'] as const) {
        for (const verdict of [habit.holdOut(k, peers), habit.early(k, peers)]) {
          expect(verdict).toMatch(/ closes on .* (less|more) often than other /u);
          expect(verdict).not.toMatch(/stays open|stayed open/u);
        }
      }
    }
    expect(habit.others('districts', 1027, 1071)).toBe(
      'Other districts closed on more than 19 in 20 of theirs.',
    );
    expect(habit.others('districts', 20, 40)).toBe(
      'Other districts closed on about half of theirs.',
    );
    expect(habit.others('private schools', 40, 40)).toBe(
      'Other private schools closed on all of theirs.',
    );
    expect(habit.counts(2, 2, 0)).toBe('It closed on both.');
    expect(habit.counts(2, 0, 2)).toBe('It started late on both.');
  });

  /** An ordinary day's view, from a base of `kind` naming `alert` (or the weather). */
  const ordinary = (base: Record<string, unknown>, chance = 0.3) =>
    stepsView(
      input(
        {
          base: { live: false, borrowed: false, ...base, points: 30 },
          reasons: [],
        } as unknown as WhyDetail,
        chance,
      ),
    );

  it('reads an own alert base’s record of that alert, and says its own days made the chance', () => {
    for (const borrowed of [false, true]) {
      const view = ordinary({ kind: 'alert', alert: 'ice_storm_warning', borrowed });
      expect(view?.rows[0]?.text).toContain('Those are days with an ice storm warning.');
      expect(view?.habit.text).toBe(
        'Our past closing lists show it on 5 storm warning days. It closed on 3, started late on 1 and stayed open on 1. Today’s chance comes from its own past days like this, in the row below.',
      );
      if (view !== null) readsPlain(view);
    }
    // An own base of a weather: that weather's record (none here), its own days the chance.
    const own = ordinary({ kind: 'similar_days', weather: 'advisory' });
    expect(own?.habit.text).toBe(
      'We do not know yet. Today’s chance comes from its own past days like this, in the row below.',
    );
    // No standing file: only what is true without it.
    const bare = stepsView({
      ...input(
        {
          base: {
            kind: 'alert',
            points: 30,
            alert: 'winter_storm_warning',
            borrowed: false,
            live: false,
          },
          reasons: [],
        } as unknown as WhyDetail,
        0.3,
      ),
      source: null,
    });
    expect(bare?.habit.text).toBe(
      'We cannot show its habit right now. Today’s chance comes from what Tahoe-Truckee did on past days like this.',
    );
  });

  it('reads a pool’s alert record and ends as a storm day, never "does not come from storm warning days"', () => {
    for (const borrowed of [false, true]) {
      for (const alert of ['winter_storm_warning', 'ice_storm_warning', 'blizzard_warning']) {
        const view = ordinary({
          kind: 'pooled',
          scope: 'county',
          alert,
          borrowed,
          of: 'districts',
        });
        expect(view?.rows[0]?.text).toMatch(/Those are days with an? [a-z ]*warning\./u);
        expect(view?.habit.text).toContain(
          'Our past closing lists show it on 5 storm warning days.',
        );
        expect(view?.habit.text).not.toContain(habit.notToday);
        expect(view?.habit.text).toMatch(/Its habit did not change today’s chance\.$/u);
        if (view !== null) readsPlain(view);
      }
    }
    const advisory = ordinary({ kind: 'pooled', scope: 'state', alert: null, weather: 'advisory' });
    expect(advisory?.habit.text).toBe(
      'We do not know yet. Our past closing lists do not show what it did on a winter advisory day. So its habit did not change today’s chance.',
    );
  });

  it('never says a chance does not come from storm warning days beside a row that names one', () => {
    const shapes: Record<string, unknown>[] = [];
    for (const borrowed of [false, true]) {
      for (const alert of ['winter_storm_warning', 'ice_storm_warning', 'blizzard_warning', null]) {
        shapes.push({ kind: 'alert', alert: alert ?? 'winter_storm_warning', borrowed });
        shapes.push({
          kind: 'pooled',
          scope: 'nation',
          alert,
          weather: null,
          borrowed,
          of: 'districts',
        });
      }
      for (const weather of ['advisory', 'cold', 'lake_snow', 'tropical', null]) {
        shapes.push({ kind: 'similar_days', weather, borrowed });
        shapes.push({
          kind: 'pooled',
          scope: 'region',
          alert: null,
          weather,
          borrowed,
          of: 'districts',
        });
      }
      shapes.push({ kind: 'day_after', borrowed });
    }
    for (const base of shapes) {
      const view = ordinary(base);
      expect(view, JSON.stringify(base)).not.toBeNull();
      const row = view?.rows[0]?.text ?? '';
      const box = view?.habit.text ?? '';
      if (/warning|advisory/u.test(row.replace('no winter warning or advisory', ''))) {
        expect([base, box.includes(habit.notToday)]).toEqual([base, false]);
      }
      // An own base of an alert or weather made the chance: never "did not change".
      if (base.kind !== 'pooled' && (base.alert ?? base.weather ?? null) !== null) {
        expect([base, box.endsWith(habit.ownAlert)]).toEqual([base, true]);
        // It never points the chance at the class record's days, and never says it has no days
        // of the kind beside saying the chance comes from its own days.
        expect([base, /days like those|did on past (storm|winter|cold)/u.test(box)]).toEqual([
          base,
          false,
        ]);
        expect([base, box.includes('do not show what it did')]).toEqual([base, false]);
      }
      if (view !== null) readsPlain(view);
    }
  });
});

describe('the truth of every row', () => {
  // Every combination of the published parts a class day can have, through the panel's rows.
  const placements = [
    { region: [], held: [] },
    { region: [[0, -2, 0]], held: [] },
    { region: [[0, 3, 0]], held: [] },
    { region: [], held: [[0, -3, 0, 0, 1]] },
    { region: [[0, -2, 0]], held: [[0, -1, -1, 0, 3]] },
  ];
  const bases = [
    { winter: [5.7, 11.2, 0.3], points: 4 }, // more advisories than a typical district
    { winter: [1.2, 0.4, 0.1], points: 13 }, // fewer
    { winter: [4, 1.4, 0.3], points: 10 }, // the same
  ];
  const forecasts: readonly (readonly [WhyDetail['read'], readonly ReasonDetail[]])[] = [
    [WAIT, []],
    [{ ...WAIT, fc: 4 }, []],
    [{ fc: null, snow: 0, feels: null, ice: null, held: null }, []],
    [{ fc: null, snow: 0.4, feels: null, ice: null, held: 'low' }, [snow(-6)]],
    [{ fc: null, snow: 3.9, feels: 13, ice: null, held: 'high' }, [snow(20), cold(1, 13)]],
    [{ fc: null, snow: 3.9, feels: 13, ice: null, held: null }, [cold(1, 13)]],
    [{ fc: null, snow: 2, feels: -5, ice: 0.12, held: 'low' }, [snow(-4), ice(2), cold(1, -5)]],
    [{ fc: null, snow: 2, feels: 8, ice: 0.12, held: 'floor' }, [snow(-3), ice(2), cold(1, 8)]],
    [{ fc: null, snow: 6, feels: 8, ice: 0.12, held: null }, [snow(5), ice(2), cold(1, 8)]],
    [{ fc: null, snow: 6, feels: null, ice: 0.12, held: 'cap' }, [snow(5), ice(2)]],
    [{ fc: null, snow: 6, feels: 4, ice: 0, held: null }, [snow(5)]],
  ];
  const cases: {
    name: string;
    view: PlainWhyView | null;
    parts: Parameters<typeof pickOf>[0];
    f: number;
  }[] = [];
  for (const [p, placement] of placements.entries()) {
    for (const [b, base] of bases.entries()) {
      for (const [f, [read, reasons]] of forecasts.entries()) {
        const file = {
          ...FILE,
          winter: [base.winter, [0, 0, 0]],
          region: { ...FILE.region, advisory: placement.region },
          held: { ...FILE.held, advisory: placement.held },
        } as unknown as StandingFile;
        const region = placement.region[0]?.[1] ?? 0;
        const held = placement.held.reduce(
          (sum, r) => sum + (r[1] ?? 0) + (r[2] ?? 0) + (r[3] ?? 0),
          0,
        );
        const points = 10 + base.points - 10 + region + held;
        const lines = reasons.reduce((sum, r) => sum + r.points, 0);
        // A chance the pipeline could publish: a base and a total of 1% or more.
        if (points < 1 || points + lines < 1) continue;
        const chance = (points + lines) / 100;
        const why = classDay(points, reasons, read, { alert: 'winter_weather_advisory' });
        const standing = points - 10 - region - held;
        const sumOf = (kind: string) =>
          reasons.filter((r) => r.kind === kind).reduce((s, r) => s + r.points, 0);
        cases.push({
          name: `placement ${String(p)}, base ${String(b)}, forecast ${String(f)}`,
          view: stepsView(input(why, chance, { file })),
          parts: {
            standing,
            region,
            held,
            snow: sumOf('snow_total'),
            ice: sumOf('ice'),
            cold: sumOf('wind_chill'),
            saidOpen: 0,
          },
          f: base.winter[0] ?? 0,
        });
      }
    }
  }

  it.each(cases)('$name adds up, and says each part true to its sign', ({ view, parts, f }) => {
    expect(view).not.toBeNull();
    if (view === null) return;
    const percent = Number(view.title.replace(/\D/g, ''));
    expect(view.rows.reduce((sum, row) => sum + amountOf(row.number), 0)).toBe(percent);
    expect(view.total?.label).toBe(`= ${String(percent)}%`);
    expect(view.rows.length).toBeLessThanOrEqual(4);
    // Each fold's parts add to the row, and the row says each part it joins.
    for (const row of view.rows) {
      if (row.parts === null) continue;
      const last = row.parts.at(-1);
      expect(last?.number).toBe(row.number);
      const each = row.parts.slice(0, -1).reduce((sum, part) => sum + amountOf(part.number), 0);
      expect(each).toBe(amountOf(row.number));
    }
    const place = view.rows.find((row) => row.key === 'place');
    const placeSum = parts.standing + parts.region + parts.held;
    expect(place?.number).toBe(placeSum === 0 ? '0' : chanceFormat.points(placeSum));
    // "More/fewer than a typical district" follows its days against the typical's.
    if (parts.standing < 0) expect(place?.text).toContain('Districts with more of them');
    if (parts.standing > 0) expect(place?.text).toContain('Districts with fewer of them');
    if (parts.region !== 0 && parts.standing !== 0) {
      const agree = parts.standing < 0 === parts.region < 0;
      expect(place?.text).toContain(
        agree ? 'Districts in its part of the country also' : 'But districts in its part',
      );
    }
    expect(place?.text.includes('So the chance goes down.')).toBe(placeSum < 0);
    expect(place?.text.includes('So the chance goes up.')).toBe(placeSum > 0);
    // At "low", no part is said to add and no part is listed.
    const snowRow = view.rows.find((row) => row.key === 'snow');
    if (snowRow?.text.includes('cannot go lower') === true || snowRow?.text.includes('as low as')) {
      expect(snowRow.text).not.toMatch(/adds/u);
      expect(snowRow.parts).toBeNull();
    }
    // The headline names the biggest part, true to its sign.
    const pick = pickOf(parts);
    const said = view.headline ?? '';
    switch (pick) {
      case 'standing':
        expect(said).toContain(f > 4 ? 'gets more' : 'gets fewer');
        break;
      case 'region':
        expect(said).toContain(parts.region > 0 ? 'close more' : 'close less');
        break;
      case 'held':
        expect(said).toContain(parts.held > 0 ? 'goes up' : 'goes down');
        break;
      case 'snow':
        expect(said).toContain(parts.snow > 0 ? 'more snow' : 'less snow');
        break;
      case 'ice':
        expect(said).toBe(chanceFormat.plain.headline.ice);
        break;
      case 'cold':
        expect(said).toBe(chanceFormat.plain.headline.cold);
        break;
      default:
        expect(said).toMatch(/That sets this chance\.$/u);
    }
    // The habit always says whether it changed today's chance.
    expect(view.habit.text).toMatch(/did not change today’s chance\.$/u);
    readsPlain(view);
  });
});
