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

/** "14 schools in 64111", "1 school in 64111", "No schools in 64111". */
function schoolsIn(n: number, zip: string): string {
  if (count(n) === '0') return `No schools in ${zip}`;
  return `${count(n)} ${n === 1 ? 'school' : 'schools'} in ${zip}`;
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

/** What a school deciding for itself posted for the day: "Pembroke Hill canceled Tuesday." */
function schoolPosted(name: string, status: StatusKey, localDate: string): string {
  return `${chanceFormat.neighborPosted(name, status, localDate)}.`;
}

/** A posted status's share of no school, as a row of the sum sets it: "100%" or "0%". */
function postedShare(status: StatusKey): string {
  switch (checkKey(copy.status, status, 'status')) {
    case 'closed':
    case 'remote':
      return '100%';
    case 'delayed':
    case 'earlyDismissal':
      return '0%';
  }
}

/** The schools the area's chance leaves out: "3 of the 14 schools here have no chance given for Tuesday and are left out." */
function notCounted(n: number, of: number, localDate: string): string {
  const on = chanceFormat.weekday(localDate);
  if (n < 1 || n > of) throw new RangeError(`copy: ${String(n)} of ${String(of)} schools`);
  const verb = n === 1 ? 'has' : 'have';
  const left = n === 1 ? 'is left out' : 'are left out';
  return `${count(n)} of the ${count(of)} ${of === 1 ? 'school' : 'schools'} here ${verb} no chance given for ${on} and ${left}.`;
}

export const areaFormat = /* @__PURE__ */ deepFreeze({
  label,
  backTo,
  states,
  schoolsIn,
  nearOthers,
  noneNear,
  statusCount,
  decides,
  districtPosted,
  schoolPosted,
  postedShare,
  notCounted,
});

export type AreaFormat = typeof areaFormat;
