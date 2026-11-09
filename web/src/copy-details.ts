/**
 * The plain details a school's listings state beside its status, in the site's own words:
 * "Buses run snow routes. No breakfast." (pipeline/snowlight/live/details.py reads them, and
 * closings.json carries them as codes, never a listing's words). The detail panel's status
 * lines say them (app/school.ts), and so do status notifications, after the words of
 * src/copy-notify.ts (src/pwa/push.ts). It loads with the panel and in the worker's own
 * script, never with the page's first script.
 * The same rules hold here as in src/copy.ts, and `npm run lint:copy` reads this file as the
 * site's copy (scripts/check-copy.mjs COPY_MODULES).
 */

import { Detail } from './types/generated/index.ts';

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

export type DetailKey = keyof typeof Detail;

/** Each detail as one short sentence, in the order the panel says them (the codes' order). */
export const detailsCopy = /* @__PURE__ */ deepFreeze({
  said: {
    students_and_staff: 'Students and staff.',
    staff_report: 'Staff report, students stay home.',
    staff_late: 'Staff report late.',
    buses_snow_routes: 'Buses run snow routes.',
    buses_emergency_routes: 'Buses run emergency routes.',
    buses_paved_roads: 'Buses run on paved roads only.',
    buses_limited: 'Buses run limited routes.',
    no_buses: 'No buses.',
    no_breakfast: 'No breakfast.',
    no_lunch: 'No lunch.',
    no_hot_lunch: 'No hot lunch.',
    grab_and_go: 'Grab-and-go meals.',
    no_am_prek: 'No morning pre-K.',
    no_pm_prek: 'No afternoon pre-K.',
    no_prek: 'No pre-K.',
    activities_cancelled: 'Activities cancelled.',
    after_school_cancelled: 'After-school activities cancelled.',
    evening_cancelled: 'Evening activities cancelled.',
    childcare_closed: 'Childcare closed.',
    childcare_open: 'Childcare open.',
    offices_closed: 'Offices closed.',
    offices_open: 'Offices open.',
  } satisfies Record<DetailKey, string>,
});

const KEY_OF: ReadonlyMap<number, DetailKey> = new Map(
  (Object.keys(Detail) as DetailKey[]).map((key) => [Detail[key], key]),
);

/** The sentences for a row's detail codes, in code order, each once; unknown codes are skipped. */
function sentences(codes: readonly number[]): string[] {
  const keys = [...new Set(codes)]
    .sort((a, b) => a - b)
    .map((code) => KEY_OF.get(code))
    .filter((key): key is DetailKey => key !== undefined);
  return keys.map((key) => detailsCopy.said[key]);
}

/** "Students and staff. Buses run snow routes. No breakfast.", or null with none. */
function said(codes: readonly number[]): string | null {
  const found = sentences(codes);
  return found.length > 0 ? found.join(' ') : null;
}

/**
 * The details that fit in `room` characters, in order, whole sentences only: the ones that
 * do not fit are left out from the last, so what is said is never cut mid-sentence. Null when
 * none fits.
 */
function within(codes: readonly number[], room: number): string | null {
  let text = '';
  for (const sentence of sentences(codes)) {
    const next = text === '' ? sentence : `${text} ${sentence}`;
    if (next.length > room) break;
    text = next;
  }
  return text === '' ? null : text;
}

/**
 * The most characters a status notification's text holds: about what a phone's lock screen
 * shows of it. The status and its day always show; the details fill what is left.
 */
const STATUS_BODY_MAX = 160;

/**
 * A status notification's text with its details after it, in the same run of sentences:
 * "Delayed start today (Tue, Jan 12). 2-hour delay. Starts at 10:00 AM. Buses run snow
 * routes. No breakfast.", within STATUS_BODY_MAX characters (whole sentences, the last ones
 * left out first); the status alone when none fits, so the status and its day always show.
 */
function afterStatus(status: string, codes: readonly number[]): string {
  const fits = within(codes, STATUS_BODY_MAX - status.length - 2);
  return fits === null ? status : `${status}. ${fits}`;
}

export const detailsFormat = /* @__PURE__ */ deepFreeze({ said, within, afterStatus });
export type DetailsFormat = typeof detailsFormat;
