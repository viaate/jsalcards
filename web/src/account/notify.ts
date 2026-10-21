/**
 * Notifications on this device (docs/notify.md): whether the browser can show
 * them, turning them on (only ever from a button the person pressed: the
 * browser asks for permission then, never on page load) and off, and the
 * account's settings. The API keeps each browser's push subscription and the
 * settings; the sender in GitHub Actions does the sending.
 *
 * iPhone and iPad show web notifications only from a site added to the Home
 * Screen (iOS 16.4 and later): in Safari itself the page shows how to add it
 * instead of a button that cannot work.
 *
 * A browser's notifications belong to the account that turned them on there,
 * which this browser remembers (OWNER_KEY). Signing in again as that account
 * brings them back with the new sign-in; signing in as another account turns
 * them off on this browser, so nobody starts getting another person's
 * notifications without pressing Turn on.
 */

import { ApiError, type Api } from './api';

export const THRESHOLDS = [30, 50, 70] as const;
export type Threshold = (typeof THRESHOLDS)[number];

export interface NotifySettings {
  readonly status: boolean;
  readonly chance: boolean;
  readonly threshold: Threshold;
  readonly night_before: boolean;
  /** "HH:MM", on the hour or half hour. */
  readonly night_time: string;
  /** "HH:MM", on the hour; equal to quiet_to: no quiet hours. */
  readonly quiet_from: string;
  readonly quiet_to: string;
}

export interface NotifyState {
  readonly settings: NotifySettings;
  /** How many browsers get this account's notifications. */
  readonly devices: number;
}

/** What this browser can do: show notifications, needs adding to the Home Screen first, or neither. */
export type Support = 'supported' | 'ios-install' | 'unsupported';

/** The parts of `window` this module reads, so tests can hand it a fake. */
export interface NotifyHost {
  readonly navigator: {
    readonly userAgent: string;
    readonly maxTouchPoints?: number;
    readonly platform?: string;
    readonly standalone?: boolean;
    readonly serviceWorker?: { readonly ready: Promise<{ readonly pushManager: PushManagerLike }> };
  };
  readonly Notification?: {
    readonly permission: NotificationPermission;
    requestPermission(): Promise<NotificationPermission>;
  };
  readonly PushManager?: unknown;
  matchMedia?(query: string): { readonly matches: boolean };
  readonly localStorage?: {
    getItem(key: string): string | null;
    setItem(key: string, value: string): void;
    removeItem(key: string): void;
  };
}

/** Where this browser keeps the id of the account that turned its notifications on. */
export const OWNER_KEY = 'snowlight.notify.owner';

/** The account that turned this browser's notifications on, or null (none, or no storage). */
export function ownerOf(env: NotifyHost | null): string | null {
  try {
    return env?.localStorage?.getItem(OWNER_KEY) ?? null;
  } catch {
    return null;
  }
}

function keepOwner(env: NotifyHost | null, id: string | null): void {
  try {
    if (id === null) env?.localStorage?.removeItem(OWNER_KEY);
    else env?.localStorage?.setItem(OWNER_KEY, id);
  } catch {
    // Private windows and blocked storage: another sign-in here turns them off.
  }
}

export interface PushManagerLike {
  getSubscription(): Promise<SubscriptionLike | null>;
  subscribe(options: {
    userVisibleOnly: boolean;
    applicationServerKey: Uint8Array;
  }): Promise<SubscriptionLike>;
}

export interface SubscriptionLike {
  readonly endpoint: string;
  toJSON(): { endpoint?: string; keys?: Record<string, string> };
  unsubscribe(): Promise<boolean>;
}

function host(): NotifyHost | null {
  return typeof window === 'undefined' ? null : (window as unknown as NotifyHost);
}

/** An iPhone, iPad or iPod (an iPad says it is a Mac, with a touch screen). */
export function isIos(nav: NotifyHost['navigator']): boolean {
  if (/\b(?:iPhone|iPad|iPod)\b/.test(nav.userAgent)) return true;
  return nav.platform === 'MacIntel' && (nav.maxTouchPoints ?? 0) > 1;
}

/** Opened from the Home Screen (an installed web app). */
export function isStandalone(env: NotifyHost): boolean {
  if (env.navigator.standalone === true) return true;
  try {
    return env.matchMedia?.('(display-mode: standalone)').matches ?? false;
  } catch {
    return false;
  }
}

/** What this browser can do with notifications. */
export function support(env: NotifyHost | null = host()): Support {
  if (env === null) return 'unsupported';
  const capable =
    env.PushManager !== undefined &&
    env.Notification !== undefined &&
    env.navigator.serviceWorker !== undefined;
  if (isIos(env.navigator) && !isStandalone(env)) return 'ios-install';
  return capable ? 'supported' : 'unsupported';
}

/** base64url to bytes, for the VAPID key. */
export function keyBytes(base64url: string): Uint8Array {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** How turning notifications on ended. */
export type TurnOn = 'on' | 'blocked' | 'unsupported' | 'failed';

export interface NotifyClient {
  /** The browser's permission now: granted, denied or default; null without the API. */
  permission(): NotificationPermission | null;
  /**
   * Whether this browser gets the signed-in account's notifications: it holds a
   * subscription, which this account turned on.
   */
  isOn(): Promise<boolean>;
  /** Asks for permission (call it only from a button press), subscribes and stores it. */
  turnOn(): Promise<TurnOn>;
  /** This browser stops getting notifications: the API forgets it, then the browser. */
  turnOff(): Promise<void>;
  /** Every browser of the account stops getting its notifications, this one too. */
  turnOffAll(): Promise<NotifyState['devices']>;
  /**
   * After a sign-in: a browser this account turned on gets its notifications again
   * with the new sign-in; one another account turned on stops getting them.
   */
  follow(): Promise<void>;
  read(): Promise<NotifyState>;
  save(change: Partial<NotifySettings>): Promise<NotifyState>;
}

async function pushManager(env: NotifyHost): Promise<PushManagerLike | null> {
  const worker = env.navigator.serviceWorker;
  if (worker === undefined) return null;
  // The worker registers after load (src/pwa/register.ts); without one, nothing to wait for.
  const ready = await Promise.race([
    worker.ready,
    new Promise<null>((resolve) => {
      setTimeout(() => {
        resolve(null);
      }, 10_000);
    }),
  ]);
  return ready === null ? null : ready.pushManager;
}

function subscriptionBody(subscription: SubscriptionLike): unknown {
  const json = subscription.toJSON();
  return {
    subscription: {
      endpoint: json.endpoint ?? subscription.endpoint,
      keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
    },
  };
}

/** The client for the signed-in account (`token`, its id `user`) on this browser. */
export function createNotifyClient(
  api: Api,
  token: () => string | null,
  user: () => string | null,
  env: NotifyHost | null = host(),
): NotifyClient {
  const call = <T>(method: string, path: string, body?: unknown): Promise<T> =>
    api.call<T>(method, path, body, token());

  const current = async (): Promise<SubscriptionLike | null> => {
    if (env === null || support(env) !== 'supported') return null;
    const manager = await pushManager(env);
    return manager === null ? null : manager.getSubscription();
  };

  /** Whether this browser's notifications are the signed-in account's own. */
  const mine = (): boolean => {
    const id = user();
    return id !== null && ownerOf(env) === id;
  };

  return {
    permission: () => env?.Notification?.permission ?? null,
    async isOn() {
      if (env?.Notification?.permission !== 'granted' || !mine()) return false;
      return (await current().catch(() => null)) !== null;
    },
    async turnOn() {
      if (env === null || support(env) !== 'supported' || env.Notification === undefined)
        return 'unsupported';
      let permission: NotificationPermission;
      try {
        permission = await env.Notification.requestPermission();
      } catch {
        return 'failed';
      }
      if (permission === 'denied') return 'blocked';
      if (permission !== 'granted') return 'failed';
      const id = user();
      if (id === null) return 'failed';
      try {
        const manager = await pushManager(env);
        if (manager === null) return 'failed';
        const { key } = await api.call<{ key: string }>('GET', '/v1/push/key');
        let held = await manager.getSubscription();
        // Another account's subscription is never handed over: this account gets its own.
        if (held !== null && ownerOf(env) !== id) {
          await held.unsubscribe().catch(() => false);
          held = null;
        }
        const subscription =
          held ??
          (await manager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
        await call('PUT', '/v1/me/push', subscriptionBody(subscription));
        keepOwner(env, id);
        return 'on';
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) throw error;
        return 'failed';
      }
    },
    async turnOff() {
      if (env?.Notification?.permission !== 'granted') return;
      const subscription = await current().catch(() => null);
      if (subscription === null) return;
      try {
        await call('DELETE', '/v1/me/push', { endpoint: subscription.endpoint });
      } finally {
        keepOwner(env, null);
        await subscription.unsubscribe().catch(() => false);
      }
    },
    async turnOffAll() {
      const { devices } = await call<{ devices: number }>('DELETE', '/v1/me/push', { all: true });
      if (env?.Notification?.permission === 'granted') {
        const subscription = await current().catch(() => null);
        keepOwner(env, null);
        await subscription?.unsubscribe().catch(() => false);
      }
      return devices;
    },
    async follow() {
      if (env?.Notification?.permission !== 'granted') return;
      const subscription = await current().catch(() => null);
      if (subscription === null) return;
      if (mine()) {
        await call('PUT', '/v1/me/push', subscriptionBody(subscription));
        return;
      }
      keepOwner(env, null);
      await subscription.unsubscribe().catch(() => false);
    },
    read: () => call<NotifyState>('GET', '/v1/me/notify'),
    save: (change) => call<NotifyState>('PATCH', '/v1/me/notify', change),
  };
}

/** Whether this browser has let the site show notifications (no question asked). */
export function granted(env: NotifyHost | null = host()): boolean {
  return env?.Notification?.permission === 'granted';
}

/** Drops this browser's subscription without the API (after the account was deleted there). */
export async function dropLocal(env: NotifyHost | null = host()): Promise<void> {
  keepOwner(env, null);
  if (env === null || !granted(env) || support(env) !== 'supported') return;
  const manager = await pushManager(env);
  const subscription = manager === null ? null : await manager.getSubscription();
  await subscription?.unsubscribe();
}
