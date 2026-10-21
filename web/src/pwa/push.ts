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

import { notifyCopy, notifyFormat } from '../copy-notify';

const STATUS_WORDS: ReadonlySet<string> = new Set([
  'closed',
  'delayed',
  'remote',
  'early_dismissal',
]);
const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
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
    return { ...base, kind, status: data.status, shift, clock };
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
  readonly options: Omit<NotificationOptions, 'data'> & { readonly data: { readonly url: string } };
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
      return notifyFormat.statusBody(
        payload.status,
        payload.day,
        payload.zone,
        now,
        payload.shift,
        payload.clock,
      );
    case 'lifted':
      return notifyFormat.openBody(payload.day, payload.zone, now);
    case 'chance':
      return notifyFormat.chanceBody(payload.percent, payload.rise, payload.day, payload.zone, now);
    case 'night':
      return notifyFormat.nightBody(payload.percent, payload.day, payload.zone, now);
  }
}

/** What to show for a push's data (null, or text that does not read: the plain notification). */
export function notificationFor(data: unknown, scope: string, icon: string, now: Date): Shown {
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
  };
  readonly clients: {
    matchAll(options?: ClientQueryOptions): Promise<readonly WindowLike[]>;
    openWindow(url: string): Promise<unknown>;
  };
  addEventListener(type: 'push', listener: (event: PushEventLike) => void): void;
  addEventListener(type: 'notificationclick', listener: (event: ClickEventLike) => void): void;
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
    event.waitUntil(scope.registration.showNotification(shown.title, shown.options));
  });
  scope.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(open(scope, clickUrl(event.notification.data, scope.registration.scope)));
  });
}
