/**
 * Two made-up nights for the chance section's tests, as the predictions and
 * closings files would give them, in the shapes app/chance.ts reads. The
 * storm, the chances and the closings are invented for these tests.
 *
 * A: Monday Jan 12, 2026, 9:05 PM in Kansas City. No status yet; Tuesday's
 *    chance is the headline. Two districts next door canceled at 8:41 and
 *    8:52 PM.
 * B: Tuesday Jan 13, 6:20 AM. Closed today; Wednesday's chance is the
 *    headline, with how cold it will feel through the night.
 */
import { copy } from '../../copy';
import type { NameOf, Names, StatusLine } from '../chance';
import type { ForecastDetail, RecordDetail, WhyDetail } from '../../data/forecast-detail';
import type { Outlook } from '../../data/school-day';
import type { ClosingsFile, DirectoryStamp } from '../../types/generated';

export const ZONE = 'America/Chicago';
export const STAMP: DirectoryStamp = { generated_on: '2026-01-05', schools: 6, districts: 4 };
/** District 0 is the school's own; 1 and 2 are next door; 3 is farther off. */
export const DISTRICT_NAMES = ['Shawnee Mission', 'Blue Valley', 'Olathe', 'De Soto'];
/** Schools 0 and 1 are in district 0, 2 and 3 in district 1, 4 in 2, 5 in 3. */
const SCHOOL_DISTRICTS = [0, 0, 1, 1, 2, 3];

export const NAMES: Names = {
  stamp: STAMP,
  districtOf: (school) => SCHOOL_DISTRICTS[school] ?? -1,
  schools: (district) => SCHOOL_DISTRICTS.filter((of) => of === district).length,
  naming: (district) => {
    const shown = DISTRICT_NAMES[district];
    return shown === undefined ? null : { shown, state: 'KS', alike: false };
  },
};
/** The districts by their names, as the section says them. */
export const NAME_OF: NameOf = (district) => DISTRICT_NAMES[district] ?? null;

const at = (iso: string): Date => new Date(iso);

export const A_NOW = at('2026-01-13T03:05:00Z');
export const B_NOW = at('2026-01-13T12:20:00Z');

/** How Tuesday's 64% adds up: 30 + 16 + 9 + 7 + 5 - 3. */
export const A_WHY: WhyDetail = {
  base: { kind: 'alert', points: 30, alert: 'winter_storm_warning' },
  reasons: [
    { kind: 'snow_total', points: 16, low: 6, high: 9, overnight: true },
    { kind: 'neighbors', points: 9, districts: [1, 2], status: 0 },
    {
      kind: 'timing',
      points: 7,
      start: at('2026-01-13T08:00:00Z'),
      end: at('2026-01-13T11:00:00Z'),
    },
    { kind: 'wind_chill', points: 5, feelsLike: -4 },
    { kind: 'snow_stops', points: -3, at: at('2026-01-13T13:00:00Z') },
  ],
};

/** Shawnee Mission's last five storms of 6 inches or more: four closed, one delayed. */
export const A_RECORD: RecordDetail = {
  proves: 'snow_total',
  inches: 6,
  days: [
    { day: '2024-01-09', inches: 8, status: 0 },
    { day: '2025-01-06', inches: 10, status: 0 },
    { day: '2025-01-10', inches: 6, status: 0 },
    { day: '2025-02-05', inches: 6, status: 1 },
    { day: '2025-02-18', inches: 7, status: 0 },
  ],
};

export const A_DETAIL: ForecastDetail = {
  previous: { noSchool: 0.41, at: at('2026-01-12T23:00:00Z') },
  announcesAt: at('2026-01-13T11:30:00Z'),
  busesAt: at('2026-01-13T13:00:00Z'),
  hours: {
    kind: 'snow_total',
    start: at('2026-01-13T03:00:00Z'),
    values: [0, 0, 0.2, 0.6, 1.1, 1.8, 3.3, 4.8, 6.3, 7.1, 7.5],
    range: { low: 6, high: 9 },
    heavy: { first: 6, last: 8 },
  },
  why: A_WHY,
  record: A_RECORD,
  events: [],
};

export const B_DETAIL: ForecastDetail = {
  previous: { noSchool: 0.3, at: at('2026-01-13T03:00:00Z') },
  announcesAt: at('2026-01-14T11:30:00Z'),
  busesAt: at('2026-01-14T13:00:00Z'),
  hours: {
    kind: 'wind_chill',
    start: at('2026-01-14T03:00:00Z'),
    values: [-1, -2, -3, -3, -4, -5, -6, -6, -7, -8, -8],
    range: null,
    heavy: null,
  },
  why: {
    base: { kind: 'day_after', points: 25 },
    reasons: [
      { kind: 'snow_stops', points: -8, at: at('2026-01-13T12:00:00Z') },
      { kind: 'cold', points: 6, feelsLike: -8 },
      { kind: 'sun', points: -5 },
      { kind: 'icy_roads', points: 4, inches: 8 },
    ],
  },
  record: {
    proves: 'base',
    inches: null,
    days: [
      { day: '2024-01-10', inches: null, status: null },
      { day: '2025-01-07', inches: null, status: 0 },
      { day: '2025-01-13', inches: null, status: null },
      { day: '2025-02-19', inches: null, status: null },
    ],
  },
  events: [{ kind: 'snow_stopped', at: at('2026-01-13T12:00:00Z'), inches: 8 }],
};

/** The night before, with Tuesday's forecast as `detail` gives it. */
export function nightOutlook(detail: ForecastDetail = A_DETAIL): Outlook {
  return {
    today: { state: 'no_threat' },
    tomorrow: {
      state: 'forecast',
      noSchool: 0.64,
      delay: 0.18,
      reasons: [0, 2],
      day: '2026-01-13',
      detail,
    },
    neighbors: [1, 2],
    timeZone: ZONE,
  };
}

export const A_OUTLOOK: Outlook = nightOutlook();

export const B_OUTLOOK: Outlook = {
  today: { state: 'forecast', noSchool: 0.97, delay: 0.02, reasons: [0], day: '2026-01-13' },
  tomorrow: {
    state: 'forecast',
    noSchool: 0.22,
    delay: 0.31,
    reasons: [2, 0],
    day: '2026-01-14',
    detail: B_DETAIL,
  },
  neighbors: [1, 2],
  timeZone: ZONE,
};

/**
 * The evening's live file at 9:00 PM: Blue Valley's two schools canceled Tuesday at 8:41 PM
 * (one of them posted again later), Olathe's at 8:52 PM, De Soto (not next door) at 8:30 PM.
 */
export const A_CLOSINGS: ClosingsFile = {
  schema_version: 1,
  generated_at: '2026-01-13T03:00:00Z',
  directory: STAMP,
  days: [
    {
      day: '2026-01-13',
      gaps: [2, 0, 0, 0],
      statuses: [0, 0, 0, 0],
      announced: [19, 5, 8, 30],
      reasons: [0, 0, 0, 0],
      shifts: [],
      clocks: [],
    },
  ],
};

/** Closed today, as the status block says it. */
export const CLOSED_TODAY: StatusLine = {
  tone: 'closed',
  headline: copy.statusLine.closed.today,
  detail: null,
  note: null,
};
