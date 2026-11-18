// @vitest-environment node
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CACHE_LIMITS,
  CACHE_NAMES,
  KEPT_HEADER,
  LIVE_FALLBACK_ENV,
  LIVE_LOOPBACK_ENV,
  LIVE_ROOT_ENV,
  LIVE_TIMEOUT_SECONDS,
  checkedLiveFallback,
  keepNewerClosings,
  markKept,
  routeFor,
  routePatterns,
  workboxOptions,
} from '../config';
import { keepData } from '../keep';
import { FakeCaches } from './fakes';

/** The second live root: the same files on the site's own domain (status/shared/live-proxy.ts). */
const LIVE = 'https://live.snow.test/v1/';
const SECOND = 'https://status.snow.test/live/v1/';

describe('a second live root', () => {
  it('is read from its own variable, only beside a first root, and never the first itself', () => {
    expect(LIVE_FALLBACK_ENV).toBe('VITE_SNOWLIGHT_LIVE_FALLBACK');
    expect(checkedLiveFallback(undefined)).toBeNull();
    expect(checkedLiveFallback({ [LIVE_ROOT_ENV]: LIVE })).toBeNull();
    expect(checkedLiveFallback({ [LIVE_ROOT_ENV]: LIVE, [LIVE_FALLBACK_ENV]: '' })).toBeNull();
    // Without a first root it is no root at all: the page reads its own data/.
    expect(checkedLiveFallback({ [LIVE_FALLBACK_ENV]: SECOND })).toBeNull();
    expect(checkedLiveFallback({ [LIVE_ROOT_ENV]: LIVE, [LIVE_FALLBACK_ENV]: SECOND })).toBe(
      SECOND,
    );
    for (const bad of [
      LIVE,
      'https://status.snow.test/live/v1',
      'http://status.snow.test/live/v1/',
      'https://status.snow.test/live/v1/?k=1',
      'http://127.0.0.1:4180/live/v1/',
    ]) {
      expect(() =>
        checkedLiveFallback({ [LIVE_ROOT_ENV]: LIVE, [LIVE_FALLBACK_ENV]: bad }),
      ).toThrow(LIVE_FALLBACK_ENV);
    }
    const local = 'http://127.0.0.1:4180/live/v1/';
    expect(
      checkedLiveFallback({
        [LIVE_ROOT_ENV]: LIVE,
        [LIVE_FALLBACK_ENV]: local,
        [LIVE_LOOPBACK_ENV]: '1',
      }),
    ).toBe(local);
  });

  it('routes the closings file at either root network-first, and nothing else there', () => {
    for (const root of [LIVE, SECOND]) {
      expect(
        routeFor(`${root}live/closings.json`, '/', { liveRoot: LIVE, liveFallback: SECOND }),
      ).toBe('live');
      expect(
        routeFor(`${root}live/closings.json?b=1`, '/', { liveRoot: LIVE, liveFallback: SECOND }),
      ).toBe('live');
      for (const other of [
        `${root}live/closings.json.bak`,
        `${root}predictions/latest.json`,
        `${root}live/season.json`,
      ]) {
        expect(routeFor(other, '/', { liveRoot: LIVE, liveFallback: SECOND })).toBeNull();
      }
    }
    expect(
      routeFor('https://evil.example/https://status.snow.test/live/v1/live/closings.json', '/', {
        liveRoot: LIVE,
        liveFallback: SECOND,
      }),
    ).toBeNull();
    // Without the second root its file has no route; without a first, neither has one.
    expect(routeFor(`${SECOND}live/closings.json`, '/', { liveRoot: LIVE })).toBeNull();
    expect(routePatterns('/', null, SECOND).live).toBeNull();
    // With one root, the route is the one it was.
    expect(routePatterns('/', LIVE, null).live).toEqual(routePatterns('/', LIVE).live);
    expect(routePatterns('/', LIVE, '').live).toEqual(routePatterns('/', LIVE).live);
  });

  it('builds the same worker as before without it', () => {
    expect(workboxOptions('/', LIVE, null)).toEqual(workboxOptions('/', LIVE));
    expect(workboxOptions('/', LIVE, '')).toEqual(workboxOptions('/', LIVE));
    expect(workboxOptions('/', null, SECOND)).toEqual(workboxOptions('/'));
  });

  it('serves both roots in the one live route, same cache and wait, and marks a kept copy', () => {
    const one = workboxOptions('/', LIVE).runtimeCaching ?? [];
    const two = workboxOptions('/', LIVE, SECOND).runtimeCaching ?? [];
    expect(two.length).toBe(one.length);
    expect(two[1]).toEqual({
      urlPattern: routePatterns('/', LIVE, SECOND).live,
      handler: 'NetworkFirst',
      options: {
        cacheName: CACHE_NAMES.data,
        networkTimeoutSeconds: LIVE_TIMEOUT_SECONDS,
        expiration: { ...CACHE_LIMITS.data, purgeOnQuotaError: true },
        cacheableResponse: { statuses: [200] },
        plugins: [keepNewerClosings, markKept],
      },
    });
    expect([two[0], ...two.slice(2)]).toEqual([one[0], ...one.slice(2)]);
  });
});

describe('markKept', () => {
  const kept = (): Response =>
    new Response('{"generated_at":"2026-01-12T12:42:00Z"}', {
      status: 200,
      statusText: 'OK',
      headers: { 'content-type': 'application/json; charset=utf-8', etag: '"a"' },
    });

  it('marks the copy the worker gives in place of an answer, and nothing else of it', async () => {
    const marked = await markKept.cachedResponseWillBeUsed({ cachedResponse: kept() });
    expect(marked?.status).toBe(200);
    expect(marked?.headers.get(KEPT_HEADER)).toBe('1');
    expect(marked?.headers.get('content-type')).toBe('application/json; charset=utf-8');
    expect(marked?.headers.get('etag')).toBe('"a"');
    expect(await marked?.text()).toBe(await kept().text());
    expect(await markKept.cachedResponseWillBeUsed({})).toBeNull();
  });

  it('works from its source alone, as sw.js holds it, with the header written out', async () => {
    const rebuilt = runInNewContext(`(${markKept.cachedResponseWillBeUsed.toString()})`, {
      Headers,
      Response,
      Promise,
    }) as typeof markKept.cachedResponseWillBeUsed;
    const marked = await rebuilt({ cachedResponse: kept() });
    expect(marked?.headers.get(KEPT_HEADER)).toBe('1');
    expect(KEPT_HEADER).toBe('x-snowlight-kept');
  });
});

describe('keepData with a second live root', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', LIVE);
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_FALLBACK', SECOND);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });
  const live = (generatedAt: string): Response =>
    new Response(JSON.stringify({ schema_version: 1, generated_at: generatedAt, days: [] }));

  it('keeps the closings file read from the second root under its own URL, newer only', async () => {
    const caches = new FakeCaches();
    const url = `${SECOND}live/closings.json`;
    await expect(
      keepData(url, live('2026-01-12T12:47:00Z'), '/', { caches }, LIVE, SECOND),
    ).resolves.toBe(true);
    await expect(
      keepData(url, live('2026-01-12T12:42:00Z'), '/', { caches }, LIVE, SECOND),
    ).resolves.toBe(false);
    expect(await caches.text(CACHE_NAMES.data, url)).toContain('2026-01-12T12:47:00Z');
    expect(await caches.text(CACHE_NAMES.data, `${LIVE}live/closings.json`)).toBeUndefined();
    // Nothing else from there, and nothing at all without the second root.
    await expect(
      keepData(`${SECOND}live/season.json`, live('x'), '/', { caches }, LIVE, SECOND),
    ).resolves.toBe(false);
    await expect(
      keepData(url, live('2026-01-12T12:52:00Z'), '/', { caches }, LIVE, null),
    ).resolves.toBe(false);
  });
});

describe('the site build', () => {
  // The status host serves the owner's live root alone (status/shared/live-proxy.ts
  // LIVE_UPSTREAM): a build whose first root is another, by the repository variable, gets no
  // second root unless one is named for it too.
  it('names the status host as the second root, only beside the default first root', () => {
    const preview = readFileSync(
      new URL('../../../../.github/workflows/preview.yml', import.meta.url),
      'utf8',
    );
    expect(preview.match(/VITE_SNOWLIGHT_LIVE_FALLBACK:.*$/gm)).toEqual([
      "VITE_SNOWLIGHT_LIVE_FALLBACK: ${{ vars.SNOWLIGHT_LIVE_FALLBACK || ((vars.SNOWLIGHT_LIVE_ROOT == '' || vars.SNOWLIGHT_LIVE_ROOT == 'https://viaate.github.io/snowlight-live/v1/') && 'https://status.snowlightmap.com/live/v1/' || '') }}",
    ]);
  });
});
