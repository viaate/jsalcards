/**
 * Which live root the page reads the live files from, when the build names
 * two (VITE_SNOWLIGHT_LIVE_ROOT, then VITE_SNOWLIGHT_LIVE_FALLBACK).
 *
 * A school's web filter can block the live host by name (it closes every
 * connection to it) while it lets the site's own domain through. The second
 * root serves the same files on that domain (status/shared/live-proxy.ts), so
 * a page on such a network still reads today's files instead of the copy its
 * worker kept, or nothing.
 *
 * The first root is read first: the second is asked only when the first does
 * not answer with the file, that is when its read fails (the connection closed
 * or refused, no network), when it answers with an error or a web page, when
 * the worker gives its kept copy in place of an answer (pwa/config.ts
 * markKept), or when no answer has come within LIVE_TIMEOUT_SECONDS. A visitor
 * on an open network so never asks the second at all. The root that answered
 * is kept for the visit (sessionStorage, LIVE_ROOT_KEY): once the second has,
 * it is read first, and the first is tried first again every
 * LIVE_ROOT_RETRY_MS. When neither answers, the page is given what the first
 * gave it (the worker's kept copy, an error), as with one root: the case is
 * never made worse than it was.
 *
 * A build without a second root (either variable unset or empty) reads as it
 * did before: liveFetch is fetchFile itself.
 */

import { KEPT_HEADER, LIVE_TIMEOUT_SECONDS, liveRootOf } from '../pwa/config';
import { fetchFile } from './files';
import type { Fetch } from './files';

/** How long the page reads the second root first, once it answered, before it tries the first: 10 minutes. */
export const LIVE_ROOT_RETRY_MS = 10 * 60_000;

/** Where the visit keeps when the second root last took over: the time, in ms since the epoch. */
export const LIVE_ROOT_KEY = 'snowlight-live-root';

/** How long a root may take before the other is asked as well (the worker's own wait). */
export const LIVE_ROOT_WAIT_MS = LIVE_TIMEOUT_SECONDS * 1000;

/** The visit's storage, as far as these reads use it. */
export type RootStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export interface LiveRootsInit {
  /** The first root, as liveRootOf gives it: the live host. */
  readonly primary: string;
  /** The second root, as liveRootOf gives it: the same files on the site's own domain. */
  readonly fallback: string;
  /** How a file is read: fetchFile in the page. */
  readonly fetch: Fetch;
  /** The visit's storage; null where it cannot be had (the choice then lasts for the page). */
  readonly store?: RootStore | null;
  readonly now?: () => number;
  readonly waitMs?: number;
}

/** Whether `response` is the file the root was asked for, fresh from it. */
export function answered(response: Response): boolean {
  if (!response.ok || response.headers.get(KEPT_HEADER) !== null) return false;
  // A filter's block page sent in its place.
  return !/^\s*text\/html/i.test(response.headers.get('content-type') ?? '');
}

type Outcome = { readonly response: Response } | { readonly error: unknown };

function discard(outcome: Outcome | undefined): void {
  if (outcome !== undefined && 'response' in outcome) {
    outcome.response.body?.cancel().catch(() => undefined);
  }
}

/**
 * A Fetch that reads a URL under `primary` from whichever of the two roots
 * answers, as the module comment says, and any other URL as `fetch` does.
 */
export function rootedFetch(init: LiveRootsInit): Fetch {
  const { primary, fallback, fetch } = init;
  const now = init.now ?? Date.now;
  const waitMs = init.waitMs ?? LIVE_ROOT_WAIT_MS;
  const store = init.store ?? null;
  /** When the second root last took over, or null while the first is read first. */
  let since: number | null = null;
  const load = (): number | null => {
    if (store !== null) {
      try {
        const value = store.getItem(LIVE_ROOT_KEY);
        if (value === null) return null;
        const at = Number(value);
        return Number.isFinite(at) ? at : null;
      } catch {
        // Storage that cannot be read: the page's own memory stands.
      }
    }
    return since;
  };
  const save = (at: number | null): void => {
    since = at;
    try {
      if (at === null) store?.removeItem(LIVE_ROOT_KEY);
      else store?.setItem(LIVE_ROOT_KEY, String(at));
    } catch {
      // Kept for this page alone.
    }
  };
  return async (input, options = {}) => {
    if (!input.startsWith(primary)) return fetch(input, options);
    const rest = input.slice(primary.length);
    const taken = load();
    const age = taken === null ? null : now() - taken;
    // The second first while it took over less than LIVE_ROOT_RETRY_MS ago (a clock set back
    // past it counts as that long).
    const secondFirst = age !== null && age >= 0 && age < LIVE_ROOT_RETRY_MS;
    const order = secondFirst ? [fallback, primary] : [primary, fallback];
    const signal = options.signal ?? null;
    const controllers: AbortController[] = [];
    const read = (root: string): Promise<Outcome> => {
      const controller = new AbortController();
      controllers.push(controller);
      const stop = (): void => {
        controller.abort(signal?.reason);
      };
      if (signal?.aborted === true) stop();
      else signal?.addEventListener('abort', stop, { once: true });
      return fetch(`${root}${rest}`, { ...options, signal: controller.signal }).then(
        (response) => {
          signal?.removeEventListener('abort', stop);
          return { response };
        },
        (error: unknown) => {
          signal?.removeEventListener('abort', stop);
          return { error };
        },
      );
    };
    const reads = [read(order[0] ?? primary)];
    let timer: ReturnType<typeof setTimeout> | undefined;
    const first = await Promise.race([
      reads[0],
      new Promise<null>((resolve) => {
        timer = setTimeout(() => {
          resolve(null);
        }, waitMs);
      }),
    ]);
    clearTimeout(timer);
    const good = (outcome: Outcome | null | undefined): outcome is { response: Response } =>
      outcome !== null &&
      outcome !== undefined &&
      'response' in outcome &&
      answered(outcome.response);
    const took = (index: number): void => {
      if (order[index] === primary) save(null);
      else if (!secondFirst) save(now());
    };
    if (good(first)) {
      took(0);
      return first.response;
    }
    if (signal?.aborted !== true) {
      // The other root, while the first may still answer: whichever answers first is read.
      reads.push(read(order[1] ?? fallback));
      const winner = await new Promise<number | null>((resolve) => {
        let left = reads.length;
        reads.forEach((reading, index) => {
          void reading.then((outcome) => {
            if (good(outcome)) resolve(index);
            else if (--left === 0) resolve(null);
          });
        });
      });
      if (winner !== null) {
        const other = 1 - winner;
        controllers[other]?.abort();
        void reads[other]?.then(discard);
        took(winner);
        const outcome = await reads[winner];
        if (outcome !== undefined && 'response' in outcome) return outcome.response;
      }
    }
    // Neither answered: what the live host gave (the worker's kept copy, an error), as with one
    // root, whichever was asked first; else the second root's kept copy.
    const settled = await Promise.all(reads);
    const own = settled[order.indexOf(primary)] ?? settled[0];
    const other = settled.find((outcome) => outcome !== own);
    if (own !== undefined && 'response' in own) {
      discard(other);
      return own.response;
    }
    if (other !== undefined && 'response' in other && other.response.ok) return other.response;
    discard(other);
    // The live host's own failure (an abort among them), as the read failed with one root.
    throw (own?.error ?? new Error('No live root answered.')) as Error;
  };
}

function visitStore(): RootStore | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage;
  } catch {
    return null;
  }
}

/**
 * How the page reads the live files: through both roots in a build that names
 * two (rootedFetch), as fetchFile does in any other.
 */
export const liveFetch: Fetch =
  import.meta.env.VITE_SNOWLIGHT_LIVE_FALLBACK === undefined ||
  import.meta.env.VITE_SNOWLIGHT_LIVE_FALLBACK === '' ||
  import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT === undefined ||
  import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT === ''
    ? fetchFile
    : builtFetch(
        import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT,
        import.meta.env.VITE_SNOWLIGHT_LIVE_FALLBACK,
      );

function builtFetch(root: string, second: string): Fetch {
  const loopback = import.meta.env.VITE_SNOWLIGHT_LIVE_LOOPBACK === '1';
  const primary = liveRootOf(root, loopback);
  const fallback = liveRootOf(second, loopback);
  if (primary === null || fallback === null || primary === fallback) return fetchFile;
  return rootedFetch({ primary, fallback, fetch: fetchFile, store: visitStore() });
}
