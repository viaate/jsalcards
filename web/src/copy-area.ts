/**
 * The area panel's words (ui/AreaPanel.svelte), for the schools around a ZIP
 * code: the part of src/copy.ts that loads with that panel rather than with
 * the page. The same rules hold here as there, and `npm run lint:copy` reads
 * this file as the site's copy (scripts/check-copy.mjs COPY_MODULES). Every
 * word it adds carries a live value: its sentences are the functions of
 * areaFormat, and its fixed words are copy.ts's.
 *
 * A name a sentence carries (a district's, a school's) always opens it, as
 * the chance section's do (src/copy-chance.ts).
 */

import { copy } from './copy.ts';
import type { StatusKey } from './copy.ts';
import { chanceFormat } from './copy-chance.ts';
import { format } from './copy-format.ts';
import { STATES } from './search/states.ts';

const { checkKey } = format;

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

/** How many schools hold a status today, as the count over the list words it: "9 closed". */
const COUNT_WORDS = {
  closed: 'closed',
  delayed: 'delayed',
  remote: 'remote',
  earlyDismissal: 'dismissing early',
} as const;

function count(n: number): string {
  return format.number(n);
}

/** "Schools around 64112": the panel, for a screen reader. */
function label(zip: string): string {
  return `Schools around ${zip}`;
}

/** "Back to 64112": back from a school to the area its list opened it from. */
function backTo(zip: string): string {
  return `${copy.detail.back} to ${zip}`;
}

/** The states a ZIP code is in, as search names them: "Missouri", "Missouri, Kansas". */
function states(codes: readonly string[]): string {
  if (codes.length === 0) throw new RangeError('copy: a ZIP code is in a state');
  return codes
    .map((code) => {
      const named = STATES.find(([known]) => known === code)?.[1];
      if (named === undefined) throw new RangeError(`copy: no state ${code}`);
      return named;
    })
    .join(', ');
}

/** The ZIP code's own schools, under its code: "14 schools", "1 school", "No schools". */
function schoolCount(n: number): string {
  if (count(n) === '0') return 'No schools';
  return `${count(n)} ${n === 1 ? 'school' : 'schools'}`;
}

/** The others taken in within `miles` of the ZIP code's point: "4 more within 2 miles". */
function nearOthers(n: number, own: number, miles: number): string {
  if (count(n) === '0') throw new RangeError('copy: no others to name');
  return `${count(n)} ${count(own) === '0' ? '' : 'more '}within ${count(miles)} miles`;
}

/** None taken in, though the ZIP code has fewer schools of its own than the area takes. */
function noneNear(own: number, miles: number): string {
  return count(own) === '0'
    ? `None within ${count(miles)} miles`
    : `No others within ${count(miles)} miles`;
}

/** The schools of the area whose records cannot be read: "2 schools did not load". */
function unread(n: number): string {
  if (count(n) === '0') throw new RangeError('copy: no schools to name');
  return `${count(n)} ${n === 1 ? 'school' : 'schools'} did not load`;
}

/** "9 closed": how many of the area's schools hold a status today. */
function statusCount(status: StatusKey, n: number): string {
  return `${count(n)} ${COUNT_WORDS[checkKey(copy.status, status, 'status')]}`;
}

/**
 * "9 schools here", "all 14 schools here", "both schools here", "the 1 school here": how many of
 * the area's schools a row speaks for. The area's own count is said once,
 * by the list and by what the chance leaves out, not on every row.
 */
function ofHere(n: number, of: number): string {
  if (n < 1 || n > of) throw new RangeError(`copy: ${String(n)} of ${String(of)} schools`);
  if (n === of && of <= 2) return of === 1 ? 'the 1 school here' : 'both schools here';
  if (n === of) return `all ${count(of)} schools here`;
  return `${count(n)} ${n === 1 ? 'school' : 'schools'} here`;
}

/** A district and the schools it decides for: "Kansas City 33 decides for 9 schools here." */
function decides(name: string, n: number, of: number): string {
  return `${name} decides for ${ofHere(n, of)}.`;
}

/**
 * What a district already posted for the day, at how many of the area's
 * schools: "Kansas City 33 canceled Tuesday at 9 schools here."
 */
function districtPosted(
  name: string,
  status: StatusKey,
  n: number,
  of: number,
  localDate: string,
): string {
  return `${chanceFormat.neighborPosted(name, status, localDate)} at ${ofHere(n, of)}.`;
}

/**
 * A district whose forecast says no weather threat for the day, at how many
 * of the area's schools: "Shawnee Mission has no weather threat Tuesday at 3 schools here."
 */
function noThreat(name: string, n: number, of: number, localDate: string): string {
  return `${name} has no weather threat ${chanceFormat.weekday(localDate)} at ${ofHere(n, of)}.`;
}

/** What a school deciding for itself posted for the day: "Pembroke Hill canceled Tuesday." */
function schoolPosted(name: string, status: StatusKey, localDate: string): string {
  return `${chanceFormat.neighborPosted(name, status, localDate)}.`;
}

/**
 * What a row counts as when it is not a chance: no school ("100%", closed or
 * remote) or school ("0%", a late start, an early dismissal or no weather threat).
 */
function share(noSchool: boolean): string {
  return noSchool ? '100%' : '0%';
}

/** Whose forecast the area's chart draws: "Kansas City 33’s forecast", "Shawnee Mission Public Schools’ forecast". */
function forecastOf(name: string): string {
  return `${name}${name.endsWith('s') ? '’' : '’s'} forecast`;
}

/**
 * The schools the area's chance leaves out, `noChance` with no chance given
 * for the day and `noCount` with one but no student count to weigh it by:
 * "3 of the 14 schools here have no chance given for Tuesday and are left out."
 */
function notCounted(noChance: number, noCount: number, of: number, localDate: string): string {
  const n = noChance + noCount;
  const on = chanceFormat.weekday(localDate);
  if (noChance < 0 || noCount < 0 || n < 1 || n > of) {
    throw new RangeError(`copy: ${String(n)} of ${String(of)} schools`);
  }
  const has = (k: number): string => (k === 1 ? 'has' : 'have');
  const here = `of the ${count(of)} ${of === 1 ? 'school' : 'schools'} here`;
  const noneGiven = `no chance given for ${on}`;
  const unweighed = 'no student count';
  if (noCount === 0 || noChance === 0) {
    const left = n === 1 ? 'is left out' : 'are left out';
    return `${count(n)} ${here} ${has(n)} ${noCount === 0 ? noneGiven : unweighed} and ${left}.`;
  }
  return `${count(n)} ${here} are left out: ${count(noChance)} ${has(noChance)} ${noneGiven} and ${count(noCount)} ${has(noCount)} ${unweighed}.`;
}

export const areaFormat = /* @__PURE__ */ deepFreeze({
  label,
  backTo,
  states,
  schoolCount,
  nearOthers,
  noneNear,
  unread,
  statusCount,
  decides,
  districtPosted,
  noThreat,
  schoolPosted,
  share,
  forecastOf,
  notCounted,
});

export type AreaFormat = typeof areaFormat;
