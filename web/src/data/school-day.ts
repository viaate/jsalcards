/**
 * What a school's detail panel says about today and tomorrow, worked out
 * from the live files, and nothing that they do not say:
 *
 * - its status: a row of live/closings.json on the school's today, and on
 *   the day after; "open" only where live/covered.json says its closings were
 *   checked that same day, and it has no row. Its today is the calendar day
 *   in its district's time zone, where the predictions file gives one, else
 *   the day that is today everywhere in the contiguous US (closings.ts
 *   todayEverywhere, the glow's rule);
 * - its outlook: the chance of no school and of a delayed start today and
 *   tomorrow, in the district's own time zone, from predictions/latest.json,
 *   by its district (a private school, with no district, by its own entry in
 *   the file's schools, in its own time zone), when the file has an entry for
 *   it, is no older than PREDICTIONS_FRESH_MS and is stamped no more than
 *   PREDICTIONS_AHEAD_MS ahead; none otherwise.
 *
 * A file for another directory, a stale file, or a school without its own
 * today (the overnight hours, without a time zone) give nothing rather than
 * anything that could be false.
 */

import { format } from '../copy-format';
import { parseInstant } from '../state/instant';
import { Status } from '../types/generated';
import type {
  ClosingsDay,
  ClosingsFile,
  CoveredFile,
  Detail,
  DayForecast,
  DirectoryStamp,
  LocalDate,
  PredictionsFile,
  Reason,
  ReasonCode,
  SchoolForecast,
} from '../types/generated';
import { decodeDay, todayEverywhere } from './closings';
import { forecastDetail, neighborsOf } from './forecast-detail';
import { UNREAD_ZONE, isIndex, isTimeZone, nextDay, parsePredictions, parseStamp } from './map-day';

export { isTimeZone, parsePredictions };
import type { ForecastDetail } from './forecast-detail';

const DETAIL_COUNT = 22;

/** Three of the pipeline's slowest passes (about every 30 minutes, S8): older, the passes have stopped. */
export const PREDICTIONS_FRESH_MS = 90 * 60_000;
/** A stamp more than this ahead of now is a clock gone wrong, and its file would never go stale. */
export const PREDICTIONS_AHEAD_MS = 15 * 60_000;

export function sameStamp(a: DirectoryStamp, b: DirectoryStamp): boolean {
  return (
    a.generated_on === b.generated_on && a.schools === b.schools && a.districts === b.districts
  );
}

export { nextDay };

/** live/covered.json, checked; null for anything else. */
export function parseCovered(value: unknown): CoveredFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  if (parseStamp(file.directory) === null || !Array.isArray(file.ranges)) return null;
  let previous = -2;
  for (const range of file.ranges as unknown[]) {
    if (!Array.isArray(range) || range.length !== 2) return null;
    const [first, last] = range as unknown[];
    // Sorted, apart and not touching: each set of schools has one encoding.
    if (!isIndex(first) || !isIndex(last) || first > last || first <= previous + 1) return null;
    previous = last;
  }
  return value as CoveredFile;
}

/** Whether the live check reached a school, by binary search over the ranges. */
export function covers(covered: CoveredFile, school: number): boolean {
  let low = 0;
  let high = covered.ranges.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const range = covered.ranges[middle];
    if (range === undefined) return false;
    const [first, last] = range;
    if (school < first) high = middle;
    else if (school > last) low = middle + 1;
    else return true;
  }
  return false;
}

/** A private school's entry in the file, by binary search (the schools are sorted). */
export function schoolEntry(predictions: PredictionsFile, school: number): SchoolForecast | null {
  const schools = predictions.schools ?? [];
  let low = 0;
  let high = schools.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const found = schools[middle];
    if (found === undefined) return null;
    if (found.school < school) low = middle + 1;
    else if (found.school > school) high = middle;
    else return found;
  }
  return null;
}

/** A school's status on one day, as its closings row gives it. */
export interface StatusRow {
  readonly status: Status;
  /** The reason code the row gives: a named Reason, or a code this page has no words for. */
  readonly reason: ReasonCode | null;
  /** When it was posted, or null when the listing gave no time. */
  readonly announcedAt: Date | null;
  /** How late the day starts or how early it ends, for a delay or early dismissal; or null. */
  readonly shiftMinutes: number | null;
  /** The stated opening or dismissal time, minutes after midnight; or null. */
  readonly clockMinute: number | null;
  /** Whether the site's own team set it by hand. */
  readonly manual: boolean;
  /** The plain details its listings state (Detail codes, ascending); empty for none. */
  readonly details: readonly Detail[];
}

export interface SchoolStatus {
  /** Today's row; "open" only when the school was checked today and has none; null when unknown. */
  readonly today: StatusRow | 'open' | null;
  /** Tomorrow's row, once announced; null otherwise (never "open": no day is checked ahead). */
  readonly tomorrow: StatusRow | null;
  /**
   * The rows announced for the days after tomorrow, earliest first (the
   * map's later-day rings, map/later-rings.ts); absent or empty for none.
   */
  readonly later?: readonly LaterRow[];
}

/** A row announced for a day after tomorrow, and its day. */
export interface LaterRow {
  readonly day: LocalDate;
  readonly row: StatusRow;
}

export const NO_STATUS: SchoolStatus = Object.freeze({ today: null, tomorrow: null });

/** The start of the UTC minute a MinutesAgo value names. */
function minuteBefore(generatedAt: string, ago: number): Date | null {
  const generated = parseInstant(generatedAt);
  if (generated === null) return null;
  return new Date((Math.floor(generated.getTime() / 60_000) - ago) * 60_000);
}

/**
 * The details of the row at `position`: the day's details column, read here rather than with
 * the file (data/closings.ts, in the first script), so a file written before the column, or
 * one whose column does not read, gives none. Details only add to a status: a column that
 * does not read never hides one.
 */
function detailsOf(group: ClosingsDay, position: number): readonly Detail[] {
  const column = (group as { readonly details?: unknown }).details;
  if (!Array.isArray(column)) return [];
  let last = -1;
  let found: readonly Detail[] = [];
  for (const entry of column as readonly unknown[]) {
    if (!Array.isArray(entry) || entry.length !== 2) return [];
    const [at, codes] = entry as readonly unknown[];
    if (!isIndex(at) || at <= last || !Array.isArray(codes) || codes.length === 0) return [];
    let previous = -1;
    for (const code of codes as readonly unknown[]) {
      if (!isIndex(code) || code <= previous || code >= DETAIL_COUNT) return [];
      previous = code;
    }
    last = at;
    if (at === position) found = codes as readonly Detail[];
  }
  return found;
}

/** The school's row on `day` (its position in the directory), or null. */
export function rowOn(closings: ClosingsFile, day: LocalDate, school: number): StatusRow | null {
  const group = closings.days.find((item) => item.day === day);
  if (group === undefined) return null;
  const rows = decodeDay(group);
  let low = 0;
  let high = rows.schools.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const found = rows.schools[middle] ?? 0;
    if (found < school) low = middle + 1;
    else if (found > school) high = middle;
    else {
      // shifts and clocks hold one entry for each delayed or early-dismissal row, in row order.
      let slot = -1;
      for (let i = 0; i <= middle; i++) {
        const status = group.statuses[i];
        if (status === Status.delayed || status === Status.early_dismissal) slot++;
      }
      const status = group.statuses[middle] ?? Status.closed;
      const shifted = status === Status.delayed || status === Status.early_dismissal;
      const ago = group.announced[middle] ?? null;
      return {
        status,
        reason: group.reasons[middle] ?? null,
        announcedAt: ago === null ? null : minuteBefore(closings.generated_at, ago),
        shiftMinutes: shifted ? (group.shifts[slot] ?? null) : null,
        clockMinute: shifted ? (group.clocks[slot] ?? null) : null,
        manual: group.manual.includes(middle),
        details: detailsOf(group, middle),
      };
    }
  }
  return null;
}

export interface StatusInput {
  /** The school's position in the directory, and the directory it is from. */
  readonly school: number;
  readonly directory: DirectoryStamp;
  readonly closings: ClosingsFile | null;
  readonly covered: CoveredFile | null;
  readonly now: Date;
  /** Its district's time zone, where the predictions file gives one: its own today. */
  readonly timeZone?: string | null;
}

/**
 * The school's today at a moment: the calendar day in its time zone, or
 * without one, or with one that cannot be read (map-day.ts UNREAD_ZONE), the
 * day that is today everywhere (null overnight): the today the map tells its
 * light by (map-day.ts clockToday). Null for a clock not known.
 */
export function schoolToday(now: Date, timeZone: string | null): LocalDate | null {
  if (timeZone === null || timeZone === UNREAD_ZONE) return todayEverywhere(now);
  try {
    return format.localDay(now, timeZone);
  } catch {
    return null;
  }
}

/** What the live files say about a school today and tomorrow. */
export function schoolStatus(input: StatusInput): SchoolStatus {
  const { school, directory, closings, covered, now } = input;
  const zone = input.timeZone ?? null;
  const today = schoolToday(now, zone);
  if (today === null || closings === null || !sameStamp(closings.directory, directory)) {
    return NO_STATUS;
  }
  const todayRow = rowOn(closings, today, school);
  const tomorrowDay = nextDay(today);
  const tomorrow = rowOn(closings, tomorrowDay, school);
  const later: LaterRow[] = [];
  for (const group of closings.days) {
    if (group.day <= tomorrowDay) continue;
    const row = rowOn(closings, group.day, school);
    if (row !== null) later.push({ day: group.day, row });
  }
  later.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
  // Only where there is one, so a school with none reads as it always has.
  const after = later.length > 0 ? { later } : {};
  if (todayRow !== null) return { today: todayRow, tomorrow, ...after };
  const checked = covered === null ? null : parseInstant(covered.generated_at);
  const open =
    covered !== null &&
    checked !== null &&
    covered.generated_at === closings.generated_at &&
    sameStamp(covered.directory, directory) &&
    schoolToday(checked, zone) === today &&
    checked.getTime() <= now.getTime() &&
    covers(covered, school);
  return { today: open ? 'open' : null, tomorrow, ...after };
}

/** One day's outlook for a school's district. */
export type DayOutlook =
  | {
      readonly state: 'forecast';
      readonly noSchool: number;
      readonly delay: number;
      readonly reasons: readonly Reason[];
      /** The day it is for, and what the chance section shows of it (forecast-detail.ts). */
      readonly day?: LocalDate;
      readonly detail?: ForecastDetail;
    }
  | { readonly state: 'no_threat' };

/**
 * The outlook the panel shows: today and tomorrow in the district's own time
 * zone (tomorrow null when the file stops at today), or null when the files
 * say nothing for this school (no file, no district, no entry for it, a
 * stale or unreadable file). `neighbors` are the districts next door, as the
 * file lists them; `timeZone` is the district's.
 */
export type Outlook = {
  readonly today: DayOutlook;
  readonly tomorrow: DayOutlook | null;
  readonly neighbors?: readonly number[];
  readonly timeZone: string;
  /** When the predictions file it is read from was made. */
  readonly generatedAt?: Date;
} | null;

export interface OutlookInput {
  /** The school's district position, or null for a school outside a district. */
  readonly district: number | null;
  /** The school's own position, for a private school's own outlook (it has no district). */
  readonly school?: number | null;
  readonly directory: DirectoryStamp;
  /** Whether this build ships predictions at all. */
  readonly shipped: boolean;
  /** The file, once read; null when it is not (yet) read or cannot be. */
  readonly predictions: PredictionsFile | null;
  readonly now: Date;
}

function dayOutlook(
  value: DayForecast,
  day: LocalDate,
  file: PredictionsFile,
  context: { readonly neighbors: readonly number[]; readonly timeZone: string },
): DayOutlook {
  switch (value.state) {
    case 'forecast':
      return {
        state: 'forecast',
        noSchool: value.p_no_school,
        delay: value.p_delay,
        reasons: value.reasons,
        day,
        detail: forecastDetail(value, {
          day,
          districts: file.directory.districts,
          generatedAt: parseInstant(file.generated_at) ?? new Date(0),
          forecastAt: parseInstant(file.forecast_at),
          nightAt: parseInstant(file.night_at),
          ...context,
        }),
      };
    case 'no_threat':
      return { state: 'no_threat' };
  }
}

/** The entry the outlook is read from: the district's, or a private school's own. */
interface Entry {
  readonly timeZone: string;
  readonly days: readonly (DayForecast | undefined)[];
  readonly neighbors: readonly number[];
}

function entryOf(input: OutlookInput, predictions: PredictionsFile): Entry | null {
  const { district } = input;
  const districts = predictions.directory.districts;
  if (district !== null) {
    const found = predictions.districts.find((item) => item.district === district);
    if (found === undefined) return null;
    return {
      timeZone: found.time_zone,
      days: found.days,
      neighbors: neighborsOf(
        (found as { readonly neighbors?: unknown }).neighbors,
        district,
        districts,
      ),
    };
  }
  const school = input.school ?? null;
  if (school === null) return null;
  const found = schoolEntry(predictions, school);
  if (found === null) return null;
  const outlooks = predictions.outlooks ?? [];
  const timeZone = (predictions.zones ?? [])[found.zone];
  if (timeZone === undefined) return null;
  return {
    timeZone,
    days: found.days.map((index) => outlooks[index]),
    // A private school's districts next door: none of them is its own.
    neighbors: neighborsOf((found as { readonly neighbors?: unknown }).neighbors, -1, districts),
  };
}

export function schoolOutlook(input: OutlookInput): Outlook {
  const { directory, shipped, predictions, now } = input;
  if (!shipped || (input.district === null && (input.school ?? null) === null)) return null;
  if (predictions === null || !sameStamp(predictions.directory, directory)) return null;
  const generated = parseInstant(predictions.generated_at);
  const age = generated === null ? Number.NaN : now.getTime() - generated.getTime();
  if (!(age <= PREDICTIONS_FRESH_MS && age >= -PREDICTIONS_AHEAD_MS)) return null;
  const entry = entryOf(input, predictions);
  if (entry === null) return null;
  // The unit's own today: its evening is still today, however late it is in the east.
  const { timeZone, neighbors } = entry;
  const today = schoolToday(now, timeZone);
  const at = today === null ? -1 : predictions.days.indexOf(today);
  const first = entry.days[at];
  if (first === undefined) return null;
  const second = entry.days[at + 1];
  const firstDay = predictions.days[at] ?? '';
  const secondDay = predictions.days[at + 1] ?? nextDay(firstDay);
  const context = { neighbors, timeZone };
  return {
    today: dayOutlook(first, firstDay, predictions, context),
    tomorrow: second === undefined ? null : dayOutlook(second, secondDay, predictions, context),
    neighbors,
    timeZone,
    // When the file was made: the share cards say the chance as of then (app/share-card.ts).
    ...(generated === null ? {} : { generatedAt: generated }),
  };
}
