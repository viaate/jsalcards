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
 * The first root is read first. The second is asked only when the first's
 * read fails the way a filter makes it fail (blocked): the read itself fails
 * (the connection closed or refused, no network), the worker gives its kept
 * copy in place of an answer (pwa/config.ts markKept, which it does only when
 * its own read failed or took too long), a web page comes in the file's place,
 * or no answer has come within LIVE_ROOT_WAIT_MS. An HTTP error from the live
 * host (a 404, a 5xx) is its own answer, given to the page as it came: the
 * live host was reached, and the second root reads that same host, so it
 * could do no better. (A filter's own page for a blocked host carries no leave
 * for this site to read it, so the browser fails the read: it is never an
 * HTTP error the page sees.) A visitor on an open network so never asks the
 * second root while the live host answers in time, whatever it answers.
 *
 * The root that answered is kept for the visit (sessionStorage, LIVE_ROOT_KEY):
 * once the second has, it is read first, and the first is tried first again
 * every LIVE_ROOT_RETRY_MS. Once a root has failed, the other is given at most
 * LIVE_ROOT_WAIT_MS from when it is asked, before the page is given what the
 * live host gave it (the worker's kept copy, its error), as with one root: the
 * case is never made worse than it was. When neither answers, the second root
 * is not asked again for LIVE_ROOT_RETRY_MS (LIVE_ROOT_OFF_KEY): the page reads
 * as it does with one root, and asks the second nothing it cannot answer.
 *
 * A build without a second root (either variable unset or empty) reads as it
 * did before: liveFetch is fetchFile itself.
 */

import { KEPT_HEADER, LIVE_TIMEOUT_SECONDS, liveRootOf } from '../pwa/config';
import { fetchFile } from './files';
import type { Fetch } from './files';

/** How long the page reads the second root first, once it answered, before it tries the first, and how long it leaves the second alone once both failed: 10 minutes. */
export const LIVE_ROOT_RETRY_MS = 10 * 60_000;

/** Where the visit keeps when the second root last took over: the time, in ms since the epoch. */
export const LIVE_ROOT_KEY = 'snowlight-live-root';

/** Where the visit keeps when both roots last failed one read: the time, in ms since the epoch. */
export const LIVE_ROOT_OFF_KEY = 'snowlight-live-root-off';

/** How long a root may take before the other is asked, and how long the other then has (the worker's own wait). */
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

/**
 * Whether a response that is not the file is the live host's own answer (an HTTP error): the
 * host was reached, so the other root, which reads the same host, is not asked.
 */
export function reached(response: Response): boolean {
  return response.status >= 400 && response.headers.get(KEPT_HEADER) === null;
}

type Outcome =
  | { readonly response: Response; readonly error?: undefined }
  | { readonly response?: undefined; readonly error: unknown };

function discard(outcome: Outcome | undefined): void {
  if (outcome?.response !== undefined) {
    outcome.response.body?.cancel().catch(() => undefined);
  }
}

/** The file `outcome` gave, or null when it gave none. */
const fileOf = (outcome: Outcome | null): Response | null =>
  outcome?.response !== undefined && answered(outcome.response) ? outcome.response : null;

/** The outcome as the read gave it: the response, or its failure thrown. */
function give(outcome: Outcome): Response {
  if (outcome.response !== undefined) return outcome.response;
  throw outcome.error as Error;
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
  /** The page's own memory of both times, where the visit's storage cannot be had. */
  const memory = new Map<string, number>();
  const load = (key: string): number | null => {
    if (store !== null) {
      try {
        const value = store.getItem(key);
        if (value === null) return null;
        const at = Number(value);
        return Number.isFinite(at) ? at : null;
      } catch {
        // Storage that cannot be read: the page's own memory stands.
      }
    }
    return memory.get(key) ?? null;
  };
  const save = (key: string, at: number | null): void => {
    if (at === null) memory.delete(key);
    else memory.set(key, at);
    try {
      if (at === null) store?.removeItem(key);
      else store?.setItem(key, String(at));
    } catch {
      // Kept for this page alone.
    }
  };
  /** Whether `key` was set less than LIVE_ROOT_RETRY_MS ago (a clock set back past it counts as that long). */
  const recent = (key: string, at: number): boolean => {
    const since = load(key);
    if (since === null) return false;
    const age = at - since;
    return age >= 0 && age < LIVE_ROOT_RETRY_MS;
  };
  return async (input, options = {}) => {
    if (!input.startsWith(primary)) return fetch(input, options);
    const started = now();
    // Both roots failed a little while ago: the live host alone, as with one root.
    if (recent(LIVE_ROOT_OFF_KEY, started)) return fetch(input, options);
    const rest = input.slice(primary.length);
    const secondFirst = recent(LIVE_ROOT_KEY, started);
    const order = secondFirst ? [fallback, primary] : [primary, fallback];
    const signal = options.signal ?? null;
    const gaveUp = (): boolean => signal?.aborted === true;
    const controllers: AbortController[] = [];
    const reads: Promise<Outcome>[] = [];
    const read = (root: string): Promise<Outcome> => {
      const controller = new AbortController();
      controllers.push(controller);
      const stop = (): void => {
        controller.abort(signal?.reason);
      };
      if (signal?.aborted === true) stop();
      else signal?.addEventListener('abort', stop, { once: true });
      const reading: Promise<Outcome> = fetch(`${root}${rest}`, {
        ...options,
        signal: controller.signal,
      }).then(
        (response) => {
          signal?.removeEventListener('abort', stop);
          return { response };
        },
        (error: unknown) => {
          signal?.removeEventListener('abort', stop);
          return { error };
        },
      );
      reads.push(reading);
      return reading;
    };
    /** Gives up the read at `index`, and lets go of its answer when it comes. */
    const drop = (index: number): void => {
      controllers[index]?.abort();
      void reads[index]?.then(discard);
    };
    const took = (index: number): void => {
      save(LIVE_ROOT_OFF_KEY, null);
      if (order[index] === primary) save(LIVE_ROOT_KEY, null);
      else if (!secondFirst) save(LIVE_ROOT_KEY, now());
    };

    let timer: ReturnType<typeof setTimeout> | undefined;
    const first: Outcome | null = await Promise.race([
      read(order[0] ?? primary),
      new Promise<null>((resolve) => {
        timer = setTimeout(() => {
          resolve(null);
        }, waitMs);
      }),
    ]);
    clearTimeout(timer);
    const outcomes: [Outcome | null, Outcome | null] = [first, null];
    const file = fileOf(first);
    if (file !== null) {
      took(0);
      return file;
    }
    if (gaveUp()) {
      drop(0);
      if (first !== null) return give(first);
      throw signal?.reason as Error;
    }
    // The live host's own error: given as it came, as with one root.
    if (order[0] === primary && first?.response !== undefined && reached(first.response)) {
      return first.response;
    }

    // The other root, while the first may still answer: whichever answers first is read. The
    // other has at most waitMs; the first, still on its way, as long as it takes, as with one root.
    void read(order[1] ?? fallback);
    let stopWaiting: (() => void) | undefined;
    const winner = await new Promise<number | null>((resolve) => {
      const done = [first !== null, false];
      const settle = (index: number, outcome: Outcome | null): void => {
        if (outcome !== null) outcomes[index] = outcome;
        done[index] = true;
        if (fileOf(outcome) !== null) resolve(index);
        else if (done[0] === true && done[1] === true) resolve(null);
      };
      if (first === null) {
        void reads[0]?.then((outcome) => {
          settle(0, outcome);
        });
      }
      void reads[1]?.then((outcome) => {
        settle(1, outcome);
      });
      timer = setTimeout(() => {
        settle(1, null);
      }, waitMs);
      stopWaiting = () => {
        resolve(null);
      };
      signal?.addEventListener('abort', stopWaiting, { once: true });
    });
    clearTimeout(timer);
    if (stopWaiting !== undefined) signal?.removeEventListener('abort', stopWaiting);
    if (winner !== null) {
      const won = fileOf(winner === 0 ? outcomes[0] : outcomes[1]);
      if (won !== null) {
        drop(1 - winner);
        took(winner);
        return won;
      }
    }
    // Neither answered: the second is left alone for a while, unless the caller gave up.
    if (!gaveUp()) {
      save(LIVE_ROOT_KEY, null);
      save(LIVE_ROOT_OFF_KEY, now());
    }
    // What the live host gave (the worker's kept copy, an error), as with one root, whichever
    // was asked first; else the second root's kept copy.
    const ownIndex = order.indexOf(primary);
    const own = ownIndex === 0 ? outcomes[0] : outcomes[1];
    const other = ownIndex === 0 ? outcomes[1] : outcomes[0];
    if (own?.response !== undefined) {
      drop(1 - ownIndex);
      return own.response;
    }
    if (
      other?.response !== undefined &&
      other.response.ok &&
      other.response.headers.get(KEPT_HEADER) !== null
    ) {
      drop(ownIndex);
      return other.response;
    }
    drop(0);
    drop(1);
    // The live host's own failure (an abort among them), as the read failed with one root.
    if (own !== null) return give(own);
    throw (gaveUp() ? signal?.reason : new Error('No live root answered.')) as Error;
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
