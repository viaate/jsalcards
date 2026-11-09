/**
 * The school panel's season line (ui/DetailPanel.svelte): how many days the
 * school has been closed, delayed, remote or dismissed early this school year,
 * from live/season.json (data/season.ts). The part of src/copy.ts that loads
 * with the panel rather than with the page. The same rules hold here as there,
 * and `npm run lint:copy` reads this file as the site's copy
 * (scripts/check-copy.mjs COPY_MODULES).
 *
 * The line says only what the file counts: the days from the day counting
 * began, which it names whenever that is later than the school year's first
 * day. A school with no day counted gets no line at all.
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

/** A school's days of each status this school year, as the season file counts them. */
export interface SeasonDays {
  readonly closed: number;
  readonly delayed: number;
  readonly remote: number;
  readonly earlyDismissal: number;
}

/** Each status as the line says it, in the order the line names them. */
const WORDS: readonly (readonly [keyof SeasonDays, string])[] = [
  ['closed', 'closed'],
  ['delayed', 'delayed'],
  ['remote', 'remote'],
  ['earlyDismissal', 'dismissed early'],
];

function whole(n: number): number {
  if (!Number.isInteger(n) || n < 0) {
    throw new RangeError(`copy: a count of days is a whole number, not ${String(n)}`);
  }
  return n;
}

/**
 * "This school year: closed 2 days, delayed 1.", or with the day counting
 * began when that is after the school year's first day: "This school year,
 * since Oct 27: closed 1 day." Each status with a day, in the order closed,
 * delayed, remote, dismissed early; the first carries its unit. `since` is
 * null when counting began with the school year.
 */
function line(days: SeasonDays, since: string | null): string {
  const parts = WORDS.filter(([key]) => whole(days[key]) > 0).map(
    ([key, word]) => `${word} ${format.number(days[key])}`,
  );
  const [first, ...rest] = parts;
  if (first === undefined) throw new RangeError('copy: a season line names at least one day');
  const unit = WORDS.find(([key]) => days[key] > 0)?.[0] ?? 'closed';
  const lead = `${first} ${days[unit] === 1 ? 'day' : 'days'}`;
  const when =
    since === null
      ? 'This school year'
      : `This school year, since ${format.dateTimeFormat('monthDay', 'UTC').format(format.parseLocalDate(since))}`;
  return `${when}: ${[lead, ...rest].join(', ')}.`;
}

export const seasonFormat = /* @__PURE__ */ deepFreeze({ line });

export type SeasonFormat = typeof seasonFormat;
