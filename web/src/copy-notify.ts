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
    intro:
      'Get a notification when a saved school closes, starts late or lets out early, and when its chance of no school is high.',
    turnOn: 'Turn on notifications',
    turnOff: 'Turn off on this device',
    turnOffAll: 'Turn off on all devices',
    on: 'Notifications are on for this device.',
    off: 'Notifications are off for this device.',
    blocked:
      'Notifications are blocked for this site. Allow them in your browser’s site settings, then come back here.',
    unsupported: 'This browser does not show notifications from websites.',
    failed: 'Notifications did not turn on. Try again in a moment.',
    noSchools: 'Save a school to get notifications about it.',
    choices: 'What to send',
    status: 'Closings, delays and early dismissals',
    statusNote: 'Sent as soon as they show on the map, at any hour.',
    chance: 'High chance of no school tomorrow',
    threshold: 'When the chance reaches',
    night: 'Evening check',
    nightNote: 'Tomorrow’s chance for each saved school, when it is 10% or more.',
    nightTime: 'Send it at',
    quiet: 'Quiet hours',
    quietNote: 'Chance notifications wait until quiet hours end. Closings still come through.',
    quietFrom: 'From',
    quietTo: 'To',
    zoneNote: 'Times are each school’s own local time.',
    saved: 'Saved',
    saving: 'Saving…',
    working: 'One moment…',
  },
  /** iPhone and iPad: web notifications only come from a site added to the Home Screen. */
  ios: {
    title: 'On iPhone, add Snowlight to your home screen first',
    steps: [
      'In Safari, tap the share button and pick add to home screen.',
      'Open Snowlight from your home screen.',
      'Turn on notifications here.',
    ],
    note: 'Only sites on the home screen can show notifications on iPhone and iPad, with iOS 16.4 or later.',
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

/** How many browsers get the account's notifications: "On 2 devices". */
function devices(count: number): string {
  return count === 1 ? 'On 1 device' : `On ${format.number(count)} devices`;
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
