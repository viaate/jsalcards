/**
 * The address store (url-store.ts), with the address parsing it reads and
 * writes with, loads after the page's first script, once the page has first
 * painted, as the map's code and the app's services do. The map and the app's
 * services start once the first try for it has settled (`tried`): with it, as
 * if it had come with the page; without it, as on a plain visit, this
 * stand-in keeping what the app opens in memory and the address as it is,
 * while the code is asked for again. Once it comes, the address opens as a
 * link would (origin "address"), or takes what the app shows when the app has
 * opened something or moved since.
 */

import STORE_URL from 'virtual:snowlight/url-store-url';

import type { Selection, UrlState } from './url';
import type { createUrlStore, StateOrigin, UrlStateListener, UrlStore } from './url-store';

/** The wait before the store's code is asked for again; each later one doubles, up to RETRY_MAX_MS. */
const RETRY_MS = 1_000;
const RETRY_MAX_MS = 30_000;

export interface LateUrlStore extends UrlStore {
  /** Settles once the first try for the store's code has: the address is read by then, unless it failed. */
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
  let started = false;
  let destroyed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let settle: (opens: boolean) => void = () => undefined;
  const opens = new Promise<boolean>((resolve) => {
    settle = resolve;
  });

  const notify = (state: UrlState, origin: StateOrigin): void => {
    for (const listener of [...listeners]) listener(state, origin);
  };

  const connect = (next: UrlStore): void => {
    store = next;
    if (changed) {
      try {
        next.select(memory.selection, { replace: true });
      } catch {
        // An id a link cannot carry: the address keeps the place alone.
        next.select(null, { replace: true });
      }
      next.setView(memory.view);
      next.flush();
    } else {
      notify(next.state, started ? 'address' : 'initial');
    }
    next.subscribe((state, origin) => {
      if (origin !== 'initial') notify(state, origin);
    });
    settle(!changed);
  };

  const attempt = (count: number, wait: number): Promise<void> =>
    load(count).then(
      ({ createUrlStore }) => {
        if (!destroyed) connect(createUrlStore());
      },
      () => {
        if (destroyed) return;
        timer = setTimeout(() => {
          void attempt(count + 1, Math.min(wait * 2, RETRY_MAX_MS));
        }, wait);
      },
    );

  const tried = after
    .then(() => attempt(0, RETRY_MS))
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
        keep({ ...memory, selection }, true);
      }
    },
    navigate(next) {
      if (store !== null) store.navigate(next);
      else keep(next, true);
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
      clearTimeout(timer);
      listeners.clear();
      store?.destroy();
    },
  };
}
