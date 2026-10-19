// @vitest-environment node
import { runInNewContext } from 'node:vm';

import type { HtmlTagDescriptor, ResolvedConfig } from 'vite';
import { describe, expect, it, vi } from 'vitest';

import {
  APPLE_TOUCH_ICON,
  CACHE_LIMITS,
  CACHE_NAMES,
  LIVE_ROOT_ENV,
  LIVE_TIMEOUT_SECONDS,
  RETIRED_CACHES,
  RETIRE_FILE,
  isRangeRequest,
  keepNewerClosings,
  onlyTiles,
  pwaHead,
  pwaOptions,
  retireCachesScript,
  routePatterns,
  workboxOptions,
} from '../config';
import { LIVE_AHEAD_MS, LIVE_AHEAD_OF_ANSWER_MS } from '../../data/live';

const SITE = 'https://snow.test';

type RuntimeRoute = NonNullable<ReturnType<typeof workboxOptions>['runtimeCaching']>[number];

/**
 * The runtime route the generated worker picks for a GET, as Workbox's router
 * does: routes in order, the first match wins; a RegExp is tested against the
 * full URL (and must match from its first character for another origin), a
 * function is called with the request. Undefined means no route: the browser
 * fetches it as if there were no worker.
 */
function routeOf(
  routes: readonly RuntimeRoute[],
  url: string,
  headers: HeadersInit = {},
): RuntimeRoute | undefined {
  const request = new Request(url, { headers });
  const parsed = new URL(url);
  return routes.find(({ urlPattern }) => {
    if (urlPattern instanceof RegExp) {
      const result = urlPattern.exec(parsed.href);
      return result !== null && (parsed.origin === SITE || result.index === 0);
    }
    if (typeof urlPattern === 'function') {
      const context = { url: parsed, request, sameOrigin: parsed.origin === SITE };
      return Boolean(urlPattern(context as Parameters<typeof urlPattern>[0]));
    }
    return false;
  });
}

describe('workboxOptions', () => {
  const options = workboxOptions('/');
  const routes = options.runtimeCaching ?? [];
  const byCache = (name: string) => routes.find((route) => route.options?.cacheName === name);
  const cachingRoutes = routes.filter((route) => route.options?.cacheName !== undefined);

  it('lets the first worker take the page, but never forces an update on it', () => {
    expect(options.clientsClaim).toBe(true);
    expect(options.skipWaiting).toBe(false);
    expect(options.cleanupOutdatedCaches).toBe(true);
    expect(options.sourcemap).toBe(false);
  });

  it('answers share links with the precached shell', () => {
    expect(options.navigateFallback).toBe('index.html');
    expect(options.navigateFallbackAllowlist).toEqual([routePatterns('/').navigation]);
  });

  it('revalidates data and tells the page when it changed', () => {
    const data = byCache(CACHE_NAMES.data);
    expect(data?.handler).toBe('StaleWhileRevalidate');
    expect(data?.urlPattern).toEqual(routePatterns('/').data);
    expect(data?.options?.broadcastUpdate).toBeDefined();
    expect(data?.options?.cacheableResponse).toEqual({ statuses: [200] });
    expect(data?.options?.expiration?.maxAgeSeconds).toBeUndefined();
  });

  it('serves the directory and search index cache-first, expiring', () => {
    const staticData = byCache(CACHE_NAMES.staticData);
    expect(staticData?.handler).toBe('CacheFirst');
    expect(staticData?.options?.expiration).toMatchObject(CACHE_LIMITS.staticData);
    // Tried before the broader data route, which would otherwise catch it.
    const order = routes.map((route) => route.options?.cacheName);
    expect(order.indexOf(CACHE_NAMES.staticData)).toBeGreaterThanOrEqual(0);
    expect(order.indexOf(CACHE_NAMES.staticData)).toBeLessThan(order.indexOf(CACHE_NAMES.data));
  });

  it('keeps a small, bounded cache of tiles', () => {
    const tiles = byCache(CACHE_NAMES.tiles);
    expect(tiles?.handler).toBe('CacheFirst');
    expect(tiles?.options?.expiration).toMatchObject({
      ...CACHE_LIMITS.tiles,
      purgeOnQuotaError: true,
    });
    expect(byCache(CACHE_NAMES.tileJson)?.handler).toBe('NetworkFirst');
  });

  it('keeps nothing but tiles in the tile cache: never a block page sent as a 200', async () => {
    expect(byCache(CACHE_NAMES.tiles)?.options?.plugins).toEqual([onlyTiles]);
    const keep = async (response: Response): Promise<boolean> =>
      (await onlyTiles.cacheWillUpdate({ response })) !== null;
    const tile = (): Response =>
      new Response(new Uint8Array([0x1a, 0]), {
        headers: { 'content-type': 'application/vnd.mapbox-vector-tile' },
      });
    expect(await keep(tile())).toBe(true);
    // An empty tile: nothing there, and nothing to ask for again.
    expect(await keep(new Response(new Uint8Array(0)))).toBe(true);
    expect(await keep(new Response('<html>', { headers: { 'content-type': 'text/html' } }))).toBe(
      false,
    );
    // Not text by its type, and still no tile: a filter's page, or a challenge's.
    for (const type of ['application/vnd.mapbox-vector-tile', 'application/octet-stream']) {
      const page = new Response('<!doctype html><title>Blocked</title>', {
        headers: { 'content-type': type },
      });
      expect(await keep(page)).toBe(false);
    }
    expect(await keep(new Response('busy', { status: 503 }))).toBe(false);
    // What it keeps can still be read by the map: it reads a copy.
    const kept = await onlyTiles.cacheWillUpdate({ response: tile() });
    expect(new Uint8Array((await kept?.arrayBuffer()) ?? new ArrayBuffer(0))).toEqual(
      new Uint8Array([0x1a, 0]),
    );
    // Written into sw.js as source text: it refers to nothing outside itself.
    const rebuilt = runInNewContext(`(${onlyTiles.cacheWillUpdate.toString()})`, {
      Promise,
      Uint8Array,
    }) as typeof onlyTiles.cacheWillUpdate;
    const page = new Response('<html>', { headers: { 'content-type': 'text/html' } });
    expect(await rebuilt({ response: page })).toBeNull();
    expect(await rebuilt({ response: tile() })).not.toBeNull();
  });

  it('answers a request asking to go past the cache from the network, not the cache', async () => {
    const cached = new Response(new Uint8Array([0x1a, 0]));
    const use = (cache: RequestCache): Promise<Response | null> =>
      onlyTiles.cachedResponseWillBeUsed({
        request: new Request('https://tiles.openfreemap.org/planet/x/7/32/45.pbf', { cache }),
        cachedResponse: cached,
      });
    expect(await use('default')).toBe(cached);
    expect(await use('reload')).toBeNull();
    const rebuilt = runInNewContext(`(${onlyTiles.cachedResponseWillBeUsed.toString()})`, {
      Promise,
    }) as typeof onlyTiles.cachedResponseWillBeUsed;
    expect(
      await rebuilt({
        request: new Request('https://tiles.openfreemap.org/planet/x/7/32/45.pbf', {
          cache: 'reload',
        }),
        cachedResponse: cached,
      }),
    ).toBeNull();
  });

  it('deletes the tile cache an earlier build kept, as its worker takes over', async () => {
    expect(RETIRED_CACHES).toContain('snowlight-tiles-v1');
    expect(Object.values(CACHE_NAMES)).not.toContain('snowlight-tiles-v1');
    expect(workboxOptions('/').importScripts).toEqual([RETIRE_FILE]);
    const listeners: ((event: { waitUntil(done: Promise<unknown>): void }) => void)[] = [];
    const deleted: string[] = [];
    runInNewContext(retireCachesScript(), {
      self: {
        addEventListener: (_type: string, listener: (typeof listeners)[number]) =>
          listeners.push(listener),
      },
      caches: {
        delete: (name: string) => {
          deleted.push(name);
          return Promise.resolve(true);
        },
      },
      Promise,
    });
    const waits: Promise<unknown>[] = [];
    for (const listener of listeners) listener({ waitUntil: (done) => waits.push(done) });
    await Promise.all(waits);
    expect(deleted).toEqual([...RETIRED_CACHES]);
  });

  it('caches only successful responses, never opaque ones or parts of files', () => {
    expect(cachingRoutes.length).toBe(Object.keys(CACHE_NAMES).length);
    for (const route of cachingRoutes) {
      expect(route.options?.cacheableResponse).toEqual({ statuses: [200] });
    }
  });

  it('passes every request for part of a file to the network, first of all routes', () => {
    const [first] = routes;
    expect(first).toEqual({ urlPattern: isRangeRequest, handler: 'NetworkOnly' });
    for (const url of [
      `${SITE}/data/schools/schools.pmtiles`,
      `${SITE}/data/schools/meta.json`,
      `${SITE}/data/live/closings.json`,
      `${SITE}/assets/geist-latin-wght-normal-abc.woff2`,
      'https://tiles.openfreemap.org/planet/x/7/32/45.pbf',
    ]) {
      expect([url, routeOf(routes, url, { Range: 'bytes=0-126' })]).toEqual([url, first]);
    }
  });

  it('leaves range-served files to the browser, so a whole one is never cached', () => {
    for (const url of [
      `${SITE}/data/schools/schools.pmtiles`,
      `${SITE}/data/schools/schools.pmtiles?v=2`,
      `${SITE}/snow/data/schools/schools.pmtiles`,
    ]) {
      expect([url, routeOf(routes, url)]).toEqual([url, undefined]);
      expect([url, routeOf(workboxOptions('/snow/').runtimeCaching ?? [], url)]).toEqual([
        url,
        undefined,
      ]);
    }
  });

  it('sends whole-file requests to the caches as before', () => {
    const cacheOf = (url: string) => routeOf(routes, url)?.options?.cacheName;
    expect(cacheOf(`${SITE}/data/schools/meta.json`)).toBe(CACHE_NAMES.staticData);
    expect(cacheOf(`${SITE}/data/schools/points.bin`)).toBe(CACHE_NAMES.staticData);
    expect(cacheOf(`${SITE}/data/live/closings.json`)).toBe(CACHE_NAMES.data);
    expect(cacheOf(`${SITE}/assets/index-abc.js`)).toBe(CACHE_NAMES.assets);
    expect(cacheOf('https://tiles.openfreemap.org/planet')).toBe(CACHE_NAMES.tileJson);
    expect(cacheOf('https://tiles.openfreemap.org/planet/x/7/32/45.pbf')).toBe(CACHE_NAMES.tiles);
  });

  it('writes a range matcher that works from its source alone, as sw.js holds it', () => {
    // Workbox writes a function matcher into sw.js with toString(): nothing it closes over survives.
    // Rebuilt from that text alone, in a fresh global scope, it must still work.
    const rebuilt = runInNewContext(`(${isRangeRequest.toString()})`) as typeof isRangeRequest;
    const ranged = new Request(`${SITE}/data/schools/schools.pmtiles`, {
      headers: { range: 'bytes=0-126' },
    });
    expect(rebuilt({ request: ranged })).toBe(true);
    expect(rebuilt({ request: new Request(`${SITE}/data/schools/meta.json`) })).toBe(false);
  });
});

describe('workboxOptions with a live root', () => {
  const LIVE = 'https://live.snow.test/v1/';
  const plain = workboxOptions('/');
  const options = workboxOptions('/', LIVE);
  const routes = options.runtimeCaching ?? [];

  it('serves the closings file at the root network-first, into the data cache, unbroadcast', () => {
    const live = routeOf(routes, `${LIVE}live/closings.json`);
    expect(live).toEqual({
      urlPattern: routePatterns('/', LIVE).live,
      handler: 'NetworkFirst',
      options: {
        cacheName: CACHE_NAMES.data,
        networkTimeoutSeconds: LIVE_TIMEOUT_SECONDS,
        expiration: { ...CACHE_LIMITS.data, purgeOnQuotaError: true },
        cacheableResponse: { statuses: [200] },
        plugins: [keepNewerClosings],
      },
    });
    expect(LIVE_TIMEOUT_SECONDS).toBe(4);
    expect(live?.options?.broadcastUpdate).toBeUndefined();
  });

  it('tries it right after the range route, before the data routes', () => {
    expect(routes[0]).toEqual(plain.runtimeCaching?.[0]);
    expect(routes[1]?.handler).toBe('NetworkFirst');
    expect(routes[1]?.urlPattern).toEqual(routePatterns('/', LIVE).live);
    expect(routes.slice(2)).toEqual(plain.runtimeCaching?.slice(1));
    // Everything else is as without a root.
    expect({ ...options, runtimeCaching: [] }).toEqual({ ...plain, runtimeCaching: [] });
    expect(routeOf(routes, `${SITE}/data/live/closings.json`)?.handler).toBe(
      'StaleWhileRevalidate',
    );
  });

  it('adds nothing without a root', () => {
    expect(workboxOptions('/', '')).toEqual(plain);
    expect(workboxOptions('/', null)).toEqual(plain);
  });
});

describe('keepNewerClosings', () => {
  const URL_ = 'https://live.snow.test/v1/live/closings.json';
  const file = (generatedAt: string, status = 200): Response =>
    new Response(JSON.stringify({ schema_version: 1, generated_at: generatedAt, days: [] }), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  const keep = async (next: Response, held: Response | undefined): Promise<boolean> =>
    (await keepNewerClosings.cacheWillUpdate({ request: new Request(URL_), response: next }, () =>
      Promise.resolve(held),
    )) !== null;

  it('keeps only a copy newer than the one kept', async () => {
    expect(await keep(file('2026-01-12T12:47:00Z'), undefined)).toBe(true);
    expect(await keep(file('2026-01-12T12:47:00Z'), file('2026-01-12T12:42:00Z'))).toBe(true);
    // An edge or a worker behind: an older copy, or the same one, leaves the kept copy.
    expect(await keep(file('2026-01-12T12:42:00Z'), file('2026-01-12T12:47:00Z'))).toBe(false);
    expect(await keep(file('2026-01-12T12:47:00Z'), file('2026-01-12T12:47:00Z'))).toBe(false);
    // A blank file is a newer file like any other.
    expect(await keep(file('2026-01-12T12:52:00Z'), file('2026-01-12T12:47:00Z'))).toBe(true);
  });

  it('never keeps a copy without a generated_at, and replaces a kept copy without one', async () => {
    expect(await keep(new Response('<html>'), undefined)).toBe(false);
    expect(await keep(new Response('{}'), undefined)).toBe(false);
    expect(await keep(new Response('null'), undefined)).toBe(false);
    expect(await keep(new Response(JSON.stringify({ generated_at: 7 })), undefined)).toBe(false);
    expect(await keep(file('2026-01-12T12:47:00Z', 500), undefined)).toBe(false);
    expect(await keep(file('2026-01-12T12:47:00Z'), new Response('garbage'))).toBe(true);
  });

  it('sets only the kept copy against the clock: one more than ten minutes ahead holds nothing off', async () => {
    const at = (minutes: number): string =>
      new Date(Date.now() + minutes * 60_000).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const give = (answer: Response, held: Response | undefined): Promise<Response> =>
      keepNewerClosings.handlerWillRespond({ request: new Request(URL_), response: answer }, () =>
        Promise.resolve(held),
      );
    expect(LIVE_AHEAD_MS).toBe(10 * 60_000);
    // The network's answer is never refused for its stamp, however far ahead.
    expect(await keep(file(at(11)), file(at(-5)))).toBe(true);
    expect(await keep(file('2099-01-01T00:00:00Z'), undefined)).toBe(true);
    const far = file('2099-01-01T00:00:00Z');
    expect(await give(far, file(at(-3)))).toBe(far);
    // A kept copy up to ten minutes ahead stands against an older answer.
    const near = file(at(9));
    expect(await give(file(at(-1)), near)).toBe(near);
    expect(await keep(file(at(-1)), file(at(9)))).toBe(false);
    // One kept further ahead (a publisher clock fault) gives way to the next sound file.
    expect(await keep(file(at(-1)), file('2099-01-01T00:00:00Z'))).toBe(true);
    const sound = file(at(-1));
    expect(await give(sound, file('2099-01-01T00:00:00Z'))).toBe(sound);
  });

  for (const back of [15, 60]) {
    it(`takes a blank published after the device clock went back ${String(back)} minutes`, async () => {
      const real = Date.now();
      const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
      // Kept at the device's own now; then the clock goes back, and a blank is published.
      const kept = file(stamp(real));
      const clock = vi.spyOn(Date, 'now').mockReturnValue(real - back * 60_000);
      try {
        const blank = file(stamp(real + 60_000));
        expect(await keep(blank, kept)).toBe(true);
        const answer = file(stamp(real + 60_000));
        expect(await keep(answer, kept)).toBe(true);
        expect(
          await keepNewerClosings.handlerWillRespond(
            { request: new Request(URL_), response: answer },
            () => Promise.resolve(kept),
          ),
        ).toBe(answer);
      } finally {
        clock.mockRestore();
      }
    });
  }

  for (const slow of [11, 12, 30, 24 * 60]) {
    it(`keeps the newer copy against an older answer on a device clock ${String(slow)} minutes slow`, async () => {
      const real = Date.parse('2026-01-12T12:00:00Z');
      const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
      const lit = (generatedAt: string): Response =>
        new Response(
          JSON.stringify({
            schema_version: 1,
            generated_at: generatedAt,
            days: [{ day: '2026-01-12', schools: [[0, 0]] }],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      const clock = vi.spyOn(Date, 'now').mockReturnValue(real - slow * 60_000);
      try {
        // Kept: the newer file, a blank that called a closing off at 12:00. The answer: an edge
        // behind, or the browser's own cache, with the older file that still lit it.
        const kept = file(stamp(real));
        for (const behind of [1, 10, 59, 60]) {
          const older = stamp(real - behind * 60_000);
          expect(await keep(lit(older), file(stamp(real)))).toBe(false);
          expect(
            await keepNewerClosings.handlerWillRespond(
              { request: new Request(URL_), response: lit(older) },
              () => Promise.resolve(kept),
            ),
          ).toBe(kept);
        }
        // A newer answer is still taken, and kept.
        const newer = file(stamp(real + 60_000));
        expect(await keep(newer, file(stamp(real)))).toBe(true);
        expect(
          await keepNewerClosings.handlerWillRespond(
            { request: new Request(URL_), response: newer },
            () => Promise.resolve(kept),
          ),
        ).toBe(newer);
        // A kept copy a publisher clock stamped far ahead still gives way to the next sound file.
        const sound = lit(stamp(real - 5 * 60_000));
        expect(await keep(lit(stamp(real - 5 * 60_000)), file('2099-01-01T00:00:00Z'))).toBe(true);
        expect(
          await keepNewerClosings.handlerWillRespond(
            { request: new Request(URL_), response: sound },
            () => Promise.resolve(file('2099-01-01T00:00:00Z')),
          ),
        ).toBe(sound);
      } finally {
        clock.mockRestore();
      }
    });
  }

  it('gives up a kept copy only when it is past both the clock and the answer by their limits', async () => {
    const real = Date.parse('2026-01-12T12:00:00Z');
    const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
    expect(LIVE_AHEAD_OF_ANSWER_MS).toBe(60 * 60_000);
    const clock = vi.spyOn(Date, 'now').mockReturnValue(real);
    try {
      const answer = stamp(real - 30 * 60_000);
      // Past the clock by more than ten minutes: it stands up to an hour past the answer.
      expect(await keep(file(answer), file(stamp(real + 30 * 60_000)))).toBe(false);
      expect(await keep(file(answer), file(stamp(real + 30 * 60_000 + 1000)))).toBe(true);
      // Within ten minutes of the clock: it stands however far past the answer.
      expect(await keep(file(stamp(real - 3 * 60 * 60_000)), file(stamp(real + 9 * 60_000)))).toBe(
        false,
      );
      // With no answer to set it by (an error), the clock alone decides.
      const far = file(stamp(real + 11 * 60_000));
      const error = new Response('', { status: 500 });
      expect(
        await keepNewerClosings.handlerWillRespond(
          { request: new Request(URL_), response: error },
          () => Promise.resolve(far),
        ),
      ).toBe(error);
      const near = file(stamp(real + 9 * 60_000));
      expect(
        await keepNewerClosings.handlerWillRespond(
          { request: new Request(URL_), response: new Response('', { status: 500 }) },
          () => Promise.resolve(near),
        ),
      ).toBe(near);
    } finally {
      clock.mockRestore();
    }
  });

  it('sets the kept copy against the clock at LIVE_AHEAD_MS in both hooks, with the answer far behind', async () => {
    const real = Date.parse('2026-01-12T12:00:00Z');
    const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const clock = vi.spyOn(Date, 'now').mockReturnValue(real);
    try {
      // The answer is two hours behind the clock, so only the clock's limit decides.
      const answer = (): Response => file(stamp(real - 2 * 60 * 60_000));
      const kept = (past: number): Response => file(stamp(real + LIVE_AHEAD_MS + past));
      // Just past the limit: the kept copy gives way, in what is kept and in what the page gets.
      expect(await keep(answer(), kept(60_000))).toBe(true);
      const sound = answer();
      expect(
        await keepNewerClosings.handlerWillRespond(
          { request: new Request(URL_), response: sound },
          () => Promise.resolve(kept(60_000)),
        ),
      ).toBe(sound);
      // Just within it: the kept copy stands, in both.
      expect(await keep(answer(), kept(-60_000))).toBe(false);
      const near = kept(-60_000);
      expect(
        await keepNewerClosings.handlerWillRespond(
          { request: new Request(URL_), response: answer() },
          () => Promise.resolve(near),
        ),
      ).toBe(near);
    } finally {
      clock.mockRestore();
    }
  });

  it('leaves the copy it keeps whole, for the cache and the page', async () => {
    const next = file('2026-01-12T12:47:00Z');
    const kept = await keepNewerClosings.cacheWillUpdate(
      {
        request: new Request(URL_),
        response: next,
      },
      () => Promise.resolve(undefined),
    );
    expect(kept).toBe(next);
    expect(await kept?.json()).toMatchObject({ generated_at: '2026-01-12T12:47:00Z' });
  });

  it('gives the page the kept copy in place of an older answer, and a newer answer as it is', async () => {
    const give = async (answer: Response, held: Response | undefined): Promise<Response> =>
      keepNewerClosings.handlerWillRespond({ request: new Request(URL_), response: answer }, () =>
        Promise.resolve(held),
      );
    const kept = file('2026-01-12T12:47:00Z');
    // Offline, the browser's cache answers with the last copy it fetched, older than the kept one.
    const older = file('2026-01-12T12:42:00Z');
    expect(await give(older, kept)).toBe(kept);
    const newer = file('2026-01-12T12:52:00Z');
    expect(await give(newer, kept)).toBe(newer);
    const same = file('2026-01-12T12:47:00Z');
    expect(await give(same, kept)).toBe(same);
    // Nothing kept: the answer, whatever it is.
    expect(await give(older, undefined)).toBe(older);
    // The host fails: the kept copy, with its own time, rather than no file.
    expect(await give(new Response('', { status: 500 }), kept)).toBe(kept);
    // The page can still read what it is given.
    expect(await (await give(older, kept)).json()).toMatchObject({
      generated_at: '2026-01-12T12:47:00Z',
    });
  });

  it('works from its source text alone, finding the kept copy in the worker’s caches', async () => {
    const held = file('2026-01-12T12:47:00Z');
    const caches = {
      match: (request: Request) => Promise.resolve(request.url === URL_ ? held : undefined),
    };
    // Workbox writes the plugin into sw.js as text, comments stripped.
    const context = { caches, JSON, globalThis: {} };
    context.globalThis = context;
    const rebuilt = runInNewContext(
      `(${keepNewerClosings.cacheWillUpdate.toString()})`,
      context,
    ) as (param: { request: Request; response: Response }) => Promise<Response | null>;
    const request = new Request(URL_);
    expect(await rebuilt({ request, response: file('2026-01-12T12:42:00Z') })).toBeNull();
    expect(await rebuilt({ request, response: file('2026-01-12T12:47:00Z') })).toBeNull();
    expect(await rebuilt({ request, response: file('2026-01-12T12:52:00Z') })).not.toBeNull();
    const respond = runInNewContext(`(${keepNewerClosings.handlerWillRespond.toString()})`, {
      caches,
      JSON,
    }) as (param: { request: Request; response: Response }) => Promise<Response>;
    expect(await respond({ request, response: file('2026-01-12T12:42:00Z') })).toBe(held);
    const newer = file('2026-01-12T12:52:00Z');
    expect(await respond({ request, response: newer })).toBe(newer);
  });
});

describe('pwaOptions', () => {
  it('generates the worker, leaves the manifest and registration to us', () => {
    expect(pwaOptions()).toMatchObject({
      strategies: 'generateSW',
      filename: 'sw.js',
      injectRegister: false,
      registerType: 'prompt',
      manifest: false,
      includeAssets: [],
    });
  });

  it('sets the worker routes for the base Vite resolves', async () => {
    const options = pwaOptions();
    await options.integration?.configureOptions?.({ base: '/snow/' } as ResolvedConfig, options);
    expect(options.workbox).toEqual(workboxOptions('/snow/'));
  });

  it('sets the live route for the live root the build’s variable names, and none without one', async () => {
    const LIVE = 'https://live.snow.test/v1/';
    const named = pwaOptions();
    const env = { [LIVE_ROOT_ENV]: LIVE };
    await named.integration?.configureOptions?.(
      { base: '/', env } as unknown as ResolvedConfig,
      named,
    );
    expect(named.workbox).toEqual(workboxOptions('/', LIVE));
    expect(LIVE_ROOT_ENV).toBe('VITE_SNOWLIGHT_LIVE_ROOT');
    const unset = pwaOptions();
    await unset.integration?.configureOptions?.(
      { base: '/', env: { BASE_URL: '/' } } as unknown as ResolvedConfig,
      unset,
    );
    expect(unset.workbox).toEqual(workboxOptions('/'));
  });

  it('fails the build for a live root set to one the page cannot read from', () => {
    const options = pwaOptions();
    for (const bad of ['https://live.snow.test/v1', 'http://live.snow.test/v1/']) {
      expect(() =>
        options.integration?.configureOptions?.(
          { base: '/', env: { [LIVE_ROOT_ENV]: bad } } as unknown as ResolvedConfig,
          options,
        ),
      ).toThrow(LIVE_ROOT_ENV);
    }
  });
});

describe('pwaHead', () => {
  function tagsFor(base: string): HtmlTagDescriptor[] {
    const links = pwaHead();
    const resolved = links.configResolved;
    const transform = links.transformIndexHtml;
    if (typeof resolved !== 'function' || typeof transform !== 'function') {
      throw new Error('links plugin hooks missing');
    }
    void resolved.call({} as never, { base } as ResolvedConfig);
    return transform.call({} as never, '', {} as never) as HtmlTagDescriptor[];
  }

  it('links the manifest and the home-screen icon under the base, with a black status bar', () => {
    expect(tagsFor('/')).toEqual([
      { tag: 'link', attrs: { rel: 'manifest', href: '/manifest.webmanifest' }, injectTo: 'head' },
      {
        tag: 'link',
        attrs: { rel: 'apple-touch-icon', href: `/${APPLE_TOUCH_ICON}` },
        injectTo: 'head',
      },
      {
        tag: 'meta',
        attrs: { name: 'apple-mobile-web-app-status-bar-style', content: 'black' },
        injectTo: 'head',
      },
    ]);
    expect(tagsFor('/snow/').map((tag) => tag.attrs?.href)).toEqual([
      '/snow/manifest.webmanifest',
      `/snow/${APPLE_TOUCH_ICON}`,
      undefined,
    ]);
  });
});
