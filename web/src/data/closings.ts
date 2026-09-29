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

import { showsSchool, showsStatus } from '../state/filter';
import type { MapFilter } from '../state/filter';
import { parseInstant } from '../state/instant';
import { Status } from '../types/generated';
import type { ClosingsDay, ClosingsFile, LocalDate, SchoolId } from '../types/generated';
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

/**
 * What the glow layer draws: where each lit school is and its status, and
 * which school each is, for a tap on its light (map/school-taps.ts).
 */
export interface LitSchools {
  /** Longitude, latitude pairs in degrees. */
  readonly lngLat: Float64Array;
  /** One status code per school: 0 closed, 1 delayed, 2 remote, 3 early dismissal. */
  readonly status: Uint8Array;
  /** Each school's kind flags in the directory (0x01 private), for the menu's filter. */
  readonly kinds: Uint8Array;
  /** When each school first lit, as performance.now() ms; NaN for no pulse. Absent on a first load. */
  readonly bornAt?: Float64Array;
  /** The school positions lit, in row order, to tell which are new next time. */
  readonly schools: ReadonlySet<number>;
  /** Each school's id, and its name as the directory writes it. */
  readonly ids: readonly SchoolId[];
  readonly names: readonly string[];
}

export const NOTHING_LIT: LitSchools = Object.freeze({
  lngLat: new Float64Array(0),
  status: new Uint8Array(0),
  kinds: new Uint8Array(0),
  schools: new Set<number>(),
  ids: [],
  names: [],
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
  const kinds = new Uint8Array(count);
  const bornAt = options.previous === null ? undefined : new Float64Array(count);
  const schools = new Set<number>();
  const ids: SchoolId[] = [];
  const names: string[] = [];
  for (let i = 0; i < count; i++) {
    const school = rows.schools[i] ?? 0;
    schools.add(school);
    ids.push(directory.meta.ids[school] ?? '');
    names.push(directory.meta.names[school] ?? '');
    lngLat[i * 2] = directory.lngLat[school * 2] ?? 0;
    lngLat[i * 2 + 1] = directory.lngLat[school * 2 + 1] ?? 0;
    kinds[i] = directory.kind[school] ?? 0;
    if (bornAt !== undefined) {
      bornAt[i] = options.previous?.has(school) === true ? Number.NaN : options.bornMs;
    }
  }
  return bornAt === undefined
    ? { lngLat, status: rows.statuses, kinds, schools, ids, names }
    : { lngLat, status: rows.statuses, kinds, bornAt, schools, ids, names };
}

/**
 * The lit schools the menu's filter keeps on the map: those in a status it
 * shows, at a school of a kind it shows. With `pulse` false none pulses in,
 * as when the filter changes and lights come back that were lit before.
 */
export function filterLit(lit: LitSchools, filter: MapFilter, pulse: boolean): LitSchools {
  const keep: number[] = [];
  const count = lit.status.length;
  for (let i = 0; i < count; i++) {
    if (showsStatus(filter, lit.status[i] ?? 0) && showsSchool(filter, lit.kinds[i] ?? 0)) {
      keep.push(i);
    }
  }
  const bornAt = pulse ? lit.bornAt : undefined;
  if (keep.length === count && bornAt === lit.bornAt) return lit;
  const lngLat = new Float64Array(keep.length * 2);
  const status = new Uint8Array(keep.length);
  const kinds = new Uint8Array(keep.length);
  const born = bornAt === undefined ? undefined : new Float64Array(keep.length);
  const all = [...lit.schools];
  const schools = new Set<number>();
  const ids: SchoolId[] = [];
  const names: string[] = [];
  keep.forEach((row, n) => {
    lngLat[n * 2] = lit.lngLat[row * 2] ?? 0;
    lngLat[n * 2 + 1] = lit.lngLat[row * 2 + 1] ?? 0;
    status[n] = lit.status[row] ?? 0;
    kinds[n] = lit.kinds[row] ?? 0;
    if (born !== undefined) born[n] = bornAt?.[row] ?? Number.NaN;
    const school = all[row];
    if (school !== undefined) schools.add(school);
    ids.push(lit.ids[row] ?? '');
    names.push(lit.names[row] ?? '');
  });
  return born === undefined
    ? { lngLat, status, kinds, schools, ids, names }
    : { lngLat, status, kinds, bornAt: born, schools, ids, names };
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

/**
 * How many of the lit schools of the kinds the menu's filter shows have each
 * status, whichever status it shows: the menu offers each status with its
 * count. Null when none is lit, as countStatuses; all nought when the schools
 * lit are all of a kind it hides.
 */
export function countShown(lit: LitSchools, filter: MapFilter): StatusCounts | null {
  if (lit.status.length === 0) return null;
  const counts: [number, number, number, number] = [0, 0, 0, 0];
  lit.status.forEach((status, row) => {
    if (status < counts.length && showsSchool(filter, lit.kinds[row] ?? 0)) {
      counts[status as Status] += 1;
    }
  });
  return counts;
}

/** Whether two sets of counts say the same. */
export function sameCounts(a: StatusCounts | null, b: StatusCounts | null): boolean {
  if (a === null || b === null) return a === b;
  return a.every((n, code) => n === b[code]);
}
