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
 * every LIVE_ROOT_RETRY_MS. The second root has at most LIVE_ROOT_WAIT_MS from
 * when it is asked, whichever is read first; once it has had them, the page
 * is given what the live host gave it (the worker's kept copy, its error) as
 * soon as the live host has given it, as with one root, and the live host
 * itself has as long as it takes: the case is never made worse than it was. A
 * 404 or 410 from the second root (a file not published yet) is the live
 * host's own answer read through it: given as it came, and the second stays
 * the visit's. Any other 4xx from it (a 403 or a 429 the live host sent the
 * proxy) is the second root failing, like a 5xx.
 *
 * When the second root fails, it is not asked again for LIVE_ROOT_RETRY_MS
 * (LIVE_ROOT_OFF_KEY): the page reads as it does with one root, and asks the
 * second nothing it cannot answer. That holds for a second root that ran past
 * its wait though the caller gave up later. One that was answering until then
 * and fails at once (a 502) is given one more try first: the next read asks
 * the live host first, then it, and a second failure in a row leaves it alone.
 * When both give a copy the worker kept, the page is given the newer, by the
 * generated_at each says.
 *
 * While the visit reads the second root first, a file is read through it at
 * most every LIVE_ROOT_SECOND_EVERY_MS, as each request there counts against
 * the account's shared free limit (docs/live.md): in between, the page is
 * given the file the second root last gave, made when it says, so the page
 * shows that file's own time. A new page (a reload) reads at once.
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

/** How often, at most, the page reads a file through the second root while it reads that root first: every 3 minutes. */
export const LIVE_ROOT_SECOND_EVERY_MS = 3 * 60_000;

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

/** The second root's errors that say the live host has no such file (its own answer). */
const NOT_THERE: ReadonlySet<number> = new Set([404, 410]);

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

/** Whether `outcome` is a copy the worker kept, given in place of an answer. */
const keptOf = (outcome: Outcome | null): Response | null =>
  outcome?.response?.ok === true && outcome.response.headers.get(KEPT_HEADER) !== null
    ? outcome.response
    : null;

/** The outcome as the read gave it: the response, or its failure thrown. */
function give(outcome: Outcome): Response {
  if (outcome.response !== undefined) return outcome.response;
  throw outcome.error as Error;
}

/** When a file says it was made (its generated_at), in ms since the epoch; null when it says none. */
async function madeAt(response: Response): Promise<number | null> {
  try {
    const match = /"generated_at"\s*:\s*"([^"]+)"/.exec(await response.clone().text());
    const at = match?.[1] === undefined ? Number.NaN : Date.parse(match[1]);
    return Number.isFinite(at) ? at : null;
  } catch {
    return null;
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
  /** The page's own memory of both times, where the visit's storage cannot be had. */
  const memory = new Map<string, number>();
  /** The last file (or 404 or 410) the second root gave for each path, and when, for LIVE_ROOT_SECOND_EVERY_MS. */
  const held = new Map<string, { readonly at: number; readonly response: Response }>();
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
  /** Whether `key` was set less than `ms` ago (a clock set back past it counts as that long). */
  const recent = (key: string, at: number, ms = LIVE_ROOT_RETRY_MS): boolean => {
    const since = load(key);
    if (since === null) return false;
    const age = at - since;
    return age >= 0 && age < ms;
  };
  return async (input, options = {}) => {
    if (!input.startsWith(primary)) return fetch(input, options);
    const started = now();
    // Both roots failed a little while ago: the live host alone, as with one root.
    if (recent(LIVE_ROOT_OFF_KEY, started)) return fetch(input, options);
    const rest = input.slice(primary.length);
    const secondFirst = recent(LIVE_ROOT_KEY, started);
    // On the second root, a path it gave less than LIVE_ROOT_SECOND_EVERY_MS ago is that file
    // again: the same file, made when it says, that the page holds already.
    const last = held.get(rest);
    if (
      secondFirst &&
      last !== undefined &&
      (options.method ?? 'GET') === 'GET' &&
      started - last.at >= 0 &&
      started - last.at < LIVE_ROOT_SECOND_EVERY_MS
    ) {
      return last.response.clone();
    }
    const order = secondFirst ? [fallback, primary] : [primary, fallback];
    const own = order.indexOf(primary);
    const second = 1 - own;
    const signal = options.signal ?? null;
    const controllers: AbortController[] = [];
    const reads: Promise<Outcome>[] = [];
    const outcomes: [Outcome | null, Outcome | null] = [null, null];
    /** Whether the second root is no longer waited for: it failed, or ran past its wait. */
    let secondOut = false;
    let finished = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    let stopWaiting: (() => void) | undefined;

    const took = (index: number, file: Response): void => {
      save(LIVE_ROOT_OFF_KEY, null);
      if (index === own) {
        save(LIVE_ROOT_KEY, null);
        held.clear();
        return;
      }
      const at = now();
      if (!recent(LIVE_ROOT_KEY, at)) save(LIVE_ROOT_KEY, at);
      const before = held.get(rest);
      if (before !== undefined) discard({ response: before.response });
      held.set(rest, { at, response: file.clone() });
    };
    /**
     * The second root failed (`ranOut`: gave nothing within its wait). It is left alone for a
     * while, but a second root that was answering until now is given one more try first: the
     * next read asks the live host first, then it.
     */
    const struck = (ranOut: boolean): void => {
      if (secondOut) return;
      secondOut = true;
      save(LIVE_ROOT_KEY, null);
      held.delete(rest);
      if (ranOut || !secondFirst) save(LIVE_ROOT_OFF_KEY, now());
    };

    type Decision =
      | { readonly kind: 'took'; readonly index: number; readonly response: Response }
      | { readonly kind: 'neither' }
      | { readonly kind: 'gaveUp' };
    const decision = await new Promise<Decision>((resolve) => {
      const decide = (value: Decision): void => {
        if (finished) return;
        finished = true;
        for (const timer of timers) clearTimeout(timer);
        if (stopWaiting !== undefined) signal?.removeEventListener('abort', stopWaiting);
        resolve(value);
      };
      /** Done once the live host has given its answer and the second is no longer waited for. */
      const check = (): void => {
        if (outcomes[own] !== null && (secondOut || outcomes[second] !== null)) {
          decide({ kind: 'neither' });
        }
      };
      const ranOut = (): void => {
        if (finished || outcomes[second] !== null) return;
        struck(true);
        check();
      };
      const start = (index: number): void => {
        if (reads[index] !== undefined || finished) return;
        const root = order[index] ?? primary;
        const controller = new AbortController();
        controllers[index] = controller;
        const reading: Promise<Outcome> = fetch(`${root}${rest}`, {
          ...options,
          signal: controller.signal,
        }).then(
          (response) => ({ response }),
          (error: unknown) => ({ error }),
        );
        reads[index] = reading;
        // The second root has the wait from when it is asked, the live host as long as it takes.
        if (index === second) timers.push(setTimeout(ranOut, waitMs));
        void reading.then((outcome) => {
          settle(index, outcome);
        });
      };
      const settle = (index: number, outcome: Outcome): void => {
        if (finished) return;
        outcomes[index] = outcome;
        const file = fileOf(outcome);
        if (file !== null) {
          decide({ kind: 'took', index, response: file });
          return;
        }
        const response = outcome.response;
        // An HTTP error from the live host, or from the second root that read it (a 404 or a
        // 410: the file is not there), is that host's own answer, given as it came. Any other
        // error from the second root (a 403 or a 429 sent to the proxy) is the second failing.
        if (
          response !== undefined &&
          ((index === own && reached(response)) ||
            (index === second && NOT_THERE.has(response.status) && reached(response)))
        ) {
          decide({ kind: 'took', index, response });
          return;
        }
        if (index === second) struck(false);
        // The root read first failed: the other is asked at once.
        if (index === 0) start(1);
        check();
      };
      if (signal?.aborted === true) {
        decide({ kind: 'gaveUp' });
        return;
      }
      stopWaiting = () => {
        decide({ kind: 'gaveUp' });
      };
      signal?.addEventListener('abort', stopWaiting, { once: true });
      start(0);
      // The root read first has not answered within the wait: the other is asked too, and
      // whichever gives the file first is read.
      timers.push(
        setTimeout(() => {
          start(1);
        }, waitMs),
      );
    });

    /** Gives up both reads, and lets go of every answer but `kept` when it comes. */
    const release = (kept: Response | null): void => {
      for (const [index, controller] of controllers.entries()) {
        // A read that already settled has nothing to stop.
        if (outcomes[index] === null) controller.abort();
        void reads[index]?.then((outcome) => {
          if (outcome.response !== kept) discard(outcome);
        });
      }
    };
    if (decision.kind === 'took') {
      release(decision.response);
      if (answered(decision.response)) took(decision.index, decision.response);
      else if (decision.index === second) {
        save(LIVE_ROOT_OFF_KEY, null);
        const at = now();
        if (!recent(LIVE_ROOT_KEY, at)) save(LIVE_ROOT_KEY, at);
        // A file the live host does not have is not asked for through the second root again
        // within LIVE_ROOT_SECOND_EVERY_MS either: each ask there counts against its limit.
        const before = held.get(rest);
        if (before !== undefined) discard({ response: before.response });
        held.set(rest, { at, response: decision.response.clone() });
      }
      return decision.response;
    }
    const mine = outcomes[own] ?? null;
    const ownCopy = keptOf(mine);
    const secondCopy = keptOf(outcomes[second] ?? null);
    if (decision.kind === 'gaveUp') {
      const response = mine?.response ?? secondCopy;
      release(response);
      if (response !== null) return response;
      if (mine !== null) return give(mine);
      throw signal?.reason as Error;
    }
    // Neither gave the file. What the live host gave (the worker's kept copy, an error), as with
    // one root; but a copy the worker kept from the second root that is newer, or the only copy.
    let chosen: Response | null = mine?.response ?? null;
    if (secondCopy !== null) {
      const [ownAt, secondAt] =
        ownCopy === null ? [null, 0] : await Promise.all([madeAt(ownCopy), madeAt(secondCopy)]);
      if (ownCopy === null || (secondAt !== null && (ownAt === null || secondAt > ownAt))) {
        chosen = secondCopy;
      }
    }
    release(chosen);
    if (chosen !== null) return chosen;
    if (mine !== null) return give(mine);
    throw new Error('No live root answered.');
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
