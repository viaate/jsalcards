/**
 * live/closings.json, read for the map: which schools glow, in which color.
 *
 * The file groups schools by local day: each school has a row on its local
 * today and, once announced, tomorrow. Each school glows with its row on its
 * MAP DAY (data/map-day.ts): its own today until 3:30 PM on its clock, its
 * own tomorrow from then, in its district's time zone as the predictions file
 * gives it; and only with that row, never another day's. A school with no
 * time zone known shows the day that is today in every contiguous US time
 * zone, UTC-4 to UTC-8 (todayEverywhere), and nothing in the four hours
 * between, when the East has moved on to the next day and the West has not.
 *
 * A file that does not match its schema, or whose stamp names another
 * directory, is not read at all: nothing is shown from it.
 */

import { showsSchool, showsStatus } from '../state/filter';
import type { MapFilter } from '../state/filter';
import { parseInstant } from '../state/instant';
import { Status } from '../types/generated';
import type {
  ClosingsDay,
  ClosingsFile,
  DirectoryStamp,
  LocalDate,
  SchoolId,
} from '../types/generated';
import { sameDirectory } from './directory';
import type { Directory } from './directory';
import { mapDay, schoolZone, todayEverywhere, zonesFor } from './map-day';
import type { MapZones, ToldZones } from './map-day';

export { todayEverywhere };

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
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
  // The rows the site's team set by hand, by position: ascending, each a row of the day.
  // A file written before the column existed has none.
  const { manual } = group;
  if (manual === undefined) return { ...(value as ClosingsDay), manual: [] };
  if (!isArray(manual)) return null;
  let last = -1;
  for (const position of manual) {
    if (!isWhole(position, last + 1, rows - 1)) return null;
    last = position;
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
  const groups: ClosingsDay[] = [];
  for (const day of days) {
    const group = parseDay(day);
    // Sorted, one group per day.
    if (group === null || group.day <= previous) return null;
    previous = group.day;
    groups.push(group);
  }
  return groups.every((group, i) => group === days[i])
    ? (value as ClosingsFile)
    : { ...(value as ClosingsFile), days: groups };
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
  /**
   * Where every school of the directory `schools` point into is, in
   * millionths of a degree (its own e6, not a copy: `lngLat` is read from
   * it), so the glow finds the schools at a lit school's place
   * (map/same-places.ts). Absent with nothing lit.
   */
  readonly places?: Int32Array;
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
  /** Now, to decide each school's map day. */
  readonly now: Date;
  /** The schools lit before, or null on the first load: only schools new since then pulse. */
  readonly previous: ReadonlySet<number> | null;
  /** performance.now() of this update, the moment new schools pulse in. */
  readonly bornMs: number;
  /**
   * Each school's time zone, from the predictions file read against this
   * file's directory; absent (or null) in a build that ships none, when every
   * school shows the day that is today everywhere. Zones read against another
   * directory light nothing: a school's position means nothing in it.
   */
  readonly zones?: MapZones | null;
  /**
   * Whether the build ships a predictions file whose zones cannot be had: each
   * school in the contiguous US then shows the map day every contiguous US
   * clock agrees on, while it is today everywhere, and none while they differ
   * (map-day.ts UNREAD_ZONE); a school outside it shows none. `zones` is not read.
   */
  readonly unread?: boolean;
  /**
   * The rows the map has accounted for, by day, school positions (Lit.seen of
   * the light before): with it, a school pulses in only for a row it did not
   * have (a newly announced one), never for one it had, that its map day
   * turning to it now shows. Without it, a school pulses in when it was not
   * lit before (`previous`).
   */
  readonly seen?: ReadonlyMap<LocalDate, ReadonlySet<number>> | null;
}

/** The rows of a file, by day: each day's school positions. */
export function rowsByDay(closings: ClosingsFile): ReadonlyMap<LocalDate, ReadonlySet<number>> {
  return new Map(closings.days.map((group) => [group.day, new Set(decodeDay(group).schools)]));
}

/** The schools lit, and the rows the map has now accounted for (LightOptions.seen). */
export interface Lit {
  readonly lit: LitSchools;
  /**
   * The file's rows whose school's map day could be told, lit or not, and the
   * rows accounted for before that still could not be: a row first seen while
   * its school's day could not be told (no zones, overnight) still pulses in
   * once it can be, as a row newly announced. On a first light (`previous`
   * null) every row of the file, for nothing pulses on a first light.
   */
  readonly seen: ReadonlyMap<LocalDate, ReadonlySet<number>>;
  /** Whether some row's school had no day to be told (map-day.ts mapDay null): it shows none. */
  readonly untold: boolean;
}

/** The zones a light is told by: LightOptions' zones, or none to be had (unread). */
function toldOf(options: LightOptions): ToldZones {
  return options.unread === true ? undefined : (options.zones ?? null);
}

/**
 * The schools to light now: each school with a row on its own map day
 * (data/map-day.ts), at its place in the directory, with that row's status.
 * Nothing when the file, or the zones, are for another directory, or any day
 * of the file has a row past the end of the directory (a broken file).
 */
export function lightSchools(
  closings: ClosingsFile,
  directory: Directory,
  options: LightOptions,
): LitSchools {
  return lightAndSee(closings, directory, options).lit;
}

/** The schools to light now (lightSchools), and the rows accounted for (Lit.seen). */
export function lightAndSee(
  closings: ClosingsFile,
  directory: Directory,
  options: LightOptions,
): Lit {
  const told = toldOf(options);
  const before = options.seen ?? null;
  const first = options.previous === null;
  const none: Lit = {
    lit: NOTHING_LIT,
    seen: first ? rowsByDay(closings) : (before ?? new Map()),
    untold: false,
  };
  if (!sameDirectory(directory, closings.directory)) return none;
  if (told !== null && told !== undefined && !zonesFor(told, closings.directory)) return none;
  const { now } = options;
  // Each zone's map day, worked out once: a file names a handful of zones.
  const days = new Map<string | null, LocalDate | null>();
  const dayIn = (zone: string | null): LocalDate | null => {
    let day = days.get(zone);
    if (day === undefined) {
      day = mapDay(now, zone);
      days.set(zone, day);
    }
    return day;
  };
  const picked: { school: number; status: number; day: LocalDate }[] = [];
  const seen = new Map<LocalDate, Set<number>>();
  let untold = false;
  for (const group of closings.days) {
    const rows = decodeDay(group);
    // Rows past the end of the directory mean a broken file: none of it is read.
    if ((rows.schools[rows.schools.length - 1] ?? 0) >= directory.count) return none;
    const accounted = new Set<number>();
    const had = before?.get(group.day);
    seen.set(group.day, accounted);
    for (let i = 0; i < rows.schools.length; i++) {
      const school = rows.schools[i] ?? 0;
      const zone = schoolZone(
        told,
        school,
        directory.district[school] ?? -1,
        directory.lngLat[school * 2] ?? Number.NaN,
        directory.lngLat[school * 2 + 1] ?? Number.NaN,
      );
      const day = dayIn(zone);
      if (day === null) untold = true;
      if (first || day !== null || had?.has(school) === true) accounted.add(school);
      if (day === group.day) {
        picked.push({ school, status: rows.statuses[i] ?? 0, day: group.day });
      }
    }
  }
  if (picked.length === 0) return { lit: NOTHING_LIT, seen, untold };
  // One row a school at most (its map day's), in school order as a day's rows are.
  picked.sort((a, b) => a.school - b.school);
  const schools = Uint32Array.from(picked, (row) => row.school);
  const statuses = Uint8Array.from(picked, (row) => row.status);
  const known =
    before === null
      ? undefined
      : (row: number) => before.get(picked[row]?.day ?? '')?.has(schools[row] ?? -1) === true;
  return {
    lit: litRows(directory, schools, statuses, options.previous, options.bornMs, known),
    seen,
    untold,
  };
}

/**
 * The status a school's light shows: its row on its map day (map-day.ts
 * mapDay, by the clock schoolZone tells), or null for none (no row that day,
 * no day to be had, a file for another directory). The lists of schools
 * beside the map (the area panel's, the school panel's nearby) read each
 * school's glyph by it, so a glyph is always the school's light.
 */
export function litStatus(
  closings: ClosingsFile | null,
  directory: DirectoryStamp,
  school: number,
  zone: string | null,
  now: Date,
): Status | null {
  if (closings === null) return null;
  const stamp = closings.directory;
  if (
    stamp.generated_on !== directory.generated_on ||
    stamp.schools !== directory.schools ||
    stamp.districts !== directory.districts
  ) {
    return null;
  }
  const day = mapDay(now, zone);
  const group = day === null ? undefined : closings.days.find((item) => item.day === day);
  if (group === undefined) return null;
  const rows = decodeDay(group);
  let low = 0;
  let high = rows.schools.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const found = rows.schools[middle] ?? 0;
    if (found < school) low = middle + 1;
    else if (found > school) high = middle;
    else return (rows.statuses[middle] ?? null) as Status | null;
  }
  return null;
}

/**
 * The lit schools for rows of school positions, ascending and in the
 * directory, and their statuses: where each is, its kind, id and name. With
 * `previous` null none pulses (no bornAt); else a row pulses in at `bornMs`
 * unless `known` says it was there before (by default: its school was lit,
 * in `previous`). Live (lightSchools) and a replay (data/replay.ts) both
 * light through it.
 */
export function litRows(
  directory: Directory,
  schoolRows: Uint32Array,
  statuses: Uint8Array,
  previous: ReadonlySet<number> | null,
  bornMs: number,
  known?: (row: number) => boolean,
): LitSchools {
  const count = schoolRows.length;
  const lngLat = new Float64Array(count * 2);
  const kinds = new Uint8Array(count);
  const bornAt = previous === null ? undefined : new Float64Array(count);
  const schools = new Set<number>();
  const ids: SchoolId[] = [];
  const names: string[] = [];
  for (let i = 0; i < count; i++) {
    const school = schoolRows[i] ?? 0;
    schools.add(school);
    ids.push(directory.meta.ids[school] ?? '');
    names.push(directory.meta.names[school] ?? '');
    lngLat[i * 2] = directory.lngLat[school * 2] ?? 0;
    lngLat[i * 2 + 1] = directory.lngLat[school * 2 + 1] ?? 0;
    kinds[i] = directory.kind[school] ?? 0;
    if (bornAt !== undefined) {
      const was = known === undefined ? previous?.has(school) === true : known(i);
      bornAt[i] = was ? Number.NaN : bornMs;
    }
  }
  const places = directory.e6;
  return bornAt === undefined
    ? { lngLat, status: statuses, kinds, schools, ids, names, places }
    : { lngLat, status: statuses, kinds, bornAt, schools, ids, names, places };
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
  const places = lit.places === undefined ? {} : { places: lit.places };
  return born === undefined
    ? { lngLat, status, kinds, schools, ids, names, ...places }
    : { lngLat, status, kinds, bornAt: born, schools, ids, names, ...places };
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
