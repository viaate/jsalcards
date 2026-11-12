/**
 * The words for closings announced for later days (the map's later-day
 * rings, map/later-rings.ts): the key's "Later days" line under the map's
 * key (ui/LaterKey.svelte). The part of src/copy.ts that loads with the rings
 * rather than with the page. The same rules hold here as there, and
 * `npm run lint:copy` reads this file as the site's copy
 * (scripts/check-copy.mjs COPY_MODULES).
 *
 * A later day is named by its weekday, with how many schools have a status
 * that day after a colon: "Thu: 10", so its count never reads as its date
 * ("Fri 13" would read as Friday the 13th); one six days or more after the
 * map's day by its date too, "Thu, Nov 19: 4", so no weekday reads as the
 * map's own. The days are always named, so no ring is read as one day's.
 */

import { format } from './copy-format.ts';

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

/** A later day and its count of schools with a status that day. */
export interface LaterDayCount {
  /** YYYY-MM-DD. */
  readonly day: string;
  readonly count: number;
}

function whole(n: number): number {
  if (!Number.isInteger(n) || n < 1) {
    throw new RangeError(`copy: a later day counts one school or more, not ${String(n)}`);
  }
  return n;
}

/** The words of the key's line for the rings. */
export const laterCopy = /* @__PURE__ */ deepFreeze({
  /** The line's title, after the ring: "Later days". */
  title: 'Later days',
});

/** From this many days after the map's day on, a later day is dated: its weekday comes round. */
export const DATED_FROM_DAYS = 6;

const DAY_MS = 86_400_000;

/**
 * A later day as the key names it before its count: its short weekday, "Thu:";
 * or its date, "Thu, Nov 19:", from DATED_FROM_DAYS after `from` (the map's
 * day) on, or where `from` is not given.
 */
function day(localDate: string, from?: string): string {
  const at = format.parseLocalDate(localDate);
  const named = near(at, from)
    ? format.dateTimeFormat('weekdayShort', 'UTC').format(at)
    : format.dateTimeFormat('day', 'UTC').format(at);
  return `${named}:`;
}

/** Whether a later day is close enough after `from` to go by its weekday alone. */
function near(at: Date, from: string | undefined): boolean {
  return (
    from !== undefined &&
    at.getTime() - format.parseLocalDate(from).getTime() < DATED_FROM_DAYS * DAY_MS
  );
}

/** A later day's count as the key shows it beside the day: "1,204". */
function count(n: number): string {
  return format.number(whole(n));
}

/**
 * The key's line read whole, for a screen reader: "Later days: Thursday, 10
 * schools; Friday, 8 schools". Each day by its whole weekday, earliest first,
 * and dated as the line dates it: "Thursday, Nov 19, 4 schools".
 */
function label(days: readonly LaterDayCount[], from?: string): string {
  if (days.length === 0) throw new RangeError('copy: the later days line names at least one day');
  const named = days.map(({ day: localDate, count: n }) => {
    const at = format.parseLocalDate(localDate);
    const weekday = format.dateTimeFormat('weekday', 'UTC').format(at);
    const named = near(at, from)
      ? weekday
      : `${weekday}, ${format.dateTimeFormat('monthDay', 'UTC').format(at)}`;
    return `${named}, ${format.schools(whole(n))}`;
  });
  return `${laterCopy.title}: ${named.join('; ')}`;
}

export const laterFormat = /* @__PURE__ */ deepFreeze({ day, count, label });

export type LaterFormat = typeof laterFormat;
