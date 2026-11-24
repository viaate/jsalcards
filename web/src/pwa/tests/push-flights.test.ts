/** A Flights trip alert as the service worker shows it (flights spec D12), on made-up facts. */
import { describe, expect, it } from 'vitest';

import {
  flightTag,
  installPush,
  notificationFor,
  type PushScope,
  type ShownLike,
  STORE_WAIT_MS,
} from '../push';
import { fakeIdb } from './fake-idb';
import { tripsCopy } from '../../copy-trips';
import SENT from '../../modes/flights/tests/alert-facts.json';

const FACTS = {
  v: 1,
  kind: 'flight',
  alert: 'faa',
  trip: '0123456789abcdef0123456789abcdef',
  carrier: 'WN',
  number: 1234,
  from: 'MCI',
  to: 'LAX',
  day: '2026-01-06',
  leaves: 370,
  cancel: 31,
  late: 12,
  level: 'cancel',
  why: null,
  faa: { airport: 'MCI', program: 1 },
  waiver: null,
  backups: [],
  more: false,
  ticket: 'unsure',
};

describe('Flights alerts in the service worker', () => {
  it('shows the trip, what changed, and opens the trip', () => {
    const shown = notificationFor(FACTS, 'https://snowlightmap.com/', '/icon.png', new Date());
    expect(shown.title).toBe('WN 1234 · MCI to LAX');
    expect(shown.options.body).toBe(
      `The FAA has a ground delay at MCI. Leaves Tue, Jan 6 at 6:10 am. ${tripsCopy.alert.noBackup}`,
    );
    expect(shown.options.tag).toBe('fl-faa-0123456789abcdef0123456789abcdef');
    // An alert with no `at` has no checked time to show (TRAV-R7-S3, below).
    expect(shown.options).not.toHaveProperty('timestamp');
    // TRAV-R3-B2: a push that replaces one still in the tray rings again, never a silent swap.
    expect(shown.options.renotify).toBe(true);
    for (const alert of ['chance', 'rise', 'fall', 'safer', 'night', 'waiver']) {
      const facts =
        alert === 'waiver'
          ? {
              ...FACTS,
              alert,
              faa: null,
              waiver: { state: 'waiver', basic: false, airport: 'MCI' },
            }
          : { ...FACTS, alert, faa: null };
      const risk = notificationFor(facts, 'https://snowlightmap.com/', '/i.png', new Date());
      expect(risk.options.tag).toBe(`fl-${flightTag(alert)}-0123456789abcdef0123456789abcdef`);
      // A safer alert with no safer flight left says nothing new (TRAV-R5-S1, below).
      expect(risk.options.renotify).toBe(alert !== 'safer');
    }
    // TRAV-R2-S4: the risk kinds share one tray slot per trip, so a fall replaces the chance.
    for (const alert of ['chance', 'rise', 'fall', 'safer', 'night'])
      expect(flightTag(alert)).toBe('risk');
    expect(flightTag('waiver')).toBe('waiver');
    expect(shown.options.data.url).toBe(
      'https://snowlightmap.com/?mode=flights&page=trips&trip=0123456789abcdef0123456789abcdef',
    );
  });
  it('says when an alert was checked when it reaches the phone late, never as current', () => {
    const checked = { ...FACTS, at: 1_767_614_400, checked: { day: '2026-01-05', minute: 360 } };
    const fresh = notificationFor(
      checked,
      'https://snowlightmap.com/',
      '/i.png',
      new Date(1_767_614_400_000 + 10 * 60_000),
    );
    expect(fresh.options.body).toBe(
      `The FAA has a ground delay at MCI. Leaves Tue, Jan 6 at 6:10 am. ${tripsCopy.alert.noBackup}`,
    );
    const late = notificationFor(
      checked,
      'https://snowlightmap.com/',
      '/i.png',
      new Date(1_767_614_400_000 + 40 * 60_000),
    );
    expect(late.options.body).toBe(
      `Checked Mon, Jan 5 at 6:00 am, MCI time. The FAA has a ground delay at MCI. Leaves Tue, Jan 6 at 6:10 am. ${tripsCopy.alert.noBackup}`,
    );
    // TRAV-R7-S3: the tray's time is when the sender checked, on time or late.
    expect(fresh.options.timestamp).toBe(1_767_614_400_000);
    expect(late.options.timestamp).toBe(1_767_614_400_000);
  });
  it('a safer alert shown after its safer flights left updates the tray without a sound (TRAV-R5-S1)', () => {
    const at = 1_767_614_400;
    const backup = {
      carrier: 'AA',
      number: 88,
      from: 'MCI',
      to: 'LAX',
      day: '2026-01-06',
      leaves: 360,
      departs: at + 3 * 3600,
      chance: 92,
      kind: 'other',
      miles: null,
      via: null,
    };
    const safer = { ...FACTS, alert: 'safer', faa: null, at, backups: [backup] };
    const show = (minutes: number) =>
      notificationFor(
        safer,
        'https://snowlightmap.com/',
        '/i.png',
        new Date((at + minutes * 60) * 1000),
      );
    expect(show(10).options).toMatchObject({ renotify: true, silent: false });
    expect(show(10).options.body).toMatch(/^Another usual flight looks safer\./);
    const late = show(61).options;
    expect(late).toMatchObject({ renotify: false, silent: true, tag: `fl-risk-${FACTS.trip}` });
    expect(late.body).not.toContain(tripsCopy.alert.safer);
  });
  it('falls back to the plain notification when the facts do not read', () => {
    const shown = notificationFor(
      { ...FACTS, faa: null },
      'https://snowlightmap.com/',
      '/i.png',
      new Date(),
    );
    expect(shown.options.tag).toBe('snowlight');
    // The Schools pushes are as they were.
    expect(shown.options.renotify).toBeUndefined();
  });

  describe('two alerts from two passes reaching the phone out of order (TRAV-R6-B1)', () => {
    const SCOPE = 'https://snowlightmap.com/';
    const T1 = 1_767_614_400;
    const T2 = T1 + 20 * 60;

    /** The worker's IndexedDB, in memory (fake-idb.ts); `broken`: every open fails. */
    function store(broken = false, options: Parameters<typeof fakeIdb>[0] = {}) {
      return fakeIdb({ broken, ...options });
    }

    /**
     * A worker scope whose tray holds what it shows, by tag, as a phone does. `deliver` settles
     * once the push is shown; `settle` once every note write is done too.
     */
    function tray(readable = true, db?: IDBFactory, clock = { now: T2 + 5 * 60 }, trayWait = 0) {
      const held = new Map<string, ShownLike>();
      const shown: { title: string; options: NotificationOptions }[] = [];
      const waits: Promise<unknown>[] = [];
      let push: ((event: never) => void) | null = null;
      const scope: PushScope = {
        ...(db === undefined ? {} : { indexedDB: db }),
        registration: {
          scope: SCOPE,
          showNotification: async (title, options = {}) => {
            await new Promise((done) => setTimeout(done, trayWait));
            shown.push({ title, options });
            const tag = options.tag ?? '';
            held.set(tag, {
              title,
              body: options.body ?? '',
              icon: options.icon ?? '',
              tag,
              data: options.data as unknown,
            });
          },
          getNotifications: (filter) =>
            readable
              ? Promise.resolve([...held.values()].filter((n) => n.tag === filter?.tag))
              : Promise.reject(new Error('no tray')),
        },
        clients: { matchAll: () => Promise.resolve([]), openWindow: () => Promise.resolve(null) },
        addEventListener(type: string, listener: (event: never) => void) {
          if (type === 'push') push = listener;
        },
      };
      installPush(scope, '/i.png', () => new Date(clock.now * 1000));
      const deliver = async (facts: unknown): Promise<void> => {
        const mine: Promise<unknown>[] = [];
        push?.({
          data: { json: () => facts },
          waitUntil: (p: Promise<unknown>) => mine.push(p),
        } as never);
        waits.push(...mine);
        await mine[0];
      };
      /** The person swipes the notification away. */
      const dismiss = (tag: string): void => {
        held.delete(tag);
      };
      const settle = async (): Promise<void> => {
        await Promise.all(waits);
      };
      /** Whether each push shown rang: [silent, renotify]. */
      const sounds = () =>
        shown.map((one) => [one.options.silent, (one.options as { renotify?: boolean }).renotify]);
      return { held, shown, deliver, dismiss, clock, settle, sounds };
    }

    const risk = (alert: string, at: number, cancel: number) => ({
      ...FACTS,
      alert,
      faa: null,
      at,
      cancel,
      late: 5,
      level: cancel >= 30 ? 'cancel' : 'low',
    });
    const tag = `fl-risk-${FACTS.trip}`;

    it('an older fall or safer that arrives after a newer chance or rise never replaces it', async () => {
      for (const [newer, older] of [
        [risk('chance', T2, 40), risk('fall', T1, 10)],
        [risk('rise', T2, 61), risk('safer', T1, 31)],
        [risk('chance', T2, 40), risk('night', T1, 31)],
      ] as const) {
        const { held, shown, deliver } = tray();
        await deliver(newer);
        await deliver(older);
        const now = held.get(tag);
        expect(now?.data).toMatchObject({ at: T2 });
        expect(now?.body).toContain(`${String(newer.cancel)}% chance`);
        expect(now?.body).not.toContain(`${String(older.cancel)}% chance`);
        // Every push still shows a notification: the newer one again, without a sound.
        expect(shown).toHaveLength(2);
        expect(shown[1]).toMatchObject({ title: shown[0]?.title, options: { silent: true } });
        expect((shown[1]?.options as { renotify?: boolean }).renotify).toBe(false);
      }
    });

    it('a newer alert after an older one replaces it, and an unreadable tray shows the push', async () => {
      const inOrder = tray();
      await inOrder.deliver(risk('fall', T1, 10));
      await inOrder.deliver(risk('chance', T2, 40));
      expect(inOrder.held.get(tag)?.data).toMatchObject({ at: T2 });
      expect(inOrder.shown[1]?.options).toMatchObject({ silent: false });
      // FAA and waiver alerts keep their own slot: a newer risk alert never hides them.
      const faa = tray();
      await faa.deliver({ ...FACTS, at: T1 });
      await faa.deliver(risk('chance', T2, 40));
      expect(faa.held.get(`fl-faa-${FACTS.trip}`)?.data).toMatchObject({ at: T1 });
      expect(faa.held.get(tag)?.data).toMatchObject({ at: T2 });
      // No tray and no store: the worker's memory still knows the newer one.
      const blind = tray(false);
      await blind.deliver(risk('chance', T2, 40));
      await blind.deliver(risk('fall', T1, 10));
      expect(blind.shown).toHaveLength(2);
      expect(blind.sounds()).toEqual([
        [false, true],
        [true, false],
      ]);
      expect(blind.held.get(tag)?.data).toMatchObject({ at: T2 });
    });

    it('drops an older alert even when the newer one was swiped away (TRAV-R7-S2)', async () => {
      const { db, notes } = store();
      const { held, shown, deliver, dismiss, settle } = tray(true, db);
      await deliver(risk('rise', T2, 61));
      dismiss(tag);
      await deliver(risk('fall', T1, 10));
      // The tray ends on the newest state, worded now, shown again without a sound.
      const now = held.get(tag);
      expect(now?.data).toMatchObject({ at: T2 });
      expect(now?.body).toContain('61% chance');
      expect(now?.body).not.toContain('10% chance');
      expect(now?.body).not.toContain(tripsCopy.alert.fall);
      expect(shown).toHaveLength(2);
      expect(shown[1]?.options).toMatchObject({ silent: true, renotify: false });
      expect(shown[1]?.options).toMatchObject({ timestamp: T2 * 1000 });
      // A newer one after that is shown as a real change, and becomes the newest.
      await deliver(risk('chance', T2 + 600, 40));
      expect(held.get(tag)?.data).toMatchObject({ at: T2 + 600 });
      expect(shown[2]?.options).toMatchObject({ silent: false, timestamp: (T2 + 600) * 1000 });
      // An FAA alert keeps its own note: a newer risk alert never drops it.
      await deliver({ ...FACTS, at: T1 });
      expect(held.get(`fl-faa-${FACTS.trip}`)?.data).toMatchObject({ at: T1 });
      await settle();
      expect([...notes.keys()].sort()).toEqual([`fl-faa-${FACTS.trip}`, tag]);
    });

    it('drops an older alert while the newer one is still in the tray, store or not', async () => {
      for (const db of [store().db, store(true).db, store(false, { throws: true }).db, undefined]) {
        const { held, shown, deliver } = tray(true, db);
        await deliver(risk('chance', T2, 40));
        await deliver(risk('fall', T1, 10));
        expect(held.get(tag)?.data).toMatchObject({ at: T2 });
        expect(shown[1]?.options).toMatchObject({ silent: true, timestamp: T2 * 1000 });
      }
    });

    it('a worker started again with no storage falls back to the tray check alone', async () => {
      for (const db of [store(true).db, store(false, { throws: true }).db, undefined]) {
        const first = tray(true, db);
        await first.deliver(risk('rise', T2, 61));
        first.dismiss(tag);
        // A new worker: nothing remembers the swiped one, so the push is shown as it is.
        const { held, shown, deliver } = tray(true, db);
        await deliver(risk('fall', T1, 10));
        expect(shown).toHaveLength(1);
        expect(held.get(tag)?.data).toMatchObject({ at: T1 });
      }
    });

    it('a newer note that no longer reads keeps an older push from ringing (TRAV-P2-S1)', async () => {
      for (const data of [{ v: 2 }, null, { ...risk('rise', T2, 61), trip: 'other' }]) {
        const { db, notes } = store();
        const first = tray(true, db);
        await first.deliver(risk('rise', T2, 61));
        await first.settle();
        // A worker update reads its notes no more; the newer alert was swiped away.
        notes.set(tag, JSON.stringify({ at: T2, data }));
        const { held, shown, deliver, sounds, settle } = tray(true, db);
        await deliver(risk('fall', T1, 10));
        expect(sounds()).toEqual([[true, false]]);
        expect(shown[0]?.options).toMatchObject({ timestamp: T1 * 1000 });
        expect(held.get(tag)?.data).toMatchObject({ at: T1 });
        // And the note stays on the newer `at`.
        await settle();
        expect(JSON.parse(notes.get(tag) ?? 'null')).toMatchObject({ at: T2 });
      }
    });

    it('two or three pushes handled at the same time end on the newest (TRAV-P1-B1)', async () => {
      const a = risk('fall', T1, 10);
      const b = risk('chance', T1 + 600, 40);
      const c = risk('rise', T2, 61);
      const orders = [
        [c, a],
        [a, c],
        [a, b, c],
        [a, c, b],
        [b, a, c],
        [b, c, a],
        [c, a, b],
        [c, b, a],
      ];
      for (const order of orders) {
        // A slow disk and a slow tray, so all the pushes are in flight at once.
        const { db, kept } = store(false, { wait: 5 });
        const { held, shown, deliver, settle } = tray(true, db, { now: T2 + 300 }, 3);
        await Promise.all(order.map((facts) => deliver(facts)));
        await settle();
        expect(held.get(tag)?.data).toMatchObject({ at: T2 });
        expect(held.get(tag)?.body).toContain('61% chance');
        expect(kept()).toEqual([T2]);
        expect(shown).toHaveLength(order.length);
        expect(shown.at(-1)?.options.data).toMatchObject({ at: T2 });
        // Only a push newer than every one before it rang.
        let top = -Infinity;
        const rings = order.map((facts) => {
          const rings = facts.at > top;
          top = Math.max(top, facts.at);
          return rings;
        });
        expect(shown.map((one) => one.options.silent !== true)).toEqual(rings);
      }
    });

    it('a slow note write never lands over a newer one (TRAV-P2-B1)', async () => {
      const chance = risk('chance', T1, 40);
      const rise = risk('rise', T1 + 1800, 70);
      const fall = risk('fall', T1 + 1200, 10);
      // The first note write takes 1.5 s, past the read limit; the next is fast.
      const { db, log, kept } = store(false, { puts: [1.5 * STORE_WAIT_MS] });
      const { held, deliver, dismiss, settle, sounds } = tray(true, db, { now: T1 + 1900 });
      await deliver(chance);
      await deliver(rise);
      // Swiped away while the first write is still under way, then a push from between them.
      dismiss(tag);
      await deliver(fall);
      expect(sounds()).toEqual([
        [false, true],
        [false, true],
        [true, false],
      ]);
      expect(held.get(tag)?.data).toMatchObject({ at: rise.at });
      expect(held.get(tag)?.body).toContain('70% chance');
      await settle();
      // The writes land in order, and the note ends on the newest.
      expect(log).toEqual([`put ${String(chance.at)}`, `put ${String(rise.at)}`]);
      expect(kept()).toEqual([rise.at]);
      // A worker started again after that still drops the push from between them.
      dismiss(tag);
      const again = tray(true, db, { now: T1 + 1900 });
      await again.deliver(fall);
      expect(again.sounds()).toEqual([[true, false]]);
      expect(again.held.get(tag)?.body).toContain('70% chance');
    }, 15_000);

    it('a write never puts an older note over a newer one, even from a fresh worker', async () => {
      // Reads slower than their limit: a fresh worker cannot see the note in time.
      const { db, kept } = store(false, { wait: 1.2 * STORE_WAIT_MS });
      const first = tray(true, db);
      await first.deliver(risk('rise', T2, 61));
      await first.settle();
      const again = tray(true, db);
      await again.deliver(risk('fall', T1, 10));
      await again.settle();
      // Read and put in one transaction: the older one is not put.
      expect(kept()).toEqual([T2]);
    }, 20_000);

    it('a store that hangs, throws or reads too slowly never lets an older push ring (TRAV-P1-S4)', async () => {
      const kinds = {
        hung: store(false, { hung: true }).db,
        broken: store(true).db,
        throws: store(false, { throws: true }).db,
        slow: store(false, { wait: 1.2 * STORE_WAIT_MS }).db,
      };
      for (const db of Object.values(kinds)) {
        const { held, deliver, dismiss, sounds } = tray(true, db);
        const started = Date.now();
        await deliver(risk('rise', T2, 61));
        // The push is shown without waiting on the store past its limit.
        expect(Date.now() - started).toBeLessThan(STORE_WAIT_MS + 500);
        dismiss(tag);
        await deliver(risk('fall', T1, 10));
        expect(sounds()).toEqual([
          [false, true],
          [true, false],
        ]);
        expect(held.get(tag)?.body).toContain('61% chance');
        expect(Date.now() - started).toBeLessThan(3 * STORE_WAIT_MS);
      }
    }, 20_000);

    it('a newer alert shown again is worded now, never naming a backup it is too late for (TRAV-P1-S1)', async () => {
      const safer = { ...SENT.safer, alert: 'chance' };
      const first = safer.backups[0];
      if (first === undefined) throw new Error('the made-up safer push has backups');
      const clock = { now: safer.at };
      const { db } = store();
      const { held, shown, deliver } = tray(true, db, clock);
      await deliver(safer);
      expect(shown[0]?.options.body).toContain('WN 1500');
      // One minute inside WN 1500's lead, an older push for the trip comes in.
      clock.now = first.departs - 2 * 3600 + 60;
      await deliver({ ...safer, alert: 'fall', at: safer.at - 1200, backups: [] });
      const now = notificationFor(safer, SCOPE, '/i.png', new Date(clock.now * 1000));
      expect(shown[1]?.options.body).toBe(now.options.body);
      expect(shown[1]?.options.body).not.toContain('WN 1500');
      expect(shown[1]?.options).toMatchObject({
        silent: true,
        renotify: false,
        timestamp: safer.at * 1000,
      });
      expect(held.get(`fl-risk-${safer.trip}`)?.data).toMatchObject({ at: safer.at });
    });

    it('a second delivery of the same push never rings again (TRAV-P1-S2)', async () => {
      for (const db of [store().db, store(true).db, undefined]) {
        const { shown, deliver, dismiss, sounds } = tray(true, db);
        const rise = risk('rise', T2, 61);
        await deliver(rise);
        await deliver(rise);
        // Swiped away first: memory (and the note) still know it, so it comes back quietly.
        dismiss(tag);
        await deliver(rise);
        expect(sounds()).toEqual([
          [false, true],
          [true, false],
          [true, false],
        ]);
        expect(shown[1]?.options.body).toBe(shown[0]?.options.body);
      }
      // A worker started again: the note still knows it.
      const { db } = store();
      const first = tray(true, db);
      await first.deliver(risk('rise', T2, 61));
      await first.settle();
      const again = tray(true, db);
      await again.deliver(risk('rise', T2, 61));
      expect(again.sounds()).toEqual([[true, false]]);
    });

    it('drops the notes of trips whose day is over, each time it writes one (TRAV-P1-S3)', async () => {
      const { db, notes, kept } = store();
      const old = {
        ...risk('chance', T1, 40),
        trip: 'ffffffffffffffffffffffffffffffff',
        day: '2026-01-03',
      };
      const clock = { now: T1 };
      const { deliver, settle } = tray(true, db, clock);
      clock.now = Date.UTC(2026, 0, 3, 12) / 1000;
      await deliver({ ...old, at: clock.now });
      await settle();
      expect(notes.size).toBe(1);
      // Two days on, a push for another trip: the old trip's note goes, the new one stays.
      clock.now = Date.UTC(2026, 0, 5, 1) / 1000;
      await deliver(risk('chance', clock.now, 40));
      await settle();
      expect(kept()).toEqual([clock.now]);
      // The note holds only the newest `at` and its facts, under the trip's own tag.
      expect([...notes.keys()]).toEqual([tag]);
      expect(Object.keys(JSON.parse(notes.get(tag) ?? '{}') as object)).toEqual(['at', 'data']);
    });

    it('shows Schools pushes at once, never behind a Flights store (TRAV-P2-S3)', async () => {
      const { db, log } = store(false, { hung: true });
      const { shown, deliver } = tray(true, db);
      const school = {
        v: 1,
        kind: 'chance',
        school: '123456789012',
        name: 'Lincoln Elementary',
        day: '2026-01-06',
        zone: 'America/Chicago',
        percent: 40,
        rise: false,
      };
      const started = Date.now();
      // A Flights push waits on its hung store; the Schools push right after does not.
      const flights = deliver(risk('chance', T2, 40));
      await deliver(school);
      expect(Date.now() - started).toBeLessThan(STORE_WAIT_MS / 2);
      expect(shown).toHaveLength(1);
      expect(shown[0]?.options.tag).toBe('chance-123456789012-2026-01-06');
      expect(shown[0]?.options).not.toHaveProperty('timestamp');
      expect(shown[0]?.options).not.toHaveProperty('silent');
      await flights;
      expect(shown).toHaveLength(2);
      expect(log).toEqual([]);
    });
  });
});
