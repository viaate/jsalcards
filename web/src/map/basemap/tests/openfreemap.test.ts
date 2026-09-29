// @vitest-environment node
/**
 * A street tile, as a worker loads it from OpenFreeMap: tried again when the
 * network fails it, holds it without an answer or turns it away for a while,
 * and never taken from an answer that is not a tile.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type * as OpenFreeMap from '../openfreemap';
import { MAX_RETRY_AFTER_MS } from '../retry';

type Module = typeof OpenFreeMap;

/** The module afresh: its TileJSON and its Retry-After are its own. */
async function fresh(): Promise<Module> {
  vi.resetModules();
  return import('../openfreemap');
}

const TEMPLATE = 'https://tiles.openfreemap.org/planet/20260913_164504_pt/{z}/{x}/{y}.pbf';
const TILE_URL = 'https://tiles.openfreemap.org/planet/20260913_164504_pt/10/242/391.pbf';
/** A vector tile's first bytes: its layers. */
const TILE = new Uint8Array([0x1a, 0x03, 0x78, 0x02, 0x01]);

interface Call {
  readonly url: string;
  readonly cache: RequestCache | undefined;
  readonly at: number;
}

/**
 * Stands in for the network: the TileJSON always, and the tile's answers in
 * turn, the last repeated. An answer of null never comes (until aborted).
 */
function network(answers: readonly (null | (() => Response))[]): Call[] {
  const calls: Call[] = [];
  let tries = 0;
  vi.stubGlobal('fetch', (url: string, init: RequestInit = {}): Promise<Response> => {
    calls.push({ url, cache: init.cache, at: Date.now() });
    if (url === 'https://tiles.openfreemap.org/planet') {
      return Promise.resolve(Response.json({ tiles: [TEMPLATE] }));
    }
    const answer = answers[Math.min(tries++, answers.length - 1)];
    if (answer === null || answer === undefined) {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => {
          reject(init.signal?.reason as Error);
        });
      });
    }
    return Promise.resolve(answer());
  });
  return calls;
}

const tile = (): Response =>
  new Response(TILE.slice(), { headers: { 'content-type': 'application/vnd.mapbox-vector-tile' } });
const tileCalls = (calls: readonly Call[]): Call[] => calls.filter((call) => call.url === TILE_URL);

/** Runs a load to its end, the clock moved on as far as it waits. */
async function settle<T>(promise: Promise<T>): Promise<T> {
  const state = { done: false };
  const watched = promise.finally(() => {
    state.done = true;
  });
  watched.catch(() => undefined);
  for (let step = 0; step < 400 && !state.done; step++) await vi.advanceTimersByTimeAsync(500);
  return watched;
}

beforeEach(() => {
  vi.useFakeTimers({ now: 1_000_000 });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('a street tile', () => {
  it('comes from the current tile set', async () => {
    const { loadOpenFreeMapTile } = await fresh();
    const calls = network([tile]);
    const loaded = await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    expect(new Uint8Array(loaded.data)).toEqual(TILE);
    expect(tileCalls(calls)).toHaveLength(1);
  });

  it('that fails, or errs, comes on a later try', async () => {
    const { loadOpenFreeMapTile, TILE_TRIES } = await fresh();
    const calls = network([
      () => new Response('busy', { status: 503 }),
      () => Response.error(),
      tile,
    ]);
    const loaded = await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    expect(new Uint8Array(loaded.data)).toEqual(TILE);
    expect(tileCalls(calls)).toHaveLength(TILE_TRIES);
  });

  it('fails after TILE_TRIES tries, for the page to ask for again', async () => {
    const { loadOpenFreeMapTile, TILE_TRIES } = await fresh();
    const calls = network([() => new Response('busy', { status: 503 })]);
    await expect(
      settle(loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal)),
    ).rejects.toThrow(/HTTP 503/);
    expect(tileCalls(calls)).toHaveLength(TILE_TRIES);
  });

  it('is never taken from a page that is not a tile, and is asked for past the cache after one', async () => {
    const { loadOpenFreeMapTile } = await fresh();
    const calls = network([
      () =>
        new Response('<!doctype html><title>Blocked</title>', {
          headers: { 'content-type': 'text/html' },
        }),
      () =>
        new Response('<!doctype html>', {
          headers: { 'content-type': 'application/octet-stream' },
        }),
      tile,
    ]);
    const loaded = await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    expect(new Uint8Array(loaded.data)).toEqual(TILE);
    expect(tileCalls(calls).map((call) => call.cache)).toEqual([undefined, 'reload', 'reload']);
  });

  it('that stalls is given up on and asked for again', async () => {
    const { loadOpenFreeMapTile, TILE_STALL_MS } = await fresh();
    const calls = network([null, tile]);
    const loaded = await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    expect(new Uint8Array(loaded.data)).toEqual(TILE);
    const [first, second] = tileCalls(calls);
    expect((second?.at ?? 0) - (first?.at ?? 0)).toBeGreaterThanOrEqual(TILE_STALL_MS);
  });

  it('waits as long as an answer turning it away asks, and so does every tile after', async () => {
    const { loadOpenFreeMapTile } = await fresh();
    const calls = network([
      () => new Response('slow down', { status: 429, headers: { 'retry-after': '5' } }),
      tile,
    ]);
    await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    const [first, second] = tileCalls(calls);
    expect((second?.at ?? 0) - (first?.at ?? 0)).toBeGreaterThanOrEqual(5000);
  });

  it('honors a Retry-After for at most MAX_RETRY_AFTER_MS', async () => {
    const { loadOpenFreeMapTile } = await fresh();
    const calls = network([
      () => new Response('slow down', { status: 503, headers: { 'retry-after': '3600' } }),
      tile,
    ]);
    await settle(
      loadOpenFreeMapTile('openfreemap://planet/10/242/391', new AbortController().signal),
    );
    const [first, second] = tileCalls(calls);
    const waited = (second?.at ?? 0) - (first?.at ?? 0);
    expect(waited).toBeGreaterThanOrEqual(MAX_RETRY_AFTER_MS);
    expect(waited).toBeLessThan(MAX_RETRY_AFTER_MS + 5000);
  });

  it('that MapLibre no longer wants is not asked for again', async () => {
    const { loadOpenFreeMapTile } = await fresh();
    const calls = network([() => new Response('busy', { status: 503 })]);
    const controller = new AbortController();
    const load = loadOpenFreeMapTile('openfreemap://planet/10/242/391', controller.signal);
    load.catch(() => undefined);
    await vi.advanceTimersByTimeAsync(10);
    controller.abort();
    await expect(settle(load)).rejects.toThrow();
    expect(tileCalls(calls)).toHaveLength(1);
  });
});

describe('the TileJSON', () => {
  it('that fails is asked for once by every tile asking in the moment, and again after', async () => {
    const { loadOpenFreeMapTile, TEMPLATE_RETRY_MS } = await fresh();
    const lookups: number[] = [];
    vi.stubGlobal('fetch', (url: string): Promise<Response> => {
      if (url !== 'https://tiles.openfreemap.org/planet') return Promise.resolve(tile());
      lookups.push(Date.now());
      return Promise.resolve(
        lookups.length === 1
          ? new Response('busy', { status: 503 })
          : Response.json({ tiles: [TEMPLATE] }),
      );
    });
    const loads = [240, 241, 242, 243].map((x) =>
      loadOpenFreeMapTile(`openfreemap://planet/10/${String(x)}/391`, new AbortController().signal),
    );
    const loaded = await settle(Promise.all(loads));
    expect(loaded).toHaveLength(4);
    expect(lookups).toHaveLength(2);
    expect((lookups[1] ?? 0) - (lookups[0] ?? 0)).toBeGreaterThanOrEqual(TEMPLATE_RETRY_MS);
  });
});

describe('what a tile is', () => {
  it('is empty, or starts with its layers, and is never text', async () => {
    const { isVectorTile } = await fresh();
    expect(isVectorTile('application/vnd.mapbox-vector-tile', TILE)).toBe(true);
    expect(isVectorTile(null, new Uint8Array(0))).toBe(true);
    expect(isVectorTile('application/x-protobuf', new TextEncoder().encode('<html>'))).toBe(false);
    expect(isVectorTile('text/html; charset=utf-8', TILE)).toBe(false);
  });
});
