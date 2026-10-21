// The service worker's push and click handlers (src/pwa/push.ts), with a fake worker scope.
// Every school and payload here is made up.
import { describe, expect, it, vi } from 'vitest';

import {
  installPush,
  notificationFor,
  readPayload,
  schoolUrl,
  type ClickEventLike,
  type PushEventLike,
  type PushScope,
  type WindowLike,
} from '../push';

const SCOPE = 'https://snowlightmap.com/';
const ICON = 'https://snowlightmap.com/icons/icon-192.png';
const CHICAGO = 'America/Chicago';
/** 07:05 in Chicago on Tue Jan 12 2027. */
const MORNING = new Date('2027-01-12T13:05:00Z');

const base = {
  v: 1,
  school: '170000000001',
  name: 'Lincoln High',
  day: '2027-01-12',
  zone: CHICAGO,
};

describe('reading a push', () => {
  it('reads each kind', () => {
    expect(
      readPayload({ ...base, kind: 'status', status: 'closed', shift: null, clock: null }),
    ).toEqual({
      school: '170000000001',
      name: 'Lincoln High',
      day: '2027-01-12',
      zone: CHICAGO,
      kind: 'status',
      status: 'closed',
      shift: null,
      clock: null,
    });
    expect(readPayload({ ...base, kind: 'lifted', was: 'delayed', open: true })?.kind).toBe(
      'lifted',
    );
    expect(readPayload({ ...base, kind: 'chance', percent: 62, rise: false })?.kind).toBe('chance');
    expect(readPayload({ ...base, kind: 'night', percent: 35 })?.kind).toBe('night');
  });

  it('refuses anything out of shape', () => {
    const bad: unknown[] = [
      null,
      'text',
      { ...base, v: 2, kind: 'night', percent: 35 },
      { ...base, school: '../x', kind: 'night', percent: 35 },
      { ...base, name: '', kind: 'night', percent: 35 },
      { ...base, day: 'Jan 12', kind: 'night', percent: 35 },
      { ...base, zone: 'Mars/Olympus', kind: 'night', percent: 35 },
      { ...base, kind: 'status', status: 'snowed_in', shift: null, clock: null },
      { ...base, kind: 'status', status: 'delayed', shift: -5, clock: null },
      { ...base, kind: 'status', status: 'delayed', shift: 120, clock: 2000 },
      { ...base, kind: 'lifted', was: 'closed' },
      // Only an open statement lifts a status: a lift without one is never shown as such.
      { ...base, kind: 'lifted', was: 'closed', open: false },
      { ...base, kind: 'chance', percent: 100, rise: false },
      { ...base, kind: 'chance', percent: 50 },
      { ...base, kind: 'other', percent: 50 },
    ];
    for (const data of bad) expect(readPayload(data)).toBeNull();
  });
});

describe('the notification', () => {
  const show = (payload: Record<string, unknown>, now = MORNING) =>
    notificationFor({ ...base, ...payload }, SCOPE, ICON, now);

  it('says a status for the school’s own today, with its date', () => {
    const shown = show({ kind: 'status', status: 'closed', shift: null, clock: null });
    expect(shown.title).toBe('Lincoln High');
    expect(shown.options.body).toBe('Closed today (Tue, Jan 12)');
    expect(shown.options.icon).toBe(ICON);
    expect(shown.options.tag).toBe('st-170000000001-2027-01-12');
    expect(shown.options.data.url).toBe('https://snowlightmap.com/?school=170000000001');
  });

  it('gives a delay and an early dismissal their times', () => {
    expect(show({ kind: 'status', status: 'delayed', shift: 120, clock: 600 }).options.body).toBe(
      'Delayed start today (Tue, Jan 12) · 2-hour delay · Starts at 10:00 AM',
    );
    expect(
      show({
        kind: 'status',
        status: 'early_dismissal',
        shift: null,
        clock: 750,
        day: '2027-01-13',
      }).options.body,
    ).toBe('Early dismissal tomorrow (Wed, Jan 13) · Dismissal at 12:30 PM');
  });

  it('names the date, not today, when it shows a day late', () => {
    const late = new Date('2027-01-13T15:00:00Z');
    expect(
      show({ kind: 'status', status: 'closed', shift: null, clock: null }, late).options.body,
    ).toBe('Closed Tue, Jan 12');
  });

  it('measures today in the school’s zone, not the device’s', () => {
    // 05:30 UTC on Jan 13 is still Jan 12 in Chicago.
    const night = new Date('2027-01-13T05:30:00Z');
    expect(
      show({ kind: 'status', status: 'remote', shift: null, clock: null }, night).options.body,
    ).toBe('Remote learning today (Tue, Jan 12)');
  });

  it('says open where the school said so', () => {
    expect(show({ kind: 'lifted', was: 'delayed', open: true }).options.body).toBe(
      'Open today (Tue, Jan 12)',
    );
  });

  it('says a chance, its rise, and the evening check', () => {
    const evening = new Date('2027-01-12T01:07:00Z'); // 19:07 on Jan 11 in Chicago
    expect(show({ kind: 'chance', percent: 62, rise: false }, evening).options.body).toBe(
      'Tomorrow (Tue, Jan 12): 62% chance of no school',
    );
    expect(show({ kind: 'chance', percent: 82, rise: true }, evening).options.body).toBe(
      'Tomorrow (Tue, Jan 12): up to 82% chance of no school',
    );
    const night = show({ kind: 'night', percent: 35 }, evening);
    expect(night.options.body).toBe('Tomorrow (Tue, Jan 12): 35% chance of no school');
    expect(night.options.tag).toBe('night-170000000001-2027-01-12');
  });

  it('shows a plain notification for a push that does not read', () => {
    const shown = notificationFor({ v: 9 }, SCOPE, ICON, MORNING);
    expect(shown.title).toBe('Snowlight');
    expect(shown.options.body).toBe('Open Snowlight for the latest closings and chances.');
    expect(shown.options.data.url).toBe(SCOPE);
  });

  it('opens the school under the worker’s scope', () => {
    expect(schoolUrl('https://viaate.github.io/jsalcards/', 'A0000005')).toBe(
      'https://viaate.github.io/jsalcards/?school=A0000005',
    );
    expect(schoolUrl('https://snowlightmap.com/?x=1#y', null)).toBe('https://snowlightmap.com/');
  });
});

function fakeScope(windows: WindowLike[] = []) {
  const handlers: Record<string, ((event: never) => void)[]> = {};
  const shown: { title: string; options: NotificationOptions | undefined }[] = [];
  const opened: string[] = [];
  const scope: PushScope = {
    registration: {
      scope: SCOPE,
      showNotification: (title, options) => {
        shown.push({ title, options });
        return Promise.resolve();
      },
    },
    clients: {
      matchAll: () => Promise.resolve(windows),
      openWindow: (url) => {
        opened.push(url);
        return Promise.resolve(null);
      },
    },
    addEventListener(type: string, listener: (event: never) => void) {
      (handlers[type] ??= []).push(listener);
    },
  };
  const fire = async (type: string, event: PushEventLike | ClickEventLike): Promise<void> => {
    const waits: Promise<unknown>[] = [];
    const withWait = { ...event, waitUntil: (p: Promise<unknown>) => waits.push(p) };
    for (const handler of handlers[type] ?? []) handler(withWait as never);
    await Promise.all(waits);
  };
  return { scope, shown, opened, fire };
}

describe('the worker’s handlers', () => {
  it('shows every push, readable or not', async () => {
    const { scope, shown, fire } = fakeScope();
    installPush(scope, ICON, () => MORNING);
    const payload = { ...base, kind: 'status', status: 'closed', shift: null, clock: null };
    await fire('push', { data: { json: () => payload }, waitUntil: () => undefined });
    await fire('push', {
      data: {
        json: () => {
          throw new SyntaxError('not JSON');
        },
      },
      waitUntil: () => undefined,
    });
    await fire('push', { data: null, waitUntil: () => undefined });
    expect(shown.map((s) => s.title)).toEqual(['Lincoln High', 'Snowlight', 'Snowlight']);
    expect(shown[0]?.options?.body).toBe('Closed today (Tue, Jan 12)');
  });

  it('a tap focuses an open Snowlight window on the school, or opens one', async () => {
    const focus = vi.fn(() => Promise.resolve());
    const navigate = vi.fn(() => Promise.resolve());
    const open = fakeScope([
      { url: 'https://other.example/' },
      { url: `${SCOPE}?zip=64108`, focus, navigate },
    ]);
    installPush(open.scope, ICON);
    const close = vi.fn();
    const url = `${SCOPE}?school=170000000001`;
    await open.fire('notificationclick', {
      notification: { data: { url }, close },
      waitUntil: () => undefined,
    });
    expect(close).toHaveBeenCalled();
    expect(focus).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(url);
    expect(open.opened).toEqual([]);

    const none = fakeScope([]);
    installPush(none.scope, ICON);
    await none.fire('notificationclick', {
      notification: { data: { url }, close },
      waitUntil: () => undefined,
    });
    expect(none.opened).toEqual([url]);
  });

  it('never opens an address outside the site', async () => {
    const { scope, opened, fire } = fakeScope();
    installPush(scope, ICON);
    await fire('notificationclick', {
      notification: { data: { url: 'https://evil.example/' }, close: () => undefined },
      waitUntil: () => undefined,
    });
    expect(opened).toEqual([SCOPE]);
  });
});
