// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { chanceFormat } from '../../copy-chance';
import type { Zones } from '../../copy-chance';
import { NO_DETAIL } from '../../data/forecast-detail';
import type { ForecastDetail, ReasonDetail, WhyDetail } from '../../data/forecast-detail';
import type { StandingFile } from '../../types/generated';
import { HABIT_MIN_SCHOOL, amountOf, pickOf, stepsView, tails, verdictOf } from '../steps';
import type { HabitView, PlainWhyView, StepsInput, StepsSource } from '../steps';
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

/** Every sentence a view shows, folds open. */
function strings(view: PlainWhyView): string[] {
  return [
    ...(view.headline === null ? [] : [view.headline]),
    ...[view.habit.lead, view.habit.text, view.habit.end, view.still].filter(
      (text): text is string => text !== null,
    ),
    ...view.rows.flatMap((row) => (row.text === '' ? [] : [row.text])),
  ];
}

/** Every label a view shows: its titles, amounts and keys, short noun phrases with no period. */
function labels(view: PlainWhyView): string[] {
  return [
    view.title,
    view.habit.title,
    ...view.habit.key.map((item) => item.label),
    ...view.rows.flatMap((row) => [
      row.number,
      row.title,
      ...(row.parts ?? []).flatMap((part) => [part.label, part.number]),
    ]),
    view.total.label,
    view.total.number,
  ];
}

/** Every sentence passes the reading test, the banned words and the house style; every label
 * (a title has no sentence for the grade to read) is short, banned-word free and in the style. */
function readsPlain(view: PlainWhyView): void {
  for (const text of strings(view)) {
    const { grade, longest } = measure(text, NAMES);
    expect([text, grade === null || grade <= 6]).toEqual([text, true]);
    expect([text, longest]).toEqual([text, Math.min(longest, 15)]);
    expect([text, bannedIn(text)]).toEqual([text, []]);
    expect([text, rules(text)]).toEqual([text, []]);
    expect(text).not.toMatch(/like most/u);
  }
  for (const text of labels(view)) {
    expect([text, text.split(/\s+/u).length <= 9, /[.!?]$/u.test(text)]).toEqual([
      text,
      true,
      false,
    ]);
    expect([text, bannedIn(text)]).toEqual([text, []]);
    expect([text, rules(text)]).toEqual([text, []]);
  }
}

/** No two rows in one panel start with the same three words (WHY-V2 V2). */
function expectNoTwoAlike(view: PlainWhyView): void {
  const starts = view.rows.map((row) =>
    row.title.split(/\s+/u).slice(0, 3).join(' ').toLowerCase(),
  );
  expect(new Set(starts).size).toBe(starts.length);
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
  it('reads a Tahoe-Truckee storm warning day as the build-up: the start, two rows, the total and its past days', () => {
    const read = { fc: null, snow: 4.7, feels: 12, ice: null, held: 'low' } as const;
    const view = stepsView(input(classDay(30, [snow(-9), cold(1, 12)], read), 0.22));
    expect(view).not.toBeNull();
    if (view === null) return;
    expect(view.title).toBe('Why 22%');
    expect(view.headline).toBe(
      'Tahoe-Truckee gets more storm warnings than a typical district. Places like that close less often on each one.',
    );
    expect(view.rows.map((row) => [row.key, row.number, row.points, row.title, row.parts])).toEqual(
      [
        ['start', '45%', 45, 'Winter storm warning', null],
        ['place', '−15', -15, 'Storm warnings are common here', null],
        ['snow', '−8', -8, `About 4.7 inches of snow by 10${NBSP}AM`, null],
      ],
    );
    expect(view.rows[0]?.text).toBe('Every storm warning day starts here.');
    // The hero already says why, so the place row does not say it again.
    expect(view.rows[1]?.text).toBe('About 11 a winter. That is 8 times a typical district.');
    expect(view.rows[2]?.text).toBe(
      'About 1 inch less than usual here. At 7 AM it will feel like 12 degrees or colder. The chance cannot go lower here, so the cold does not change it.',
    );
    expect(view.still).toBeNull();
    expect(view.total).toEqual({ label: 'All together', number: '22%' });
    expect(view.habit).toEqual({
      title: 'Tahoe-Truckee’s past storm warning days',
      days: null,
      key: [],
      lead: null,
      text: 'Closed on 3 of 5 in past closing lists. Those lists show mostly days off.',
      end: 'This does not change Thursday’s 22% yet.',
    });
    readsPlain(view);
  });

  it('says "today’s" only when the chance is for today (WHY-V2 V3)', () => {
    const read = { fc: null, snow: 4.7, feels: 12, ice: null, held: 'low' } as const;
    const why = classDay(30, [snow(-9), cold(1, 12)], read);
    expect(stepsView({ ...input(why, 0.22), today: true })?.habit.end).toBe(
      'This does not change today’s 22% yet.',
    );
    expect(stepsView({ ...input(why, 0.22), today: false })?.habit.end).toBe(
      'This does not change Thursday’s 22% yet.',
    );
  });

  it('waits for the 9 PM forecast in the quiet line, never a row, and says it on the evening before', () => {
    const view = stepsView(input(classDay(30, [], WAIT), 0.3));
    expect(view?.rows.map((row) => row.key)).toEqual(['start', 'place']);
    expect(view?.still).toBe(
      'The forecast is not in this chance yet. We add it at 9 PM Wednesday.',
    );
    if (view !== null) readsPlain(view);
  });

  it('says the charter-only district and the private school by their county', () => {
    const charter = stepsView({
      ...input(classDay(57, [], WAIT), 0.57, { unit: { kind: 'district', index: 1 } }),
      district: 'Creekside Charter',
    });
    expect(charter?.rows[1]?.number).toBe('+12');
    expect(charter?.rows[1]?.title).toBe('Storm warnings are rare here');
    expect(charter?.rows[1]?.text).toBe(
      'Creekside Charter has only charter or online schools. So we use the districts in its county. Almost none a winter. It is 1.4 in a typical district.',
    );
    expect(charter?.headline).toBe(
      'A typical district in this school’s county gets few storm warnings. Places like that close more on each one.',
    );
    expect(charter?.habit.text).toBe('None on file yet.');
    expect(charter?.habit.end).toBeNull();
    const school = stepsView({
      ...input(classDay(57, [], null, { of: 'private_schools' }), 0.57, {
        unit: { kind: 'school', index: 0 },
      }),
      district: 'Lake Tahoe School',
    });
    expect(school?.habit.title).toBe('Lake Tahoe School’s past storm warning days');
    expect(school?.habit.text).toBe('None on file yet.');
    expect(school?.rows[1]?.text).toMatch(
      /^For a private school, we use the districts in its county\./u,
    );
    expect(school?.rows.map((row) => row.key)).toEqual(['start', 'place']);
    expect(school?.still).toBe('The forecast does not change a private school’s chance.');
    for (const view of [charter, school]) if (view !== null) readsPlain(view);
  });

  it('falls back to the predictions file alone, and still adds up', () => {
    const read = { fc: null, snow: 8.2, feels: null, ice: null, held: null } as const;
    const view = stepsView({
      ...input(classDay(31, [snow(32)], read, { standing: 'more' }), 0.63),
      source: null,
    });
    expect(view?.rows.map((row) => row.number)).toEqual(['31%', '+32']);
    expect(view?.rows.map((row) => row.title)).toEqual([
      'Winter storm warning',
      `About 8.2 inches of snow by 10${NBSP}AM`,
    ]);
    expect(view?.rows[0]?.text).toBe(
      'A winter storm warning is out for Thursday. For Tahoe-Truckee, days like that start at 31%. Tahoe-Truckee gets more storm warnings than a typical district. Places like that close less often on each one.',
    );
    expect(view?.habit.text).toBe('We cannot show its past days right now.');
    expect(view?.habit.end).toBe('This does not change Thursday’s 63% yet.');
    expect(view?.headline).toBe(
      'The forecast has more snow than usual here, so the chance goes up.',
    );
    if (view !== null) readsPlain(view);
  });

  it('shows an ordinary day as its start, said once in all, and says its past days did not change it', () => {
    const calm = {
      base: { kind: 'similar_days', points: 1, borrowed: false, live: false },
      reasons: [],
    } as unknown as WhyDetail;
    const view = stepsView(input(calm, 0.01));
    expect(view?.rows).toEqual([
      {
        key: 'start',
        number: '1%',
        points: 1,
        title: 'No winter alert',
        text: 'This chance comes from Tahoe-Truckee’s own past days like this. Fewer than 1 in 20 of them had no school.',
        parts: null,
      },
    ]);
    expect(view?.total).toEqual({ label: 'All together', number: '1%' });
    expect(view?.headline).toBe(
      'No winter warning or advisory is out. Schools almost never close on days like this.',
    );
    expect(view?.habit.end).toBe('Thursday’s 1% does not come from storm warning days.');
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
    expect(view?.rows.map((row) => [row.number, row.title, row.text]).slice(2)).toEqual([
      ['+12', 'Snow', 'Today’s snow sentence.'],
      ['+2', 'Wind chill at the bus stop', 'Today’s cold sentence.'],
    ]);
  });
});

describe('the habit', () => {
  it('judges a complete record only on 5 days or more, against the districts near it', () => {
    expect(verdictOf({ closed: 4, of: 4 }, 0.96)).toBeNull();
    expect(verdictOf({ closed: 5, of: 5 }, 0.96)).toBe('like');
    expect(verdictOf({ closed: 3, of: 6 }, 0.96)).toBe('hold');
    expect(verdictOf({ closed: 12, of: 12 }, 0.74)).toBe('close');
    expect(verdictOf({ closed: 8, of: 11 }, 0.433)).toBe('close');
    expect(tails(5, 5, 0.96).high).toBeCloseTo(0.96 ** 5, 10);
    // one day with school when 99.7% of the districts near it had none: never "holds out", and
    // never "about like most" either (the test said it is not), so no verdict
    expect(tails(7, 6, 0.997).low).toBeLessThan(0.05);
    expect(HABIT_MIN_SCHOOL).toBe(2);
    expect(verdictOf({ closed: 6, of: 7 }, 0.997)).toBeNull();
    expect(verdictOf({ closed: 5, of: 7 }, 0.997)).toBe('hold');
  });

  it('never judges a closings-only record from the lists, however many days', () => {
    const file = {
      ...FILE,
      record: { advisory: [[0, 12, 0, 12]], warning: [], cold: [] },
      record_sum: { advisory: [752, 0, 1012], warning: [1027, 10, 1071], cold: [24, 6, 32] },
    } as unknown as StandingFile;
    const read = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
    const advisory = classDay(10, [], read, { alert: 'winter_weather_advisory' });
    const view = stepsView({ ...input(advisory, 0.1, { file }), district: 'Tahoe-Truckee' });
    expect(view?.habit).toEqual({
      title: 'Tahoe-Truckee’s past winter advisory days',
      days: null,
      key: [],
      lead: null,
      text: 'Closed on 12 of 12 in past closing lists. Those lists show mostly days off.',
      end: 'This does not change Thursday’s 10% yet.',
    });
  });
});

describe('the habit, true to what it measures and to the base', () => {
  it('says a late-heavy closings-only record as the lists show it, with no verdict', () => {
    const file = {
      ...FILE,
      record: { advisory: [[0, 2, 4, 6]], warning: [], cold: [] },
      record_sum: { advisory: [744, 93, 1006], warning: [1027, 10, 1071], cold: [24, 6, 32] },
    } as unknown as StandingFile;
    const read = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
    const advisory = classDay(10, [], read, { alert: 'winter_weather_advisory' });
    const view = stepsView(input(advisory, 0.1, { file }));
    expect(view?.habit.text).toBe(
      'Closed on 2 of 6 in past closing lists. Those lists show mostly days off.',
    );
    expect(view?.habit.lead).toBeNull();
    if (view !== null) readsPlain(view);
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

  it('reads an own alert base’s record of that alert, and says its own days made the chance once, in the start row', () => {
    for (const borrowed of [false, true]) {
      const view = ordinary({ kind: 'alert', alert: 'ice_storm_warning', borrowed });
      expect(view?.rows[0]?.title).toBe('Ice storm warning');
      // The title names the alert, so the line does not say it again.
      expect(view?.rows[0]?.text).not.toContain('Those are days with');
      expect(view?.habit.text).toBe(
        'Closed on 3 of 5 in past closing lists. Those lists show mostly days off.',
      );
      expect(view?.rows[0]?.text).toContain('This chance comes from Tahoe-Truckee’s own past days');
      expect(view?.habit.end).toBeNull();
      if (view !== null) readsPlain(view);
    }
    // An own base of a weather with no record of it: its own days made the chance, so the box
    // says only that it cannot show them, never "None on file yet." (B1).
    const own = ordinary({ kind: 'similar_days', weather: 'advisory' });
    expect([own?.habit.text, own?.habit.end]).toEqual(['We cannot show them here yet.', null]);
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
    expect([bare?.habit.text, bare?.habit.end]).toEqual([
      'We cannot show its past days right now.',
      null,
    ]);
    expect(bare?.rows[0]?.text).toContain('This chance comes from Tahoe-Truckee’s own past days');
  });

  it('never says "None on file yet." beside a start row that says its own past days made the chance (B1)', () => {
    const empty = { advisory: [], warning: [], cold: [] };
    const files = [
      { ...FILE, record: empty },
      {
        ...FILE,
        record: { advisory: [[0, 0, 0, 0]], warning: [[0, 0, 0, 0]], cold: [[0, 0, 0, 0]] },
      },
      FILE,
    ] as unknown as StandingFile[];
    const bases: Record<string, unknown>[] = [];
    for (const borrowed of [false, true]) {
      for (const alert of [
        'winter_storm_warning',
        'ice_storm_warning',
        'blizzard_warning',
        'winter_weather_advisory',
        'extreme_cold_warning',
      ]) {
        bases.push({ kind: 'alert', alert, borrowed });
        bases.push({ kind: 'pooled', scope: 'county', alert, borrowed, of: 'districts' });
      }
      for (const weather of ['advisory', 'cold', 'lake_snow', null]) {
        bases.push({ kind: 'similar_days', weather, borrowed });
      }
      bases.push({ kind: 'day_after' });
    }
    let own = 0;
    for (const file of files) {
      for (const base of bases) {
        const view = stepsView(
          input(
            {
              base: { live: false, borrowed: false, ...base, points: 30 },
              reasons: [],
            } as unknown as WhyDetail,
            0.3,
            { file },
          ),
        );
        if (view === null) continue;
        // Its own past days of the kind the box shows (an alert or a weather) made the chance.
        const named = (base.alert ?? base.weather ?? null) !== null;
        const fromOwn =
          named && base.kind !== 'pooled' && (view.rows[0]?.text ?? '').includes('own past days');
        if (fromOwn) own += 1;
        expect([base, fromOwn && view.habit.text === 'None on file yet.']).toEqual([base, false]);
        expect([base, fromOwn && /none|no days/iu.test(view.habit.text ?? '')]).toEqual([
          base,
          false,
        ]);
      }
    }
    expect(own).toBeGreaterThan(10);
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
        expect(view?.rows[0]?.title).toMatch(/warning$/u);
        expect(view?.rows[0]?.text).not.toContain('Those are days with');
        expect(view?.habit.title).toBe('Tahoe-Truckee’s past storm warning days');
        expect(view?.habit.text).toBe(
          'Closed on 3 of 5 in past closing lists. Those lists show mostly days off.',
        );
        expect(view?.habit.end).toBe('This does not change Thursday’s 30% yet.');
        if (view !== null) readsPlain(view);
      }
    }
    const advisory = ordinary({ kind: 'pooled', scope: 'state', alert: null, weather: 'advisory' });
    expect([advisory?.habit.title, advisory?.habit.text, advisory?.habit.end]).toEqual([
      'Tahoe-Truckee’s past winter advisory days',
      'None on file yet.',
      null,
    ]);
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
      const end = view?.habit.end ?? '';
      if (/warning|advisory/u.test(row.replace('no winter warning or advisory', ''))) {
        expect([base, end.includes('does not come from storm warning days')]).toEqual([
          base,
          false,
        ]);
      }
      // An own base of an alert or weather made the chance: never "does not change", and its
      // start row says so, so the box ends on nothing (said once).
      if (base.kind !== 'pooled' && (base.alert ?? base.weather ?? null) !== null) {
        expect([base, row.startsWith('This chance comes from'), end]).toEqual([base, true, '']);
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
    s: number | null;
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
          s: read?.snow ?? null,
        });
      }
    }
  }

  it.each(cases)('$name adds up, and says each part true to its sign', ({ view, parts, f, s }) => {
    expect(view).not.toBeNull();
    if (view === null) return;
    const percent = Number(view.title.replace(/\D/g, ''));
    expect(view.rows.reduce((sum, row) => sum + amountOf(row.number), 0)).toBe(percent);
    expect(view.rows.map((row) => row.points)).toEqual(
      view.rows.map((row) => amountOf(row.number)),
    );
    expect(view.total).toEqual({ label: 'All together', number: `${String(percent)}%` });
    expect(view.rows[0]?.key).toBe('start');
    expect(view.rows.length).toBeLessThanOrEqual(7);
    expectNoTwoAlike(view);
    // No row for a part that did not move the chance (a joined row's parts count).
    for (const row of view.rows.slice(1)) {
      const moved = row.points !== 0 || (row.parts ?? []).some((part) => amountOf(part.number));
      expect([row.key, moved]).toEqual([row.key, true]);
    }
    // Each fold's parts add to the row, and the row says each part it joins.
    for (const row of view.rows) {
      if (row.parts === null) continue;
      const last = row.parts.at(-1);
      expect(last?.number).toBe(row.number);
      const each = row.parts.slice(0, -1).reduce((sum, part) => sum + amountOf(part.number), 0);
      expect(each).toBe(amountOf(row.number));
    }
    // The place's parts, each its own row only where it moved the chance (COPY-RULES 1), so
    // each title agrees with its own sign (S2).
    const place = view.rows.find((row) => row.key === 'place');
    const region = view.rows.find((row) => row.key === 'region');
    const held = view.rows.find((row) => row.key === 'held');
    expect([place !== undefined, region !== undefined, held !== undefined]).toEqual([
      parts.standing !== 0,
      parts.region !== 0,
      parts.held !== 0,
    ]);
    if (place !== undefined) {
      expect(place.number).toBe(chanceFormat.points(parts.standing));
      // The title follows its days against the typical district's, which its sign agrees with.
      expect(place.title).toMatch(
        f > 4 ? / (are common|come more often) here$/u : / (are rare|come less often) here$/u,
      );
      expect(parts.standing < 0).toBe(f > 4);
      expect(place.text).not.toMatch(/part of the country|normal range/u);
    }
    if (region !== undefined) {
      expect(region.number).toBe(chanceFormat.points(parts.region));
      expect(region.title).toBe(chanceFormat.plain.build.regionTitle);
      expect(region.text).toBe(
        `Districts in its part of the country close ${parts.region < 0 ? 'less' : 'more'} on these days.`,
      );
    }
    if (held !== undefined) {
      expect(held.number).toBe(chanceFormat.points(parts.held));
      expect(held.text.endsWith(parts.held < 0 ? 'goes down.' : 'goes up.')).toBe(true);
    }
    if (parts.standing === 0) {
      // How often they come, checked and 0: the quiet line says it.
      expect(view.still).toMatch(
        /^(There is no change|No change) from how often winter advisories come here[.,]/u,
      );
    }
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
      case 'snow': {
        // "More snow" or "less snow" only where the amounts as shown agree (LR-V5): the floored
        // snow against district 0's usual of 0.91, shown as 0.9.
        const shown = Math.floor((s ?? 0) * 10 + 1e-9);
        const agrees = s === null || (parts.snow > 0 ? shown > 9 : shown < 9);
        if (agrees) expect(said).toContain(parts.snow > 0 ? 'more snow' : 'less snow');
        else
          expect(said).toBe(
            chanceFormat.plain.headline.parts('winter_weather_advisory', 'Thursday'),
          );
        break;
      }
      case 'ice':
        expect(said).toBe(chanceFormat.plain.headline.ice);
        break;
      case 'cold':
        expect(said).toBe(chanceFormat.plain.headline.cold);
        break;
      default:
        // The start sets it only when it is the whole chance (LR-V2).
        expect(said).toMatch(
          view.rows.length === 1 ? /That sets this chance\.$/u : /The parts below add up/u,
        );
    }
    // No record of the kind here: only that, and never "like most".
    expect([view.habit.text, view.habit.end]).toEqual(['None on file yet.', null]);
    readsPlain(view);
  });
});

describe('the build-up says nothing false at its edges (WHY-V2 r2)', () => {
  const { build, headline } = chanceFormat.plain;
  const calm = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
  const viewOf = (winter: readonly number[], points: number, read: WhyDetail['read']) => {
    const file = { ...FILE, winter: [winter, [0, 0, 0]] } as unknown as StandingFile;
    const why = classDay(points, [], read, { alert: 'winter_weather_advisory' });
    return stepsView(input(why, points / 100, { file }));
  };

  it('says "half" at exactly half a typical district, never "under half" (B1)', () => {
    // 2 advisories a winter against a typical 4: 118 published districts.
    const view = viewOf([2, 0.7, 0.1], 13, calm);
    const place = view?.rows.find((row) => row.key === 'place');
    expect(place?.text).toContain('About 2 a winter. That is half a typical district.');
    expect(place?.text).not.toContain('under half');
    expect(place?.title).toBe('Winter advisories are rare here');
  });

  it('never says the alert sets the chance when how often they come moved it, against its side (S2)', () => {
    // Fewer advisories than a typical district, yet the part takes 3 away: its sign disagrees.
    const view = viewOf([1.2, 0.4, 0.1], 7, calm);
    const place = view?.rows.find((row) => row.key === 'place');
    expect(place?.number).toBe(chanceFormat.points(-3));
    expect(view?.headline).toBe(headline.parts('winter_weather_advisory', 'Thursday'));
    expect(view?.headline).not.toMatch(/sets this chance/u);
  });

  it('names the ice and cold that joined a folded snow row in the quiet line (S5)', () => {
    const read = { fc: null, snow: 1, feels: 20, ice: 0.05, held: null } as const;
    const view = viewOf([4, 1.4, 0.3], 10, read);
    expect(view?.rows.map((row) => row.key)).toEqual(['start']);
    expect(view?.still).toBe(build.still('advisory', true, 'usual', 'both'));
    expect(view?.still).toMatch(/the snow, ice or cold\./u);
    const iceOnly = viewOf([4, 1.4, 0.3], 10, { ...read, feels: null });
    expect(iceOnly?.still).toMatch(/No change from the snow or ice\./u);
  });

  it('says the snow before the ice and cold that joined its row, its fold under its bar (look S3)', () => {
    const read = { fc: null, snow: 3.9, feels: 13, ice: 0.12, held: 'high' } as const;
    const file = {
      ...FILE,
      winter: [
        [4, 1.4, 0.3],
        [0, 0, 0],
      ],
    } as unknown as StandingFile;
    const why = classDay(10, [snow(9), ice(2), cold(1, 13)], read, {
      alert: 'winter_weather_advisory',
    });
    const view = stepsView(input(why, 0.22, { file }));
    const text = view?.rows.find((row) => row.key === 'snow')?.text ?? '';
    const at = (part: string) => text.indexOf(part);
    expect(at('Each extra inch')).toBeGreaterThanOrEqual(0);
    expect(at('Each extra inch')).toBeLessThan(at('The forecast also shows'));
    expect(at('The forecast also shows')).toBeLessThan(at('Ice adds'));
  });
});

describe('the hero and the rows say what moved the chance (WHY-V2 r3, LR-V2 and LR-V6)', () => {
  const { build, headline, row } = chanceFormat.plain;
  // How often advisories come here matches a typical district, so the place part is 0.
  const file = {
    ...FILE,
    winter: [
      [4, 1.4, 0.3],
      [0, 0, 0],
    ],
  } as unknown as StandingFile;
  const advisory = { alert: 'winter_weather_advisory' } as const;
  const viewOf = (reasons: readonly ReasonDetail[], read: WhyDetail['read'], points = 10) => {
    const total = points + reasons.reduce((sum, one) => sum + one.points, 0);
    const one = input(classDay(points, reasons, read, advisory), total / 100, { file });
    return stepsView({ ...one, lines: reasons.map(() => 'The forecast has this line.') });
  };
  const calm = { fc: null, snow: 2, feels: null, ice: null, held: null } as const;
  const line = (kind: string, points: number) => ({ kind, points }) as unknown as ReasonDetail;

  it.each([
    ['a timing line', line('timing', 2), 'Heaviest snow'],
    ['a when the snow ends line', line('snow_stops', -3), 'When the snow ends'],
    ['a sun line', line('sun', -1), 'Sun before the day'],
  ])('never says the alert sets the chance when only %s moved it', (_, reason, title) => {
    const view = viewOf([reason], calm);
    expect(view?.rows.map((one) => one.key)).toHaveLength(2);
    expect(view?.rows[1]?.title).toBe(title);
    expect(view?.rows[1]?.number).toBe(chanceFormat.points(reason.points));
    expect(view?.headline).toBe(headline.parts('winter_weather_advisory', 'Thursday'));
    expect(view?.headline).not.toMatch(/sets this chance/u);
  });

  it('says the alert sets the chance only when the start is the whole chance', () => {
    const view = viewOf([], calm);
    expect(view?.rows.map((one) => one.key)).toEqual(['start']);
    expect(view?.total.number).toBe('10%');
    expect(view?.headline).toBe(headline.start('winter_weather_advisory', 'Thursday'));
  });

  it('gives ice its own row when the snow moved nothing, with no 0 part in sight (LR-V6)', () => {
    // At "floor" the ice joins the snow; with no snow line the snow part is 0.
    const read = { fc: null, snow: 0.4, feels: null, ice: 0.1, held: 'floor' } as const;
    const view = viewOf([ice(4)], read);
    expect(view?.rows.map((one) => one.key)).toEqual(['start', 'ice']);
    const iceRow = view?.rows[1];
    expect(iceRow?.title).toBe(build.iceTitle('0.1', `10${NBSP}AM`));
    expect(iceRow?.number).toBe('+4');
    expect(iceRow?.parts).toBeNull();
    expect(iceRow?.text).not.toMatch(/snow/iu);
    for (const one of view?.rows ?? []) {
      expect(one.title).not.toMatch(/snow/iu);
      for (const part of one.parts ?? []) expect(amountOf(part.number)).not.toBe(0);
    }
    // The snow is named once, in the quiet line.
    expect(view?.still).toBe(build.still('advisory', true, 'plain', null));
    expect(view?.still).toMatch(/or from the snow\.$/u);
    expect(view?.headline).toBe(headline.ice);
    if (view !== null) readsPlain(view);
  });

  it('gives cold its own row when the snow moved nothing, and the 0 ice stays quiet (LR-V6)', () => {
    const read = { fc: null, snow: 0.4, feels: 5, ice: 0.05, held: 'floor' } as const;
    const view = viewOf([cold(2, 5)], read);
    expect(view?.rows.map((one) => one.key)).toEqual(['start', 'cold']);
    expect(view?.rows[1]?.title).toBe(build.coldTitle);
    expect(view?.rows[1]?.parts).toBeNull();
    expect(view?.still).toMatch(/No change from the snow or ice\./u);
    expect(view?.rows.map((one) => one.text).join(' ')).not.toContain(row.iceSmall);
  });
});

describe('the snow’s words agree with its amounts as shown (WHY-V2 r4, LR-V5)', () => {
  const { build, headline, row } = chanceFormat.plain;
  const advisory = { alert: 'winter_weather_advisory' } as const;
  /** District 0 with this usual (hundredths) and the advisory's place part 0. */
  const fileWith = (usual: number, alone: number | null = 120) =>
    ({
      ...FILE,
      winter: [
        [4, 1.4, 0.3],
        [0, 0, 0],
      ],
      usual: { advisory: [usual, 120], warning: [562, 177] },
      alone: { advisory: [alone, null], warning: [null, null] },
    }) as unknown as StandingFile;
  const viewOf = (
    usual: number,
    reasons: readonly ReasonDetail[],
    read: WhyDetail['read'],
    alone: number | null = 120,
  ) => {
    const total = 10 + reasons.reduce((sum, one) => sum + one.points, 0);
    const one = input(classDay(10, reasons, read, advisory), total / 100, {
      file: fileWith(usual, alone),
    });
    return stepsView({ ...one, lines: reasons.map(() => 'The forecast has this line.') });
  };
  const readOf = (s: number) =>
    ({ fc: null, snow: s, feels: null, ice: null, held: null }) as const;
  const snowRow = (view: PlainWhyView | null) => view?.rows.find((one) => one.key === 'snow');
  /** No word that weighs the snow against the usual. */
  const COMPARES = /more|less|twice|half|has about/u;

  it.each([
    // [case, usual, raw snow, part, the row's words, the hero says more or less]
    ['Fulton 58: 1.6 shown against the 1.7 usual at +3', 165, 1.68, 3, row.snowMoves(true)],
    [
      'Kansas City 33: 1.4 against 1.4 at +3',
      142,
      1.49,
      3,
      `About the 1.4 inches usual here. ${row.snowMoves(true)}`,
    ],
    [
      'Kansas City 33: 1.44 read, 1.4 against 1.4 at +3',
      142,
      1.44,
      3,
      `About the 1.4 inches usual here. ${row.snowMoves(true)}`,
    ],
    [
      'the snow equal to the usual at +2',
      200,
      2,
      2,
      `About the 2 inches usual here. ${row.snowMoves(true)}`,
    ],
    [
      'the snow equal to the usual at −2',
      150,
      1.5,
      -2,
      `About the 1.5 inches usual here. ${row.snowMoves(false)}`,
    ],
    ['2.5 shown against the 1.4 usual at −2 (S3)', 142, 2.5, -2, row.snowMoves(false)],
    ['2.8 shown against the 1.4 usual at −2 (S3)', 142, 2.8, -2, row.snowMoves(false)],
    ['1.2 shown against the 1.4 usual at +3', 140, 1.2, 3, row.snowMoves(true)],
  ])('never says more or less against the amounts as shown: %s', (_, usual, s, points, said) => {
    const view = viewOf(usual, [snow(points)], readOf(s));
    expect(view).not.toBeNull();
    const one = snowRow(view);
    expect(one?.number).toBe(chanceFormat.points(points));
    expect(one?.text).toBe(said);
    expect(one?.text).not.toMatch(/This forecast has (more|less)/u);
    expect(one?.text.replace(/About the [\d.]+ inch(es)? usual here\. /u, '')).not.toMatch(
      COMPARES,
    );
    // The hero names no comparison either: the parts below add up.
    expect(view?.headline).toBe(headline.parts('winter_weather_advisory', 'Thursday'));
    expect(view?.headline).not.toBe(headline.snow(points > 0));
    if (view !== null) readsPlain(view);
  });

  it.each([
    // Each edge of the side test, one tenth past the usual as shown.
    ['1.5 against 1.4 at +3', 140, 1.5, 3, 'A bit more than the 1.4 inches usual here.'],
    ['1.3 against 1.4 at −3', 140, 1.3, -3, 'A bit less than the 1.4 inches usual here.'],
    [
      '1.68 floored to 1.6 against 1.5 at +3',
      150,
      1.68,
      3,
      'A bit more than the 1.5 inches usual here.',
    ],
    [
      '1.6 against 1.65 shown as 1.7 at −3',
      165,
      1.6,
      -3,
      'A bit less than the 1.7 inches usual here.',
    ],
  ])('says more or less where the amounts as shown agree: %s', (_, usual, s, points, said) => {
    const view = viewOf(usual, [snow(points)], readOf(s));
    expect(snowRow(view)?.text).toBe(said);
    expect(said).toBe(build.snowGap(Math.floor(s * 10 + 1e-9) / 10, usual / 100));
    expect(view?.headline).toBe(headline.snow(points > 0));
  });

  it('keeps the cap’s sentence in the quiet line when the capped snow row moved nothing (S1)', () => {
    const read = { fc: null, snow: 0.7, feels: null, ice: null, held: 'cap' } as const;
    const view = viewOf(142, [], read);
    expect(view?.rows.map((one) => one.key)).toEqual(['start']);
    // The rule's quiet line, then the cap on its own; never the snow row's whole text.
    expect(view?.still).toBe(`${build.still('advisory', true, 'plain', null) ?? ''} ${row.capped}`);
    expect(view?.still).not.toContain(row.snowSmall);
    expect(view?.still).not.toMatch(/is usual here on days like this/u);
    // About the usual as shown: the quiet line says so.
    const usual = viewOf(142, [], { ...read, snow: 1.4 });
    expect(usual?.still).toBe(
      `${build.still('advisory', true, 'usual', null) ?? ''} ${row.capped}`,
    );
  });

  it('keeps a row whose published parts met the bound at 0, never "no change from" them (S2)', () => {
    const line = (kind: string, points: number) => ({ kind, points }) as unknown as ReasonDetail;
    const lowCold = { fc: null, snow: 1, feels: 5, ice: null, held: 'low' } as const;
    const one = viewOf(142, [snow(-3), cold(3, 5), line('timing', -2)], lowCold);
    expect(one?.rows.map((x) => x.key)).toContain('snow');
    expect(snowRow(one)?.number).toBe('0');
    expect(snowRow(one)?.text).toContain(row.lowNoChange(false, true));
    expect(one?.still ?? '').not.toMatch(/the snow or cold/u);
    const lowIce = { fc: null, snow: 1, feels: null, ice: 0.1, held: 'low' } as const;
    const two = viewOf(142, [snow(-2), ice(2)], lowIce);
    expect(snowRow(two)?.text).toContain(row.lowNoChange(true, false));
    expect(two?.still ?? '').not.toMatch(/the snow or ice/u);
    // The start is not the whole story, so the alert never "sets" the chance.
    expect(two?.headline).not.toMatch(/sets this chance/u);
  });
});

describe('a complete record (records-mo, WHY-V2 3)', () => {
  const { build } = chanceFormat.plain;
  // Kansas City 33's rows in pipeline/data/records/mo/mo-record-ed1.csv.gz:
  // [unit, no school, at home, short, days, same100, winters].
  const KC33 = {
    advisory: [[0, 7, 2, 1, 13, 719, 5]],
    warning: [[0, 6, 2, 0, 6, 597, 5]],
    cold: [],
  };
  const fileWith = (full: Record<string, unknown>) =>
    ({ ...FILE, record_full: full }) as unknown as StandingFile;
  const read = { fc: null, snow: 1, feels: null, ice: null, held: null } as const;
  const advisoryDay = classDay(10, [], read, { alert: 'winter_weather_advisory' });
  const warningDay = classDay(30, [snow(-9), cold(1, 12)], {
    fc: null,
    snow: 4.7,
    feels: 12,
    ice: null,
    held: 'low',
  });
  const habitOf = (full: Record<string, unknown>, why = advisoryDay, district = 'Kansas City 33') =>
    stepsView({
      ...input(why, why === advisoryDay ? 0.1 : 0.22, { file: fileWith(full) }),
      district,
    })?.habit;
  /** The box's words as one line: the lead, the gap or the few days, the ending. */
  const words = (habit: HabitView | undefined) =>
    [habit?.lead, habit?.text, habit?.end].filter((x) => x !== null && x !== undefined).join(' ');
  const row = (noSchool: number, home: number, of: number, same100: number) => ({
    advisory: [[0, noSchool, home, 0, of, same100, 5]],
    warning: [],
    cold: [],
  });

  /** Every sentence alone: grade 6 or under, 15 words or fewer, no banned word, the house style. */
  function sentencesRead(text: string, names: readonly string[]): void {
    const sentences = text.match(/[^.]+\./gu) ?? [];
    expect(sentences.length).toBeLessThanOrEqual(5);
    for (const sentence of sentences.map((x) => x.trim())) {
      const { grade, longest } = measure(sentence, names);
      expect([sentence, grade === null || grade <= 6]).toEqual([sentence, true]);
      expect([sentence, longest]).toEqual([sentence, Math.min(longest, 15)]);
      expect([sentence, bannedIn(sentence)]).toEqual([sentence, []]);
      expect(sentence).not.toMatch(/[!—]/u);
      expect(sentence).not.toMatch(/like most/u);
    }
  }

  it('reads Kansas City 33 on a winter advisory day: its days as marks, the key and the lead, with no gap line', () => {
    const habit = habitOf(KC33);
    expect(habit).toEqual({
      title: 'Kansas City 33’s past winter advisory days',
      days: [
        ...Array.from({ length: 5 }, () => 'closed'),
        'remote',
        'remote',
        ...Array.from({ length: 6 }, () => 'school'),
      ],
      key: [
        { mark: 'closed', label: 'Closed 5' },
        { mark: 'remote', label: 'Remote 2' },
        { mark: 'school', label: 'School 6' },
      ],
      lead: 'No school on 7 of 13.',
      // 7 of 13 against 7.19: no verdict, and a gap under a day, so nothing.
      text: null,
      end: 'This does not change Thursday’s 10% yet.',
    });
    sentencesRead(words(habit), ['Kansas City 33']);
  });

  it('reads its storm warning record, all no school, never "closed on every" with remote days', () => {
    const habit = habitOf(KC33, warningDay);
    expect(habit?.lead).toBe('No school on all 6.');
    expect(habit?.key.map((item) => item.label)).toEqual(['Closed 4', 'Remote 2']);
    expect(habit?.text).toBeNull();
    expect(habit?.end).toBe('This does not change Thursday’s 22% yet.');
    expect(words(habit)).not.toMatch(/Closed on (every|all)/u);
  });

  it('ends an ordinary day with the storm warning record and an alert day with its own days', () => {
    const file = fileWith(KC33);
    const ordinary = stepsView({
      ...input(
        {
          base: { kind: 'similar_days', points: 4, weather: null, borrowed: false },
          reasons: [],
          read,
        } as unknown as WhyDetail,
        0.04,
        { file },
      ),
      district: 'Kansas City 33',
    });
    expect(words(ordinary?.habit)).toBe(
      'No school on all 6. Thursday’s 4% does not come from storm warning days.',
    );
    const alert = stepsView({
      ...input(
        {
          base: { kind: 'alert', points: 40, alert: 'winter_weather_advisory', borrowed: false },
          reasons: [],
          read,
        } as unknown as WhyDetail,
        0.4,
        { file },
      ),
      district: 'Kansas City 33',
    });
    expect(words(alert?.habit)).toBe(
      'No school on 7 of 13. Thursday’s 40% starts from its days in our past closing lists.',
    );
    for (const habit of [ordinary?.habit, alert?.habit])
      sentencesRead(words(habit), ['Kansas City 33']);
  });

  it('says every form of the gap true to the test (COPY-RULES 3)', () => {
    const cases: [ReturnType<typeof row>, string][] = [
      // Raymore-Peculiar and Fulton 58: the test says it closes easily.
      [
        row(8, 0, 11, 476),
        'No school on 8 of 11. It tends to close easily. Districts near it had no school on about 5 of those 11 days.',
      ],
      [
        row(8, 0, 9, 454),
        'No school on 8 of 9. It tends to close easily. Districts near it had no school on about 5 of those 9 days.',
      ],
      // The test says it holds out.
      [
        row(3, 1, 6, 576),
        'No school on 3 of 6. It tends to hold out. Districts near it had no school on about 6 of those 6 days.',
      ],
      // No verdict, but a gap of a day or more that rounds away: always "a bit".
      [
        row(8, 0, 12, 666),
        'No school on 8 of 12. That is a bit more than districts near it, about 7 of 12.',
      ],
      [
        row(3, 0, 10, 440),
        'No school on 3 of 10. That is a bit fewer than districts near it, about 4 of 10.',
      ],
      [
        row(0, 0, 5, 100),
        'School on all 5. That is a bit fewer than districts near it, about 1 of 5.',
      ],
      // A gap under a day, or one that rounds to its own: nothing.
      [row(7, 2, 13, 719), 'No school on 7 of 13.'],
      [row(6, 0, 9, 510), 'No school on 6 of 9.'],
      // Under 5 days: too few, never a gap.
      [
        row(2, 1, 3, 255),
        'No school on 2 of 3. Only 3 days on file. That is too few to tell a habit.',
      ],
      [
        row(3, 0, 3, 100),
        'No school on 3 of 3. Only 3 days on file. That is too few to tell a habit.',
      ],
    ];
    for (const [full, said] of cases) {
      const habit = habitOf(full);
      expect(words(habit)).toBe(`${said} This does not change Thursday’s 10% yet.`);
      sentencesRead(words(habit), ['Kansas City 33']);
    }
  });

  it('shows the complete record in place of the lists and never judges one day with school', () => {
    const lists = { ...FILE, record: { advisory: [[0, 12, 0, 12]], warning: [], cold: [] } };
    const view = stepsView({
      ...input(advisoryDay, 0.1, {
        file: { ...lists, record_full: KC33 } as unknown as StandingFile,
      }),
      district: 'Kansas City 33',
    });
    expect(view?.habit.lead).toBe('No school on 7 of 13.');
    expect(words(view?.habit)).not.toContain('closing lists');
    // 6 of 7 with no school beside 0.997 near it: the test says it holds out, but on one day with
    // school (maybe a closing the file does not hold), so no verdict and a gap under a day.
    const one = habitOf({ advisory: [], warning: [[0, 6, 2, 0, 7, 698, 5]], cold: [] }, warningDay);
    expect(words(one)).toBe('No school on 6 of 7. This does not change Thursday’s 22% yet.');
    expect(verdictOf({ closed: 5, of: 7 }, 0.997)).toBe('hold');
  });

  it('reads a record that does not add up as no complete record', () => {
    // More at home than with no school: not a record the box can show.
    const habit = habitOf(row(2, 3, 6, 300));
    expect([habit?.lead, habit?.days, habit?.text]).toEqual([null, null, 'None on file yet.']);
  });

  it('words each lead and gap at the edges', () => {
    expect(build.recordLead(6, 6)).toBe('No school on all 6.');
    expect(build.recordLead(0, 5)).toBe('School on all 5.');
    expect(build.recordLead(4, 4)).toBe('No school on 4 of 4.');
    expect(() => build.recordLead(4, 3)).toThrow(RangeError);
    expect(build.recordGap(7, 13, 7.2, null)).toBeNull();
    expect(build.recordGap(6, 6, 5.99, null)).toBeNull();
    // A gap of a day that rounds to its own count says nothing.
    expect(build.recordGap(5, 10, 6.4, null)).toBe(
      'That is a bit fewer than districts near it, about 6 of 10.',
    );
    expect(build.recordGap(5, 10, 3.6, null)).toBe(
      'That is a bit more than districts near it, about 4 of 10.',
    );
    expect(build.recordGap(5, 10, 4.1, null)).toBeNull();
  });

  it('gives the stored same100 the exact share’s verdict but within a hundredth of the turn', () => {
    // 3 of 11 no-school days, sums of peer shares 5.000 to 8.000: tenths (same10) flip the
    // verdict on 10 times more sums than hundredths (same100), and hundredths only within 0.005
    // of where it turns (spec same-round.txt: 0 of Missouri's 1,529 rows).
    let byTenths = 0;
    let byHundredths = 0;
    const at = (sum: number) => verdictOf({ closed: 3, of: 11 }, sum / 11);
    for (let thousandths = 5000; thousandths < 8000; thousandths += 1) {
      const exact = at(thousandths / 1000);
      if (at(Math.floor((thousandths + 50) / 100) / 10) !== exact) byTenths += 1;
      if (at(Math.floor((thousandths + 5) / 10) / 100) !== exact) byHundredths += 1;
    }
    expect(byTenths).toBeGreaterThan(0);
    expect(byHundredths * 10).toBeLessThanOrEqual(byTenths);
  });
});
