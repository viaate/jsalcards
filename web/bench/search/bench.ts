/**
 * Bench page script: drives the real search client and worker in the page,
 * the way the site will, and reports timings to the Playwright spec.
 */
import { createSearchClient, isAbortError } from '../../src/search/index';
import type { IndexInfo, SearchClient } from '../../src/search/index';

export interface QueryTiming {
  readonly q: string;
  /** Milliseconds from search() to the resolved promise, on the main thread. */
  readonly roundTrip: number;
  /** Milliseconds the worker spent on the query. */
  readonly worker: number;
  readonly hits: number;
}

export interface StartResult {
  readonly info: IndexInfo;
  /** Milliseconds from createSearchClient() to ready, on the main thread. */
  readonly readyMs: number;
}

/** How one promise settled, and when, in milliseconds from createSearchClient(). */
export interface Settled {
  readonly outcome: 'resolved' | 'rejected' | 'pending';
  readonly ms: number;
  readonly error: string;
  readonly errorName: string;
  readonly abort: boolean;
}

/** What a client did when its worker could not run. */
export interface FailureProbe {
  readonly ready: Settled;
  /** A search made before the failure. */
  readonly waiting: Settled;
  /** A search made after `ready` settled. */
  readonly later: Settled;
}

export interface BurstResult {
  readonly sent: number;
  readonly superseded: number;
  readonly resolved: number;
  readonly lastQuery: string;
}

/**
 * Queries go in and timings come out through separate calls, outside the
 * traced window, so moving bench data across never shows up as a long
 * main-thread task.
 */
export interface SearchBench {
  setQueries(queries: readonly string[]): void;
  start(indexUrl: string): Promise<void>;
  run(): Promise<void>;
  burst(count: number): Promise<void>;
  results(): { start: StartResult | null; timings: QueryTiming[]; burst: BurstResult | null };
  /**
   * Starts a fresh client and reports how `ready`, a waiting search and a
   * later search settle, giving up on each after `waitMs`.
   */
  probe(indexUrl: string, waitMs: number): Promise<FailureProbe>;
}

declare global {
  interface Window {
    searchBench: SearchBench;
  }
}

let client: SearchClient | null = null;
let lastWorkerMs = 0;
let queries: readonly string[] = [];
let started: StartResult | null = null;
let timings: QueryTiming[] = [];
let burstResult: BurstResult | null = null;

function need(): SearchClient {
  if (!client) throw new Error('start() first');
  return client;
}

window.searchBench = {
  setQueries(list) {
    queries = list;
  },

  async start(indexUrl) {
    performance.mark('search-start');
    const t0 = performance.now();
    client = createSearchClient(new URL(indexUrl, location.href), {
      onQueryTime: (ms) => {
        lastWorkerMs = ms;
      },
    });
    const info = await client.ready;
    performance.mark('search-ready');
    started = { info, readyMs: performance.now() - t0 };
  },

  async run() {
    const c = need();
    const out: QueryTiming[] = [];
    for (const q of queries) {
      lastWorkerMs = 0;
      const t0 = performance.now();
      const r = await c.search(q);
      out.push({
        q,
        roundTrip: performance.now() - t0,
        worker: lastWorkerMs,
        hits: r.schools.length + r.cities.length + r.zips.length,
      });
    }
    timings = out;
  },

  async burst(count) {
    const c = need();
    const list = queries.slice(0, count);
    let superseded = 0;
    let resolved = 0;
    const all = list.map((q) =>
      c.search(q).then(
        () => {
          resolved++;
        },
        (error: unknown) => {
          if (isAbortError(error)) superseded++;
          else throw error;
        },
      ),
    );
    await Promise.all(all);
    burstResult = { sent: list.length, superseded, resolved, lastQuery: list.at(-1) ?? '' };
  },

  results() {
    return { start: started, timings, burst: burstResult };
  },

  async probe(indexUrl, waitMs) {
    const t0 = performance.now();
    const settled = (promise: Promise<unknown>): Promise<Settled> =>
      Promise.race([
        promise.then(
          (): Settled => ({
            outcome: 'resolved',
            ms: performance.now() - t0,
            error: '',
            errorName: '',
            abort: false,
          }),
          (error: unknown): Settled => ({
            outcome: 'rejected',
            ms: performance.now() - t0,
            error: String(error),
            errorName: error instanceof Error ? error.name : typeof error,
            abort: isAbortError(error),
          }),
        ),
        new Promise<Settled>((done) => {
          setTimeout(() => {
            done({ outcome: 'pending', ms: waitMs, error: '', errorName: '', abort: false });
          }, waitMs);
        }),
      ]);
    const probeClient = createSearchClient(new URL(indexUrl, location.href));
    const waiting = settled(probeClient.search('lancaster'));
    const ready = await settled(probeClient.ready);
    const later = await settled(probeClient.search('springfield'));
    const result = { ready, waiting: await waiting, later };
    probeClient.destroy();
    return result;
  },
};
