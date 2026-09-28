import { describe, expect, it } from 'vitest';

import type { ClosingsDay, CoveredFile, PredictionsFile } from '../../types/generated';
import {
  NO_STATUS,
  covers,
  nextDay,
  parseCovered,
  parsePredictions,
  schoolOutlook,
  schoolStatus,
} from '../school-day';
import { testClosings, testDay, testMeta } from './builders';
import type { TestSchool } from './builders';

/** Made up for these tests. */
const SCHOOLS: TestSchool[] = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: 0 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: 0 },
  { id: '010000500872', name: 'Third', lon: -86.5, lat: 33.8, district: 0 },
  { id: 'A1902690', name: 'Fourth', lon: -94.6, lat: 39.0, district: -1 },
];
const META = testMeta(SCHOOLS, ['0100005']);
const STAMP = { generated_on: META.generated_on, schools: 4, districts: 1 };
/** Noon in Alabama, 18:00 UTC on Jan 12: the same day everywhere in the contiguous US. */
const NOON = new Date('2026-01-12T18:00:00Z');
const GENERATED = '2026-01-12T17:40:00Z';

function covered(ranges: CoveredFile['ranges'], generatedAt = GENERATED): CoveredFile {
  return { schema_version: 1, generated_at: generatedAt, directory: STAMP, ranges };
}

/** A delayed row with its time columns filled in, then a closed one. */
function delayedDay(day: string): ClosingsDay {
  return {
    day,
    gaps: [1, 0],
    statuses: [1, 0],
    announced: [45, null],
    reasons: [1, null],
    shifts: [120],
    clocks: [600],
  };
}

describe('reading covered.json and predictions', () => {
  it('reads covered ranges and finds a school in them', () => {
    const file = covered([
      [0, 1],
      [3, 3],
    ]);
    expect(parseCovered(file)).toEqual(file);
    expect([0, 1, 2, 3, 4].map((school) => covers(file, school))).toEqual([
      true,
      true,
      false,
      true,
      false,
    ]);
    // Ranges touching or out of order have another encoding: refused.
    expect(
      parseCovered(
        covered([
          [0, 1],
          [2, 3],
        ]),
      ),
    ).toBeNull();
    expect(parseCovered(covered([[3, 1]]))).toBeNull();
    expect(parseCovered({ ...file, generated_at: 'today' })).toBeNull();
  });

  it('reads a predictions file of consecutive days and checked forecasts', () => {
    const file: PredictionsFile = {
      schema_version: 1,
      generated_at: GENERATED,
      directory: STAMP,
      days: ['2026-01-12', '2026-01-13'],
      districts: [
        {
          district: 0,
          days: [
            { state: 'forecast', p_no_school: 0.34, p_delay: 0.12, reasons: [0, 1] },
            { state: 'no_threat' },
          ],
        },
      ],
    };
    expect(parsePredictions(file)).toEqual(file);
    expect(parsePredictions({ ...file, days: ['2026-01-12', '2026-01-14'] })).toBeNull();
    expect(
      parsePredictions({
        ...file,
        districts: [{ district: 0, days: [{ state: 'forecast', p_no_school: 1.2 }, file] }],
      }),
    ).toBeNull();
    expect(parsePredictions({ ...file, districts: [{ district: 0, days: [] }] })).toBeNull();
    expect(nextDay('2026-02-28')).toBe('2026-03-01');
    expect(nextDay('2028-02-28')).toBe('2028-02-29');
  });
});

describe('a school’s status', () => {
  const closings = testClosings(GENERATED, META, [
    testDay('2026-01-12', [[0, 0]]),
    delayedDay('2026-01-13'),
  ]);

  it('reads its row today and tomorrow, every column', () => {
    expect(
      schoolStatus({ school: 0, directory: STAMP, closings, covered: null, now: NOON }),
    ).toEqual({
      today: { status: 0, reason: 0, announcedAt: null, shiftMinutes: null, clockMinute: null },
      tomorrow: null,
    });
    expect(
      schoolStatus({ school: 1, directory: STAMP, closings, covered: null, now: NOON }),
    ).toEqual({
      today: null,
      tomorrow: {
        status: 1,
        reason: 1,
        announcedAt: new Date('2026-01-12T16:55:00Z'),
        shiftMinutes: 120,
        clockMinute: 600,
      },
    });
    expect(
      schoolStatus({ school: 2, directory: STAMP, closings, covered: null, now: NOON }).tomorrow,
    ).toMatchObject({ status: 0, shiftMinutes: null, clockMinute: null });
  });

  it('says open only where the school was checked today and has no row', () => {
    const checked = covered([[0, 3]]);
    const status = (school: number, file: CoveredFile | null, now = NOON) =>
      schoolStatus({ school, directory: STAMP, closings, covered: file, now });
    expect(status(3, checked)).toEqual({ today: 'open', tomorrow: null });
    // Closed today is closed, checked or not; open is only ever today.
    expect(status(0, checked).today).toMatchObject({ status: 0 });
    expect(status(1, checked)).toMatchObject({ today: 'open', tomorrow: { status: 1 } });
    // Not checked, checked with another file, or checked another day: nothing said.
    expect(status(3, covered([[0, 2]]))).toEqual(NO_STATUS);
    expect(status(3, covered([[0, 3]], '2026-01-12T17:45:00Z'))).toEqual(NO_STATUS);
    const yesterday = testClosings('2026-01-11T17:40:00Z', META, []);
    expect(
      schoolStatus({
        school: 3,
        directory: STAMP,
        closings: yesterday,
        covered: covered([[0, 3]], '2026-01-11T17:40:00Z'),
        now: NOON,
      }),
    ).toEqual(NO_STATUS);
    expect(status(3, null)).toEqual(NO_STATUS);
  });

  it('says nothing overnight, without a file, or from another directory’s file', () => {
    const overnight = new Date('2026-01-13T05:00:00Z');
    expect(
      schoolStatus({ school: 0, directory: STAMP, closings, covered: null, now: overnight }),
    ).toEqual(NO_STATUS);
    expect(
      schoolStatus({ school: 0, directory: STAMP, closings: null, covered: null, now: NOON }),
    ).toEqual(NO_STATUS);
    expect(
      schoolStatus({
        school: 0,
        directory: { ...STAMP, generated_on: '2026-01-06' },
        closings,
        covered: null,
        now: NOON,
      }),
    ).toEqual(NO_STATUS);
  });
});

describe('a school’s outlook', () => {
  const predictions: PredictionsFile = {
    schema_version: 1,
    generated_at: GENERATED,
    directory: STAMP,
    days: ['2026-01-12', '2026-01-13'],
    districts: [
      {
        district: 0,
        days: [
          { state: 'forecast', p_no_school: 0.34, p_delay: 0.12, reasons: [0] },
          { state: 'no_threat' },
        ],
      },
      { district: 1, days: [{ state: 'not_enough_data' }, { state: 'not_enough_data' }] },
    ],
  };
  const input = { district: 0, directory: STAMP, shipped: true, predictions, now: NOON };

  it('gives today’s and tomorrow’s chances from the district’s forecast', () => {
    expect(schoolOutlook(input)).toEqual({
      today: { state: 'forecast', noSchool: 0.34, delay: 0.12, reasons: [0] },
      tomorrow: { state: 'no_threat' },
    });
    // The file's last day is today: tomorrow has none.
    expect(schoolOutlook({ ...input, now: new Date('2026-01-13T18:00:00Z') })).toEqual({
      today: { state: 'no_threat' },
      tomorrow: null,
    });
  });

  it('says there is not enough data where no history gives a chance', () => {
    expect(schoolOutlook({ ...input, shipped: false, predictions: null })).toBe('not_enough_data');
    expect(schoolOutlook({ ...input, district: null })).toBe('not_enough_data');
    expect(schoolOutlook({ ...input, district: 1 })).toBe('not_enough_data');
    expect(schoolOutlook({ ...input, district: 7 })).toBe('not_enough_data');
  });

  it('leaves the outlook out where the files cannot say for now', () => {
    // Shipped but not read, from another directory, stale, or overnight.
    expect(schoolOutlook({ ...input, predictions: null })).toBeNull();
    expect(
      schoolOutlook({ ...input, directory: { ...STAMP, generated_on: '2026-01-06' } }),
    ).toBeNull();
    expect(schoolOutlook({ ...input, now: new Date('2026-01-15T18:00:00Z') })).toBeNull();
    expect(schoolOutlook({ ...input, now: new Date('2026-01-13T05:00:00Z') })).toBeNull();
  });
});
