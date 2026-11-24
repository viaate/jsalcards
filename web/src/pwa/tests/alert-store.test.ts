/** The page clearing the worker's notes of shown Flights alerts (TRAV-P1-S3), on fakes. */
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Api } from '../../account/api';
import type { AccountStore } from '../../account/session';
import { createTripsClient } from '../../modes/flights/trips';
import { forgetAlerts, forgetTrip } from '../alert-store';
import { installPush, type PushScope } from '../push';
import { fakeIdb } from './fake-idb';

const TRIP = '0123456789abcdef0123456789abcdef';
const NOTE = JSON.stringify({ at: 1, data: null });

/** The notes database with a note for each of this trip's tags and one for another trip. */
function notes(options: Parameters<typeof fakeIdb>[0] = {}) {
  const fake = fakeIdb(options);
  for (const tag of ['risk', 'faa', 'waiver'].map((group) => `fl-${group}-${TRIP}`))
    fake.notes.set(tag, NOTE);
  fake.notes.set('fl-risk-other', NOTE);
  return fake;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the worker’s Flights alert notes, cleared by the page', () => {
  it('drops them all, or one trip’s, and never fails', async () => {
    const all = notes();
    await forgetAlerts(all.db);
    expect(all.notes.size).toBe(0);
    expect(all.log).toEqual(['drop']);
    const one = notes();
    await forgetTrip(TRIP, one.db);
    expect([...one.notes.keys()]).toEqual(['fl-risk-other']);
    for (const broken of [{ broken: true }, { throws: true }]) {
      await expect(forgetAlerts(notes(broken).db)).resolves.toBeUndefined();
      await expect(forgetTrip(TRIP, notes(broken).db)).resolves.toBeUndefined();
    }
    await expect(forgetAlerts(null)).resolves.toBeUndefined();
    await expect(forgetTrip(TRIP, null)).resolves.toBeUndefined();
  });

  it('a store that never answers does not hold the page up', async () => {
    const started = Date.now();
    await forgetAlerts(notes({ hung: true }).db);
    await forgetTrip(TRIP, notes({ hung: true }).db);
    expect(Date.now() - started).toBeLessThan(3000);
  });

  it('the drop waits for a note write under way, so no note is left after it', async () => {
    const fake = fakeIdb({ puts: [300] });
    const waits: Promise<unknown>[] = [];
    let push = null as ((event: never) => void) | null;
    const scope: PushScope = {
      indexedDB: fake.db,
      registration: {
        scope: 'https://snowlightmap.com/',
        showNotification: () => Promise.resolve(),
        getNotifications: () => Promise.resolve([]),
      },
      clients: { matchAll: () => Promise.resolve([]), openWindow: () => Promise.resolve(null) },
      addEventListener(type: string, listener: (event: never) => void) {
        if (type === 'push') push = listener;
      },
    };
    installPush(scope, '/i.png', () => new Date(1_767_614_400_000));
    const facts = {
      v: 1,
      kind: 'flight',
      alert: 'chance',
      trip: TRIP,
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
      faa: null,
      waiver: null,
      backups: [],
      more: false,
      ticket: 'unsure',
      at: 1_767_614_400,
    };
    push?.({
      data: { json: () => facts },
      waitUntil: (p: Promise<unknown>) => waits.push(p),
    } as never);
    await waits[0];
    // Signed out while the worker is still writing its note.
    await forgetAlerts(fake.db);
    await Promise.all(waits);
    await new Promise((done) => setTimeout(done, 50));
    expect(fake.log).toEqual(['put 1767614400', 'drop']);
    expect(fake.notes.size).toBe(0);
  });

  it('a deleted trip and Flights alerts turned off take their notes with them', async () => {
    const fake = notes();
    vi.stubGlobal('indexedDB', fake.db);
    let alerts = true;
    const api: Api = {
      root: 'https://api.test',
      call: <T>(): Promise<T> =>
        Promise.resolve({
          settings: {
            alerts,
            threshold: 50,
            night_before: true,
            night_time: '19:00',
            email: false,
          },
        } as T),
    };
    const store = { api, token: () => 'tok', signedOut: () => undefined };
    const trips = createTripsClient(store as unknown as AccountStore);
    await trips.remove(TRIP);
    expect([...fake.notes.keys()]).toEqual(['fl-risk-other']);
    await trips.setNotify({ threshold: 50 });
    expect(fake.log).not.toContain('drop');
    alerts = false;
    await trips.setNotify({ alerts: false });
    expect(fake.log).toContain('drop');
    expect(fake.notes.size).toBe(0);
  });
});
