/** A Flights trip alert as the service worker shows it (flights spec D12), on made-up facts. */
import { describe, expect, it } from 'vitest';

import { flightTag, installPush, notificationFor, type PushScope, type ShownLike } from '../push';
import { tripsCopy } from '../../copy-trips';

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

    /** A worker scope whose tray holds what it shows, by tag, as a phone does. */
    function tray(readable = true) {
      const held = new Map<string, ShownLike>();
      const shown: { title: string; options: NotificationOptions }[] = [];
      let push: ((event: never) => void) | null = null;
      const scope: PushScope = {
        registration: {
          scope: SCOPE,
          showNotification: (title, options = {}) => {
            shown.push({ title, options });
            const tag = options.tag ?? '';
            held.set(tag, {
              title,
              body: options.body ?? '',
              icon: options.icon ?? '',
              tag,
              data: options.data as unknown,
            });
            return Promise.resolve();
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
      installPush(scope, '/i.png', () => new Date((T2 + 5 * 60) * 1000));
      const deliver = async (facts: unknown): Promise<void> => {
        const waits: Promise<unknown>[] = [];
        push?.({
          data: { json: () => facts },
          waitUntil: (p: Promise<unknown>) => waits.push(p),
        } as never);
        await Promise.all(waits);
      };
      return { held, shown, deliver };
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
      const blind = tray(false);
      await blind.deliver(risk('chance', T2, 40));
      await blind.deliver(risk('fall', T1, 10));
      expect(blind.shown).toHaveLength(2);
    });
  });
});
