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
 * from them, and a forecast is said as the forecast's claim ("The forecast has
 * the snow ending by 6 AM"), never hedged. Every time is the school's wall
 * clock, in its district's time zone, with the zone's short name after it where
 * the viewer's clock differs ("7 AM CT"): one zone in every sentence.
 */

import { copy, format } from './copy.ts';
import type { StatusKey } from './copy.ts';
import { STATES } from './search/states.ts';

const { checkInstant, checkKey, clockText, dateTimeFormat, localDay, parseLocalDate, part } =
  format;

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
  /** The chart's titles. */
  snowTitle: 'Snow on the ground, hour by hour',
  coldTonight: 'How cold it will feel tonight',
  coldTitle: 'How cold it will feel, hour by hour',
  /** The chart's first hour, when that hour is this one. */
  now: 'Now',
  /** The chart's key: "Usually announces 5:30 AM", "Heaviest snow 2 to 5 AM". */
  usuallyAnnounces: 'Usually announces',
  heaviest: 'Heaviest snow',
});

const NBSP = ' ';
let weekdayFormat: Intl.DateTimeFormat | undefined;
const MS_PER_DAY = 86_400_000;

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
/** A true minus, the one on the site, so a take-away and a cold both line up: "−3", "−8 F". */
const MINUS = '−';
/** The shares a rate is said as, besides "1 in N", the easiest to read first. */
const SHARES: readonly (readonly [some: number, of: number])[] = [
  [1, 2],
  [1, 3],
  [2, 3],
  [1, 4],
  [3, 4],
  [1, 5],
  [2, 5],
  [3, 5],
  [4, 5],
  [1, 10],
  [3, 10],
  [7, 10],
  [9, 10],
  [19, 20],
  [49, 50],
  [99, 100],
];

/** The weather alerts a district's base chance is counted over, as a plural noun. */
const ALERT_PLURALS = {
  winter_storm_warning: 'winter storm warnings',
  winter_weather_advisory: 'winter weather advisories',
  ice_storm_warning: 'ice storm warnings',
  blizzard_warning: 'blizzard warnings',
  extreme_cold_warning: 'extreme cold warnings',
} as const;

export type AlertKind = keyof typeof ALERT_PLURALS;

/** The districts a pooled base counts, as the start of its sentence, around the district's name. */
const POOLS = {
  nearby: (district: string) => `Districts near ${district}`,
  county: (district: string) => `Districts in ${district}’s county`,
  state: (district: string) => `Districts in ${district}’s state`,
  region: (district: string) => `Districts in ${district}’s region`,
} as const;

/** A status a district posted, as the chance section words it. */
export type PostedKey = StatusKey;

/**
 * Where the section's times are said: the school's time zone, and the
 * viewer's, for the school's zone name after a time when their clocks differ.
 */
export interface Zones {
  readonly school: string;
  readonly viewer: string;
}

/** The base of the sum: where the chance starts for a district. */
export type BaseInput =
  | { readonly kind: 'alert'; readonly points: number; readonly alert: AlertKind }
  | { readonly kind: 'day_after'; readonly points: number }
  | { readonly kind: 'similar_days'; readonly points: number }
  | {
      readonly kind: 'pooled';
      readonly points: number;
      readonly scope: keyof typeof POOLS;
      readonly alert: AlertKind | null;
    };

/** The district's record in storms like this, counted, for the sentence that cites it. */
export interface RecordCount {
  /** Days with no school (closed or remote). */
  readonly closed: number;
  /** Of those, the days the district went remote. */
  readonly remote: number;
  /** Days counted. */
  readonly days: number;
  /** The least snow of a storm counted. */
  readonly inches: number;
}

/** One reason and what it needs to be said. Times are instants; the school's zone words them. */
export type ReasonInput =
  | {
      readonly kind: 'snow_total';
      readonly points: number;
      readonly low: number;
      readonly high: number;
      readonly overnight: boolean;
      /** The record the sentence cites, or null to leave that sentence out. */
      readonly record: RecordCount | null;
      /** The chart already says how much: the sentence names the reason alone. */
      readonly said?: boolean;
    }
  | { readonly kind: 'record'; readonly points: number; readonly record: RecordCount }
  | {
      readonly kind: 'neighbors';
      readonly points: number;
      /** The districts' short names, or null where they cannot be read: then only how many. */
      readonly names: readonly string[] | null;
      readonly count: number;
      readonly status: PostedKey;
      /** The timeline already lists who: the sentence names the reason alone. */
      readonly said?: boolean;
      /** The timeline has one of them posting otherwise: what they did goes unsaid, never said two ways. */
      readonly otherwise?: boolean;
    }
  | {
      readonly kind: 'timing';
      readonly points: number;
      readonly start: Date;
      readonly end: Date;
      readonly buses: Date | null;
      /** The chart's key already says the hours. */
      readonly said?: boolean;
    }
  | {
      readonly kind: 'wind_chill';
      readonly points: number;
      readonly feelsLike: number;
      /** The chart already says how cold. */
      readonly said?: boolean;
    }
  | {
      readonly kind: 'cold';
      readonly points: number;
      readonly feelsLike: number;
      /** The day it is for (YYYY-MM-DD). */
      readonly day: string;
      /** The chart already says how cold. */
      readonly said?: boolean;
    }
  | {
      readonly kind: 'snow_stops';
      readonly points: number;
      readonly at: Date;
      readonly buses: Date | null;
      /** The day the chance is for (YYYY-MM-DD). */
      readonly day: string;
      /** The timeline already says when it stopped. */
      readonly said?: boolean;
      /** The chart already says the bus hour. */
      readonly busesSaid?: boolean;
    }
  | {
      readonly kind: 'sun';
      readonly points: number;
      /** The day the chance is for (YYYY-MM-DD): the sun is the afternoon before it. */
      readonly day: string;
    }
  | { readonly kind: 'icy_roads'; readonly points: number; readonly inches: number }
  | { readonly kind: 'ice'; readonly points: number; readonly inches: number };

/** Where a chance moved from: the run before, and when it was made. */
export interface MovedInput {
  readonly previous: number;
  readonly current: number;
  readonly at: Date;
  readonly now: Date;
  readonly zones: Zones;
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

const zoneNames = new Map<string, string>();

/** A time zone's short name: "CT", "ET"; "MST" where it keeps one time all year. */
function zoneName(timeZone: string, at: Date): string {
  let name = zoneNames.get(timeZone);
  if (name === undefined) {
    let parts: Intl.DateTimeFormatPart[];
    try {
      parts = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'shortGeneric',
      }).formatToParts(at);
    } catch {
      parts = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'short' }).formatToParts(
        at,
      );
    }
    name = part(parts, 'timeZoneName');
    zoneNames.set(timeZone, name);
  }
  return name;
}

/**
 * After a school's time, its zone's short name where the viewer's clock
 * reads otherwise at that moment (" CT"); nothing where the clocks agree.
 */
function zoneAfter(at: Date, zones: Zones): string {
  const { school, viewer } = zones;
  if (school === viewer) return '';
  const same =
    shortTime(at, school) === shortTime(at, viewer) &&
    localDay(at, school) === localDay(at, viewer);
  return same ? '' : `${NBSP}${zoneName(school, at)}`;
}

/** A school's time, with its zone where the viewer's differs: "7 AM", "7 AM CT". */
function clock(instant: Date, zones: Zones): string {
  return `${shortTime(instant, zones.school)}${zoneAfter(instant, zones)}`;
}

/** Hours from one time to another: "2 to 5 AM", "11 PM to 2 AM", "2:30 to 5 AM CT". */
function hourSpan(start: Date, end: Date, zones: Zones): string {
  const from = shortTime(start, zones.school);
  const to = shortTime(end, zones.school);
  const half = (text: string): string => text.slice(-2);
  const bare = (text: string): string => text.slice(0, -3);
  const span = half(from) === half(to) ? `${bare(from)} to ${to}` : `${from} to ${to}`;
  return `${span}${zoneAfter(end, zones)}`;
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
  const { previous, current, at, now, zones } = input;
  const zone = zones.school;
  const days = Math.round(
    (parseLocalDate(dayOf(now, zone)).getTime() - parseLocalDate(dayOf(at, zone)).getTime()) /
      MS_PER_DAY,
  );
  if (days < 0 || days > 6 || at.getTime() > now.getTime()) return null;
  const hour = localHour(at, zone);
  const when =
    days === 0
      ? `at ${clock(at, zones)}`
      : days === 1
        ? hour >= 17
          ? 'last night'
          : 'yesterday'
        : `on ${weekday(dayOf(at, zone))}`;
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
  const left = until(at, now);
  if (left === null) return null;
  const span = left.text.replaceAll(NBSP, ' ');
  return left.minutes >= 12 * 60 ? `${weekday(dayOf(at, timeZone))}, in ${span}` : `in ${span}`;
}

/** How long until a moment, unbroken: "8h 25m", "45m", "8h"; null once it has come. */
function until(at: Date, now: Date): { text: string; minutes: number } | null {
  // Whole minutes still to go, rounded up: 30 seconds before is "1m".
  const minutes = Math.ceil((checkInstant(at).getTime() - checkInstant(now).getTime()) / MINUTE_MS);
  if (minutes <= 0) return null;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const text =
    hours === 0
      ? `${String(rest)}m`
      : rest === 0
        ? `${String(hours)}h`
        : `${String(hours)}h${NBSP}${String(rest)}m`;
  return { text, minutes };
}

/** A moment on the section's timeline: its time within the last day, else its day: "8:41 PM", "Mon, Jan 12". */
function momentTime(instant: Date, now: Date, zones: Zones): string {
  const ago = checkInstant(now).getTime() - checkInstant(instant).getTime();
  // A plain space before the zone: in the timeline's narrow first column it takes a line of its own.
  return ago < 24 * HOUR_MS
    ? `${format.time(instant, zones.school)}${zoneAfter(instant, zones).replace(NBSP, ' ')}`
    : format.day(localDay(instant, zones.school));
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

/** A district next door in another state, by its state: "Teton County in Wyoming". */
function inState(name: string, state: string): string {
  const named = STATES.find(([code]) => code === state)?.[1];
  if (named === undefined) throw new RangeError(`copy: no state ${state}`);
  return `${name} in ${named}`;
}

/** A district known by its number alone: "District 300". */
function district(number: string): string {
  return `District ${number}`;
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

/** Snow on the chart: "7.5 in", "6 to 9 in". */
function inches(low: number, high: number = low): string {
  return low === high ? `${tenths(high)}${NBSP}in` : `${tenths(low)} to ${tenths(high)}${NBSP}in`;
}

/** How cold it feels, with the site's one minus sign: "−8 F", "12 F". */
function degrees(value: number): string {
  const whole = Math.round(value);
  return `${whole < 0 ? MINUS : ''}${String(Math.abs(whole))}${NBSP}F`;
}

/** "Usually announces 5:30 AM", then ", in 8h 25m" while to come; one night, so no weekday. */
function announcesKey(instant: Date, zones: Zones, now: Date | null = null): string {
  const key = `${chanceCopy.usuallyAnnounces} ${clock(instant, zones)}`;
  const left = now === null ? null : until(instant, now);
  return left === null ? key : `${key}, in${NBSP}${left.text}`;
}

/** The announcement's words as wide as any countdown on a night of at most 36 hours makes them. */
function announcesWidest(instant: Date, zones: Zones): string {
  return `${chanceCopy.usuallyAnnounces} ${clock(instant, zones)}, in${NBSP}99h${NBSP}59m`;
}

/** The chart's key: "Heaviest snow 2 to 5 AM". */
function heaviestKey(start: Date, end: Date, zones: Zones): string {
  return `${chanceCopy.heaviest} ${hourSpan(start, end, zones)}`;
}

/**
 * The chart's answer, in two parts, the value first: "6 to 9 in" and
 * " when buses run at 7 AM".
 */
function busesKey(value: string, buses: Date, zones: Zones): { value: string; rest: string } {
  return { value, rest: ` when buses run at ${clock(buses, zones)}` };
}

/** The chart in a sentence, for a screen reader. */
function chartSummary(
  kind: 'snow_total' | 'wind_chill',
  buses: Date,
  low: number,
  high: number,
  zones: Zones,
): string {
  const at = clock(buses, zones);
  return kind === 'snow_total'
    ? `By ${at}, when the buses run, the forecast has ${inchWords(low, high)} of snow on the ground.`
    : `At ${at}, when the buses run, the forecast has it feeling like ${degrees(high)}.`;
}

/** The delayed start, as one plain line: "18% chance of a delayed start instead". */
function delayInstead(probability: number): string {
  return `${format.chance(probability)} chance of a delayed start instead`;
}

/** A share read at a glance, true to the whole percent ("3 in 10"), else "more than 3 in 5". */
function shareOf(percent: number): { some: number; of: number; more: boolean } {
  if (!Number.isInteger(percent) || percent < 1 || percent > 99) {
    throw new RangeError(`copy: a share is 1 to 99 percent, not ${String(percent)}`);
  }
  const one = Math.round(100 / percent);
  const shares = [...SHARES, [1, one] as const];
  const exact = shares.find(([some, of]) => Math.round((some * 100) / of) === percent);
  if (exact !== undefined) return { some: exact[0], of: exact[1], more: false };
  let below: readonly [number, number] = [1, 100];
  for (const share of [...SHARES, ...Array.from({ length: 99 }, (_, n) => [1, n + 2] as const)]) {
    const [some, of] = share;
    if ((some * 100) / of <= percent - 0.5 && some / of > below[0] / below[1]) below = share;
  }
  return { some: below[0], of: below[1], more: true };
}

/** The district's record, counted: "It closed 4 of the last 5 times it got 6 inches or more." */
function recordSentence(record: RecordCount, subject: string): string {
  const { closed, remote, days, inches: least } = record;
  if (
    !Number.isInteger(days) ||
    days < 1 ||
    !Number.isInteger(closed) ||
    closed > days ||
    !Number.isInteger(remote) ||
    remote < 0 ||
    remote > closed
  ) {
    throw new RangeError(`copy: ${String(closed)} of ${String(days)} is not a record`);
  }
  const storms = `it got ${inchWords(least, least)} or more`;
  // What it did on those days, and no more: a remote day is not a closing.
  const did = remote === 0 ? 'closed' : remote === closed ? 'went remote' : 'closed or went remote';
  if (days === 1) {
    return closed === 1
      ? `${subject} ${did} the last time ${storms}.`
      : `${subject} stayed open the last time ${storms}.`;
  }
  const count =
    closed === days
      ? `each of the last ${String(days)}`
      : closed === 0
        ? `none of the last ${String(days)}`
        : `${String(closed)} of the last ${String(days)}`;
  return `${subject} ${did} ${count} times ${storms}.`;
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

/** Where the sum starts: the district's own rate, or its neighbors', as a count. */
function baseReason(input: BaseInput, district: string): string {
  const { points: percent } = input;
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
    throw new RangeError(`copy: a base is 0 to 100 percent, not ${String(percent)}`);
  }
  const extreme = percent === 0 ? 'almost never' : percent === 100 ? 'almost always' : null;
  const share = extreme === null ? shareOf(percent) : null;
  const rate = (noun: string): string =>
    share === null
      ? ''
      : `${share.more ? 'more than ' : ''}${String(share.some)} ${noun}in ${String(share.of)}`;
  const times = rate(share?.some === 1 ? 'time ' : 'times ');
  switch (input.kind) {
    case 'alert': {
      const alerts = ALERT_PLURALS[checkKey(ALERT_PLURALS, input.alert, 'alert')];
      return extreme === null
        ? `${district} cancels for ${rate('')} ${alerts}.`
        : `${district} ${extreme} cancels for ${alerts}.`;
    }
    case 'day_after':
      return extreme === null
        ? `After a snow day, ${district} stays closed the next day ${times}.`
        : `After a snow day, ${district} ${extreme} stays closed the next day.`;
    case 'similar_days':
      return extreme === null
        ? `On days like this, ${district} closes ${times}.`
        : `On days like this, ${district} ${extreme} closes.`;
    case 'pooled': {
      const who = POOLS[checkKey(POOLS, input.scope, 'pool')](district);
      if (input.alert !== null) {
        const alerts = ALERT_PLURALS[checkKey(ALERT_PLURALS, input.alert, 'alert')];
        return extreme === null
          ? `${who} close for ${rate('')} ${alerts}.`
          : `${who} ${extreme} close for ${alerts}.`;
      }
      return extreme === null
        ? `${who} close ${times} on days like this.`
        : `${who} ${extreme} close on days like this.`;
    }
  }
}

/** When the heaviest snow falls against the buses: "just before the buses". */
function timingRest(start: Date, end: Date, buses: Date): string {
  const b = buses.getTime();
  if (start.getTime() > b) return 'after the buses are out';
  if (end.getTime() > b) return 'while the buses are out';
  if (b - end.getTime() <= 3 * HOUR_MS) return 'just before the buses';
  return 'well before the buses';
}

/**
 * One reason, as one short sentence: "Blue Valley and Olathe, next door,
 * canceled."; a forecast as the forecast's claim. `district` is the
 * district's short name; `now` and `zones` word the times.
 */
function reason(input: ReasonInput, district: string, now: Date, zones: Zones): string {
  points(input.points);
  const zone = zones.school;
  switch (input.kind) {
    case 'snow_total': {
      const cited = input.record === null ? '' : ` ${recordSentence(input.record, 'It')}`;
      const than = input.points > 0 ? 'more' : 'less';
      if (input.said === true) {
        return `${than === 'more' ? 'More' : 'Less'} snow than most storms.${cited}`;
      }
      const when = input.overnight ? ' overnight' : '';
      return `The forecast has ${inchWords(input.low, input.high)}${when}, ${than} than most storms.${cited}`;
    }
    case 'record':
      return recordSentence(input.record, district);
    case 'neighbors': {
      const { count, status } = input;
      if (!Number.isInteger(count) || count < 1) {
        throw new RangeError(`copy: ${String(count)} districts next door`);
      }
      const done = {
        closed: 'canceled',
        delayed: 'delayed the start',
        remote: 'went remote',
        earlyDismissal: 'called an early dismissal',
      }[checkKey(copy.status, status, 'status')];
      if (input.otherwise === true) {
        return count === 1
          ? 'What a district next door posted.'
          : 'What districts next door posted.';
      }
      if (input.said === true) {
        return count === 1 ? `A district next door ${done}.` : `Districts next door ${done}.`;
      }
      if (input.names === null || input.names.length === 0) {
        return count === 1
          ? `A district next door ${done}.`
          : `${String(count)} districts next door ${done}.`;
      }
      return `${names(input.names)}, next door, ${done}.`;
    }
    case 'timing': {
      if (input.end.getTime() <= input.start.getTime()) {
        throw new RangeError('copy: the heaviest snow ends before it starts');
      }
      const span = hourSpan(input.start, input.end, zones);
      if (input.buses === null) return `The forecast has the heaviest snow ${span}.`;
      const rest = timingRest(input.start, input.end, input.buses);
      return input.said === true
        ? `${chanceCopy.heaviest} ${rest}.`
        : `The forecast has the heaviest snow ${span}, ${rest}.`;
    }
    case 'wind_chill':
      return input.said === true
        ? 'Wind chill at the bus stop.'
        : `The forecast has a wind chill of ${degrees(input.feelsLike)} at the bus stop.`;
    case 'cold':
      return input.said === true
        ? `Cold at the bus stop ${weekday(input.day)} morning.`
        : `The forecast has it feeling like ${degrees(input.feelsLike)} at the bus stop ${weekday(input.day)} morning.`;
    case 'snow_stops': {
      const at = clock(input.at, zones);
      const buses = input.buses?.getTime() ?? null;
      if (input.at.getTime() <= now.getTime()) {
        const full = dayOf(input.at, zone) < input.day;
        if (input.said === true) {
          return full
            ? 'The snow stopped, a full day for the plows.'
            : 'The snow stopped, a head start for the plows.';
        }
        return full
          ? `The snow stopped at ${at}, a full day for the plows.`
          : `The snow stopped at ${at}, a head start for the plows.`;
      }
      if (buses !== null && input.at.getTime() > buses) {
        return `The forecast has snow until ${at}, after the buses go out.`;
      }
      if (buses !== null && input.at.getTime() === buses) {
        return input.busesSaid === true
          ? 'The forecast has the snow ending as the buses go out.'
          : `The forecast has the snow ending at ${at}, as the buses go out.`;
      }
      return `The forecast has the snow ending by ${at}, a head start for the plows.`;
    }
    case 'sun': {
      // The afternoon before the day the chance is for: this afternoon the evening before, but
      // yesterday's once that day has begun.
      const before = dayOf(new Date(parseLocalDate(input.day).getTime() - MS_PER_DAY), 'UTC');
      const today = dayOf(now, zone);
      if (today < before) {
        return `The forecast has sun ${weekday(before)} afternoon to help melt the ice.`;
      }
      if (today > before) {
        return today === input.day
          ? 'Sun yesterday afternoon helped melt the ice.'
          : `Sun ${weekday(before)} afternoon helped melt the ice.`;
      }
      return localHour(now, zone) < 15
        ? 'The forecast has sun this afternoon to help melt the ice.'
        : 'Sun earlier today helped melt the ice.';
    }
    case 'icy_roads':
      return `Side streets stay icy after ${inchWords(input.inches, input.inches)} of snow.`;
    case 'ice':
      return `The forecast has freezing rain leaving ${inchWords(input.inches, input.inches)} of ice.`;
  }
}

export const chanceFormat = /* @__PURE__ */ deepFreeze({
  weekday,
  chanceOn,
  chanceNumber,
  howWeGot,
  points,
  shortTime,
  clock,
  hourSpan,
  moved,
  countdown,
  momentTime,
  neighborPosted,
  inState,
  district,
  usuallyAnnounces,
  weatherEvent,
  inches,
  degrees,
  announcesKey,
  announcesWidest,
  heaviestKey,
  busesKey,
  chartSummary,
  delayInstead,
  shareOf,
  baseReason,
  reason,
});

export type ChanceFormat = typeof chanceFormat;
