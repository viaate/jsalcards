/**
 * The owner's report (Oct 28 2026): a school in Winthrop, WA, viewed from Central time at
 * 10:05 AM (8:05 AM on the school's clock), still headlined Wednesday's chance of no school,
 * a day already under way. From 05:00 on the school's own clock its day's chance is spent:
 * the panel gives the next school day's chance the predictions file holds, and today's real
 * status where the live files know it. Made-up schools and chances, in the files' shapes.
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

/** A predictions file as the pipeline writes it: no bus time, every part but the sum left out. */
function predictions(generatedAt: Date, days: readonly [Day, Day]): PredictionsFile {
  const file = {
    schema_version: 1,
    generated_at: generatedAt.toISOString().replace('.000', ''),
    directory: STAMP,
    days: days.map(({ day }) => day),
    districts: [
      {
        district: 0,
        time_zone: PACIFIC,
        days: days.map((day) =>
          'chance' in day
            ? {
                state: 'forecast',
                p_no_school: day.chance,
                p_delay: 0.04,
                reasons: [],
                previous: null,
                announces_at: null,
                buses_at: null,
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
  const file = predictions(generated, live.days ?? WEEK);
  const outlook = schoolOutlook({
    district: 0,
    directory: STAMP,
    shipped: true,
    predictions: file,
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
    record: RECORD,
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
    expect(JSON.stringify(view)).not.toContain('93');
  });

  it('keeps today’s chance until 04:59 on the school’s clock, and spends it at 05:00', () => {
    // 11:59 UTC is 4:59 AM in Winthrop (and 6:59 AM for the viewer).
    expect(panel('2026-10-28T11:59:00Z')?.chance).toMatchObject({
      day: '2026-10-28',
      number: '93',
      meaning: 'Chance of no school Wednesday',
    });
    expect(panel('2026-10-28T12:00:00Z')?.chance).toMatchObject({
      day: '2026-10-29',
      number: '12',
    });
  });

  it('rolls a Friday to Monday only where the file holds Monday, and invents no day', () => {
    const friday: readonly [Day, Day] = [{ day: '2026-10-30', chance: 0.2 }, { day: '2026-10-31' }];
    expect(panel('2026-10-30T11:59:00Z', { days: friday })?.chance?.day).toBe('2026-10-30');
    // From 05:00 Friday the file's next day is Saturday, no school day: no chance at all.
    const spent = panel('2026-10-30T12:00:00Z', { days: friday });
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
