/**
 * The owner's report (Oct 28 2026): a school in Winthrop, WA, viewed from Central time at
 * 10:05 AM (8:05 AM on the school's clock), still headlined Wednesday's chance of no school,
 * a day already under way. From 07:30 on the school's own clock (the owner, Oct 30 2026: "id
 * change it to 7:30") its day's chance is spent: the panel gives the next school day's chance
 * the predictions file holds, and today's real status where the live files know it. Before
 * then today is not called yet: no "Open today", whatever the forecast, and today's chance
 * shows alone where there is one. Made-up schools and chances, in the files' shapes.
 */

import { describe, expect, it } from 'vitest';

import { copy } from '../../copy';
import type { SchoolRecord } from '../../data/details';
import { parseCovered, parsePredictions, schoolOutlook, schoolStatus } from '../../data/school-day';
import { testClosings, testDay, testMeta } from '../../data/tests/builders';
import type { ClosingsDay, CoveredFile, LocalDate, PredictionsFile } from '../../types/generated';
import { schoolView } from '../school';
import type { SchoolView } from '../school';

const PACIFIC = 'America/Los_Angeles';
/** The viewer, two hours east of the school. */
const VIEWER = 'America/Chicago';
const META = testMeta(
  [
    { id: '530000100001', name: 'TEST VALLEY ALT', lon: -120.18, lat: 48.47, district: 0 },
    { id: '530000100002', name: 'TEST VALLEY ELEM', lon: -120.18, lat: 48.48, district: 0 },
  ],
  ['5300001'],
);
const STAMP = { generated_on: META.generated_on, schools: 2, districts: 1 };
const RECORD: SchoolRecord = {
  id: '530000100001',
  index: 0,
  name: 'TEST VALLEY ALT',
  private: false,
  charter: false,
  virtual: false,
  district: { index: 0, id: '5300001', name: 'TEST VALLEY SCHOOL DISTRICT' },
  street: null,
  city: 'WINTHROP',
  state: 'WA',
  zip: null,
  county: 'Okanogan County',
  grades: { low: 'KG', high: '12' },
  enrollment: 40,
  phone: null,
  nearby: [],
  directory: STAMP,
};

type Day = { readonly day: LocalDate; readonly chance: number } | { readonly day: LocalDate };

/**
 * A predictions file as the pipeline writes it: every part but the sum left out, and buses
 * only on the first day where `buses` gives them.
 */
function predictions(
  generatedAt: Date,
  days: readonly [Day, Day],
  buses: string | null = null,
): PredictionsFile {
  const file = {
    schema_version: 1,
    generated_at: generatedAt.toISOString().replace('.000', ''),
    directory: STAMP,
    days: days.map(({ day }) => day),
    districts: [
      {
        district: 0,
        time_zone: PACIFIC,
        days: days.map((day, i) =>
          'chance' in day
            ? {
                state: 'forecast',
                p_no_school: day.chance,
                p_delay: 0.04,
                reasons: [],
                previous: null,
                announces_at: null,
                buses_at: i === 0 ? buses : null,
                hours: null,
                why: {
                  base: {
                    kind: 'similar_days',
                    points: Math.round(day.chance * 100),
                    borrowed: false,
                    live: false,
                  },
                  reasons: [],
                },
                record: null,
                events: [],
              }
            : { state: 'no_threat' },
        ),
      },
    ],
  };
  const parsed = parsePredictions(file);
  if (parsed === null) throw new Error('the test file does not parse');
  return parsed;
}

const WEEK: readonly [Day, Day] = [
  { day: '2026-10-28', chance: 0.93 },
  { day: '2026-10-29', chance: 0.12 },
];

interface Live {
  readonly days?: readonly [Day, Day];
  readonly rows?: readonly ClosingsDay[];
  /** Whether the live check reached the school's closings. */
  readonly covered?: boolean;
  /** The first day's buses (UTC). */
  readonly buses?: string;
  /** No predictions file the panel can show (stale, or not read). */
  readonly stale?: boolean;
  /** The school's state, where it is not Washington's. */
  readonly state?: string;
}

/** The panel at `iso`, from the live files as they would be read then. */
function panel(iso: string, live: Live = {}): SchoolView | null {
  const now = new Date(iso);
  const generated = new Date(now.getTime() - 5 * 60_000);
  const stamp = generated.toISOString().replace('.000', '');
  const closings = testClosings(stamp, META, live.rows ?? []);
  const covered: CoveredFile | null = live.covered
    ? parseCovered({ schema_version: 1, generated_at: stamp, directory: STAMP, ranges: [[0, 1]] })
    : null;
  const file = predictions(generated, live.days ?? WEEK, live.buses ?? null);
  const outlook = schoolOutlook({
    district: 0,
    directory: STAMP,
    shipped: true,
    predictions: live.stale === true ? null : file,
    now,
  });
  const status = schoolStatus({
    school: 0,
    directory: STAMP,
    closings,
    covered,
    now,
    timeZone: outlook?.timeZone ?? null,
  });
  return schoolView({
    id: RECORD.id,
    hint: null,
    record: live.state === undefined ? RECORD : { ...RECORD, state: live.state },
    settled: true,
    status,
    outlook,
    closings,
    now,
    timeZone: VIEWER,
  });
}

describe('a day under way on the school’s own clock', () => {
  it('rolls a Pacific school viewed from Central at 10:05 AM CT to the next school day', () => {
    // 15:05 UTC: 10:05 AM in Chicago, 8:05 AM in Winthrop, Wednesday Oct 28.
    const view = panel('2026-10-28T15:05:00Z');
    expect(view?.chance).toMatchObject({
      day: '2026-10-29',
      number: '12',
      meaning: 'Chance of no school Thursday',
      // How we got N% explains the day headlined, and no other.
      why: { title: 'How we got 12%' },
    });
    expect(JSON.stringify(view)).not.toMatch(/"93"|93%|Wednesday/);
  });

  it('keeps today’s chance until 07:29 on the school’s clock, and spends it at 07:30', () => {
    // 12:00 UTC is 5 AM in Winthrop, where districts mostly have not called it yet.
    expect(panel('2026-10-28T12:00:00Z')?.chance).toMatchObject({
      day: '2026-10-28',
      number: '93',
    });
    // 14:29 UTC is 7:29 AM in Winthrop (and 9:29 AM for the viewer).
    expect(panel('2026-10-28T14:29:00Z')?.chance).toMatchObject({
      day: '2026-10-28',
      number: '93',
      meaning: 'Chance of no school Wednesday',
    });
    expect(panel('2026-10-28T14:30:00Z')?.chance).toMatchObject({
      day: '2026-10-29',
      number: '12',
    });
  });

  it('rolls a Friday to Monday only where the file holds Monday, and invents no day', () => {
    const friday: readonly [Day, Day] = [{ day: '2026-10-30', chance: 0.2 }, { day: '2026-10-31' }];
    expect(panel('2026-10-30T14:29:00Z', { days: friday })?.chance?.day).toBe('2026-10-30');
    // From 07:30 Friday the file's next day is Saturday, no school day: no chance at all.
    const spent = panel('2026-10-30T14:30:00Z', { days: friday });
    expect(spent?.chance).toBeNull();
    expect(JSON.stringify(spent)).not.toMatch(/Chance of no school|%/);
    // Sunday's file holds Monday: Monday's chance.
    const sunday: readonly [Day, Day] = [{ day: '2026-11-01' }, { day: '2026-11-02', chance: 0.3 }];
    expect(panel('2026-11-01T18:00:00Z', { days: sunday })?.chance).toMatchObject({
      day: '2026-11-02',
      meaning: 'Chance of no school Monday',
    });
  });

  it('shows today’s status from its closings row, with the next day’s chance', () => {
    const closed = panel('2026-10-28T15:05:00Z', {
      rows: [testDay('2026-10-28', [[0, 0]])],
    });
    expect(closed?.chance?.status.map((line) => line.headline)).toEqual([
      copy.statusLine.closed.today,
    ]);
    expect(closed?.chance?.day).toBe('2026-10-29');
    const delayed = panel('2026-10-28T15:05:00Z', {
      rows: [testDay('2026-10-28', [[0, 1]])],
    });
    expect(delayed?.chance?.status[0]?.headline).toBe(copy.statusLine.delayed.today);
    expect(delayed?.chance?.day).toBe('2026-10-29');
  });

  it('spends a day the school already decided at once, at 6 AM on its clock', () => {
    // 13:00 UTC is 6 AM in Winthrop: closed today, so tomorrow's chance beside it.
    const closed = panel('2026-10-28T13:00:00Z', {
      rows: [testDay('2026-10-28', [[0, 0]])],
    });
    expect(closed?.chance?.status.map((line) => line.headline)).toEqual([
      copy.statusLine.closed.today,
    ]);
    expect(closed?.chance).toMatchObject({ day: '2026-10-29', number: '12' });
    expect(JSON.stringify(closed)).not.toMatch(/"93"|93%/);
  });

  it('says no Open today beside today’s chance, and says it once today is under way', () => {
    // 6 AM in Winthrop, covered with no row: not called yet, so today's chance alone.
    const early = panel('2026-10-28T13:00:00Z', { covered: true });
    expect(early?.status).toEqual([]);
    expect(early?.chance?.status).toEqual([]);
    expect(early?.chance).toMatchObject({ day: '2026-10-28', number: '93' });
    expect(JSON.stringify(early)).not.toContain(copy.open.today);
    // 7:29 AM: the same.
    const last = panel('2026-10-28T14:29:00Z', { covered: true });
    expect(last?.chance?.status).toEqual([]);
    expect(last?.chance?.day).toBe('2026-10-28');
    // 7:30 AM: today under way, Open today, and tomorrow's chance.
    const under = panel('2026-10-28T14:30:00Z', { covered: true });
    expect(under?.status.map((line) => line.headline)).toEqual([copy.open.today]);
    expect(under?.chance?.status).toEqual([
      { tone: 'open', headline: copy.open.today, detail: null, note: null },
    ]);
    expect(under?.chance).toMatchObject({ day: '2026-10-29', number: '12' });
  });

  it('says no Open today before 07:30 on the school’s clock, whatever the forecast', () => {
    const said = (view: SchoolView | null): readonly string[] =>
      view?.status.map((line) => line.headline) ?? [];
    // No threat today: no chance for today, and still not called at 6 AM or 7:29 AM.
    const calm: readonly [Day, Day] = [{ day: '2026-10-28' }, { day: '2026-10-29', chance: 0.12 }];
    for (const iso of ['2026-10-28T13:00:00Z', '2026-10-28T14:29:00Z']) {
      const quiet = panel(iso, { covered: true, days: calm });
      expect(said(quiet)).toEqual([]);
      expect(quiet?.chance?.status).toEqual([]);
      expect(quiet?.chance?.day).toBe('2026-10-29');
      expect(JSON.stringify(quiet)).not.toContain(copy.open.today);
    }
    const quiet = panel('2026-10-28T14:30:00Z', { covered: true, days: calm });
    expect(quiet?.chance?.status.map((line) => line.headline)).toEqual([copy.open.today]);
    // A stale or missing predictions file (a dark predict loop on a storm morning): no chance
    // and no Open today before 07:30 on the school's clock, the Pacific's for Washington.
    expect(said(panel('2026-10-28T13:00:00Z', { covered: true, stale: true }))).toEqual([]);
    expect(said(panel('2026-10-28T14:29:00Z', { covered: true, stale: true }))).toEqual([]);
    const late = panel('2026-10-28T14:30:00Z', { covered: true, stale: true });
    expect(said(late)).toEqual([copy.open.today]);
    expect(late?.chance).toBeNull();
    // Buses at 7 AM on the school's clock (14:00 UTC): today is under way from them.
    expect(
      said(panel('2026-10-28T13:59:00Z', { covered: true, buses: '2026-10-28T14:00:00Z' })),
    ).toEqual([]);
    const buses = panel('2026-10-28T14:00:00Z', { covered: true, buses: '2026-10-28T14:00:00Z' });
    expect(said(buses)).toEqual([copy.open.today]);
    expect(buses?.chance).toMatchObject({ day: '2026-10-29', number: '12' });
  });

  it('says Open today from 07:30 on the clock its state keeps where the file gives none', () => {
    const said = (view: SchoolView | null): readonly string[] =>
      view?.status.map((line) => line.headline) ?? [];
    const stale = (iso: string, state: string): readonly string[] =>
      said(panel(iso, { covered: true, stale: true, state }));
    // New York keeps Eastern time alone: 7:30 AM EDT is 11:30 UTC on Wednesday Oct 28.
    expect(stale('2026-10-28T11:29:00Z', 'NY')).toEqual([]);
    expect(stale('2026-10-28T11:30:00Z', 'NY')).toEqual([copy.open.today]);
    // Missouri keeps Central time alone: 7:30 AM CDT is 12:30 UTC.
    expect(stale('2026-10-28T12:29:00Z', 'MO')).toEqual([]);
    expect(stale('2026-10-28T12:30:00Z', 'MO')).toEqual([copy.open.today]);
    // Texas keeps Mountain time in El Paso, its latest: 7:30 AM MDT is 13:30 UTC.
    expect(stale('2026-10-28T13:29:00Z', 'TX')).toEqual([]);
    expect(stale('2026-10-28T13:30:00Z', 'TX')).toEqual([copy.open.today]);
    // Guam's clock is ahead of the US date: Wednesday ends there at 14:00 UTC, so from then
    // "Open today" would name a day gone, and the panel says none.
    expect(stale('2026-10-28T13:59:00Z', 'GU')).toEqual([copy.open.today]);
    expect(stale('2026-10-28T14:00:00Z', 'GU')).toEqual([]);
  });

  it('says Open today only for a school the live check reached with no row', () => {
    const open = panel('2026-10-28T15:05:00Z', { covered: true });
    expect(open?.chance?.status).toEqual([
      { tone: 'open', headline: copy.open.today, detail: null, note: null },
    ]);
    expect(open?.chance?.day).toBe('2026-10-29');
    // Not reached: nothing about today, and never "open".
    const unknown = panel('2026-10-28T15:05:00Z', { covered: false });
    expect(unknown?.status).toEqual([]);
    expect(unknown?.chance?.status).toEqual([]);
    expect(unknown?.chance?.day).toBe('2026-10-29');
  });
});
