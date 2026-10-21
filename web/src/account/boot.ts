/**
 * The account controls' start, loaded after the first paint and only in a
 * build with an API root (account/config.ts): the store, its health check and
 * stored session, and the pin kept in step with the saved schools. Returns
 * null when the API does not answer, and the page then shows no account
 * controls at all.
 */

import type { Services } from '../app/boot';
import type { SchoolId } from '../types/generated';
import type AccountControl from '../ui/account/AccountControl.svelte';
import { createApi } from './api';
import { syncPins } from './pins';
import { createAccountStore, type AccountStore } from './session';

export interface Accounts {
  readonly store: AccountStore;
  readonly Control: typeof AccountControl;
}

/** A school's name as its panel shows it, read once; null after 10 s or when there is none. */
export function nameVia(app: Services, id: SchoolId): Promise<string | null> {
  return new Promise((resolve) => {
    let stop: () => void = () => undefined;
    let done = false;
    const finish = (name: string | null): void => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      queueMicrotask(() => {
        stop();
      });
      resolve(name);
    };
    const timer = setTimeout(() => {
      finish(null);
    }, 10_000);
    stop = app.watchSchool(id, null, (view) => {
      if (view === null) finish(null);
      else if (!view.loading && view.name !== '') finish(view.name);
    });
  });
}

export async function startAccounts(
  root: string,
  services: Promise<Services | null>,
  signal: AbortSignal,
): Promise<Accounts | null> {
  const api = createApi(root);
  // Notifications (account/notify.ts), loaded only when this browser has allowed them.
  const notify = () => import('./notify');
  const allowed = (): boolean =>
    typeof Notification !== 'undefined' && Notification.permission === 'granted';
  const store = createAccountStore(api, {
    // Logging out stops this browser's notifications for the account.
    onLogout: async (held) => {
      if (allowed())
        await (
          await notify()
        )
          .createNotifyClient(
            api,
            () => held,
            () => null,
          )
          .turnOff();
    },
    onDeleted: async () => {
      if (allowed()) await (await notify()).dropLocal();
    },
  });
  const [, control] = await Promise.all([
    store.start(),
    import('../ui/account/AccountControl.svelte'),
  ]);
  if (signal.aborted || !store.state.available) return null;
  // After a sign-in, a browser's notifications come back only for the account that turned
  // them on here; another account's sign-in turns them off (account/notify.ts follow).
  let following: string | null = null;
  const stopFollowing = store.subscribe((state) => {
    const id = state.user?.id ?? null;
    if (id === following) return;
    following = id;
    if (id === null || !allowed()) return;
    void notify()
      .then((m) =>
        m
          .createNotifyClient(
            api,
            () => store.token(),
            () => store.state.user?.id ?? null,
          )
          .follow(),
      )
      .catch(() => undefined);
  });
  signal.addEventListener('abort', stopFollowing, { once: true });
  void services.then((app) => {
    if (app === null || signal.aborted) return;
    const stop = syncPins({ account: store, pins: app.pins, nameOf: (id) => nameVia(app, id) });
    signal.addEventListener('abort', stop, { once: true });
  });
  return { store, Control: control.default };
}
