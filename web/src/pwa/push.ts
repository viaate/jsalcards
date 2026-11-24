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
import { ALERT_NOTES, finished, openNotes, type AlertDb } from './alert-store';

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
    /** `timestamp` is in the Notifications spec but not in TypeScript's DOM types. */
    readonly timestamp?: number;
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
        // The tray says when the sender checked, not when the phone got it (TRAV-R7-S3).
        ...(alert.at === null ? {} : { timestamp: alert.at * 1000 }),
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
  /** Absent, or failing: the worker checks the tray and its memory alone. */
  readonly indexedDB?: AlertDb;
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
 * The newest Flights alert shown under a tag: its `at` and its facts. The worker keeps it two
 * ways (TRAV-R7-S2, TRAV-P2-B1). In memory, set the moment a push is shown and read first, so no
 * write still under way can open a gap while the worker runs. And as a note in IndexedDB
 * (alert-store.ts), for after the worker has stopped: the tray forgets an alert the person swiped
 * away, the note does not, so an older push that comes after it is still dropped. A note whose
 * trip day is over is dropped (TRAV-P1-S3); the page drops them all at sign-out and the like.
 */
interface Kept {
  readonly at: number;
  readonly data: unknown;
}

/** How long a store or tray read may take before the push goes on without it (TRAV-P1-S4). */
export const STORE_WAIT_MS = 1000;
const DAY_MS = 86_400_000;
const NOTE_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Runs a read for at most STORE_WAIT_MS; past that, or when it fails, `fallback`. A store or
 * tray that hangs must not keep the push from showing. Only reads are cut short: a write is
 * never (see Notes.keep).
 */
async function timed<T>(work: () => Promise<T>, fallback: T): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work().catch(() => fallback),
      new Promise<T>((resolve) => (timer = setTimeout(resolve, STORE_WAIT_MS, fallback))),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/** A stored note, read back: its `at` and facts, or null. */
function readNote(note: unknown): Kept | null {
  const at = isRecord(note) ? checkedAt(note) : null;
  return at === null || !isRecord(note) ? null : { at, data: note.data };
}

/** Whether a note's trip day is over (any US airport's day is over once this UTC date is past). */
function over(note: Kept, now: Date): boolean {
  const day = isRecord(note.data) ? note.data.day : null;
  const done = new Date(now.getTime() - DAY_MS).toISOString().slice(0, 10);
  return typeof day !== 'string' || !NOTE_DAY.test(day) || day < done;
}

function request<T>(asked: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    asked.onsuccess = () => {
      resolve(asked.result);
    };
    asked.onerror = () => {
      reject(asked.error ?? new Error('The alert note cannot be read.'));
    };
  });
}

/** The worker's notes, in memory and in IndexedDB. */
class Notes {
  private readonly shown = new Map<string, Kept>();
  private open: Promise<IDBDatabase> | null = null;
  /** The one write chain: each write waits behind the one before it, however long that takes. */
  private writes: Promise<void> = Promise.resolve();

  constructor(private readonly db: AlertDb | undefined) {}

  private notes(): Promise<IDBDatabase> {
    if (this.db === undefined) return Promise.reject(new Error('No store.'));
    if (this.open === null) {
      const opening = openNotes(this.db, () => {
        if (this.open === opening) this.open = null;
      });
      opening.catch(() => {
        if (this.open === opening) this.open = null;
      });
      this.open = opening;
    }
    return this.open;
  }

  /** The newest alert known in memory under `tag`, or null. */
  remembered(tag: string): Kept | null {
    return this.shown.get(tag) ?? null;
  }

  /** Remembers `kept` as the newest under `tag`, unless a newer one is known. */
  remember(tag: string, kept: Kept, now: Date): void {
    const old = this.shown.get(tag);
    if (old === undefined || old.at < kept.at) this.shown.set(tag, kept);
    for (const [key, note] of this.shown) if (over(note, now)) this.shown.delete(key);
  }

  /** The note under `tag`, or null (none, or it cannot be read in time). */
  read(tag: string): Promise<Kept | null> {
    return timed(async () => {
      const open = await this.notes();
      const store = open.transaction(ALERT_NOTES, 'readonly').objectStore(ALERT_NOTES);
      return readNote(await request<unknown>(store.get(tag)));
    }, null);
  }

  /**
   * Notes `kept` under `tag`. In one readwrite transaction it reads the note and puts the new one
   * only when there is none or it is older (compare and set), then drops notes whose day is over.
   * Never cut short and never left behind: the next write waits on this one, and a transaction is
   * all or nothing, so no write lands late over a newer note.
   */
  keep(tag: string, kept: Kept, now: Date): Promise<void> {
    const write = this.writes.then(async () => {
      const open = await this.notes();
      const transaction = open.transaction(ALERT_NOTES, 'readwrite');
      const done = finished(transaction);
      const store = transaction.objectStore(ALERT_NOTES);
      const old = store.get(tag);
      old.onsuccess = () => {
        const note = readNote(old.result);
        if (note === null || note.at < kept.at) store.put({ at: kept.at, data: kept.data }, tag);
        const keys = store.getAllKeys();
        keys.onsuccess = () => {
          const all = store.getAll();
          all.onsuccess = () => {
            keys.result.forEach((key, i) => {
              const one = readNote(all.result[i]);
              if (one === null || over(one, now)) store.delete(key);
            });
          };
        };
      };
      await done;
    });
    // A write that fails leaves the note as it was: the tray and memory still hold the newest.
    this.writes = write.catch(() => undefined);
    return this.writes;
  }
}

/** A notification shown again, never as a new change: no sound, its own checked time. */
function quiet(options: Shown['options']): Shown['options'] {
  const at = checkedAt(options.data);
  return {
    ...options,
    renotify: false,
    silent: true,
    ...(at === null ? {} : { timestamp: at * 1000 }),
  };
}

/**
 * Shows a Flights push, unless the same or a newer alert was shown under its tag (TRAV-R6-B1,
 * TRAV-R7-S2, TRAV-P1-S1, TRAV-P1-S2, TRAV-P2-S1): alerts from two passes can reach a phone out
 * of order, or twice, and an older one must never stand as the current one or ring. Then the
 * newest is shown again, without a sound: from memory or the note, in its words at `now`, so it
 * never names a backup that can no longer be caught; from the tray as it is. When the newest
 * cannot be worded, the push itself is shown, without a sound. The push always shows a
 * notification (a browser requires one). Resolves once shown, with the note's write, if any.
 */
async function showFlights(
  scope: PushScope,
  notes: Notes,
  data: unknown,
  shownFor: (data: unknown) => Shown,
  now: Date,
): Promise<{ readonly written: Promise<void> | null }> {
  const shown = shownFor(data);
  const at = checkedAt(shown.options.data) ?? -Infinity;
  const tag = shown.options.tag ?? '';
  const mine = notes.remembered(tag);
  const [held, note] = await Promise.all([
    timed(async () => (await scope.registration.getNotifications?.({ tag })) ?? [], []),
    notes.read(tag),
  ]);
  // The newest alert in the tray under this tag (the tray cannot be read: none).
  let tray: ShownLike | null = null;
  for (const one of held) {
    if ((checkedAt(one.data) ?? -Infinity) > (checkedAt(tray?.data) ?? -Infinity)) tray = one;
  }
  const trayAt = checkedAt(tray?.data) ?? -Infinity;
  const known = [mine, note]
    .filter((one): one is Kept => one !== null && one.at >= at)
    .sort((a, b) => b.at - a.at);
  const newest = Math.max(trayAt, ...known.map((one) => one.at));
  if (newest < at) {
    await scope.registration.showNotification(shown.title, shown.options);
    notes.remember(tag, { at, data }, now);
    return { written: notes.keep(tag, { at, data }, now) };
  }
  // The same or a newer alert was shown: this push never rings.
  for (const one of known) {
    notes.remember(tag, one, now);
    const again = shownFor(one.data);
    // Only an alert that reads back whole, under this tag, with its own `at`.
    if (one.at >= trayAt && again.options.tag === tag && checkedAt(again.options.data) === one.at) {
      await scope.registration.showNotification(again.title, quiet(again.options));
      return { written: null };
    }
  }
  if (tray !== null && trayAt > at) {
    await scope.registration.showNotification(
      tray.title,
      quiet({
        body: tray.body,
        icon: tray.icon,
        tag: tray.tag,
        data: tray.data as Shown['options']['data'],
      }),
    );
    return { written: null };
  }
  // The same alert again, or a newer one that no longer reads: this push, without a sound.
  await scope.registration.showNotification(shown.title, quiet(shown.options));
  return { written: null };
}

/** Installs the push and click handlers on the worker's scope. `now` is for tests. */
export function installPush(
  scope: PushScope,
  icon: string,
  now: () => Date = () => new Date(),
): void {
  let db: AlertDb | undefined;
  try {
    db = scope.indexedDB;
  } catch {
    db = undefined;
  }
  const notes = new Notes(db);
  /** The Flights pushes waiting under each tag. */
  const queues = new Map<string, Promise<unknown>>();
  scope.addEventListener('push', (event) => {
    let data: unknown;
    try {
      data = event.data?.json() ?? null;
    } catch {
      data = null;
    }
    const first = notificationFor(data, scope.registration.scope, icon, now());
    const tag = first.options.tag;
    if (checkedAt(first.options.data) === null || tag === undefined) {
      // Schools pushes (no `at`) are shown at once, as they always were (TRAV-P2-S3).
      event.waitUntil(scope.registration.showNotification(first.title, first.options));
      return;
    }
    // One Flights push at a time per tag (TRAV-P1-B1): each reads the tray and the notes only
    // after the one before it has shown, so two in flight together never leave the older last.
    const before = queues.get(tag) ?? Promise.resolve();
    const run = before.then(() => {
      const at = now();
      return showFlights(
        scope,
        notes,
        data,
        (facts) => notificationFor(facts, scope.registration.scope, icon, at),
        at,
      );
    });
    const after = run.then(
      () => undefined,
      () => undefined,
    );
    queues.set(tag, after);
    void after.then(() => {
      if (queues.get(tag) === after) queues.delete(tag);
    });
    event.waitUntil(run);
    // The note's write keeps the worker up until it is done.
    event.waitUntil(
      run.then(
        ({ written }) => written,
        () => undefined,
      ),
    );
  });
  scope.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(open(scope, clickUrl(event.notification.data, scope.registration.scope)));
  });
}
