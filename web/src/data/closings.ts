/**
 * live/closings.json, read for the map: which schools glow, in which color.
 *
 * The file groups schools by local day: each school has a row on its local
 * today and, once announced, tomorrow. The directory does not say which time
 * zone a school is in, so the map shows a day only while it is today in every
 * contiguous US time zone, UTC-4 to UTC-8: from 08:00 UTC to 04:00 UTC the
 * next day. In the four hours between, when the East has moved on to the next
 * day and the West has not, nothing glows rather than a day that is already
 * over, or not yet begun, for some of the schools shown.
 *
 * A file that does not match its schema, or whose stamp names another
 * directory, is not read at all: nothing is shown from it.
 */

import { parseInstant } from '../state/instant';
import { Status } from '../types/generated';
import type { ClosingsDay, ClosingsFile, LocalDate } from '../types/generated';
import { sameDirectory } from './directory';
import type { Directory } from './directory';

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const HOUR_MS = 3_600_000;
/** Eastern Daylight Time, the contiguous US zone furthest ahead of UTC. */
const EAST_OFFSET_HOURS = -4;
/** Pacific Standard Time, the one furthest behind. */
const WEST_OFFSET_HOURS = -8;
const MAX_MINUTES_AGO = 20_160;
const MAX_SHIFT_MINUTES = 720;
const MINUTES_PER_DAY = 1440;
const REASON_COUNT = 8;
const MAX_INDEX = 4_294_967_294;

function isWhole(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function isNullOr(value: unknown, check: (item: unknown) => boolean): boolean {
  return value === null || check(value);
}

function isArray(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

function isStatus(value: unknown): value is Status {
  return isWhole(value, 0, 3);
}

/** Whether a status carries a shift and a clock entry. */
function isShifted(status: Status): boolean {
  return status === Status.delayed || status === Status.early_dismissal;
}

function parseDay(value: unknown): ClosingsDay | null {
  if (typeof value !== 'object' || value === null) return null;
  const group = value as Record<string, unknown>;
  const { day, gaps, statuses, announced, reasons, shifts, clocks } = group;
  if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
  if (!isArray(gaps) || !isArray(statuses) || !isArray(announced) || !isArray(reasons)) {
    return null;
  }
  if (!isArray(shifts) || !isArray(clocks)) return null;
  const rows = gaps.length;
  if (rows === 0 || statuses.length !== rows) return null;
  if (announced.length !== rows || reasons.length !== rows) return null;
  let shifted = 0;
  for (let i = 0; i < rows; i++) {
    const status = statuses[i];
    if (!isWhole(gaps[i], 0, MAX_INDEX) || !isStatus(status)) return null;
    if (!isNullOr(announced[i], (item) => isWhole(item, 0, MAX_MINUTES_AGO))) return null;
    if (!isNullOr(reasons[i], (item) => isWhole(item, 0, REASON_COUNT - 1))) return null;
    if (isShifted(status)) shifted++;
  }
  if (shifts.length !== shifted || clocks.length !== shifted) return null;
  for (let k = 0; k < shifted; k++) {
    if (!isNullOr(shifts[k], (item) => isWhole(item, 1, MAX_SHIFT_MINUTES))) return null;
    if (!isNullOr(clocks[k], (item) => isWhole(item, 0, MINUTES_PER_DAY - 1))) return null;
  }
  return value as ClosingsDay;
}

/** closings.json, checked against its schema; null for anything else. */
export function parseClosings(value: unknown): ClosingsFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  const { directory, days } = file;
  if (typeof directory !== 'object' || directory === null) return null;
  const stamp = directory as Record<string, unknown>;
  if (typeof stamp.generated_on !== 'string' || !LOCAL_DATE.test(stamp.generated_on)) return null;
  if (!isWhole(stamp.schools, 0, MAX_INDEX) || !isWhole(stamp.districts, 0, MAX_INDEX)) {
    return null;
  }
  if (!isArray(days) || days.length > 3) return null;
  let previous = '';
  for (const day of days) {
    const group = parseDay(day);
    // Sorted, one group per day.
    if (group === null || group.day <= previous) return null;
    previous = group.day;
  }
  return value as ClosingsFile;
}

/** One day's rows as arrays: school positions, ascending, and their statuses. */
export interface DayRows {
  readonly day: LocalDate;
  readonly schools: Uint32Array;
  readonly statuses: Uint8Array;
}

/** Turns the gap column back into school positions. */
export function decodeDay(group: ClosingsDay): DayRows {
  const rows = group.gaps.length;
  const schools = new Uint32Array(rows);
  const statuses = new Uint8Array(rows);
  let previous = -1;
  for (let i = 0; i < rows; i++) {
    previous += 1 + (group.gaps[i] ?? 0);
    schools[i] = previous;
    statuses[i] = group.statuses[i] ?? 0;
  }
  return { day: group.day, schools, statuses };
}

function utcDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * The calendar day that is today in every contiguous US time zone at `now`,
 * or null in the hours when the East has reached the next day and the West
 * has not.
 */
export function todayEverywhere(now: Date): LocalDate | null {
  const time = now.getTime();
  if (!Number.isFinite(time)) return null;
  const east = utcDate(time + EAST_OFFSET_HOURS * HOUR_MS);
  const west = utcDate(time + WEST_OFFSET_HOURS * HOUR_MS);
  return east === west ? east : null;
}

/** What the glow layer draws: where each lit school is and its status. */
export interface LitSchools {
  /** Longitude, latitude pairs in degrees. */
  readonly lngLat: Float64Array;
  /** One status code per school: 0 closed, 1 delayed, 2 remote, 3 early dismissal. */
  readonly status: Uint8Array;
  /** When each school first lit, as performance.now() ms; NaN for no pulse. Absent on a first load. */
  readonly bornAt?: Float64Array;
  /** The school positions lit, to tell which are new next time. */
  readonly schools: ReadonlySet<number>;
}

export const NOTHING_LIT: LitSchools = Object.freeze({
  lngLat: new Float64Array(0),
  status: new Uint8Array(0),
  schools: new Set<number>(),
});

export interface LightOptions {
  /** Now, to decide which day is today. */
  readonly now: Date;
  /** The schools lit before, or null on the first load: only schools new since then pulse. */
  readonly previous: ReadonlySet<number> | null;
  /** performance.now() of this update, the moment new schools pulse in. */
  readonly bornMs: number;
}

/**
 * The schools to light today: each school with a row on the day that is
 * today everywhere, at its place in the directory. Nothing when the file is
 * for another directory, today has no rows, or it is the overnight hours.
 */
export function lightSchools(
  closings: ClosingsFile,
  directory: Directory,
  options: LightOptions,
): LitSchools {
  if (!sameDirectory(directory, closings.directory)) return NOTHING_LIT;
  const today = todayEverywhere(options.now);
  const group = closings.days.find((item) => item.day === today);
  if (today === null || group === undefined) return NOTHING_LIT;
  const rows = decodeDay(group);
  const count = rows.schools.length;
  // Rows past the end of the directory mean a broken file: none of it is read.
  if ((rows.schools[count - 1] ?? 0) >= directory.count) return NOTHING_LIT;

  const lngLat = new Float64Array(count * 2);
  const bornAt = options.previous === null ? undefined : new Float64Array(count);
  const schools = new Set<number>();
  for (let i = 0; i < count; i++) {
    const school = rows.schools[i] ?? 0;
    schools.add(school);
    lngLat[i * 2] = directory.lngLat[school * 2] ?? 0;
    lngLat[i * 2 + 1] = directory.lngLat[school * 2 + 1] ?? 0;
    if (bornAt !== undefined) {
      bornAt[i] = options.previous?.has(school) === true ? Number.NaN : options.bornMs;
    }
  }
  return bornAt === undefined
    ? { lngLat, status: rows.statuses, schools }
    : { lngLat, status: rows.statuses, bornAt, schools };
}

/** How many schools the map lights in each status, by status code (closed … early dismissal). */
export type StatusCounts = readonly [number, number, number, number];

/**
 * How many of the lit schools have each status: the schools the map shows,
 * counted, and nothing else. Null when none is lit, so no count is given
 * where the map shows nothing.
 */
export function countStatuses(lit: LitSchools): StatusCounts | null {
  if (lit.status.length === 0) return null;
  const counts: [number, number, number, number] = [0, 0, 0, 0];
  for (const status of lit.status) {
    if (status < counts.length) counts[status as Status] += 1;
  }
  return counts;
}

/** Whether two sets of counts say the same. */
export function sameCounts(a: StatusCounts | null, b: StatusCounts | null): boolean {
  if (a === null || b === null) return a === b;
  return a.every((n, code) => n === b[code]);
}
