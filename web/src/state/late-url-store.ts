/**
 * The address store (url-store.ts), with the address parsing it reads and
 * writes with, loads after the page's first script, once the page has first
 * painted, as the map's code and the app's services do. The map and the app's
 * services start once the first try for it has settled (`tried`): its code
 * came, failed, or has not come within its deadline (app/tries.ts). With it,
 * they start as if it had come with the page; without it, as on a plain visit,
 * this stand-in keeping what the app opens in memory and the address as it
 * is, while the code is asked for again. Once it comes, the address opens as
 * a link would (origin "address"), or takes what the app shows when the app
 * has opened something or moved since: one step on from the link after a
 * pick, as a pick would have been.
 */

import STORE_URL from 'virtual:snowlight/url-store-url';

import { tries } from '../app/tries';
import type { Selection, UrlState } from './url';
import type { createUrlStore, StateOrigin, UrlStateListener, UrlStore } from './url-store';

export interface LateUrlStore extends UrlStore {
  /**
   * Settles once the first try for the store's code has worked, failed or gone
   * past its deadline: the address is read by then, unless that try did not work.
   */
  readonly tried: Promise<void>;
  /** Whether the address is read: the store's code is in. */
  readonly read: boolean;
  /**
   * Settles once the address is read: true when it opens as a link would,
   * false when it took what the app had opened or moved to while it was unread.
   */
  readonly opens: Promise<boolean>;
}

/** The store's code. */
export interface UrlStoreModule {
  readonly createUrlStore: typeof createUrlStore;
}

/**
 * The store's code, at the first try, and under an address of its own at
 * each later one: a browser keeps a module that failed to download as failed.
 */
function loadStore(attempt: number): Promise<UrlStoreModule> {
  if (attempt === 0) return import('./url-store');
  return import(
    /* @vite-ignore */ `${STORE_URL}?retry=${String(attempt)}`
  ) as Promise<UrlStoreModule>;
}

function sameSelection(a: Selection | null, b: Selection | null): boolean {
  return a === b || (a !== null && b !== null && a.kind === b.kind && a.id === b.id);
}

export interface LateUrlStoreOptions {
  /** The first try waits for this: the page's first paint. */
  readonly after?: Promise<unknown>;
  /** The store's code, at a try counted from 0; by default the build's chunk of it. */
  readonly load?: (attempt: number) => Promise<UrlStoreModule>;
}

export function lateUrlStore(options: LateUrlStoreOptions = {}): LateUrlStore {
  const { after = Promise.resolve(), load = loadStore } = options;
  const listeners = new Set<UrlStateListener>();
  let store: UrlStore | null = null;
  /** What the app has opened, and the map's view, while the address is unread. */
  let memory: UrlState = { selection: null, view: null };
  /** Whether the app opened or closed anything, or moved the map, while the address was unread. */
  let changed = false;
  /** Whether that was a step of its own, a pick or a tap, which writes a history entry. */
  let stepped = false;
  let started = false;
  let destroyed = false;
  let stopTries: () => void = () => undefined;
  let settle: (opens: boolean) => void = () => undefined;
  const opens = new Promise<boolean>((resolve) => {
    settle = resolve;
  });

  const notify = (state: UrlState, origin: StateOrigin): void => {
    for (const listener of [...listeners]) listener(state, origin);
  };

  const connect = (next: UrlStore): void => {
    store = next;
    if (!changed) {
      notify(next.state, started ? 'address' : 'initial');
    } else {
      // After a pick, one step on from the link, so Back returns to it, as on a link that was read.
      const write = (state: UrlState): void => {
        if (stepped) {
          next.navigate(state);
        } else {
          next.select(state.selection, { replace: true });
          next.setView(state.view);
        }
      };
      try {
        write(memory);
      } catch {
        // An id a link cannot carry: the address keeps the place alone.
        write({ selection: null, view: memory.view });
      }
      next.flush();
    }
    next.subscribe((state, origin) => {
      if (origin !== 'initial') notify(state, origin);
    });
    settle(!changed);
  };

  const tried = after
    .then(() => {
      if (destroyed) return;
      const attempts = tries(load);
      stopTries = attempts.stop;
      void attempts.won.then(({ createUrlStore }) => {
        if (!destroyed) connect(createUrlStore());
      });
      return attempts.first;
    })
    .then(() => {
      started = true;
    });

  /** A change the app makes while the address is unread. */
  const keep = (next: UrlState, moved: boolean): void => {
    memory = next;
    changed ||= moved;
    notify(memory, 'app');
  };

  return {
    tried,
    opens,
    get read() {
      return store !== null;
    },
    get state() {
      return store?.state ?? memory;
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(store?.state ?? memory, 'initial');
      return () => {
        listeners.delete(listener);
      };
    },
    select(selection, options) {
      if (store !== null) {
        store.select(selection, options);
      } else if (!sameSelection(memory.selection, selection)) {
        stepped ||= selection !== null && options?.replace !== true;
        keep({ ...memory, selection }, true);
      }
    },
    navigate(next) {
      if (store !== null) {
        store.navigate(next);
      } else {
        stepped = true;
        keep(next, true);
      }
    },
    setView(view) {
      if (store !== null) store.setView(view);
      else if (view !== null || memory.view !== null) keep({ ...memory, view }, view !== null);
    },
    flush() {
      store?.flush();
    },
    shareUrl(options) {
      // Only the store's code can write a link: the app shares nothing until it is in.
      if (store === null) throw new Error('Snowlight: the address is not read yet');
      return store.shareUrl(options);
    },
    destroy() {
      destroyed = true;
      stopTries();
      listeners.clear();
      store?.destroy();
    },
  };
}
