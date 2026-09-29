/**
 * The chance section's sentences (ui/ChanceSection.svelte): the part of
 * src/copy.ts that loads with the school panel rather than with the page, so
 * the first paint carries none of it. The same rules hold here as there: every
 * word the section shows is written in this file or in copy.ts (its fixed words
 * are chanceCopy), in the house style, and `npm run lint:copy` reads both as
 * the site's copy (scripts/check-copy.mjs COPY_MODULES).
 *
 * The predictions file sends kinds and numbers, never words
 * (pipeline/snowlight/schemas/predictions.py): each sentence here is written
 * from them. A time is the viewer's wall clock, as every time on the site is.
 */

import {
  checkInstant,
  checkKey,
  clockText,
  copy,
  dateTimeFormat,
  format,
  localDay,
  parseLocalDate,
  part,
} from './copy.ts';
import type { StatusKey } from './copy.ts';

/** Recursively freezes an object graph so no string can be changed at runtime. */
function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

/**
 * The section's fixed words. Its sentences, which carry live values, are the
 * functions of chanceFormat below.
 */
export const chanceCopy = /* @__PURE__ */ deepFreeze({
  /** Before the weekday: "Chance of no school Tuesday". */
  noSchool: 'Chance of no school',
  /** Before the chance: "How we got 64%". */
  howWeGot: 'How we got',
  key: 'Each reason adds or takes away points.',
  start: 'Where we start:',
  /** The chart's titles. */
  snowTitle: 'Snow on the ground, hour by hour',
  coldTonight: 'How cold it will feel tonight',
  coldTitle: 'How cold it will feel, hour by hour',
  /** Under the chart's first hour, when that hour is this one. */
  now: 'Now',
  /** The chart's two moments: "Usually announces 5:30 AM", "Buses 7 AM". */
  usuallyAnnounces: 'Usually announces',
  buses: 'Buses',
  /** Words beside the lit bars: "Heaviest snow 2 to 5 AM". */
  heaviest: 'Heaviest snow',
  /** A day in a district's record, by what it did. */
  open: 'Open',
  closed: 'Closed',
  delayed: 'Delayed',
  remote: 'Remote',
  earlyDismissal: 'Early dismissal',
  /** For a screen reader: the record under a reason. */
  record: 'The district’s record',
});

const NBSP = '\u00a0';
let weekdayFormat: Intl.DateTimeFormat | undefined;
const MS_PER_DAY = 86_400_000;

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
/** A true minus, so a take-away lines up with the pluses: "−3". */
const MINUS = '\u2212';

/** The weather alerts a district's base chance is counted over, as a plural noun. */
const ALERT_PLURALS = {
  winter_storm_warning: 'winter storm warnings',
  winter_weather_advisory: 'winter weather advisories',
  ice_storm_warning: 'ice storm warnings',
  blizzard_warning: 'blizzard warnings',
  extreme_cold_warning: 'extreme cold warnings',
} as const;

export type AlertKind = keyof typeof ALERT_PLURALS;

/** A sentence in two parts: the bold words that lead it, then the rest, which starts with a space. */
export interface Said {
  readonly lead: string;
  readonly rest: string;
}

/** A status a district posted, as the chance section words it. */
export type PostedKey = StatusKey;

/** The base of the sum: where the chance starts for a district. */
export type BaseInput =
  | { readonly kind: 'alert'; readonly points: number; readonly alert: AlertKind }
  | { readonly kind: 'day_after'; readonly points: number }
  | { readonly kind: 'similar_days'; readonly points: number };

/** The district's record in storms like this, counted, for the sentence that cites it. */
export interface RecordCount {
  /** Days with no school (closed or remote). */
  readonly closed: number;
  /** Days counted. */
  readonly days: number;
  /** The least snow of a storm counted. */
  readonly inches: number;
}

/** One reason and what it needs to be said. Times are instants; the viewer's zone words them. */
export type ReasonInput =
  | {
      readonly kind: 'snow_total';
      readonly points: number;
      readonly low: number;
      readonly high: number;
      readonly overnight: boolean;
      /** The record the sentence cites, or null to leave that sentence out. */
      readonly record: RecordCount | null;
    }
  | { readonly kind: 'record'; readonly points: number; readonly record: RecordCount }
  | {
      readonly kind: 'neighbors';
      readonly points: number;
      /** The districts' short names, or null where they cannot be read: then only how many. */
      readonly names: readonly string[] | null;
      readonly count: number;
      readonly status: PostedKey;
    }
  | {
      readonly kind: 'timing';
      readonly points: number;
      readonly start: Date;
      readonly end: Date;
      readonly buses: Date | null;
    }
  | { readonly kind: 'wind_chill'; readonly points: number; readonly feelsLike: number }
  | {
      readonly kind: 'cold';
      readonly points: number;
      readonly feelsLike: number;
      /** The day it is for (YYYY-MM-DD). */
      readonly day: string;
    }
  | {
      readonly kind: 'snow_stops';
      readonly points: number;
      readonly at: Date;
      readonly buses: Date | null;
      /** The day the chance is for (YYYY-MM-DD). */
      readonly day: string;
    }
  | { readonly kind: 'sun'; readonly points: number }
  | { readonly kind: 'icy_roads'; readonly points: number; readonly inches: number }
  | { readonly kind: 'ice'; readonly points: number; readonly inches: number };

/** Where a chance moved from: the run before, and when it was made. */
export interface MovedInput {
  readonly previous: number;
  readonly current: number;
  readonly at: Date;
  readonly now: Date;
  readonly timeZone: string;
}

/**
 * The hour of the day (0 to 23) an instant falls in, in a time zone. Not words:
 * the chance section's chart uses it to choose which hours to name.
 */
export function localHour(instant: Date, timeZone: string): number {
  const parts = dateTimeFormat('clock', timeZone).formatToParts(checkInstant(instant));
  return Number(part(parts, 'hour')) % 24;
}

/** A calendar day (YYYY-MM-DD) as its weekday: "Tuesday". */
function weekday(localDate: string): string {
  weekdayFormat ??= new Intl.DateTimeFormat('en-US', { weekday: 'long', timeZone: 'UTC' });
  return weekdayFormat.format(parseLocalDate(localDate));
}

/** "Chance of no school Tuesday", for a calendar day. */
function chanceOn(localDate: string): string {
  return `${chanceCopy.noSchool} ${weekday(localDate)}`;
}

/** The headline number without its sign: "64", or "<1" and ">99" at the ends, as format.chance() says. */
function chanceNumber(probability: number): string {
  return format.chance(probability).slice(0, -1);
}

/** "How we got 64%". */
function howWeGot(probability: number): string {
  return `${chanceCopy.howWeGot} ${format.chance(probability)}`;
}

/** Whole percentage points with their sign: "+16", "−3". */
function points(n: number): string {
  if (!Number.isInteger(n) || n === 0) {
    throw new RangeError(`copy: points are a whole number other than 0, not ${String(n)}`);
  }
  return n > 0 ? `+${String(n)}` : `${MINUS}${String(-n)}`;
}

/** A time of day, to the minute only where it is not on the hour: "5 PM", "5:30 AM". */
function shortTime(instant: Date, timeZone: string): string {
  const parts = dateTimeFormat('clock', timeZone).formatToParts(checkInstant(instant));
  const hour24 = Number(part(parts, 'hour')) % 24;
  const minute = Number(part(parts, 'minute'));
  if (minute !== 0) return clockText(hour24, minute);
  const hour = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${String(hour)}${NBSP}${hour24 < 12 ? 'AM' : 'PM'}`;
}

/** Hours from one time to another: "2 to 5 AM", "11 PM to 2 AM", "2:30 to 5 AM". */
function hourSpan(start: Date, end: Date, timeZone: string): string {
  const from = shortTime(start, timeZone);
  const to = shortTime(end, timeZone);
  const half = (text: string): string => text.slice(-2);
  const bare = (text: string): string => text.slice(0, -3);
  return half(from) === half(to) ? `${bare(from)} to ${to}` : `${from} to ${to}`;
}

/** The local calendar day of an instant (YYYY-MM-DD). */
function dayOf(instant: Date, timeZone: string): string {
  return localDay(instant, timeZone);
}

/**
 * Which way the chance moved since the run before, and from what:
 * "Up from 41% at 5 PM", "Down from 30% last night", "Up from 12% yesterday",
 * "Down from 50% on Sunday", "Same as at 5 PM". Null for a run more than six
 * days old, which says nothing about tonight.
 */
function moved(input: MovedInput): string | null {
  const { previous, current, at, now, timeZone } = input;
  const days = Math.round(
    (parseLocalDate(dayOf(now, timeZone)).getTime() -
      parseLocalDate(dayOf(at, timeZone)).getTime()) /
      MS_PER_DAY,
  );
  if (days < 0 || days > 6 || at.getTime() > now.getTime()) return null;
  const hour = localHour(at, timeZone);
  const when =
    days === 0
      ? `at ${shortTime(at, timeZone)}`
      : days === 1
        ? hour >= 17
          ? 'last night'
          : 'yesterday'
        : `on ${weekday(dayOf(at, timeZone))}`;
  const before = Math.round(previous * 100);
  const after = Math.round(current * 100);
  if (before === after) return `Same as ${when}`;
  return `${before < after ? 'Up' : 'Down'} from ${format.chance(previous)} ${when}`;
}

/**
 * How long until a moment, for the district's usual announcement: "in 8h 25m",
 * "in 45m", "in 8h"; with its weekday when it is half a day or more away:
 * "Wednesday, in 23h 10m". Null once the moment has come.
 */
function countdown(at: Date, now: Date, timeZone: string): string | null {
  // Whole minutes still to go, rounded up: 30 seconds before is "in 1m".
  const minutes = Math.ceil((checkInstant(at).getTime() - checkInstant(now).getTime()) / MINUTE_MS);
  if (minutes <= 0) return null;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const span =
    hours === 0
      ? `${String(rest)}m`
      : rest === 0
        ? `${String(hours)}h`
        : `${String(hours)}h ${String(rest)}m`;
  return minutes >= 12 * 60 ? `${weekday(dayOf(at, timeZone))}, in ${span}` : `in ${span}`;
}

/** A moment on the section's timeline: its time within the last day, else its day: "8:41 PM", "Mon, Jan 12". */
function momentTime(instant: Date, now: Date, timeZone: string): string {
  const ago = checkInstant(now).getTime() - checkInstant(instant).getTime();
  return ago < 24 * HOUR_MS
    ? format.time(instant, timeZone)
    : format.day(localDay(instant, timeZone));
}

/** What a district next door posted for a day: "Blue Valley canceled Tuesday". */
function neighborPosted(name: string, status: PostedKey, localDate: string): string {
  const on = weekday(localDate);
  switch (checkKey(copy.status, status, 'status')) {
    case 'closed':
      return `${name} canceled ${on}`;
    case 'delayed':
      return `${name} starts late ${on}`;
    case 'remote':
      return `${name} is remote ${on}`;
    case 'earlyDismissal':
      return `${name} lets out early ${on}`;
  }
}

/** "Shawnee Mission usually announces". */
function usuallyAnnounces(name: string): string {
  return `${name} usually announces`;
}

/** Weather that already happened: "Snow started", "Snow stopped, 8 inches in all". */
function weatherEvent(kind: 'snow_started' | 'snow_stopped', inches: number | null): string {
  if (kind === 'snow_started') return 'Snow started';
  return inches === null ? 'Snow stopped' : `Snow stopped, ${inchWords(inches, inches)} in all`;
}

/** A measure in tenths, without a trailing zero: 7.5, 8. */
function tenths(value: number): string {
  if (!Number.isFinite(value)) throw new RangeError(`copy: ${String(value)} is not a measure`);
  const rounded = Math.round(value * 10) / 10;
  return String(Object.is(rounded, -0) ? 0 : rounded);
}

/** Snow in words: "8 inches", "6 to 9 inches", "1 inch", "0.5 to 1 inch". */
function inchWords(low: number, high: number): string {
  const unit = tenths(high) === '1' ? 'inch' : 'inches';
  return low === high ? `${tenths(high)} ${unit}` : `${tenths(low)} to ${tenths(high)} ${unit}`;
}

/** Snow on the chart: "7.5 in", "6 to 9 in"; the scale's own 0 is "0". */
function inches(low: number, high: number = low): string {
  return low === high ? `${tenths(high)}${NBSP}in` : `${tenths(low)} to ${tenths(high)}${NBSP}in`;
}

/** How cold it feels: "-8 F", "12 F". */
function degrees(value: number): string {
  return `${String(Math.round(value) === 0 ? 0 : Math.round(value))}${NBSP}F`;
}

/** The chart's moments: "Usually announces 5:30 AM", "Buses 7 AM". */
function announcesFlag(instant: Date, timeZone: string): string {
  return `${chanceCopy.usuallyAnnounces} ${shortTime(instant, timeZone)}`;
}

function busesFlag(instant: Date, timeZone: string): string {
  return `${chanceCopy.buses} ${shortTime(instant, timeZone)}`;
}

/** Beside the lit bars: "Heaviest snow 2 to 5 AM". */
function heaviest(start: Date, end: Date, timeZone: string): string {
  return `${chanceCopy.heaviest} ${hourSpan(start, end, timeZone)}`;
}

/** The chart in a sentence, for a screen reader. */
function chartSummary(
  kind: 'snow_total' | 'wind_chill',
  buses: Date,
  low: number,
  high: number,
  timeZone: string,
): string {
  const at = shortTime(buses, timeZone);
  return kind === 'snow_total'
    ? `By ${at}, when the buses run, ${inchWords(low, high)} of snow should be on the ground.`
    : `At ${at}, when the buses run, it will feel like ${degrees(high)}.`;
}

/** The delayed start, as one plain line: "18% chance of a delayed start instead". */
function delayInstead(probability: number): string {
  return `${format.chance(probability)} chance of a delayed start instead`;
}

/**
 * A share as a count a 12-year-old reads at a glance: "3 in 10", "1 in 4",
 * "13 in 20". The simplest fraction within 2 points of it.
 */
function shareOf(percent: number): { some: number; of: number } {
  if (!Number.isInteger(percent) || percent < 1 || percent > 99) {
    throw new RangeError(`copy: a share is 1 to 99 percent, not ${String(percent)}`);
  }
  for (const whole of [2, 3, 4, 5, 10, 20, 25, 50]) {
    const some = Math.round((percent / 100) * whole);
    if (some >= 1 && some < whole && Math.abs(some / whole - percent / 100) <= 0.02) {
      return { some, of: whole };
    }
  }
  return { some: percent, of: 100 };
}

/** The district's record, counted: "It closed 4 of the last 5 times it got 6 inches or more." */
function recordSentence(record: RecordCount, subject: string): string {
  const { closed, days, inches: least } = record;
  if (!Number.isInteger(days) || days < 1 || !Number.isInteger(closed) || closed > days) {
    throw new RangeError(`copy: ${String(closed)} of ${String(days)} is not a record`);
  }
  const storms = `it got ${inchWords(least, least)} or more`;
  if (days === 1) {
    return closed === 1
      ? `${subject} closed the last time ${storms}.`
      : `${subject} stayed open the last time ${storms}.`;
  }
  const count =
    closed === days
      ? `each of the last ${String(days)}`
      : closed === 0
        ? `none of the last ${String(days)}`
        : `${String(closed)} of the last ${String(days)}`;
  return `${subject} closed ${count} times ${storms}.`;
}

/** "Blue Valley and Olathe", "A, B and C", "A, B and 2 more". */
function names(list: readonly string[]): string {
  if (list.length === 0) throw new RangeError('copy: no names to list');
  if (list.length <= 3) {
    return list.length === 1
      ? (list[0] ?? '')
      : `${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}`;
  }
  return `${list.slice(0, 2).join(', ')} and ${String(list.length - 2)} more`;
}

/** Where the sum starts: "Where we start:" and the district's own rate, as a count. */
function baseReason(input: BaseInput, district: string): Said {
  const { points: percent } = input;
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
    throw new RangeError(`copy: a base is 0 to 100 percent, not ${String(percent)}`);
  }
  const extreme = percent === 0 ? 'almost never' : percent === 100 ? 'almost always' : null;
  const share = extreme === null ? shareOf(percent) : null;
  const rate = (noun: string): string =>
    share === null ? '' : `about ${String(share.some)} ${noun}in ${String(share.of)}`;
  let rest: string;
  switch (input.kind) {
    case 'alert': {
      const alerts = ALERT_PLURALS[checkKey(ALERT_PLURALS, input.alert, 'alert')];
      rest =
        extreme === null
          ? `${district} cancels for ${rate('')} ${alerts}.`
          : `${district} ${extreme} cancels for ${alerts}.`;
      break;
    }
    case 'day_after':
      rest =
        extreme === null
          ? `after a snow day, ${district} stays closed the next day ${rate(share?.some === 1 ? 'time ' : 'times ')}.`
          : `after a snow day, ${district} ${extreme} stays closed the next day.`;
      break;
    case 'similar_days':
      rest =
        extreme === null
          ? `on days like this, ${district} closes ${rate(share?.some === 1 ? 'time ' : 'times ')}.`
          : `on days like this, ${district} ${extreme} closes.`;
      break;
  }
  return { lead: chanceCopy.start, rest: ` ${rest}` };
}

/** The relation of the heaviest snow to the buses, as the end of its sentence. */
function timingRest(start: Date, end: Date, buses: Date | null, timeZone: string): string {
  const span = hourSpan(start, end, timeZone);
  if (buses === null) return ` falls from ${span}.`;
  const b = buses.getTime();
  if (start.getTime() > b) return ` falls from ${span}, after the buses are out.`;
  if (end.getTime() > b) return ` falls from ${span}, while the buses are out.`;
  if (b - end.getTime() <= 3 * HOUR_MS) return ` falls from ${span}, just before the buses go out.`;
  return ` falls from ${span}, well before the buses go out.`;
}

/**
 * One reason, as a sentence with its bold lead: "A bigger storm than most," and
 * " 6 to 9 inches overnight. It closed 4 of the last 5 times it got 6 inches or more."
 * `district` is the district's short name; `now` and `timeZone` word the times.
 */
function reason(input: ReasonInput, district: string, now: Date, timeZone: string): Said {
  points(input.points);
  switch (input.kind) {
    case 'snow_total': {
      const cited = input.record === null ? '' : ` ${recordSentence(input.record, 'It')}`;
      return {
        lead: input.points > 0 ? 'A bigger storm than most,' : 'A smaller storm than most,',
        rest: ` ${inchWords(input.low, input.high)}${input.overnight ? ' overnight' : ''}.${cited}`,
      };
    }
    case 'record':
      return { lead: `${district}’s record:`, rest: ` ${recordSentence(input.record, 'it')}` };
    case 'neighbors': {
      const { count, status } = input;
      if (!Number.isInteger(count) || count < 1) {
        throw new RangeError(`copy: ${String(count)} districts next door`);
      }
      const verb = input.names === null ? count === 1 : input.names.length === 1;
      const has = verb ? 'has' : 'have';
      const done = {
        closed: 'already canceled',
        delayed: 'already delayed the start',
        remote: 'already gone remote',
        earlyDismissal: 'already called an early dismissal',
      }[checkKey(copy.status, status, 'status')];
      if (input.names === null || input.names.length === 0) {
        return count === 1
          ? { lead: 'A district next door', rest: ` has ${done}.` }
          : { lead: `${String(count)} districts next door`, rest: ` have ${done}.` };
      }
      return { lead: `${names(input.names)},`, rest: ` next door, ${has} ${done}.` };
    }
    case 'timing':
      if (input.end.getTime() <= input.start.getTime()) {
        throw new RangeError('copy: the heaviest snow ends before it starts');
      }
      return {
        lead: 'The heaviest snow',
        rest: timingRest(input.start, input.end, input.buses, timeZone),
      };
    case 'wind_chill':
      return {
        lead: 'The wind',
        rest: ` will make it feel like ${degrees(input.feelsLike)} at the bus stop.`,
      };
    case 'cold':
      return {
        lead: `It will feel like ${degrees(input.feelsLike)}`,
        rest: ` at the bus stop on ${weekday(input.day)} morning.`,
      };
    case 'snow_stops': {
      const at = shortTime(input.at, timeZone);
      if (input.at.getTime() <= now.getTime()) {
        return dayOf(input.at, timeZone) < input.day
          ? {
              lead: `The snow stopped around ${at},`,
              rest: ' so the plows have all day to clear the roads.',
            }
          : {
              lead: `The snow stopped around ${at},`,
              rest: ' which gives the plows a head start.',
            };
      }
      if (input.buses !== null && input.at.getTime() > input.buses.getTime()) {
        return { lead: `The snow keeps falling until ${at},`, rest: ' after the buses go out.' };
      }
      return {
        lead: `The snow should stop by ${at},`,
        rest: ' which gives the plows a head start.',
      };
    }
    case 'sun': {
      return localHour(now, timeZone) < 15
        ? { lead: 'Sun this afternoon', rest: ' will help the salt melt the ice.' }
        : { lead: 'Sun earlier today', rest: ' helped the salt melt the ice.' };
    }
    case 'icy_roads':
      return {
        lead: 'Some side streets could stay icy',
        rest: ` after ${inchWords(input.inches, input.inches)} of snow.`,
      };
    case 'ice':
      return {
        lead: 'Freezing rain',
        rest: ` could leave ${inchWords(input.inches, input.inches)} of ice on the roads.`,
      };
  }
}

/** A day in a district's record, by what it did: "Closed", "Open". */
function recordOutcome(status: StatusKey | 'open'): string {
  return chanceCopy[checkKey(chanceCopy, status, 'outcome') as 'open'];
}

/** A day in the record for a screen reader: "Closed, Jan 9, 2024, 8 inches". */
function recordDay(status: StatusKey | 'open', localDate: string, snow: number | null): string {
  const said = `${recordOutcome(status)}, ${format.dayWithYear(localDate)}`;
  return snow === null ? said : `${said}, ${inchWords(snow, snow)}`;
}

export const chanceFormat = /* @__PURE__ */ deepFreeze({
  weekday,
  chanceOn,
  chanceNumber,
  howWeGot,
  points,
  shortTime,
  hourSpan,
  moved,
  countdown,
  momentTime,
  neighborPosted,
  usuallyAnnounces,
  weatherEvent,
  inches,
  degrees,
  announcesFlag,
  busesFlag,
  heaviest,
  chartSummary,
  delayInstead,
  shareOf,
  baseReason,
  reason,
  recordOutcome,
  recordDay,
});

export type ChanceFormat = typeof chanceFormat;
