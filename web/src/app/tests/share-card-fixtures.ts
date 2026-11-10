/**
 * Made-up schools and days for the share cards' tests and sample pictures, as
 * the school panel's view (app/school.ts schoolView) gives them: a school
 * closed, one delayed, one remote and one with only a chance, in Kansas on
 * Monday Jan 12, 2026. The schools, their town and county, the statuses, the
 * storm and the chances are all invented for these tests and the samples
 * alone, so no sample can be taken for a real school's day.
 */
import { NO_STATUS } from '../../data/school-day';
import type { SchoolStatus, StatusRow } from '../../data/school-day';
import type { SchoolRecord } from '../../data/details';
import { Detail, Reason, Status } from '../../types/generated';
import type { ClosingsFile, SeasonFile } from '../../types/generated';
import { schoolView } from '../school';
import type { SchoolView, ViewInput } from '../school';
import { A_CLOSINGS, A_NOW, A_OUTLOOK, STAMP, ZONE } from './chance-fixtures';

/** 6:55 AM in Kansas City, Monday Jan 12, 2026. */
export const MORNING = new Date('2026-01-12T12:55:00Z');
export const URL_OF = (id: string): string => `https://snowlightmap.com/?school=${id}`;

/** An invented public school, in district 0 of the chance fixtures' directory. */
export const SCHOOL: SchoolRecord = {
  id: '201164001574',
  index: 0,
  name: 'LANTERN HILL HIGH',
  private: false,
  charter: false,
  virtual: false,
  district: { index: 0, id: '2011640', name: 'LANTERN HILL UNIFIED SCHOOLS' },
  street: null,
  city: 'BRIARWOOD',
  state: 'KS',
  zip: null,
  county: 'Sample County',
  grades: { low: '09', high: '12' },
  enrollment: 0,
  phone: null,
  nearby: [],
  directory: STAMP,
};

/** A school name long enough to wrap on any card. */
export const LONG_SCHOOL: SchoolRecord = {
  ...SCHOOL,
  id: '201164009999',
  name: 'LANTERN HILL NORTHWEST ACADEMY FOR INTERNATIONAL BACCALAUREATE AND ADVANCED SCIENCE STUDIES',
};

/** The live file of the morning, made at 6:55 AM. */
export const MORNING_CLOSINGS: ClosingsFile = {
  ...A_CLOSINGS,
  generated_at: '2026-01-12T12:55:00Z',
};

function row(status: Status, reason: Reason | null, extra: Partial<StatusRow> = {}): StatusRow {
  return {
    status,
    reason,
    announcedAt: new Date('2026-01-12T11:12:00Z'),
    shiftMinutes: null,
    clockMinute: null,
    manual: false,
    details: [],
    ...extra,
  };
}

export const CLOSED: SchoolStatus = {
  today: row(Status.closed, Reason.winter_storm),
  tomorrow: null,
};
export const DELAYED: SchoolStatus = {
  today: row(Status.delayed, Reason.ice, {
    shiftMinutes: 120,
    clockMinute: 600,
    details: [Detail.buses_snow_routes, Detail.no_breakfast],
  }),
  tomorrow: null,
};
export const REMOTE: SchoolStatus = {
  today: row(Status.remote, Reason.extreme_cold),
  tomorrow: null,
};
/** Closed today, and tomorrow too. */
export const CLOSED_TWO_DAYS: SchoolStatus = {
  today: row(Status.closed, Reason.winter_storm),
  tomorrow: row(Status.closed, Reason.winter_storm),
};

/** SYNTHETIC: the invented school closed two days and delayed one this school year. */
export const SEASON: SeasonFile = {
  schema_version: 1,
  season: '2025-2026',
  since: '2025-08-01',
  through: '2026-01-11',
  directory: STAMP,
  content_sha256: '5'.repeat(64),
  gaps: [0],
  closed: [2],
  delayed: [1],
  remote: [0],
  early_dismissal: [0],
};

export function viewInput(overrides: Partial<ViewInput> = {}): ViewInput {
  return {
    id: SCHOOL.id,
    hint: null,
    record: SCHOOL,
    settled: true,
    status: NO_STATUS,
    outlook: null,
    zone: ZONE,
    closings: MORNING_CLOSINGS,
    now: MORNING,
    timeZone: ZONE,
    ...overrides,
  };
}

export function viewOf(overrides: Partial<ViewInput> = {}): SchoolView {
  const view = schoolView(viewInput(overrides));
  if (view === null) throw new Error('no view');
  return view;
}

/** The predictions file of the evening was made at 8:50 PM. */
export const EVENING_PREDICTIONS_AT = new Date('2026-01-13T02:50:00Z');

/** The four sample schools: closed, delayed, remote, and a chance alone the evening before. */
export function samples(): { name: string; view: SchoolView; now: Date }[] {
  return [
    { name: 'closed', view: viewOf({ status: CLOSED, season: SEASON }), now: MORNING },
    { name: 'delayed', view: viewOf({ status: DELAYED }), now: MORNING },
    { name: 'remote', view: viewOf({ status: REMOTE }), now: MORNING },
    {
      name: 'chance',
      view: viewOf({
        now: A_NOW,
        closings: A_CLOSINGS,
        outlook: A_OUTLOOK === null ? null : { ...A_OUTLOOK, generatedAt: EVENING_PREDICTIONS_AT },
      }),
      now: A_NOW,
    },
  ];
}
