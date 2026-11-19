// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { chanceFormat } from '../../copy-chance';
import type { Zones } from '../../copy-chance';
import { NO_DETAIL } from '../../data/forecast-detail';
import type { ForecastDetail, ReasonDetail, WhyDetail } from '../../data/forecast-detail';
import type { StandingFile } from '../../types/generated';
import { stepsView } from '../steps';
import type { StepsInput, StepsSource, StepsView } from '../steps';

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../scripts/check-copy.mjs',
);
const { problems } = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string, file?: string) => string[];
};

/** The copy rules' problems with a text, the names a test gives aside (a name keeps its case). */
const NAMES = [
  'Tahoe-Truckee',
  'Tahoe-Truckee’s',
  'Westwood',
  'Westwood’s',
  'Creekside',
  'Charter',
  'Charter’s',
];
function rules(text: string): string[] {
  return problems(text, 'src/copy-chance.ts').filter(
    (problem) => !NAMES.some((name) => problem === `Title Case "${name}"`),
  );
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

function detail(why: WhyDetail): ForecastDetail {
  return { ...NO_DETAIL, why };
}

function warning(
  points: number,
  reasons: readonly ReasonDetail[],
  read: WhyDetail['read'],
  of: 'districts' | 'private_schools' = 'districts',
): WhyDetail {
  return {
    base: {
      kind: 'class',
      points,
      alert: 'winter_storm_warning',
      standing: 'usual',
      of,
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
    delay: Math.round((1 - chance) * 0.11 * 100) / 100,
    day: '2026-11-19',
    district: 'Tahoe-Truckee',
    zones: ZONES,
    source: { file: FILE, unit: { kind: 'district', index: 0 }, forecastCheck: [], ...source },
    nightChart: false,
  };
}

/** Every string a view shows, for the copy rules. */
function strings(view: StepsView): string[] {
  return [
    ...(view.whole === null ? [] : [view.whole]),
    view.record.text,
    ...view.record.help,
    ...view.rows.flatMap((row) => [row.text, ...row.help]),
    ...(view.delayHelp === null ? [] : [view.delayHelp]),
  ];
}

function sum(view: StepsView): number {
  return view.rows.reduce((total, row) => {
    if (row.key === 'start') return total + Number(row.number.replace('%', ''));
    return total + (row.number === '0' ? 0 : Number(row.number.replace('−', '-')));
  }, 0);
}

const WAIT = { fc: 0, snow: null, feels: null, ice: null, held: null } as const;

describe('the why, step by step', () => {
  it('heads with the record, then adds the start, the standing and the waiting forecast', () => {
    const view = stepsView(input(warning(30, [], WAIT), 0.3));
    expect(view).not.toBeNull();
    if (view === null) return;
    expect(view.whole).toBe(
      'This chance is for Tahoe-Truckee as a whole, the same at each of its schools.',
    );
    expect(view.record.text).toBe(
      'From fall 2015 to spring 2026, the past closings lists we count tell us what Tahoe-Truckee did on 5 of its school days with a storm warning: no school on 3, a late start on 1 and school on 1. This chance does not weigh that record by itself yet.',
    );
    expect(view.record.help[0]).toBe('This winter’s days are not in that record.');
    expect(view.record.help[1]).toContain('1,027 of the 1,071 school days with a storm warning');
    expect(view.record.help.join(' ')).not.toMatch(/\bmost of\b/);
    expect(view.rows.map((row) => [row.key, row.number])).toEqual([
      ['start', '45%'],
      ['standing', '−15'],
      ['forecast', '0'],
    ]);
    expect(view.rows[1]?.text).toBe(
      'Tahoe-Truckee gets 11.2 school days with a storm warning a winter. Across districts that get any, the middle is 1.4.',
    );
    expect(view.rows[2]?.text).toBe(
      'The forecast is not in this chance yet. It counts from 9\u00a0PM Wednesday, the evening before.',
    );
    expect(sum(view)).toBe(30);
    expect(view.delayHelp).toContain('we put the chance of a delayed start at 11%');
    for (const text of strings(view)) expect([text, rules(text)]).toEqual([text, []]);
  });

  it('says a lower bound held day as one net row whose help says enough more snow raises it', () => {
    const read = { fc: null, snow: 0.5, feels: 12, ice: null, held: 'low' } as const;
    const lines = [
      { kind: 'snow_total', points: -9, low: null, high: null, against: 'here' },
      { kind: 'wind_chill', points: 1, feelsLike: 12, at: null },
    ] as unknown as ReasonDetail[];
    const view = stepsView(input(warning(30, lines, read), 0.22));
    expect(view?.rows.at(-1)?.number).toBe('−8');
    expect(view?.rows.at(-1)?.text).toBe(
      'The forecast has 0.5 inches or more of snow by 10\u00a0AM at half its schools, and half will feel 12 F or colder at 7 AM.',
    );
    expect(view?.rows.at(-1)?.help[0]).toBe(
      'A forecast can take a winter storm warning day here only this far down, so the cold does not change the number.',
    );
    expect(view?.rows.at(-1)?.help[1]).toContain('Enough more snow raises it');
    expect(view === null ? null : sum(view)).toBe(22);
  });

  it('gives the snow its row at 0 beside a cold line, and the high help past the bend', () => {
    const read = { fc: null, snow: 3.9, feels: 13, ice: null, held: 'high' } as const;
    const lines = [
      { kind: 'wind_chill', points: 1, feelsLike: 13, at: null },
    ] as unknown as ReasonDetail[];
    const view = stepsView(input(warning(30, lines, read), 0.31));
    expect(view?.rows.map((row) => row.key)).toEqual([
      'start',
      'standing',
      'forecast-snow',
      'forecast-cold',
    ]);
    expect(view?.rows[2]?.number).toBe('0');
    expect(view?.rows[2]?.help[0]).toBe('That moves it less than a point.');
    expect(view?.rows[2]?.help).toContain('Past this much snow, more adds less and less.');
  });

  it('says the one school and county forms with no district line', () => {
    const view = stepsView({
      ...input(warning(57, [], WAIT), 0.57),
      district: 'Creekside Charter',
      source: { file: FILE, unit: { kind: 'district', index: 1 }, forecastCheck: [] },
    });
    expect(view?.whole).toBeNull();
    expect(view?.record.text).toBe(
      'This chance does not weigh Creekside Charter’s own record by itself yet, and from fall 2015 to spring 2026 no past closings list we count tells us what Creekside Charter did on a school day with a storm warning.',
    );
    expect(view?.record.help).toHaveLength(2);
    expect(view?.rows[1]?.text).toContain('Creekside Charter’s own school, so it takes the middle');
    expect(view?.rows[1]?.number).toBe('+12');
  });

  it('says the private school its own way', () => {
    const view = stepsView({
      ...input(warning(57, [], null, 'private_schools'), 0.57),
      district: 'Lake Tahoe School',
      source: { file: FILE, unit: { kind: 'school', index: 0 }, forecastCheck: [] },
    });
    expect(view?.rows[0]?.text).toBe(
      'A school day with a winter storm warning starts at 45% for a school in a place that gets 1.4 school days with a storm warning a winter.',
    );
    expect(view?.rows.at(-1)?.text).toContain('does not move a private school’s chance');
    expect(view?.whole).toBeNull();
  });

  it('keeps today’s why where a step would not add or a day is not a storm-class one', () => {
    // The base and the lines do not add to the chance.
    expect(stepsView(input(warning(30, [], WAIT), 0.31))).toBeNull();
    // A day said open.
    const open = [{ kind: 'said_open', points: -29 }] as unknown as ReasonDetail[];
    expect(stepsView(input(warning(30, open, WAIT), 0.01))).toBeNull();
    // No forecast step fields at all.
    expect(stepsView(input(warning(30, [], null), 0.3))).toBeNull();
    // The bus hour timing with no line, or without today's sentence for each line.
    const timing = { ...WAIT, fc: 6 };
    expect(stepsView(input(warning(30, [], timing), 0.3))).toBeNull();
    const snow = [{ kind: 'snow_total', points: 12 }] as unknown as ReasonDetail[];
    expect(stepsView(input(warning(30, snow, timing), 0.42))).toBeNull();
    // A pooled day.
    const pooled = { base: { kind: 'pooled', points: 30 }, reasons: [] } as unknown as WhyDetail;
    expect(stepsView(input(pooled, 0.3))).toBeNull();
  });
});

describe('the steps beside today’s lines and the holds', () => {
  it('shows a bus hour timing day’s record and base rows, then today’s line sentences', () => {
    const timing = { ...WAIT, fc: 6 };
    const lines = [
      { kind: 'snow_total', points: 12 },
      { kind: 'wind_chill', points: 2 },
    ] as unknown as ReasonDetail[];
    const view = stepsView({
      ...input(warning(30, lines, timing), 0.44),
      lines: ['Today’s snow sentence.', 'Today’s cold sentence.'],
    });
    expect(view?.record.text).toContain('tell us what Tahoe-Truckee did on 5 of its school days');
    expect(view?.rows.map((row) => [row.key, row.number, row.text])).toEqual([
      ['start', '45%', expect.any(String)],
      ['standing', '−15', expect.any(String)],
      ['forecast-line-0', '+12', 'Today’s snow sentence.'],
      ['forecast-line-1', '+2', 'Today’s cold sentence.'],
    ]);
    if (view !== null) expect(sum(view)).toBe(44);
  });

  it('shows a hold that moved the chance under a point as a 0 row, and one that did not act not at all', () => {
    const acted = {
      ...FILE,
      held: { advisory: [], warning: [[0, 0, 0, 0, 1]], cold: [] },
    } as unknown as StandingFile;
    const view = stepsView(input(warning(30, [], WAIT), 0.3, { file: acted }));
    expect(view?.rows.map((row) => [row.key, row.number])).toEqual([
      ['start', '45%'],
      ['standing', '−15'],
      ['held-pull', '0'],
      ['forecast', '0'],
    ]);
    expect(view?.rows[2]?.text).toContain('it is moved part of the way back to the start');
    const quiet = {
      ...FILE,
      held: { advisory: [], warning: [[0, 0, 0, 0, 0]], cold: [] },
    } as unknown as StandingFile;
    const none = stepsView(input(warning(30, [], WAIT), 0.3, { file: quiet }));
    expect(none?.rows.map((row) => row.key)).toEqual(['start', 'standing', 'forecast']);
  });

  it('names an alert with its article in a private school’s start, and gives every fold its own name', () => {
    const start = chanceFormat.steps.startStep({
      who: { name: 'Lake School', school: true, set: { mixed: false, one: true } },
      alert: 'ice_storm_warning',
      klass: 'warning',
      now: 45,
      prior: 45,
      fit: 45,
      storms: 0,
      shrunk: null,
      ref: 1.4,
    });
    expect(start.help[1]).toMatch(/^An ice storm warning reaches this school for this day\./);
    const view = stepsView(input(warning(30, [], WAIT), 0.3));
    const names = view?.rows.map((row) => row.name) ?? [];
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('the record note’s counts', () => {
  it.each([
    [{ closed: 0, delayed: 0, of: 1 }, 'school that day'],
    [{ closed: 1, delayed: 0, of: 1 }, 'no school that day'],
    [{ closed: 0, delayed: 1, of: 1 }, 'a late start that day'],
    [{ closed: 3, delayed: 0, of: 4 }, 'no school on 3 and school on 1'],
    [{ closed: 2, delayed: 0, of: 4 }, 'no school on 2 and school on 2'],
    [{ closed: 1, delayed: 0, of: 4 }, 'no school on 1 and school on 3'],
    [{ closed: 4, delayed: 0, of: 4 }, 'no school on each of them'],
    [{ closed: 2, delayed: 1, of: 4 }, 'no school on 2, a late start on 1 and school on 1'],
  ])('%j reads "%s"', (record, said) => {
    expect(chanceFormat.steps.recordParts(record)).toBe(said);
  });

  it('passes the copy rules in every form', () => {
    for (const set of [
      { mixed: false, one: false },
      { mixed: true, one: false },
      { mixed: false, one: true },
      { mixed: true, one: true },
    ]) {
      for (const school of [false, true]) {
        const note = chanceFormat.steps.recordNote({
          who: { name: 'Westwood', school, set },
          klass: 'advisory',
          first: 2015,
          last: 2025,
          record: { closed: 0, delayed: 0, of: 1 },
          sum: { closed: 495, of: 667 },
          region: true,
        });
        for (const text of [note.main, ...note.help])
          expect([text, rules(text)]).toEqual([text, []]);
      }
    }
  });
});
