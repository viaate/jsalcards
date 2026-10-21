/**
 * The words of notifications: Settings > Notifications, the iPhone guide, the
 * offer after saving a school, and the notifications themselves, which the
 * service worker writes from what the sender pushes (src/pwa/push.ts). It
 * loads with the account controls and in the worker's own script, never with
 * the page's first script. The same rules hold here as in src/copy.ts, and
 * `npm run lint:copy` reads this file as the site's copy (scripts/check-copy.mjs
 * COPY_MODULES). A school's name is the one its account saved, shown as it is.
 */

import { copy, type StatusKey } from './copy.ts';
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

const DOT = ' · ';

export const notifyCopy = /* @__PURE__ */ deepFreeze({
  settings: {
    title: 'Notifications',
    /** The header row's switch, as a screen reader names it. */
    device: 'Notifications on this device',
    blocked: 'Blocked in site settings',
    unsupported: 'Not in this browser',
    failed: 'Try again',
    noSchools: 'Save a school first',
    status: 'Closings and delays',
    chance: 'Chance alerts',
    /** The 30%, 50% and 70% choice under chance alerts, as a screen reader names it. */
    threshold: 'Alert when the chance reaches',
    night: 'Evening check',
    nightTime: 'Send at',
    quiet: 'Quiet hours',
    /** Beside the quiet hours: only chance alerts wait, closings still come through. */
    quietHolds: 'Chance alerts only',
    quietFrom: 'Quiet hours start',
    quietTo: 'Quiet hours end',
    turnOffAll: 'Turn off everywhere',
    saved: 'Saved',
    saving: 'Saving…',
  },
  /** iPhone and iPad: web notifications only come from a site added to the home screen. */
  ios: {
    title: 'Add to home screen first',
    how: 'How',
    steps: [
      'In Safari, tap Share, then Add to Home Screen',
      'Open Snowlight from your home screen',
      'Turn on notifications here',
    ],
  },
  /** After a school is saved, while notifications are off on this device. */
  offer: {
    turnOn: 'Turn on notifications',
    later: 'Not now',
  },
  /** The notifications. */
  push: {
    fallbackTitle: 'Snowlight',
    fallbackBody: 'Open Snowlight for the latest closings and chances.',
    /** A status the school has since said it is open on (the sender's only lift). */
    open: { today: 'Open today', tomorrow: 'Open tomorrow', on: 'Open' },
  },
});

/** The payload's status words and the site's status keys. */
const STATUS_OF: Readonly<Record<string, StatusKey>> = Object.freeze({
  closed: 'closed',
  delayed: 'delayed',
  remote: 'remote',
  early_dismissal: 'earlyDismissal',
});

/** A payload's status word as the site's key; RangeError for any other. */
function statusKey(word: string): StatusKey {
  const key = STATUS_OF[word];
  if (key === undefined) throw new RangeError(`copy: no status ${word}`);
  return key;
}

/** Days from the school's today to `localDate`, in its zone. */
function offset(localDate: string, now: Date, timeZone: string): number {
  const day = format.parseLocalDate(localDate).getTime();
  const today = format.parseLocalDate(format.localDay(now, timeZone)).getTime();
  return Math.round((day - today) / 86_400_000);
}

/** "Today (Tue, Jan 12)", "Tomorrow (Wed, Jan 13)", or "Mon, Jan 11" for another day. */
function heading(localDate: string, now: Date, timeZone: string): string {
  const days = offset(localDate, now, timeZone);
  const day = format.day(localDate);
  if (days === 0) return `Today (${day})`;
  if (days === 1) return `Tomorrow (${day})`;
  return day;
}

/** A line with its date: "Closed today (Tue, Jan 12)"; another day already names its date. */
function dated(
  line: { today: string; tomorrow: string; on: string },
  localDate: string,
  now: Date,
  timeZone: string,
): string {
  const days = offset(localDate, now, timeZone);
  if (days === 0) return `${line.today} (${format.day(localDate)})`;
  if (days === 1) return `${line.tomorrow} (${format.day(localDate)})`;
  return `${line.on} ${format.day(localDate)}`;
}

/**
 * A status notification's text: "Closed today (Tue, Jan 12)",
 * "Delayed start tomorrow (Wed, Jan 13) · 2-hour delay · Starts at 10:00 AM".
 */
function statusBody(
  word: string,
  localDate: string,
  timeZone: string,
  now: Date,
  shift: number | null,
  clock: number | null,
): string {
  const key = statusKey(word);
  const line = dated(copy.statusLine[key], localDate, now, timeZone);
  const detail =
    key === 'delayed'
      ? format.delay(shift, clock)
      : key === 'earlyDismissal'
        ? format.dismissal(shift, clock)
        : null;
  return detail === null ? line : `${line}${DOT}${detail}`;
}

/**
 * A status lifted by an open statement: "Open today (Tue, Jan 12)". A status that only left
 * the map is never said to be lifted (docs/notify.md), so this is the one lifted line.
 */
function openBody(localDate: string, timeZone: string, now: Date): string {
  return dated(notifyCopy.push.open, localDate, now, timeZone);
}

/**
 * A chance notification: "Tomorrow (Wed, Jan 13): 62% chance of no school"; after a rise of
 * 20 points or more, "Tomorrow (Wed, Jan 13): up to 82% chance of no school".
 */
function chanceBody(
  percent: number,
  rise: boolean,
  localDate: string,
  timeZone: string,
  now: Date,
): string {
  const chance = `${format.chance(percent / 100)} chance of no school`;
  return `${heading(localDate, now, timeZone)}: ${rise ? 'up to ' : ''}${chance}`;
}

/** The evening check: "Tomorrow (Wed, Jan 13): 35% chance of no school". */
function nightBody(percent: number, localDate: string, timeZone: string, now: Date): string {
  return `${heading(localDate, now, timeZone)}: ${format.chance(percent / 100)} chance of no school`;
}

/** How many browsers get the account's notifications: "2 devices". */
function devices(count: number): string {
  return count === 1 ? '1 device' : `${format.number(count)} devices`;
}

/** A threshold choice: "30%". */
function threshold(percent: number): string {
  return `${format.number(percent)}%`;
}

/** A clock choice from "HH:MM": "8:00 PM". */
function hour(hhmm: string): string {
  const match = /^(\d{2}):(\d{2})$/.exec(hhmm);
  if (match === null) throw new RangeError(`copy: "${hhmm}" is not a time (HH:MM)`);
  return format.clockText(Number(match[1]), Number(match[2]));
}

/** The offer after saving a school: "Get a notification when Lincoln High closes or starts late?" */
function offer(school: string): string {
  return `Get a notification when ${school} closes or starts late?`;
}

export const notifyFormat = /* @__PURE__ */ deepFreeze({
  statusBody,
  openBody,
  devices,
  chanceBody,
  nightBody,
  threshold,
  hour,
  offer,
});

export type NotifyCopy = typeof notifyCopy;
