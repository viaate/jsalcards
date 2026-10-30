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
 * on the day forecast in its own time zone. The file leaves every part at its
 * default out (a null, a false, an empty list; base.CompactModel), so a missing
 * part reads as that default; a part that is there but not what the schema says
 * reads as null (an event is left out), and the rest still shows: the headline
 * never waits on a chart. Whether the sum adds up to the
 * chance is the view's to check (app/chance.ts), since that is where the
 * number and its sum meet.
 */

import { format } from '../copy-format';
import { parseInstant } from '../state/instant';
import { nightOf } from './night';
import type { NightDetail } from './night';
import type { AlertKind, CountedWeather, LocalDate, Status } from '../types/generated';

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const HOUR_MS = 3_600_000;
const MAX_HOURS = 36;
const MAX_INDEX = 4_294_967_294;
const STATUS_COUNT = 4;
/** Status codes (types/generated Status): a closing or a remote day next door only adds. */
const CLOSED = 0;
const REMOTE = 2;
const SCOPES = ['nearby', 'county', 'state', 'region', 'nation'] as const;
/** Whose recorded days a pooled base counts: districts', or private schools' only (C3). */
const POOLED_OF = ['districts', 'private_schools'] as const;
const ALERTS: readonly AlertKind[] = [
  'winter_storm_warning',
  'winter_weather_advisory',
  'ice_storm_warning',
  'blizzard_warning',
  'extreme_cold_warning',
];
/**
 * The weather a base with no one alert kind names its days by ("winter advisory days"): every
 * value of the contract's enum, which `satisfies` holds complete, so a new one fails the
 * type check instead of dropping the why section of forecasts that name it.
 */
const WEATHER_KEYS = {
  advisory: true,
  cold: true,
  lake_snow: true,
  tropical: true,
} as const satisfies Record<CountedWeather, true>;
export const WEATHERS = Object.keys(WEATHER_KEYS) as readonly CountedWeather[];

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

/** Whose recorded days a pooled base counts. */
export type PoolOf = (typeof POOLED_OF)[number];

/**
 * Where the chance starts. `borrowed`: the day's own weather (or the day after a snow day)
 * has too few recorded days, so the chance is counted over other recorded days, which the
 * sentence names. `live`: the days counted are days the live pipeline read, not the
 * archive's recorded days, and the sentence says so.
 */
export type BaseDetail =
  | {
      readonly kind: 'alert';
      readonly points: number;
      readonly alert: AlertKind;
      readonly borrowed: boolean;
      readonly live: boolean;
    }
  | { readonly kind: 'day_after'; readonly points: number; readonly live: boolean }
  | {
      readonly kind: 'similar_days';
      readonly points: number;
      /** The weather of the days counted, or null (or missing) for days with no winter alert. */
      readonly weather?: CountedWeather | null;
      readonly borrowed: boolean;
      readonly live: boolean;
    }
  | {
      readonly kind: 'pooled';
      readonly points: number;
      readonly scope: PoolScope;
      readonly alert: AlertKind | null;
      /** With no alert, the weather of the days counted (null or missing: no winter alert). */
      readonly weather?: CountedWeather | null;
      readonly borrowed: boolean;
      readonly live: boolean;
      /** Whose days: districts', or private schools' only (a private school's chance). */
      readonly of: PoolOf;
    };

export type ReasonDetail =
  | {
      readonly kind: 'snow_total';
      readonly points: number;
      /**
       * The range the line states, or both null: a deciding school's forecast leaves the
       * range the line could state, so it states only the comparison.
       */
      readonly low: number | null;
      readonly high: number | null;
      readonly overnight: boolean;
      /** The recorded days the snow is weighed against, as the pipeline states it. */
      readonly against: 'storms' | 'advisory';
      /** When the forecast the amount is from was issued, or null where the file gives none. */
      readonly at: Date | null;
    }
  | { readonly kind: 'record'; readonly points: number }
  | {
      readonly kind: 'neighbors';
      readonly points: number;
      readonly districts: readonly number[];
      readonly status: Status;
    }
  | { readonly kind: 'timing'; readonly points: number; readonly start: Date; readonly end: Date }
  | {
      readonly kind: 'wind_chill';
      readonly points: number;
      /** How cold it feels, or null where the schools' forecasts do not all read it. */
      readonly feelsLike: number | null;
      /** When the forecast it is from was issued, or null. */
      readonly at: Date | null;
    }
  | { readonly kind: 'cold'; readonly points: number; readonly feelsLike: number }
  | { readonly kind: 'snow_stops'; readonly points: number; readonly at: Date }
  | { readonly kind: 'sun'; readonly points: number }
  | { readonly kind: 'icy_roads'; readonly points: number; readonly inches: number }
  | {
      readonly kind: 'ice';
      readonly points: number;
      /** The ice, or null where the schools' forecasts do not all read it. */
      readonly inches: number | null;
      /** When the forecast it is from was issued, or null. */
      readonly at: Date | null;
    }
  /** The district or the school said school is on: it takes the chance down to the floor. */
  | { readonly kind: 'said_open'; readonly points: number }
  | OutlookDetail;

/** The forecast kind an outlook line reads: snow, ice, or how cold it feels at 7 AM. */
export type OutlookKind = 'snow' | 'ice' | 'feels';

/**
 * The night-before outlook (S7-F, pipeline/snowlight/schemas/predictions.py OutlookReason):
 * before 5 AM on the day with no warning yet, how the cases like this one ended. `c0` and
 * `heads` are what was out at the file's time; `forecast` the forecast's kind and its least
 * and most over the district's schools (null: little or no snow or ice); `like` the cases
 * counted (bucket range and heads-up, 6 for any); `to` the weather class the cases moved the
 * chance toward; `share` the percent of those cases at `scope` whose 5 AM record was `to`.
 * `at` is the forecast's time and `generatedAt` the file's, from which the line's hours come.
 */
export interface OutlookDetail {
  readonly kind: 'outlook';
  readonly points: number;
  readonly c0: 0 | 1;
  readonly heads: number;
  readonly forecast: {
    readonly kind: OutlookKind;
    readonly low: number;
    readonly high: number;
  } | null;
  readonly like: { readonly low: number; readonly high: number; readonly heads: number };
  readonly to: number;
  readonly share: number;
  readonly scope: 'state' | 'region' | 'nation';
  readonly at: Date;
  readonly generatedAt: Date;
}

const OUTLOOK_KINDS: readonly OutlookKind[] = ['snow', 'ice', 'feels'];
const OUTLOOK_SCOPES = ['state', 'region', 'nation'] as const;
const HEADS_UPS = 6;
const BUCKETS = 14;
const CLASSES = 8;

/** An outlook line's forecast range, as the contract states it: null where it is quiet. */
function outlookRange(value: unknown): OutlookDetail['forecast'] | undefined {
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value) || value.length !== 3) return undefined;
  const [kind, low, high] = value as readonly unknown[];
  if (!isWhole(kind, 0, 2) || typeof low !== 'number' || typeof high !== 'number') return undefined;
  if (!Number.isFinite(low) || !Number.isFinite(high) || low > high) return undefined;
  const named = OUTLOOK_KINDS[kind];
  if (named === undefined) return undefined;
  if (named === 'ice') {
    const hundredths = (n: number): boolean => Math.abs(Math.round(n * 100) - n * 100) < 1e-6;
    return low >= 0 && high <= 120 && hundredths(low) && hundredths(high)
      ? { kind: named, low, high }
      : undefined;
  }
  if (!Number.isInteger(low) || !Number.isInteger(high)) return undefined;
  if (named === 'snow') return low >= 0 && high <= 120 ? { kind: named, low, high } : undefined;
  return low >= -80 && high <= 130 ? { kind: named, low, high } : undefined;
}

/** An outlook line, checked as the contract states it, or null. */
function outlookOf(
  reason: Fields,
  points: number,
  times: { readonly forecastAt: Date | null; readonly generatedAt: Date },
): OutlookDetail | null {
  const { now, like, to, share, scope } = reason;
  const { forecastAt, generatedAt } = times;
  // The line names the forecast's time: a file without it says no outlook line truly.
  if (forecastAt === null || forecastAt > generatedAt) return null;
  if (!isWhole(now, 0, 2 * HEADS_UPS - 1) || !isWhole(to, 0, CLASSES - 1)) return null;
  if (!isWhole(share, 1, 100) || !isWhole(scope, 0, 2)) return null;
  const c0 = Math.floor(now / HEADS_UPS);
  if (to === c0 || (c0 !== 0 && c0 !== 1)) return null;
  if (!Array.isArray(like) || like.length !== 3) return null;
  const [low, high, heads] = like as readonly unknown[];
  if (!isWhole(low, 0, BUCKETS - 1) || !isWhole(high, low, BUCKETS - 1)) return null;
  if (!isWhole(heads, 0, HEADS_UPS)) return null;
  const forecast = outlookRange(reason.f);
  if (forecast === undefined) return null;
  const named = OUTLOOK_SCOPES[scope];
  if (named === undefined) return null;
  return {
    kind: 'outlook',
    points,
    c0,
    heads: now % HEADS_UPS,
    forecast,
    like: { low, high, heads },
    to,
    share,
    scope: named,
    at: forecastAt,
    generatedAt,
  };
}

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
  /**
   * The base names the nation because the district's region holds too few recorded days of the
   * weather (`why.base.thin`): few local records. Read from the base alone, so it holds even
   * where the sum's other parts do not read; false where the file does not say it. The panel
   * says it only on a day with a weather alert (app/chance.ts `fewLocalRecords`).
   */
  readonly thin: boolean;
  readonly record: RecordDetail | null;
  readonly events: readonly EventDetail[];
  /** The night chart (data/night.ts), checked as the contract checks it, or null. */
  readonly night: NightDetail | null;
}

export const NO_DETAIL: ForecastDetail = Object.freeze({
  previous: null,
  announcesAt: null,
  busesAt: null,
  hours: null,
  why: null,
  thin: false,
  record: null,
  events: [],
  night: null,
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
  const { kind, values } = series;
  // A compact file leaves a null range and heavy hours out.
  const low = series.low ?? null;
  const high = series.high ?? null;
  const heavy = series.heavy ?? null;
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

/** The weather a base names its days by, as a part of the base only when it names one. */
function weatherOf(named: CountedWeather | null): { readonly weather?: CountedWeather } {
  return named === null ? {} : { weather: named };
}

function baseOf(value: unknown): BaseDetail | null {
  const base = fields(value);
  if (base === null || !isWhole(base.points, 0, 100)) return null;
  const { points } = base;
  // Which days the sentence counts must be known, or it could name the wrong ones: other
  // weather's days, or the archive's recorded days for days read live. A compact file leaves
  // a false flag out; a flag that is there must be a boolean.
  const borrowed = base.borrowed ?? false;
  const live = base.live ?? false;
  if (typeof borrowed !== 'boolean' || typeof live !== 'boolean') return null;
  const lent = borrowed;
  // The weather the days are named by must be one the sentence can say, and a pooled base
  // names its days one way only.
  const weather = base.weather ?? null;
  if (weather !== null && !WEATHERS.includes(weather as CountedWeather)) return null;
  const named = weather as CountedWeather | null;
  switch (base.kind) {
    case 'alert':
      return ALERTS.includes(base.alert as AlertKind)
        ? { kind: 'alert', points, alert: base.alert as AlertKind, borrowed: lent, live }
        : null;
    case 'day_after':
      return { kind: 'day_after', points, live };
    case 'similar_days':
      return { kind: 'similar_days', points, ...weatherOf(named), borrowed: lent, live };
    case 'pooled': {
      const scope = SCOPES.find((item) => item === base.scope);
      const alert = base.alert ?? null;
      const of = POOLED_OF.find((item) => item === (base.of ?? 'districts'));
      if (scope === undefined || (alert !== null && !ALERTS.includes(alert as AlertKind))) {
        return null;
      }
      if (alert !== null && named !== null) return null;
      if (of === undefined) return null;
      return {
        kind: 'pooled',
        points,
        scope,
        alert: alert as AlertKind | null,
        ...weatherOf(named),
        borrowed: lent,
        live,
        of,
      };
    }
    default:
      return null;
  }
}

/** A forecast's issue time: null where the file leaves it out, undefined where it is not one. */
function issuedAt(value: unknown): Date | null | undefined {
  if (value === undefined || value === null) return null;
  return parseInstant(value) ?? undefined;
}

/** The side each kind's points are on, where its weather only ever pushes one way. */
const ADDS = new Set(['wind_chill', 'cold', 'icy_roads', 'ice']);
const TAKES_AWAY = new Set(['sun', 'said_open']);

function reasonOf(
  value: unknown,
  districts: number,
  times: { readonly forecastAt: Date | null; readonly generatedAt: Date },
): ReasonDetail | null {
  const reason = fields(value);
  if (reason === null || !isWhole(reason.points, -100, 100) || reason.points === 0) return null;
  const { points } = reason;
  const kind = String(reason.kind);
  // A sign the weather cannot have: the sum would explain the chance with a false reason.
  if ((ADDS.has(kind) && points < 0) || (TAKES_AWAY.has(kind) && points > 0)) return null;
  switch (reason.kind) {
    case 'snow_total': {
      const { low, high, overnight } = reason;
      // A key the file leaves out is at its default: storms, and no forecast time.
      const against = reason.against ?? 'storms';
      const at = issuedAt(reason.at);
      if (against !== 'storms' && against !== 'advisory') return null;
      if (at === undefined || typeof overnight !== 'boolean') return null;
      // No amount (both keys missing or null): the line states only the comparison, which is
      // of the window's snow, so never "overnight".
      if ((low ?? null) === null && (high ?? null) === null) {
        return overnight
          ? null
          : { kind: 'snow_total', points, low: null, high: null, overnight, against, at };
      }
      return isInches(low) && isInches(high) && low <= high
        ? { kind: 'snow_total', points, low, high, overnight, against, at }
        : null;
    }
    case 'record':
    case 'sun':
    case 'said_open':
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
    case 'wind_chill': {
      const at = issuedAt(reason.at);
      const feelsLike = reason.feels_like ?? null;
      return (feelsLike === null || isWhole(feelsLike, -80, 130)) && at !== undefined
        ? { kind: 'wind_chill', points, feelsLike, at }
        : null;
    }
    case 'cold':
      return isWhole(reason.feels_like, -80, 130)
        ? { kind: 'cold', points, feelsLike: reason.feels_like }
        : null;
    case 'snow_stops': {
      const at = parseInstant(reason.at);
      return at === null ? null : { kind: 'snow_stops', points, at };
    }
    case 'icy_roads':
      return isInches(reason.inches) ? { kind: 'icy_roads', points, inches: reason.inches } : null;
    case 'ice': {
      const at = issuedAt(reason.at);
      const inches = reason.inches ?? null;
      return (inches === null || isInches(inches)) && at !== undefined
        ? { kind: 'ice', points, inches, at }
        : null;
    }
    case 'outlook':
      return outlookOf(reason, points, times);
    default:
      return null;
  }
}

/** What a sum's parts are checked against: the district's neighbors, buses and chart. */
interface WhyContext {
  readonly districts: number;
  readonly forecastAt: Date | null;
  readonly generatedAt: Date;
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
  // A compact file leaves a base with no reasons as the base alone.
  const list = why?.reasons ?? [];
  if (base === null || !Array.isArray(list)) return null;
  const reasons = list.map((item) => reasonOf(item, context.districts, context));
  if (!reasons.every((item): item is ReasonDetail => item !== null)) return null;
  if (new Set(reasons.map((item) => item.kind)).size !== reasons.length) return null;
  if (!reasons.every((item) => agrees(item, context))) return null;
  return { base, reasons };
}

/**
 * Whether a forecast's base says few local records: a pooled base over the nation's recorded
 * days with the flag set, as the contract allows it only there (never one read live). A flag
 * on any other base, or one that is not `true`, says nothing.
 */
function thinOf(value: unknown): boolean {
  const base = fields(fields(value)?.base);
  return (
    base !== null &&
    base.thin === true &&
    base.kind === 'pooled' &&
    base.scope === 'nation' &&
    (base.live ?? false) === false
  );
}

function recordOf(value: unknown, day: LocalDate): RecordDetail | null {
  const record = fields(value);
  if (record === null) return null;
  const { proves, days } = record;
  const inches = record.inches ?? null;
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
  /**
   * When the forecast the file's outlook lines read was issued (its `forecast_at`), or null
   * where the file gives none: an outlook line then does not read, and nor does its sum.
   */
  readonly forecastAt?: Date | null;
  /** The district's neighbors, as the file lists them. */
  readonly neighbors: readonly number[];
  /** The district's time zone, where its days and wall-clock times are. */
  readonly timeZone: string;
  /**
   * The hourly forecast every night chart of the file is from (its `night_at`), or null where
   * the file gives none or gives one that does not read: then no night reads.
   */
  readonly nightAt?: Date | null;
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
    why: whyOf(forecast.why, {
      ...context,
      forecastAt: context.forecastAt ?? null,
      busesAt,
      hours,
    }),
    thin: thinOf(forecast.why),
    record: recordOf(forecast.record, day),
    events: eventsOf(forecast.events, generatedAt),
    night: nightIn(forecast.night, context),
  };
}

/** The forecast's night, or null: whatever fails in reading it, the rest of the forecast stands. */
function nightIn(value: unknown, context: DetailContext): NightDetail | null {
  try {
    return nightOf(value, {
      day: context.day,
      timeZone: context.timeZone,
      generatedAt: context.generatedAt,
      nightAt: context.nightAt ?? null,
    });
  } catch {
    return null;
  }
}

/** A district's neighbors, as the file lists them: other districts in the directory, or none. */
export function neighborsOf(value: unknown, district: number, districts: number): number[] {
  if (!Array.isArray(value)) return [];
  const list = value.filter(
    (item): item is number => isWhole(item, 0, districts - 1) && item !== district,
  );
  return [...new Set(list)];
}
