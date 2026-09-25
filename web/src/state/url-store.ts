/**
 * Keeps the address bar and the app in step.
 *
 * - Map moves go through `setView` and are written with history.replaceState
 *   once the map has been still for a moment, so panning never adds history.
 * - Opening a school, district or ZIP pushes one history entry, so Back
 *   returns to what was open before (or to nothing). Closing it replaces the
 *   current entry, so Forward never reopens something that was closed.
 * - Back and Forward re-read the address and tell subscribers, with the
 *   origin "history", so the map can move to the view that entry holds.
 *
 * A link can hold a selection and a view together: that is the school as the
 * sender saw it, so the app opens the school and keeps that view rather than
 * moving to the school. Parameters other modules add to the query are left as
 * they are.
 */

import {
  EMPTY_STATE,
  mergeHref,
  parseUrlState,
  roundView,
  sameSelection,
  sameState,
  sameView,
  shareHref,
  stateQuery,
} from './url';
import type { Selection, UrlState, View } from './url';

/** Where a state change came from. */
export type StateOrigin =
  /** The address the page opened with, sent to each new subscriber. */
  | 'initial'
  /** Back or Forward. */
  | 'history'
  /** A call to select or setView. */
  | 'app';

export type UrlStateListener = (state: UrlState, origin: StateOrigin) => void;

/** The parts of `window` the store uses, so tests can hand it a fake. */
export interface UrlStoreHost extends EventTarget {
  readonly location: { readonly href: string };
  readonly history: Pick<History, 'state' | 'pushState' | 'replaceState'>;
  readonly document?: Pick<
    Document,
    'visibilityState' | 'addEventListener' | 'removeEventListener'
  >;
  setTimeout(handler: () => void, timeout: number): number;
  clearTimeout(id: number | undefined): void;
}

export interface UrlStoreOptions {
  /** Defaults to `window`. */
  host?: UrlStoreHost;
  /** How long the view must be still before it is written. Default 300 ms. */
  debounceMs?: number;
}

export interface ShareOptions {
  /** Whether the link keeps the map view. Defaults to true only when nothing is selected. */
  view?: boolean;
}

export interface UrlStore {
  /** The state the address bar holds, or is about to hold. */
  readonly state: UrlState;
  /**
   * Calls `listener` now with the current state (origin "initial") and after
   * every change. Returns the function that stops it. Also a Svelte store.
   */
  subscribe(listener: UrlStateListener): () => void;
  /** Opens a school, district or ZIP, or closes it with null. */
  select(selection: Selection | null): void;
  /** Records the map view. Written after `debounceMs` without another call. */
  setView(view: View | null): void;
  /** Writes a pending view now. */
  flush(): void;
  /** An absolute link to the current selection (and view, see ShareOptions). */
  shareUrl(options?: ShareOptions): string;
  /** Writes what is pending and stops listening to the page. */
  destroy(): void;
}

const DEFAULT_DEBOUNCE_MS = 300;
/** After the browser refuses a write: wait this long, this many times, then leave it to the next change. */
const RETRY_MS = 2_000;
const RETRIES = 3;

/** Throws on a malformed id: the app passes only ids it has looked up, so this is a bug. */
function checkSelection(selection: Selection | null): void {
  if (selection !== null) stateQuery({ selection, view: null });
}

export function createUrlStore(options: UrlStoreOptions = {}): UrlStore {
  const host: UrlStoreHost = options.host ?? window;
  const debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS;
  const listeners = new Set<UrlStateListener>();

  let state: UrlState = EMPTY_STATE;
  let timer: number | undefined;
  let destroyed = false;
  let warned = false;

  const notify = (origin: StateOrigin): void => {
    for (const listener of [...listeners]) listener(state, origin);
  };

  /** Writes `state` to the current entry, or to a new one. False if the browser refused. */
  const write = (mode: 'push' | 'replace'): boolean => {
    const target = mergeHref(host.location.href, state);
    if (mode === 'replace' && target === host.location.href) return true;
    try {
      if (mode === 'push') host.history.pushState(null, '', target);
      else host.history.replaceState(host.history.state, '', target);
      return true;
    } catch (error) {
      // Safari throws once a page rewrites its URL too often; the next write catches up.
      if (!warned) console.warn('Snowlight: could not update the address', error);
      warned = true;
      return false;
    }
  };

  const cancel = (): void => {
    if (timer !== undefined) host.clearTimeout(timer);
    timer = undefined;
  };

  const flush = (): void => {
    if (timer === undefined) return;
    cancel();
    write('replace');
  };

  const schedule = (delay = debounceMs, retries = RETRIES): void => {
    cancel();
    timer = host.setTimeout(() => {
      timer = undefined;
      if (!write('replace') && retries > 0) schedule(RETRY_MS, retries - 1);
    }, delay);
  };

  /** Reads the address and drops what does not parse from it. */
  const load = (): void => {
    state = parseUrlState(new URL(host.location.href).search);
    write('replace');
  };

  const onPopState = (): void => {
    // A pending view belongs to the entry just left; writing it here would overwrite this one.
    cancel();
    const before = state;
    load();
    // Hash-only navigations fire popstate too; they change nothing here.
    if (!sameState(before, state)) notify('history');
  };
  const onHidden = (): void => {
    if (host.document?.visibilityState !== 'visible') flush();
  };

  load();
  host.addEventListener('popstate', onPopState);
  host.addEventListener('pagehide', flush);
  host.document?.addEventListener('visibilitychange', onHidden);

  return {
    get state() {
      return state;
    },

    subscribe(listener) {
      listeners.add(listener);
      listener(state, 'initial');
      return () => {
        listeners.delete(listener);
      };
    },

    select(selection) {
      checkSelection(selection);
      if (destroyed || sameSelection(state.selection, selection)) return;
      // Leave the current entry with its latest view before moving on.
      flush();
      state = { ...state, selection };
      write(selection === null ? 'replace' : 'push');
      notify('app');
    },

    setView(view) {
      if (destroyed) return;
      const rounded = view === null ? null : roundView(view);
      if (sameView(state.view, rounded)) return;
      state = { ...state, view: rounded };
      schedule();
      notify('app');
    },

    flush,

    shareUrl(shareOptions = {}) {
      const withView = shareOptions.view ?? state.selection === null;
      return shareHref(host.location.href, {
        selection: state.selection,
        view: withView ? state.view : null,
      });
    },

    destroy() {
      if (destroyed) return;
      flush();
      destroyed = true;
      listeners.clear();
      host.removeEventListener('popstate', onPopState);
      host.removeEventListener('pagehide', flush);
      host.document?.removeEventListener('visibilitychange', onHidden);
    },
  };
}
