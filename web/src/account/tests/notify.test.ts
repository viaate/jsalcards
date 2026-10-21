// Notifications on this device (src/account/notify.ts): what the browser can do, the iPhone
// case, and turning them on and off, against a fake browser and a fake API.
import { describe, expect, it, vi } from 'vitest';

import { ApiError, type Api } from '../api';
import {
  createNotifyClient,
  dropLocal,
  keyBytes,
  OWNER_KEY,
  ownerOf,
  support,
  type NotifyHost,
  type PushManagerLike,
  type SubscriptionLike,
} from '../notify';

const CHROME = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36';
const IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1';
const IPAD_AS_MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15';
const KEY =
  'BOr1Y2l0z3Hq3B7lmDiyTFR8WlVxiWwVWiL1VnhSq0dUh8Q2tWh5QK7cvfIr8YVd6c0Q3BB6KmFqv3yWG5yKEn0';

function subscription(endpoint = 'https://fcm.googleapis.com/fcm/send/abc') {
  const unsubscribe = vi.fn(() => Promise.resolve(true));
  const held: SubscriptionLike = {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh: 'p', auth: 'a' } }),
    unsubscribe,
  };
  return { held, unsubscribe };
}

function browser(
  options: {
    ua?: string;
    permission?: NotificationPermission;
    answer?: NotificationPermission;
    standalone?: boolean;
    held?: SubscriptionLike | null;
    push?: boolean;
    platform?: string;
    touch?: number;
    owner?: string;
  } = {},
) {
  const stored = new Map<string, string>();
  if (options.owner !== undefined) stored.set(OWNER_KEY, options.owner);
  let permission = options.permission ?? 'default';
  let held = options.held ?? null;
  const subscribe = vi.fn<PushManagerLike['subscribe']>(() => {
    const made = subscription().held;
    held = made;
    return Promise.resolve(made);
  });
  const manager: PushManagerLike = {
    getSubscription: () => Promise.resolve(held),
    subscribe,
  };
  const requestPermission = vi.fn(() => {
    permission = options.answer ?? 'granted';
    return Promise.resolve(permission);
  });
  const env: NotifyHost = {
    navigator: {
      userAgent: options.ua ?? CHROME,
      platform: options.platform ?? 'Linux x86_64',
      maxTouchPoints: options.touch ?? 0,
      ...(options.standalone === undefined ? {} : { standalone: options.standalone }),
      serviceWorker: { ready: Promise.resolve({ pushManager: manager }) },
    },
    Notification: {
      get permission() {
        return permission;
      },
      requestPermission,
    },
    PushManager: options.push === false ? undefined : {},
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: (key) => stored.get(key) ?? null,
      setItem: (key, value) => void stored.set(key, value),
      removeItem: (key) => void stored.delete(key),
    },
  };
  return { env, subscribe, requestPermission, stored };
}

function fakeApi(fail?: (path: string) => ApiError | null) {
  const calls: { method: string; path: string; body: unknown; token: string | null | undefined }[] =
    [];
  const api: Api = {
    root: 'https://api.test',
    call<T>(method: string, path: string, body?: unknown, token?: string | null): Promise<T> {
      calls.push({ method, path, body, token });
      const error = fail?.(path) ?? null;
      if (error !== null) return Promise.reject(error);
      if (path === '/v1/push/key') return Promise.resolve({ key: KEY } as T);
      return Promise.resolve({ devices: 1 } as T);
    },
  };
  return { api, calls };
}

describe('what the browser can do', () => {
  it('shows notifications with a push manager, a worker and permission', () => {
    expect(support(browser().env)).toBe('supported');
    expect(support(browser({ push: false }).env)).toBe('unsupported');
    expect(support(null)).toBe('unsupported');
  });

  it('asks an iPhone or iPad in Safari to add the site to the home screen first', () => {
    expect(support(browser({ ua: IPHONE, push: false }).env)).toBe('ios-install');
    expect(
      support(browser({ ua: IPAD_AS_MAC, platform: 'MacIntel', touch: 5, push: false }).env),
    ).toBe('ios-install');
    expect(support(browser({ ua: IPHONE, standalone: true }).env)).toBe('supported');
    // A Mac without a touch screen is a Mac.
    expect(support(browser({ ua: IPAD_AS_MAC, platform: 'MacIntel', touch: 0 }).env)).toBe(
      'supported',
    );
  });

  it('reads the VAPID key', () => {
    const bytes = keyBytes(KEY);
    expect(bytes.length).toBe(65);
    expect(bytes[0]).toBe(4);
  });
});

describe('turning notifications on and off', () => {
  it('asks for permission only when asked to, then subscribes and stores the subscription', async () => {
    const { env, subscribe, requestPermission } = browser();
    const { api, calls } = fakeApi();
    const client = createNotifyClient(
      api,
      () => 'tok',
      () => 'u1',
      env,
    );
    expect(requestPermission).not.toHaveBeenCalled();
    expect(await client.isOn()).toBe(false);
    expect(await client.turnOn()).toBe('on');
    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(subscribe.mock.calls[0]?.[0].userVisibleOnly).toBe(true);
    expect(subscribe.mock.calls[0]?.[0].applicationServerKey).toEqual(keyBytes(KEY));
    const put = calls.find((call) => call.path === '/v1/me/push');
    expect(put).toEqual({
      method: 'PUT',
      path: '/v1/me/push',
      body: {
        subscription: {
          endpoint: 'https://fcm.googleapis.com/fcm/send/abc',
          keys: { p256dh: 'p', auth: 'a' },
        },
      },
      token: 'tok',
    });
    expect(await client.isOn()).toBe(true);
    expect(ownerOf(env)).toBe('u1');
  });

  it('says when the browser blocks them', async () => {
    const { env, subscribe } = browser({ answer: 'denied' });
    const client = createNotifyClient(
      fakeApi().api,
      () => 'tok',
      () => 'u1',
      env,
    );
    expect(await client.turnOn()).toBe('blocked');
    expect(subscribe).not.toHaveBeenCalled();
  });

  it('fails without a key from the API, and in a browser that cannot', async () => {
    const { env } = browser();
    const off = fakeApi((path) => (path === '/v1/push/key' ? new ApiError('push_off', 404) : null));
    expect(
      await createNotifyClient(
        off.api,
        () => 'tok',
        () => 'u1',
        env,
      ).turnOn(),
    ).toBe('failed');
    const iphone = browser({ ua: IPHONE, push: false });
    expect(
      await createNotifyClient(
        fakeApi().api,
        () => 'tok',
        () => 'u1',
        iphone.env,
      ).turnOn(),
    ).toBe('unsupported');
    expect(iphone.requestPermission).not.toHaveBeenCalled();
  });

  it('turning off forgets the browser in the API, then in the browser', async () => {
    const { held, unsubscribe } = subscription();
    const { env } = browser({ permission: 'granted', held });
    const { api, calls } = fakeApi();
    await createNotifyClient(
      api,
      () => 'tok',
      () => 'u1',
      env,
    ).turnOff();
    expect(calls).toEqual([
      {
        method: 'DELETE',
        path: '/v1/me/push',
        body: { endpoint: held.endpoint },
        token: 'tok',
      },
    ]);
    expect(unsubscribe).toHaveBeenCalled();
  });

  it('follows the signed-in account without asking anything', async () => {
    const { held } = subscription();
    const granted = browser({ permission: 'granted', held, owner: 'u1' });
    const { api, calls } = fakeApi();
    await createNotifyClient(
      api,
      () => 'tok2',
      () => 'u1',
      granted.env,
    ).follow();
    expect(calls.map((call) => [call.method, call.path, call.token])).toEqual([
      ['PUT', '/v1/me/push', 'tok2'],
    ]);
    expect(granted.requestPermission).not.toHaveBeenCalled();
    const asked = browser({ permission: 'default' });
    const none = fakeApi();
    await createNotifyClient(
      none.api,
      () => 'tok2',
      () => 'u1',
      asked.env,
    ).follow();
    expect(none.calls).toEqual([]);
  });

  it('drops the browser’s subscription after the account is deleted', async () => {
    const { held, unsubscribe } = subscription();
    const deleted = browser({ permission: 'granted', held, owner: 'u1' });
    await dropLocal(deleted.env);
    expect(unsubscribe).toHaveBeenCalled();
    expect(ownerOf(deleted.env)).toBeNull();
  });

  it('never hands one account’s notifications to another who signs in', async () => {
    const { held, unsubscribe } = subscription();
    const shared = browser({ permission: 'granted', held, owner: 'u1' });
    const { api, calls } = fakeApi();
    const next = createNotifyClient(
      api,
      () => 'tok9',
      () => 'u9',
      shared.env,
    );
    expect(await next.isOn()).toBe(false);
    await next.follow();
    expect(calls).toEqual([]);
    expect(unsubscribe).toHaveBeenCalled();
    expect(ownerOf(shared.env)).toBeNull();
    // With nothing remembered (storage cleared or blocked), it is not handed over either.
    const other = subscription();
    const unknown = browser({ permission: 'granted', held: other.held });
    await createNotifyClient(
      api,
      () => 'tok9',
      () => 'u9',
      unknown.env,
    ).follow();
    expect(calls).toEqual([]);
    expect(other.unsubscribe).toHaveBeenCalled();
  });

  it('turning on after another account gets this account its own subscription', async () => {
    const { held, unsubscribe } = subscription('https://fcm.googleapis.com/fcm/send/old');
    const shared = browser({ permission: 'granted', held, owner: 'u1' });
    const { api, calls } = fakeApi();
    expect(
      await createNotifyClient(
        api,
        () => 'tok9',
        () => 'u9',
        shared.env,
      ).turnOn(),
    ).toBe('on');
    expect(unsubscribe).toHaveBeenCalled();
    expect(shared.subscribe).toHaveBeenCalledTimes(1);
    const put = calls.find((call) => call.method === 'PUT');
    expect((put?.body as { subscription: { endpoint: string } }).subscription.endpoint).toBe(
      'https://fcm.googleapis.com/fcm/send/abc',
    );
    expect(ownerOf(shared.env)).toBe('u9');
  });

  it('turns off every device of the account, this one too', async () => {
    const { held, unsubscribe } = subscription();
    const mine = browser({ permission: 'granted', held, owner: 'u1' });
    const api: Api = {
      root: 'https://api.test',
      call<T>(method: string, path: string, body?: unknown): Promise<T> {
        expect([method, path, body]).toEqual(['DELETE', '/v1/me/push', { all: true }]);
        return Promise.resolve({ devices: 0 } as T);
      },
    };
    expect(
      await createNotifyClient(
        api,
        () => 'tok',
        () => 'u1',
        mine.env,
      ).turnOffAll(),
    ).toBe(0);
    expect(unsubscribe).toHaveBeenCalled();
    expect(ownerOf(mine.env)).toBeNull();
  });
});
