/**
 * Main-thread search API. All matching runs in a worker; this side only
 * posts messages, so no search work ever blocks the page.
 *
 *   const search = createSearchClient(indexUrl);
 *   const results = await search.search('lancaster pa');
 *
 * At most one query is in flight. A new search() supersedes the one before
 * it: the older promise rejects at once with an AbortError (see
 * isAbortError) and its answer, if it comes, is dropped. So only the newest
 * input ever resolves, however fast someone types.
 *
 * Every promise settles. If the worker cannot start (its script fails to
 * load, is blocked, or throws before the index is ready) or the index
 * cannot load, `ready`, every waiting search and every later search reject
 * with a SearchUnavailableError. If the worker reports an error after that,
 * or leaves a query unanswered for `queryTimeoutMs`, only the query in
 * flight rejects and later searches go on.
 */
import type { IndexInfo, SearchResults, WorkerRequest, WorkerResponse } from './types';

export interface SearchOptions {
  /** Results per group, 1 to 50. Default 5. */
  readonly limit?: number;
  /** Aborting rejects this search with an AbortError. */
  readonly signal?: AbortSignal;
}

export interface SearchClient {
  /** Resolves when the index is loaded; rejects if it cannot be. */
  readonly ready: Promise<IndexInfo>;
  search(query: string, options?: SearchOptions): Promise<SearchResults>;
  /** Stops the worker. Pending and later searches reject with an AbortError. */
  destroy(): void;
}

/**
 * The parts of a Worker the client uses; tests pass a MessagePort or a fake.
 * A real Worker fires `error` when its script fails to load or throws, and
 * `messageerror` when a message from it cannot be deserialized.
 */
export interface WorkerLike {
  postMessage(message: WorkerRequest): void;
  addEventListener(
    type: 'message' | 'messageerror',
    listener: (event: MessageEvent<unknown>) => void,
  ): void;
  addEventListener(type: 'error', listener: (event: Event) => void): void;
  terminate?(): void;
}

export interface ClientOptions {
  /** Defaults to a new module worker running worker.ts. */
  readonly worker?: WorkerLike;
  /** Called with the worker's own milliseconds for each answered query. */
  readonly onQueryTime?: (ms: number) => void;
  /**
   * Milliseconds a query may go unanswered once sent to a ready worker
   * before it rejects. Default 5000: a query takes a few milliseconds, so
   * this only fires when the worker has stopped answering. Infinity turns
   * it off.
   */
  readonly queryTimeoutMs?: number;
}

export const DEFAULT_QUERY_TIMEOUT_MS = 5000;

/**
 * Search cannot run at all: the worker did not start or the index did not
 * load. `ready` and every search reject with this, for good.
 */
export class SearchUnavailableError extends Error {
  override readonly name = 'SearchUnavailableError';
}

/** True for the rejection of a superseded, aborted or destroyed search. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function abortError(reason: string): DOMException {
  return new DOMException(reason, 'AbortError');
}

function emptyResults(query: string): SearchResults {
  return { query, schools: [], cities: [], zips: [], order: ['schools', 'cities', 'zips'] };
}

function defaultWorker(): WorkerLike {
  return new Worker(new URL('./worker.ts', import.meta.url), {
    type: 'module',
    name: 'snowlight-search',
  });
}

/** What a worker `error` event says, when it says anything. */
function describeWorkerError(event: Event): { detail: string; cause: unknown } {
  const e = event as Partial<ErrorEvent>;
  const detail = typeof e.message === 'string' && e.message.length > 0 ? `: ${e.message}` : '';
  return { detail, cause: e.error ?? event };
}

/** Longest delay setTimeout keeps; longer ones fire at once. */
const MAX_TIMER_MS = 2 ** 31 - 1;

/** The query timeout to use: null for none (Infinity), the default for nonsense. */
function queryTimeout(ms: number | undefined): number | null {
  if (ms === Number.POSITIVE_INFINITY) return null;
  if (ms === undefined || !Number.isFinite(ms) || ms <= 0) return DEFAULT_QUERY_TIMEOUT_MS;
  return Math.min(ms, MAX_TIMER_MS);
}

interface Pending {
  readonly id: number;
  readonly q: string;
  readonly limit: number;
  readonly resolve: (results: SearchResults) => void;
  readonly reject: (error: unknown) => void;
  /** Rejected already; its answer is ignored. */
  settled: boolean;
  unlisten: () => void;
}

export function createSearchClient(url: string | URL, options: ClientOptions = {}): SearchClient {
  let nextId = 1;
  let inFlight: Pending | null = null;
  let queued: Pending | null = null;
  let isReady = false;
  let failure: SearchUnavailableError | null = null;
  let destroyed = false;
  let terminated = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeoutMs = queryTimeout(options.queryTimeoutMs);

  let resolveReady!: (info: IndexInfo) => void;
  let rejectReady!: (error: unknown) => void;
  const ready = new Promise<IndexInfo>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  // Callers that only search still learn of failures through search().
  ready.catch(() => undefined);

  let worker: WorkerLike | null = null;
  try {
    worker = options.worker ?? defaultWorker();
  } catch (error) {
    // A blocked or invalid worker URL throws in the constructor.
    failure = new SearchUnavailableError('Snowlight search: the search worker could not start', {
      cause: error,
    });
    rejectReady(failure);
  }

  const stopWorker = (): void => {
    if (terminated) return;
    terminated = true;
    worker?.terminate?.();
  };

  /** Sends a message; false when there is no worker to take it. */
  const post = (message: WorkerRequest): boolean => {
    if (terminated || !worker) return false;
    try {
      worker.postMessage(message);
      return true;
    } catch {
      return false;
    }
  };

  const clearTimer = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };

  const settle = (p: Pending, error: unknown): void => {
    if (p.settled) return;
    p.settled = true;
    p.unlisten();
    p.reject(error);
  };

  const pump = (): void => {
    if (!isReady || failure !== null || inFlight || !queued) return;
    const p = queued;
    queued = null;
    if (!post({ type: 'query', id: p.id, q: p.q, limit: p.limit })) {
      settle(p, new Error('Snowlight search: the search worker could not take the query'));
      return;
    }
    inFlight = p;
    clearTimer();
    if (timeoutMs === null) return;
    timer = setTimeout(() => {
      timer = undefined;
      if (inFlight !== p) return;
      // The worker may still answer; that late answer no longer matches.
      // A superseded query had its cancel sent already.
      if (!p.settled) post({ type: 'cancel', id: p.id });
      inFlight = null;
      settle(p, new Error('Snowlight search: the search worker did not answer in time'));
      pump();
    }, timeoutMs);
  };

  /** Rejects a search that is waiting or in flight, as superseded or aborted. */
  const drop = (p: Pending, reason: string): void => {
    if (queued === p) queued = null;
    if (inFlight === p) post({ type: 'cancel', id: p.id });
    settle(p, abortError(reason));
  };

  const finish = (id: number, outcome: (p: Pending) => void): void => {
    const p = inFlight;
    if (p?.id !== id) return;
    inFlight = null;
    clearTimer();
    if (!p.settled) {
      p.settled = true;
      p.unlisten();
      outcome(p);
    }
    pump();
  };

  /** Search cannot run: reject ready, everything waiting, and all later searches. */
  const fail = (message: string, cause?: unknown): void => {
    if (failure !== null || destroyed) return;
    failure = new SearchUnavailableError(
      `Snowlight search: ${message}`,
      cause === undefined ? undefined : { cause },
    );
    rejectReady(failure);
    clearTimer();
    const waiting = [inFlight, queued];
    inFlight = null;
    queued = null;
    for (const p of waiting) if (p) settle(p, failure);
    stopWorker();
  };

  /** The worker is running but lost the query in flight: reject only that one. */
  const loseInFlight = (message: string, cause?: unknown): void => {
    const p = inFlight;
    if (!p) return;
    inFlight = null;
    clearTimer();
    settle(
      p,
      new Error(`Snowlight search: ${message}`, cause === undefined ? undefined : { cause }),
    );
    pump();
  };

  if (worker) {
    worker.addEventListener('message', (event) => {
      if (destroyed || failure !== null) return;
      const data = event.data as WorkerResponse | null;
      if (!data || typeof data !== 'object') return;
      switch (data.type) {
        case 'ready':
          if (isReady) return;
          isReady = true;
          resolveReady(data.info);
          pump();
          return;
        case 'load-error':
          fail(data.message);
          return;
        case 'result':
          options.onQueryTime?.(data.ms);
          finish(data.id, (p) => {
            p.resolve(data.results);
          });
          return;
        case 'cancelled':
          finish(data.id, (p) => {
            p.reject(abortError('Search cancelled'));
          });
          return;
        case 'query-error':
          finish(data.id, (p) => {
            p.reject(new Error(`Snowlight search: ${data.message}`));
          });
          return;
      }
    });

    worker.addEventListener('error', (event) => {
      if (destroyed || failure !== null) return;
      const { detail, cause } = describeWorkerError(event);
      // Before ready this is a worker that never started: its script did
      // not load, was blocked, or threw. After ready the worker still runs,
      // but whatever it was doing is lost.
      if (!isReady) fail(`the search worker failed to start${detail}`, cause);
      else loseInFlight(`the search worker failed${detail}`, cause);
    });

    worker.addEventListener('messageerror', (event) => {
      if (destroyed || failure !== null) return;
      // An answer arrived that could not be read. Before ready it was the
      // ready message itself.
      if (!isReady) fail('the search worker sent an unreadable message', event);
      else loseInFlight('the search worker sent an unreadable answer', event);
    });

    try {
      worker.postMessage({ type: 'load', url: String(url) });
    } catch (error) {
      fail('the search worker could not start', error);
    }
  }

  const search = (query: string, opts: SearchOptions = {}): Promise<SearchResults> => {
    if (destroyed) return Promise.reject(abortError('Search client destroyed'));
    if (failure !== null) return Promise.reject(failure);
    const signal = opts.signal;
    if (signal?.aborted) return Promise.reject(abortError('Search aborted'));
    // Supersede whatever is pending, even for empty input.
    if (queued) drop(queued, 'Search superseded');
    if (inFlight) drop(inFlight, 'Search superseded');
    if (query.trim().length === 0) return Promise.resolve(emptyResults(query));

    return new Promise<SearchResults>((resolve, reject) => {
      const limit = Math.max(1, Math.min(50, Math.floor(opts.limit ?? 5) || 5));
      const p: Pending = {
        id: nextId++,
        q: query,
        limit,
        resolve,
        reject,
        settled: false,
        unlisten: () => undefined,
      };
      if (signal) {
        const onAbort = (): void => {
          drop(p, 'Search aborted');
        };
        signal.addEventListener('abort', onAbort, { once: true });
        p.unlisten = () => {
          signal.removeEventListener('abort', onAbort);
        };
      }
      queued = p;
      pump();
    });
  };

  const destroy = (): void => {
    if (destroyed) return;
    destroyed = true;
    clearTimer();
    for (const p of [inFlight, queued]) if (p) settle(p, abortError('Search client destroyed'));
    inFlight = null;
    queued = null;
    if (!isReady && failure === null) rejectReady(abortError('Search client destroyed'));
    stopWorker();
  };

  return { ready, search, destroy };
}
