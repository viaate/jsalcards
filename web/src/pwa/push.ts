/**
 * The service worker's notifications (docs/notify.md): it shows each push the
 * sender sends (pipeline/snowlight/notify) as a notification in the site's own
 * words (src/copy-notify.ts), and a tap opens the school on the map.
 *
 * The sender pushes facts, not text: the school's id and saved name, its
 * local day and time zone, and the status or chance. The words are made here,
 * when the notification shows, against the school's today in its own zone, so
 * one delivered late still says the right day ("Closed Tue, Jan 12", not
 * "today"). A push that does not read still shows a plain notification that
 * opens the map: a browser requires one for every push.
 *
 * tools/push-worker.ts bundles push-worker.ts, which installs these, into the
 * script the generated worker imports (PUSH_FILE).
 */

import { detailsFormat } from '../copy-details';
import { notifyCopy, notifyFormat } from '../copy-notify';
import { alertBody, alertRings, alertTitle } from '../copy-trips';
import { readAlert } from '../modes/flights/alert';

const STATUS_WORDS: ReadonlySet<string> = new Set([
  'closed',
  'delayed',
  'remote',
  'early_dismissal',
]);
const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
/** How many detail codes there are (types/generated Detail: 0 to 21). */
const DETAILS = 22;
/** A school id: NCES (12 digits) or PSS (8 capitals or digits). */
const SCHOOL_ID = /^(?:\d{12}|[0-9A-Z]{8})$/;

interface Base {
  readonly school: string;
  readonly name: string;
  readonly day: string;
  readonly zone: string;
}

export type PushPayload =
  | (Base & {
      readonly kind: 'status';
      readonly status: string;
      readonly shift: number | null;
      readonly clock: number | null;
      /** The plain details beside the status (Detail codes, ascending); empty for none. */
      readonly details: readonly number[];
    })
  /** Lifted by an open statement: the sender sends no other lift (docs/notify.md). */
  | (Base & { readonly kind: 'lifted'; readonly was: string; readonly open: true })
  | (Base & { readonly kind: 'chance'; readonly percent: number; readonly rise: boolean })
  | (Base & { readonly kind: 'night'; readonly percent: number });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function minutes(value: unknown, max: number): number | null | undefined {
  if (value === null) return null;
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max
    ? value
    : undefined;
}

/**
 * A status push's detail codes: distinct, ascending, each a Detail code. Details only add to
 * a status, so a payload without them, or with ones that do not read, says the status alone.
 */
function detailCodes(value: unknown): readonly number[] {
  if (!Array.isArray(value)) return [];
  let last = -1;
  for (const code of value as readonly unknown[]) {
    if (typeof code !== 'number' || !Number.isInteger(code) || code <= last || code >= DETAILS) {
      return [];
    }
    last = code;
  }
  return value as readonly number[];
}

function knownZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** A push's payload, read strictly; null when anything in it is missing or out of range. */
export function readPayload(data: unknown): PushPayload | null {
  if (!isRecord(data) || data.v !== 1) return null;
  const { school, name, day, zone, kind } = data;
  if (typeof school !== 'string' || !SCHOOL_ID.test(school)) return null;
  if (typeof name !== 'string' || name.trim() === '' || name.length > 120) return null;
  if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
  if (typeof zone !== 'string' || !knownZone(zone)) return null;
  const base = { school, name: name.trim(), day, zone };
  if (kind === 'status') {
    const shift = minutes(data.shift, 600);
    const clock = minutes(data.clock, 1439);
    if (typeof data.status !== 'string' || !STATUS_WORDS.has(data.status)) return null;
    if (shift === undefined || clock === undefined) return null;
    return { ...base, kind, status: data.status, shift, clock, details: detailCodes(data.details) };
  }
  if (kind === 'lifted') {
    if (typeof data.was !== 'string' || !STATUS_WORDS.has(data.was)) return null;
    if (data.open !== true) return null;
    return { ...base, kind, was: data.was, open: true };
  }
  const percent = data.percent;
  if (typeof percent !== 'number' || !Number.isInteger(percent) || percent < 1 || percent > 99)
    return null;
  if (kind === 'chance') {
    if (typeof data.rise !== 'boolean') return null;
    return { ...base, kind, percent, rise: data.rise };
  }
  if (kind === 'night') return { ...base, kind, percent };
  return null;
}

export interface Shown {
  readonly title: string;
  /** `renotify` is in the Notifications spec but not in TypeScript's DOM types. */
  readonly options: Omit<NotificationOptions, 'data'> & {
    readonly data: { readonly url: string; readonly at?: number | null };
    readonly renotify?: boolean;
  };
}

/** The map opened on a school (?school=ID), under the worker's scope. */
export function schoolUrl(scope: string, school: string | null): string {
  const url = new URL(scope);
  url.search = '';
  url.hash = '';
  if (school !== null) url.searchParams.set('school', school);
  return url.href;
}

/** The text of a payload's notification at `now`. */
export function bodyOf(payload: PushPayload, now: Date): string {
  switch (payload.kind) {
    case 'status':
      return detailsFormat.afterStatus(
        notifyFormat.statusBody(
          payload.status,
          payload.day,
          payload.zone,
          now,
          payload.shift,
          payload.clock,
        ),
        payload.details,
      );
    case 'lifted':
      return notifyFormat.openBody(payload.day, payload.zone, now);
    case 'chance':
      return notifyFormat.chanceBody(payload.percent, payload.rise, payload.day, payload.zone, now);
    case 'night':
      return notifyFormat.nightBody(payload.percent, payload.day, payload.zone, now);
  }
}

/** The map opened on a saved trip (?mode=flights&page=trips&trip=ID), under the worker's scope. */
export function tripUrl(scope: string, trip: string): string {
  const url = new URL(scope);
  url.search = '';
  url.hash = '';
  url.searchParams.set('mode', 'flights');
  url.searchParams.set('page', 'trips');
  url.searchParams.set('trip', trip);
  return url.href;
}

/** The tray group of a Flights alert kind: the risk kinds share one. */
export function flightTag(kind: string): string {
  return kind === 'faa' || kind === 'waiver' ? kind : 'risk';
}

/** What to show for a push's data (null, or text that does not read: the plain notification). */
export function notificationFor(data: unknown, scope: string, icon: string, now: Date): Shown {
  // A Flights trip alert (flights spec D12): its facts in copy-trips.ts's words.
  const alert = readAlert(data);
  if (alert !== null) {
    const at = Math.floor(now.getTime() / 1000);
    const rings = alertRings(alert, at);
    return {
      title: alertTitle(alert),
      options: {
        body: alertBody(alert, at),
        icon,
        // The trip's risk (chance, rise, fall, safer, evening check) is one notification: the
        // newest replaces the last, so an old number never stays in the tray. FAA and waiver
        // alerts keep their own.
        tag: `fl-${flightTag(alert.alert)}-${alert.trip}`,
        // Each one is a real change: one that replaces an earlier push still in the tray rings
        // and shows again, never a silent swap. A safer alert shown after its safer flights left
        // says only the chance already said (TRAV-R5-S1): it updates the tray without a sound.
        renotify: rings,
        silent: !rings,
        // `at`: when the sender checked, so the worker never lets an older one replace a newer
        // one already in the tray (TRAV-R6-B1).
        data: { url: tripUrl(scope, alert.trip), at: alert.at },
      },
    };
  }
  const payload = readPayload(data);
  if (payload === null) {
    return {
      title: notifyCopy.push.fallbackTitle,
      options: {
        body: notifyCopy.push.fallbackBody,
        icon,
        tag: 'snowlight',
        data: { url: schoolUrl(scope, null) },
      },
    };
  }
  const group = payload.kind === 'status' || payload.kind === 'lifted' ? 'st' : payload.kind;
  return {
    title: payload.name,
    options: {
      body: bodyOf(payload, now),
      icon,
      // One notification per school, day and kind: a newer one replaces it.
      tag: `${group}-${payload.school}-${payload.day}`,
      data: { url: schoolUrl(scope, payload.school) },
    },
  };
}

/** The parts of the worker's global scope these handlers use (tests hand it a fake). */
export interface PushScope {
  readonly registration: {
    readonly scope: string;
    showNotification(title: string, options?: NotificationOptions): Promise<void>;
    getNotifications?(filter?: GetNotificationOptions): Promise<readonly ShownLike[]>;
  };
  readonly clients: {
    matchAll(options?: ClientQueryOptions): Promise<readonly WindowLike[]>;
    openWindow(url: string): Promise<unknown>;
  };
  addEventListener(type: 'push', listener: (event: PushEventLike) => void): void;
  addEventListener(type: 'notificationclick', listener: (event: ClickEventLike) => void): void;
}

/** A notification in the tray, as getNotifications gives it. */
export interface ShownLike {
  readonly title: string;
  readonly body: string;
  readonly icon: string;
  readonly tag: string;
  readonly data: unknown;
}

export interface WindowLike {
  readonly url: string;
  focus?(): Promise<unknown>;
  navigate?(url: string): Promise<unknown>;
}

export interface PushEventLike {
  readonly data: { json(): unknown } | null;
  waitUntil(promise: Promise<unknown>): void;
}

export interface ClickEventLike {
  readonly notification: { readonly data: unknown; close(): void };
  waitUntil(promise: Promise<unknown>): void;
}

/** The address a tapped notification opens: its own, when it is under the scope. */
function clickUrl(data: unknown, scope: string): string {
  const url = isRecord(data) && typeof data.url === 'string' ? data.url : '';
  return url.startsWith(scope) ? url : scope;
}

/** Opens `url` in a Snowlight window that is open already, or in a new one. */
async function open(scope: PushScope, url: string): Promise<void> {
  const windows = await scope.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const mine = windows.find((client) => client.url.startsWith(scope.registration.scope));
  if (mine?.navigate !== undefined && mine.focus !== undefined) {
    try {
      await mine.focus();
      await mine.navigate(url);
      return;
    } catch {
      // A window that cannot be moved: a new one instead.
    }
  }
  await scope.clients.openWindow(url);
}

/** When the sender checked a shown Flights alert (its data's `at`), or null. */
function checkedAt(data: unknown): number | null {
  return isRecord(data) && typeof data.at === 'number' ? data.at : null;
}

/**
 * Shows a push, unless the tray holds a newer Flights alert under its tag (TRAV-R6-B1): alerts
 * from two passes can reach a phone out of order, and an older one must never stand as the
 * current one. Then the newer one is shown again as it is, without a sound, so the push still
 * shows a notification and the tray keeps the newest.
 */
async function show(scope: PushScope, shown: Shown): Promise<void> {
  const at = checkedAt(shown.options.data);
  const tag = shown.options.tag;
  if (at !== null && tag !== undefined && scope.registration.getNotifications !== undefined) {
    let held: readonly ShownLike[] = [];
    try {
      held = await scope.registration.getNotifications({ tag });
    } catch {
      // The tray cannot be read: show the push as it is.
    }
    const newer = held.find((one) => (checkedAt(one.data) ?? -Infinity) > at);
    if (newer !== undefined) {
      const again: Shown['options'] = {
        body: newer.body,
        icon: newer.icon,
        tag: newer.tag,
        data: newer.data as Shown['options']['data'],
        renotify: false,
        silent: true,
      };
      await scope.registration.showNotification(newer.title, again);
      return;
    }
  }
  await scope.registration.showNotification(shown.title, shown.options);
}

/** Installs the push and click handlers on the worker's scope. `now` is for tests. */
export function installPush(
  scope: PushScope,
  icon: string,
  now: () => Date = () => new Date(),
): void {
  scope.addEventListener('push', (event) => {
    let data: unknown;
    try {
      data = event.data?.json() ?? null;
    } catch {
      data = null;
    }
    const shown = notificationFor(data, scope.registration.scope, icon, now());
    event.waitUntil(show(scope, shown));
  });
  scope.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(open(scope, clickUrl(event.notification.data, scope.registration.scope)));
  });
}
