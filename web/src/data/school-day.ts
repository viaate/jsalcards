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
 *   by its district, when the file has an entry for it, is no older than
 *   PREDICTIONS_FRESH_MS and is stamped no more than PREDICTIONS_AHEAD_MS
 *   ahead; none otherwise.
 *
 * A file for another directory, a stale file, or a school without its own
 * today (the overnight hours, without a time zone) give nothing rather than
 * anything that could be false.
 */

import { format } from '../copy-format';
import { parseInstant } from '../state/instant';
import { Status } from '../types/generated';
import type {
  ClosingsFile,
  CoveredFile,
  DirectoryStamp,
  LocalDate,
  PredictionsFile,
  Reason,
} from '../types/generated';
import { decodeDay, todayEverywhere } from './closings';
import { forecastDetail, neighborsOf } from './forecast-detail';
import type { ForecastDetail } from './forecast-detail';

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_INDEX = 4_294_967_294;
const REASON_COUNT = 8;
const DAY_MS = 86_400_000;

/** Three of the pipeline's slowest passes (about every 30 minutes, S8): older, the passes have stopped. */
export const PREDICTIONS_FRESH_MS = 90 * 60_000;
/** A stamp more than this ahead of now is a clock gone wrong, and its file would never go stale. */
export const PREDICTIONS_AHEAD_MS = 15 * 60_000;

function isIndex(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= MAX_INDEX;
}

function isProbability(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

/** A chance of no school: never a certainty (0.01 to 0.99), so its sum always shows. */
function isChance(value: unknown): value is number {
  return isProbability(value) && value >= 0.01 && value <= 0.99;
}

const zones = new Map<string, boolean>();

/** An IANA time zone this browser knows: "America/Chicago". */
export function isTimeZone(value: unknown): value is string {
  if (typeof value !== 'string' || value === '') return false;
  let known = zones.get(value);
  if (known === undefined) {
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: value });
      known = true;
    } catch {
      known = false;
    }
    zones.set(value, known);
  }
  return known;
}

function parseStamp(value: unknown): DirectoryStamp | null {
  if (typeof value !== 'object' || value === null) return null;
  const { generated_on: day, schools, districts } = value as Record<string, unknown>;
  if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
  if (!isIndex(schools) || !isIndex(districts)) return null;
  return { generated_on: day, schools, districts };
}

export function sameStamp(a: DirectoryStamp, b: DirectoryStamp): boolean {
  return (
    a.generated_on === b.generated_on && a.schools === b.schools && a.districts === b.districts
  );
}

/** The calendar day after `day` (YYYY-MM-DD). */
export function nextDay(day: LocalDate): LocalDate {
  return new Date(Date.parse(`${day}T00:00:00Z`) + DAY_MS).toISOString().slice(0, 10);
}

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

function parseForecast(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const day = value as Record<string, unknown>;
  switch (day.state) {
    case 'no_threat':
      return true;
    case 'forecast':
      return (
        isChance(day.p_no_school) &&
        isProbability(day.p_delay) &&
        Array.isArray(day.reasons) &&
        day.reasons.every(
          (reason) =>
            typeof reason === 'number' &&
            Number.isInteger(reason) &&
            reason >= 0 &&
            reason < REASON_COUNT,
        )
      );
    default:
      return false;
  }
}

/** predictions/latest.json, checked; null for anything else. */
export function parsePredictions(value: unknown): PredictionsFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  if (parseStamp(file.directory) === null) return null;
  const { days, districts } = file;
  if (!Array.isArray(days) || days.length === 0 || !Array.isArray(districts)) return null;
  let previous = '';
  for (const day of days as unknown[]) {
    // Consecutive days, today first.
    if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
    if (previous !== '' && day !== nextDay(previous)) return null;
    previous = day;
  }
  for (const entry of districts as unknown[]) {
    if (typeof entry !== 'object' || entry === null) return null;
    const { district, time_zone: zone, days: forecasts } = entry as Record<string, unknown>;
    if (!isIndex(district) || !Array.isArray(forecasts) || forecasts.length !== days.length) {
      return null;
    }
    if (!isTimeZone(zone)) return null;
    if (!forecasts.every(parseForecast)) return null;
  }
  return value as PredictionsFile;
}

/** A school's status on one day, as its closings row gives it. */
export interface StatusRow {
  readonly status: Status;
  readonly reason: Reason | null;
  /** When it was posted, or null when the listing gave no time. */
  readonly announcedAt: Date | null;
  /** How late the day starts or how early it ends, for a delay or early dismissal; or null. */
  readonly shiftMinutes: number | null;
  /** The stated opening or dismissal time, minutes after midnight; or null. */
  readonly clockMinute: number | null;
}

export interface SchoolStatus {
  /** Today's row; "open" only when the school was checked today and has none; null when unknown. */
  readonly today: StatusRow | 'open' | null;
  /** Tomorrow's row, once announced; null otherwise (never "open": no day is checked ahead). */
  readonly tomorrow: StatusRow | null;
}

export const NO_STATUS: SchoolStatus = Object.freeze({ today: null, tomorrow: null });

/** The start of the UTC minute a MinutesAgo value names. */
function minuteBefore(generatedAt: string, ago: number): Date | null {
  const generated = parseInstant(generatedAt);
  if (generated === null) return null;
  return new Date((Math.floor(generated.getTime() / 60_000) - ago) * 60_000);
}

/** The school's row on `day`, or null. */
function rowOn(closings: ClosingsFile, day: LocalDate, school: number): StatusRow | null {
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
 * without one the day that is today everywhere (null overnight).
 */
export function schoolToday(now: Date, timeZone: string | null): LocalDate | null {
  if (timeZone === null) return todayEverywhere(now);
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
  const tomorrow = rowOn(closings, nextDay(today), school);
  if (todayRow !== null) return { today: todayRow, tomorrow };
  const checked = covered === null ? null : parseInstant(covered.generated_at);
  const open =
    covered !== null &&
    checked !== null &&
    covered.generated_at === closings.generated_at &&
    sameStamp(covered.directory, directory) &&
    schoolToday(checked, zone) === today &&
    checked.getTime() <= now.getTime() &&
    covers(covered, school);
  return { today: open ? 'open' : null, tomorrow };
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
} | null;

export interface OutlookInput {
  /** The school's district position, or null for a school outside a district. */
  readonly district: number | null;
  readonly directory: DirectoryStamp;
  /** Whether this build ships predictions at all. */
  readonly shipped: boolean;
  /** The file, once read; null when it is not (yet) read or cannot be. */
  readonly predictions: PredictionsFile | null;
  readonly now: Date;
}

function dayOutlook(
  value: PredictionsFile['districts'][number]['days'][number],
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
          ...context,
        }),
      };
    case 'no_threat':
      return { state: 'no_threat' };
  }
}

export function schoolOutlook(input: OutlookInput): Outlook {
  const { district, directory, shipped, predictions, now } = input;
  if (!shipped || district === null) return null;
  if (predictions === null || !sameStamp(predictions.directory, directory)) return null;
  const generated = parseInstant(predictions.generated_at);
  const age = generated === null ? Number.NaN : now.getTime() - generated.getTime();
  if (!(age <= PREDICTIONS_FRESH_MS && age >= -PREDICTIONS_AHEAD_MS)) return null;
  const entry = predictions.districts.find((item) => item.district === district);
  if (entry === undefined) return null;
  // The district's own today: its evening is still today, however late it is in the east.
  const timeZone = entry.time_zone;
  const today = schoolToday(now, timeZone);
  const at = today === null ? -1 : predictions.days.indexOf(today);
  const first = entry.days[at];
  if (first === undefined) return null;
  const second = entry.days[at + 1];
  const firstDay = predictions.days[at] ?? '';
  const secondDay = predictions.days[at + 1] ?? nextDay(firstDay);
  const neighbors = neighborsOf(
    (entry as { readonly neighbors?: unknown }).neighbors,
    district,
    predictions.directory.districts,
  );
  const context = { neighbors, timeZone };
  return {
    today: dayOutlook(first, firstDay, predictions, context),
    tomorrow: second === undefined ? null : dayOutlook(second, secondDay, predictions, context),
    neighbors,
    timeZone,
  };
}
