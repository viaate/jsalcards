/**
 * What a forecast in predictions/latest.json says beyond its chances, for the
 * school panel's chance section (pipeline/snowlight/schemas/predictions.py):
 * the run before, when the district usually announces and its buses run, the
 * night hour by hour, how the chance adds up, the district's record and the
 * weather that already happened.
 *
 * Each part is read on its own and checked here as the schema states it,
 * the checks across parts too: each reason's points on the side its weather
 * pushes, the timing reason on the chart's heaviest hours, the districts next
 * door in the reason among the district's neighbors, and the district's times
 * on the day forecast in its own time zone. A part that is missing or not what
 * the schema says reads as null (an event is left out), and the rest still
 * shows: the headline never waits on a chart. Whether the sum adds up to the
 * chance is the view's to check (app/chance.ts), since that is where the
 * number and its sum meet.
 */

import { format } from '../copy';
import { parseInstant } from '../state/instant';
import type { AlertKind, LocalDate, Status } from '../types/generated';

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const HOUR_MS = 3_600_000;
const MAX_HOURS = 36;
const MAX_INDEX = 4_294_967_294;
const STATUS_COUNT = 4;
/** Status codes (types/generated Status): a closing or a remote day next door only adds. */
const CLOSED = 0;
const REMOTE = 2;
const SCOPES = ['nearby', 'county', 'state', 'region'] as const;
const ALERTS: readonly AlertKind[] = [
  'winter_storm_warning',
  'winter_weather_advisory',
  'ice_storm_warning',
  'blizzard_warning',
  'extreme_cold_warning',
];

/** The run before this one: its chance of no school, and when it was made. */
export interface PreviousRun {
  readonly noSchool: number;
  readonly at: Date;
}

/** One measure an hour, from `start` to the bus hour. */
export interface HoursDetail {
  readonly kind: 'snow_total' | 'wind_chill';
  readonly start: Date;
  readonly values: readonly number[];
  /** The total's range at the bus hour (snow only), or null. */
  readonly range: { readonly low: number; readonly high: number } | null;
  /** The hours the snow falls fastest, by position, or null. */
  readonly heavy: { readonly first: number; readonly last: number } | null;
}

/** Where the districts of a pooled base are, around the district. */
export type PoolScope = (typeof SCOPES)[number];

export type BaseDetail =
  | { readonly kind: 'alert'; readonly points: number; readonly alert: AlertKind }
  | { readonly kind: 'day_after'; readonly points: number }
  | { readonly kind: 'similar_days'; readonly points: number }
  | {
      readonly kind: 'pooled';
      readonly points: number;
      readonly scope: PoolScope;
      readonly alert: AlertKind | null;
    };

export type ReasonDetail =
  | {
      readonly kind: 'snow_total';
      readonly points: number;
      readonly low: number;
      readonly high: number;
      readonly overnight: boolean;
    }
  | { readonly kind: 'record'; readonly points: number }
  | {
      readonly kind: 'neighbors';
      readonly points: number;
      readonly districts: readonly number[];
      readonly status: Status;
    }
  | { readonly kind: 'timing'; readonly points: number; readonly start: Date; readonly end: Date }
  | { readonly kind: 'wind_chill'; readonly points: number; readonly feelsLike: number }
  | { readonly kind: 'cold'; readonly points: number; readonly feelsLike: number }
  | { readonly kind: 'snow_stops'; readonly points: number; readonly at: Date }
  | { readonly kind: 'sun'; readonly points: number }
  | { readonly kind: 'icy_roads'; readonly points: number; readonly inches: number }
  | { readonly kind: 'ice'; readonly points: number; readonly inches: number };

export interface WhyDetail {
  readonly base: BaseDetail;
  readonly reasons: readonly ReasonDetail[];
}

export interface PastDayDetail {
  readonly day: LocalDate;
  readonly inches: number | null;
  /** What the district did; null when it opened. */
  readonly status: Status | null;
}

export interface RecordDetail {
  readonly proves: 'base' | 'snow_total' | 'record';
  readonly inches: number | null;
  readonly days: readonly PastDayDetail[];
}

export type EventDetail =
  | { readonly kind: 'snow_started'; readonly at: Date }
  | { readonly kind: 'snow_stopped'; readonly at: Date; readonly inches: number };

export interface ForecastDetail {
  readonly previous: PreviousRun | null;
  readonly announcesAt: Date | null;
  readonly busesAt: Date | null;
  readonly hours: HoursDetail | null;
  readonly why: WhyDetail | null;
  readonly record: RecordDetail | null;
  readonly events: readonly EventDetail[];
}

export const NO_DETAIL: ForecastDetail = Object.freeze({
  previous: null,
  announcesAt: null,
  busesAt: null,
  hours: null,
  why: null,
  record: null,
  events: [],
});

type Fields = Readonly<Record<string, unknown>>;

function fields(value: unknown): Fields | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Fields)
    : null;
}

function isWhole(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

/** A chance of no school: never a certainty, 0.01 to 0.99. */
function isChance(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0.01 && value <= 0.99;
}

/** A measure in tenths within [min, max]. */
function isTenths(value: unknown, min: number, max: number): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= min &&
    value <= max &&
    Math.abs(Math.round(value * 10) - value * 10) < 1e-9
  );
}

function isInches(value: unknown): value is number {
  return isTenths(value, 0, 120);
}

function isStatus(value: unknown): value is Status {
  return isWhole(value, 0, STATUS_COUNT - 1);
}

function previousOf(value: unknown): PreviousRun | null {
  const run = fields(value);
  const at = parseInstant(run?.at);
  return run !== null && isChance(run.p_no_school) && at !== null
    ? { noSchool: run.p_no_school, at }
    : null;
}

function hoursOf(value: unknown, busesAt: Date | null): HoursDetail | null {
  const series = fields(value);
  if (series === null || busesAt === null) return null;
  const { kind, values, low, high, heavy } = series;
  const start = parseInstant(series.start);
  if (kind !== 'snow_total' && kind !== 'wind_chill') return null;
  if (start === null || start.getTime() % HOUR_MS !== 0) return null;
  if (!Array.isArray(values) || values.length < 2 || values.length > MAX_HOURS) return null;
  if (!values.every((item) => isTenths(item, -80, 130))) return null;
  const numbers = values as readonly number[];
  // The last value is the bus hour's.
  const busHour = Math.floor(busesAt.getTime() / HOUR_MS) * HOUR_MS;
  if (start.getTime() + (numbers.length - 1) * HOUR_MS !== busHour) return null;
  const last = numbers.at(-1) ?? 0;
  if (kind === 'wind_chill') {
    return low === null && high === null && heavy === null
      ? { kind, start, values: numbers, range: null, heavy: null }
      : null;
  }
  if (numbers.some((item, i) => item < 0 || (i > 0 && item < (numbers[i - 1] ?? 0)))) return null;
  let range: HoursDetail['range'] = null;
  if (low !== null || high !== null) {
    if (!isInches(low) || !isInches(high) || !(low <= last && last <= high)) return null;
    range = { low, high };
  }
  let span: HoursDetail['heavy'] = null;
  if (heavy !== null) {
    const lit = fields(heavy);
    const first = lit?.first;
    const final = lit?.last;
    if (!isWhole(first, 1, numbers.length - 1) || !isWhole(final, first, numbers.length - 1)) {
      return null;
    }
    span = { first, last: final };
  }
  return { kind, start, values: numbers, range, heavy: span };
}

function baseOf(value: unknown): BaseDetail | null {
  const base = fields(value);
  if (base === null || !isWhole(base.points, 0, 100)) return null;
  const { points } = base;
  switch (base.kind) {
    case 'alert':
      return ALERTS.includes(base.alert as AlertKind)
        ? { kind: 'alert', points, alert: base.alert as AlertKind }
        : null;
    case 'day_after':
    case 'similar_days':
      return { kind: base.kind, points };
    case 'pooled': {
      const scope = SCOPES.find((item) => item === base.scope);
      const alert = base.alert ?? null;
      if (scope === undefined || (alert !== null && !ALERTS.includes(alert as AlertKind))) {
        return null;
      }
      return { kind: 'pooled', points, scope, alert: alert as AlertKind | null };
    }
    default:
      return null;
  }
}

/** The side each kind's points are on, where its weather only ever pushes one way. */
const ADDS = new Set(['wind_chill', 'cold', 'icy_roads', 'ice']);
const TAKES_AWAY = new Set(['sun']);

function reasonOf(value: unknown, districts: number): ReasonDetail | null {
  const reason = fields(value);
  if (reason === null || !isWhole(reason.points, -100, 100) || reason.points === 0) return null;
  const { points } = reason;
  const kind = String(reason.kind);
  // A sign the weather cannot have: the sum would explain the chance with a false reason.
  if ((ADDS.has(kind) && points < 0) || (TAKES_AWAY.has(kind) && points > 0)) return null;
  switch (reason.kind) {
    case 'snow_total': {
      const { low, high, overnight } = reason;
      return isInches(low) && isInches(high) && low <= high && typeof overnight === 'boolean'
        ? { kind: 'snow_total', points, low, high, overnight }
        : null;
    }
    case 'record':
    case 'sun':
      return { kind: reason.kind, points };
    case 'neighbors': {
      const list = reason.districts;
      if (!Array.isArray(list) || list.length === 0 || !isStatus(reason.status)) return null;
      if (!list.every((item) => isWhole(item, 0, Math.min(districts - 1, MAX_INDEX)))) return null;
      if (new Set(list).size !== list.length) return null;
      if ((reason.status === CLOSED || reason.status === REMOTE) && points < 0) return null;
      return {
        kind: 'neighbors',
        points,
        districts: list,
        status: reason.status,
      };
    }
    case 'timing': {
      const start = parseInstant(reason.start);
      const end = parseInstant(reason.end);
      return start !== null && end !== null && start < end
        ? { kind: 'timing', points, start, end }
        : null;
    }
    case 'wind_chill':
    case 'cold':
      return isWhole(reason.feels_like, -80, 130)
        ? { kind: reason.kind, points, feelsLike: reason.feels_like }
        : null;
    case 'snow_stops': {
      const at = parseInstant(reason.at);
      return at === null ? null : { kind: 'snow_stops', points, at };
    }
    case 'icy_roads':
    case 'ice':
      return isInches(reason.inches) ? { kind: reason.kind, points, inches: reason.inches } : null;
    default:
      return null;
  }
}

/** What a sum's parts are checked against: the district's neighbors, buses and chart. */
interface WhyContext {
  readonly districts: number;
  readonly neighbors: readonly number[];
  readonly busesAt: Date | null;
  readonly hours: HoursDetail | null;
}

/** Whether a reason agrees with the rest of the forecast. */
function agrees(reason: ReasonDetail, context: WhyContext): boolean {
  const { neighbors, busesAt, hours } = context;
  switch (reason.kind) {
    case 'neighbors':
      return reason.districts.every((district) => neighbors.includes(district));
    case 'snow_stops':
      // Snow that stops before the buses only makes the morning easier.
      return busesAt === null || reason.at >= busesAt || reason.points < 0;
    case 'timing': {
      const heavy = hours?.heavy ?? null;
      if (hours === null || heavy === null) return true;
      const from = hours.start.getTime() + (heavy.first - 1) * HOUR_MS;
      const to = hours.start.getTime() + heavy.last * HOUR_MS;
      return reason.start.getTime() === from && reason.end.getTime() === to;
    }
    default:
      return true;
  }
}

/** The sum's parts, all of them read, or null: a sum with a part left out would be false. */
function whyOf(value: unknown, context: WhyContext): WhyDetail | null {
  const why = fields(value);
  const base = baseOf(why?.base);
  const list = why?.reasons;
  if (base === null || !Array.isArray(list)) return null;
  const reasons = list.map((item) => reasonOf(item, context.districts));
  if (!reasons.every((item): item is ReasonDetail => item !== null)) return null;
  if (new Set(reasons.map((item) => item.kind)).size !== reasons.length) return null;
  if (!reasons.every((item) => agrees(item, context))) return null;
  return { base, reasons };
}

function recordOf(value: unknown, day: LocalDate): RecordDetail | null {
  const record = fields(value);
  if (record === null) return null;
  const { proves, inches, days } = record;
  if (proves !== 'base' && proves !== 'snow_total' && proves !== 'record') return null;
  if (inches !== null && !isInches(inches)) return null;
  if (!Array.isArray(days) || days.length === 0 || days.length > 8) return null;
  const read: PastDayDetail[] = [];
  for (const item of days as unknown[]) {
    const past = fields(item);
    const date = past?.day;
    const snow = past?.inches ?? null;
    const status = past?.status ?? null;
    if (typeof date !== 'string' || !LOCAL_DATE.test(date) || date >= day) return null;
    if ((snow !== null && !isInches(snow)) || (status !== null && !isStatus(status))) return null;
    if (read.length > 0 && date <= (read.at(-1)?.day ?? '')) return null;
    read.push({ day: date, inches: snow, status });
  }
  // A record of storms counts storms of at least its inches, and says how much fell each time.
  if (proves !== 'base') {
    if (inches === null) return null;
    if (read.some((past) => past.inches === null || past.inches < inches)) return null;
  }
  return { proves, inches, days: read };
}

function eventsOf(value: unknown, generatedAt: Date): EventDetail[] {
  if (!Array.isArray(value)) return [];
  const events: EventDetail[] = [];
  for (const item of value as unknown[]) {
    const event = fields(item);
    const at = parseInstant(event?.at);
    // Only what has already happened, in time order.
    if (at === null || at > generatedAt || (events.at(-1)?.at ?? at) > at) continue;
    if (event?.kind === 'snow_started') events.push({ kind: 'snow_started', at });
    else if (event?.kind === 'snow_stopped' && isInches(event.inches)) {
      events.push({ kind: 'snow_stopped', at, inches: event.inches });
    }
  }
  return events;
}

/** What a forecast is read against. */
export interface DetailContext {
  /** The day it is for. */
  readonly day: LocalDate;
  /** The directory's district count. */
  readonly districts: number;
  /** The file's time: what already happened is before it. */
  readonly generatedAt: Date;
  /** The district's neighbors, as the file lists them. */
  readonly neighbors: readonly number[];
  /** The district's time zone, where its days and wall-clock times are. */
  readonly timeZone: string;
}

/** The calendar day of an instant in a time zone, or null. */
function dayIn(instant: Date, timeZone: string): LocalDate | null {
  try {
    return format.localDay(instant, timeZone);
  } catch {
    return null;
  }
}

/** The calendar day before `day` (YYYY-MM-DD). */
function dayBefore(day: LocalDate): LocalDate {
  return new Date(Date.parse(`${day}T00:00:00Z`) - 24 * HOUR_MS).toISOString().slice(0, 10);
}

/**
 * The chance section's parts of one forecast, each checked on its own and
 * against the rest: the buses run on the day forecast and the district
 * announces that day or the evening before, before its buses, in its own
 * time zone; a time that does not reads as null.
 */
export function forecastDetail(value: unknown, context: DetailContext): ForecastDetail {
  const { day, generatedAt, timeZone } = context;
  const forecast = fields(value);
  if (forecast === null) return NO_DETAIL;
  const buses = parseInstant(forecast.buses_at);
  const busesAt = buses !== null && dayIn(buses, timeZone) === day ? buses : null;
  const announces = parseInstant(forecast.announces_at);
  const announceDay = announces === null ? null : dayIn(announces, timeZone);
  const announcesAt =
    announces !== null &&
    (announceDay === day || announceDay === dayBefore(day)) &&
    (busesAt === null || announces < busesAt)
      ? announces
      : null;
  const previous = previousOf(forecast.previous);
  const hours = hoursOf(forecast.hours, busesAt);
  return {
    previous: previous !== null && previous.at < generatedAt ? previous : null,
    announcesAt,
    busesAt,
    hours,
    why: whyOf(forecast.why, { ...context, busesAt, hours }),
    record: recordOf(forecast.record, day),
    events: eventsOf(forecast.events, generatedAt),
  };
}

/** A district's neighbors, as the file lists them: other districts in the directory, or none. */
export function neighborsOf(value: unknown, district: number, districts: number): number[] {
  if (!Array.isArray(value)) return [];
  const list = value.filter(
    (item): item is number => isWhole(item, 0, districts - 1) && item !== district,
  );
  return [...new Set(list)];
}
