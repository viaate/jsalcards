/**
 * The night chart (option (iv), pipeline/snowlight/schemas/predictions.py NightSnow; docs/predict.md
 * "The night chart"): new snow an hour at a time, from the weather service's hourly forecast
 * (NOAA's National Blend of Models), from the first whole hour after the file's time (never
 * before 6 PM the evening before) to 7 AM on the day, at every public school of the district.
 *
 * `nightDay` and `nightOpen` are the TypeScript twins of the contract's `night_day` and
 * `night_open`, held to them by the shared golden file
 * (pipeline/tests/predict/golden/night_day.json). `nightOf` reads one night and checks it the
 * way the contract does; `nightShows` says whether it may show at a moment. Both are total: any
 * failure inside them reads as no chart, so a bad night, or a bug here, never hides a chance,
 * a status or another district (critic 3, B1).
 */

import { format } from '../copy-format';
import type { LocalDate } from '../types/generated';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
/** The night day is the local date of a moment plus this (wall-clock hours). */
const NIGHT_AHEAD_MS = 17 * HOUR_MS;
/** The chart never starts before 6 PM the evening before, and ends at 7 AM on its day. */
const NIGHT_FROM_HOUR = 18;
const NIGHT_END_HOUR = 7;
/** It is written and shown only before 6 AM on its day, so its last hour is still ahead. */
const NIGHT_CLOSE_HOUR = 6;
export const NIGHT_MAX_BARS = 13;
const NIGHT_MAX_LEAST = 99.9;
const NIGHT_MAX_HIGH = 99;
const NIGHT_MIN_INCHES = 1;
const NIGHT_TENTHS_BELOW = 2;
/** The pipeline charts from a cycle at most this old (generated_at - night_at). */
export const NIGHT_MAX_AGE_MS = 150 * MINUTE_MS;
/** The phone shows the chart while its cycle is at most this old: the pipeline's 150 min, plus one
 * missed heartbeat and the file's way to the phone. */
export const CHART_NBM_MAX_AGE_MS = 195 * MINUTE_MS;
/** The phone drops the chart once its first hour is wholly past. */
export const FIRST_HOUR_MS = HOUR_MS;

/** The wall clock of an instant in a time zone, as milliseconds of that day and time in UTC. */
function wallClock(instant: Date, timeZone: string): number {
  const parts = format.dateTimeFormat('clock', timeZone).formatToParts(instant);
  const hour = Number(format.part(parts, 'hour')) % 24;
  const minute = Number(format.part(parts, 'minute'));
  return (
    Date.parse(`${format.localDay(instant, timeZone)}T00:00:00Z`) + (hour * 60 + minute) * MINUTE_MS
  );
}

/** The instant a calendar day's hour strikes in a time zone (two steps settle any offset). */
function atLocal(day: LocalDate, hour: number, timeZone: string): Date {
  const target = Date.parse(`${day}T00:00:00Z`) + hour * HOUR_MS;
  let at = target;
  for (let i = 0; i < 3; i++) at += target - wallClock(new Date(at), timeZone);
  return new Date(at);
}

function dayBefore(day: LocalDate): LocalDate {
  return new Date(Date.parse(`${day}T00:00:00Z`) - DAY_MS).toISOString().slice(0, 10);
}

/** The school day whose night chart a moment belongs to: its local date plus 17 wall-clock hours. */
export function nightDay(moment: Date, timeZone: string): LocalDate {
  const seconds = moment.getUTCSeconds() * 1000 + moment.getUTCMilliseconds();
  return new Date(wallClock(moment, timeZone) + seconds + NIGHT_AHEAD_MS)
    .toISOString()
    .slice(0, 10);
}

/** Whether a moment is inside its night day's window: before 6 AM local on that day. */
export function nightOpen(moment: Date, timeZone: string): boolean {
  return moment < atLocal(nightDay(moment, timeZone), NIGHT_CLOSE_HOUR, timeZone);
}

/** The window for a moment: its night day, Start and End, and the hours between. */
export function nightWindow(
  moment: Date,
  timeZone: string,
): { readonly day: LocalDate; readonly start: Date; readonly end: Date; readonly hours: number } {
  const day = nightDay(moment, timeZone);
  const after = Math.floor(moment.getTime() / HOUR_MS) * HOUR_MS + HOUR_MS;
  const evening = atLocal(dayBefore(day), NIGHT_FROM_HOUR, timeZone).getTime();
  const start = new Date(Math.max(after, evening));
  const end = atLocal(day, NIGHT_END_HOUR, timeZone);
  return {
    day,
    start,
    end,
    hours: Math.max(0, Math.round((end.getTime() - start.getTime()) / HOUR_MS)),
  };
}

/** One night chart, read and checked. Instant k is Start + k hours, from 0 (Start) to `hours`. */
export interface NightDetail {
  readonly day: LocalDate;
  readonly timeZone: string;
  readonly start: Date;
  readonly end: Date;
  /** The bar instants, Start to End: one more than the hours. */
  readonly instants: readonly Date[];
  /** At least this much new snow at every public school from Start to instant k + 1. */
  readonly least: readonly number[];
  /** Every public school's total from Start to End lies in [low, high]; `tenths` when high < 2. */
  readonly range: { readonly low: number; readonly high: number; readonly tenths: boolean };
  /** The heaviest span, by instants (3 or 4 hours apart), with its times; or null. */
  readonly heavy: {
    readonly first: number;
    readonly last: number;
    readonly from: Date;
    readonly to: Date;
  } | null;
  /** The hourly forecast's time (the cycle). */
  readonly nightAt: Date;
}

function isTenths(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    Math.abs(Math.round(value * 10) - value * 10) < 1e-6
  );
}

function isWhole(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

/** What a night is read against: its day, its district's zone, and the file's two times. */
export interface NightContext {
  readonly day: LocalDate;
  readonly timeZone: string;
  readonly generatedAt: Date;
  readonly nightAt: Date | null;
}

function readNight(value: unknown, context: NightContext): NightDetail | null {
  if (typeof value !== 'object' || value === null) return null;
  const night = value as Record<string, unknown>;
  const { day, timeZone, generatedAt, nightAt } = context;
  if (nightAt === null || nightAt > generatedAt) return null;
  if (generatedAt.getTime() - nightAt.getTime() > NIGHT_MAX_AGE_MS) return null;
  const { least, low, high } = night;
  const heavy = night.heavy ?? null;
  // least_bound and least_falls.
  if (!Array.isArray(least) || least.length < 1 || least.length > NIGHT_MAX_BARS) return null;
  const bars = least as unknown[];
  if (!bars.every((bar) => isTenths(bar) && bar >= 0 && bar <= NIGHT_MAX_LEAST)) return null;
  const values = bars as number[];
  for (let i = 1; i < values.length; i++) if ((values[i] ?? 0) < (values[i - 1] ?? 0)) return null;
  // range.
  const last = values.at(-1) ?? 0;
  if (!isTenths(low) || !isTenths(high)) return null;
  if (!(low <= last && last <= high && high <= NIGHT_MAX_HIGH && high >= NIGHT_MIN_INCHES))
    return null;
  const tenths = high < NIGHT_TENTHS_BELOW;
  if (!tenths && (!Number.isInteger(low) || !Number.isInteger(high))) return null;
  // window and bars.
  const window = nightWindow(generatedAt, timeZone);
  if (window.day !== day || !nightOpen(generatedAt, timeZone)) return null;
  if (window.hours !== values.length) return null;
  const instants = Array.from(
    { length: values.length + 1 },
    (_, k) => new Date(window.start.getTime() + k * HOUR_MS),
  );
  // heavy.
  let span: NightDetail['heavy'] = null;
  if (heavy !== null) {
    if (!Array.isArray(heavy) || heavy.length !== 2) return null;
    const [first, end] = heavy as unknown[];
    if (!isWhole(first) || !isWhole(end)) return null;
    if (!(first >= 0 && first < end && end <= values.length)) return null;
    if (end - first !== 3 && end - first !== 4) return null;
    const from = instants[first];
    const to = instants[end];
    if (from === undefined || to === undefined) return null;
    span = { first, last: end, from, to };
  }
  return {
    day,
    timeZone,
    start: window.start,
    end: window.end,
    instants,
    least: values,
    range: { low, high, tenths },
    heavy: span,
    nightAt,
  };
}

/**
 * One district-day's night, checked as the contract checks it (pipeline
 * schemas/predictions.py check_night_fields, check_night and check_night_at), or null: a night
 * that fails any check, or any failure in the reading, is no chart.
 */
export function nightOf(value: unknown, context: NightContext): NightDetail | null {
  if (value === undefined || value === null) return null;
  try {
    return readNight(value, context);
  } catch {
    return null;
  }
}

/**
 * Whether a night may show at `now`: its hourly forecast at most CHART_NBM_MAX_AGE_MS old, its
 * first hour not yet wholly past, and `now` still inside its day's window.
 */
export function nightShows(night: NightDetail, now: Date): boolean {
  try {
    if (now.getTime() - night.nightAt.getTime() > CHART_NBM_MAX_AGE_MS) return false;
    if (now.getTime() >= night.start.getTime() + FIRST_HOUR_MS) return false;
    return nightOpen(now, night.timeZone) && nightDay(now, night.timeZone) === night.day;
  } catch {
    return false;
  }
}

/**
 * The moment a night stops showing (nightShows turns false at it and stays false after, from
 * any moment its file was made): the first of its cycle CHART_NBM_MAX_AGE_MS old, its first hour
 * wholly past, and 6 AM on its day. A panel left open hides the chart at it on its own clock,
 * before its next reading. An unreadable clock gives the night's Start: no chart.
 */
export function nightUntil(night: NightDetail): Date {
  try {
    const close = atLocal(night.day, NIGHT_CLOSE_HOUR, night.timeZone).getTime();
    const until = Math.min(
      // Shown while at most CHART_NBM_MAX_AGE_MS old: the first moment past it.
      night.nightAt.getTime() + CHART_NBM_MAX_AGE_MS + 1,
      night.start.getTime() + FIRST_HOUR_MS,
      close,
    );
    return Number.isFinite(until) ? new Date(until) : night.start;
  } catch {
    return night.start;
  }
}
