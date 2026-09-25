// @vitest-environment node
import { runInNewContext } from 'node:vm';

import type { HtmlTagDescriptor, ResolvedConfig } from 'vite';
import { describe, expect, it } from 'vitest';

import {
  APPLE_TOUCH_ICON,
  CACHE_LIMITS,
  CACHE_NAMES,
  isRangeRequest,
  pwaHead,
  pwaOptions,
  routePatterns,
  workboxOptions,
} from '../config';

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
