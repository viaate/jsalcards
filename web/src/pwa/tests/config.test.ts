// @vitest-environment node
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { PUBLISHED_PATHS } from '../../types/generated';
import {
  CACHE_LIMITS,
  CACHE_NAMES,
  DATA_DIR,
  PRECACHE_GLOBS,
  RANGE_SERVED_EXTENSIONS,
  TILE_ORIGIN,
  isCacheUpdatedMessage,
  isRangeServed,
  normalizeBase,
  routeFor,
  routePatterns,
} from '../config';

const SITE = 'https://snowlight.example';

describe('routeFor', () => {
  it.each([
    ['/data/live/closings.json', 'data'],
    ['/data/live/covered.json', 'data'],
    ['/data/live/alerts.json?t=1', 'data'],
    ['/data/predictions/latest.json', 'data'],
    ['/data/stats/season.json', 'data'],
    ['/data/track-record.json', 'data'],
    ['/data/replays/index.json', 'data'],
    ['/data/replays/2026-01-12.json', 'staticData'],
    ['/data/replays/2026-01-12-b.json', 'staticData'],
    ['/data/schools/meta.json', 'staticData'],
    ['/data/schools/points.bin', 'staticData'],
    ['/data/search-index.bin', 'staticData'],
    ['/data/search/index.3f2a.bin', 'staticData'],
    ['/data/searchable.json', 'data'],
    ['/assets/geist-cyrillic-wght-normal-X_5orZeX.woff2', 'assets'],
    ['/assets/index-h0gZq8Cr.js', 'assets'],
    ['/assets/index-h0gZq8Cr.js.map', null],
    ['/index.html', null],
    ['/sw.js', null],
    ['/manifest.webmanifest', null],
    ['/icons/icon-192.png', null],
    ['/other/data/live/closings.json', null],
    ['/datalive/closings.json', null],
    // Range-served: no route, so the browser asks the server for exactly the bytes it needs.
    ['/data/schools/schools.pmtiles', null],
    ['/data/schools/schools.pmtiles?v=2', null],
    ['/data/schools/schools.pmtiles#x', null],
    ['/data/replays/2026-01-12.pmtiles', null],
    ['/data/overlay.pmtiles', null],
    ['/data/schools/schools.pmtiles.json', 'staticData'],
    ['/data/schools/pmtiles.json', 'staticData'],
    ['/data/live/closings.json?f=a.pmtiles', 'data'],
  ])('%s → %s', (path, route) => {
    expect(routeFor(`${SITE}${path}`, '/')).toBe(route);
  });

  it('sends every request for part of a file to the range route, whatever the file', () => {
    for (const path of [
      '/data/schools/schools.pmtiles',
      '/data/schools/meta.json',
      '/data/live/closings.json',
      '/assets/index-h0gZq8Cr.js',
    ]) {
      expect([path, routeFor(`${SITE}${path}`, '/', { range: true })]).toEqual([path, 'range']);
    }
    expect(routeFor(`${TILE_ORIGIN}/planet/x/7/32/45.pbf`, '/', { range: true })).toBe('range');
    expect(routeFor(`${SITE}/data/schools/meta.json`, '/', { range: false })).toBe('staticData');
  });

  it('sends every published file to the right cache', () => {
    const expected: Record<keyof typeof PUBLISHED_PATHS, string> = {
      alerts: 'data',
      closings: 'data',
      covered: 'data',
      predictions: 'data',
      replayIndex: 'data',
      replay: 'staticData',
      schoolDirectory: 'staticData',
      seasonStats: 'data',
      trackRecord: 'data',
    };
    for (const [key, path] of Object.entries(PUBLISHED_PATHS)) {
      const url = `${SITE}/${DATA_DIR}${path.replace('{id}', '2026-01-12')}`;
      expect([key, routeFor(url, '/')]).toEqual([key, expected[key as keyof typeof expected]]);
    }
  });

  it('caches none of the files the registry publishes for range reads, and the rest cache-first', () => {
    // The published files that are not JSON documents, from the pipeline's registry.
    const registry = readFileSync(
      new URL('../../../../pipeline/snowlight/schemas/registry.py', import.meta.url),
      'utf8',
    );
    const block = /OTHER_PUBLISHED_FILES[^=]*=\s*\(([^)]*)\)/.exec(registry)?.[1] ?? '';
    const files = [...block.matchAll(/"([^"]+)"/g)].map((match) => match[1] ?? '');
    expect(files).toContain('schools/schools.pmtiles');
    for (const file of files) {
      const url = `${SITE}/${DATA_DIR}${file}`;
      expect([file, routeFor(url, '/')]).toEqual([file, isRangeServed(url) ? null : 'staticData']);
    }
  });

  it('follows the site base', () => {
    expect(routeFor(`${SITE}/snowlight/data/live/closings.json`, '/snowlight/')).toBe('data');
    expect(routeFor(`${SITE}/data/live/closings.json`, '/snowlight/')).toBeNull();
    expect(routeFor(`${SITE}/snowlight/data/schools/meta.json`, 'snowlight')).toBe('staticData');
  });

  it('keeps OpenFreeMap tiles and the TileJSON apart', () => {
    expect(routeFor(`${TILE_ORIGIN}/planet`, '/')).toBe('tileJson');
    expect(routeFor(`${TILE_ORIGIN}/planet/20260101_001001_pt/7/32/45.pbf`, '/')).toBe('tiles');
    expect(routeFor(`${TILE_ORIGIN}/fonts/Noto%20Sans/0-255.pbf`, '/')).toBe('tiles');
    expect(routeFor('https://evil.example/https://tiles.openfreemap.org/planet', '/')).toBeNull();
    expect(routeFor('http://tiles.openfreemap.org/planet/1/2/3.pbf', '/')).toBeNull();
  });

  it('uses the host the basemap uses', () => {
    const source = readFileSync(
      new URL('../../map/basemap/openfreemap.ts', import.meta.url),
      'utf8',
    );
    const tilejson = /TILEJSON_URL = '([^']+)'/.exec(source)?.[1];
    expect(tilejson).toBeDefined();
    expect(new URL(tilejson ?? '').origin).toBe(TILE_ORIGIN);
    expect(routeFor(tilejson ?? '', '/')).toBe('tileJson');
  });
});

describe('navigation', () => {
  it('serves the app shell for the page and its share links only', () => {
    const { navigation } = routePatterns('/');
    for (const path of ['/', '/index.html', '/?school=010000500870&at=40,-90,6', '/?']) {
      expect([path, navigation.test(path)]).toEqual([path, true]);
    }
    for (const path of ['/about', '/data/live/closings.json', '/index.htm', '//x', '/sw.js']) {
      expect([path, navigation.test(path)]).toEqual([path, false]);
    }
  });

  it('follows the site base', () => {
    const { navigation } = routePatterns('/snowlight/');
    expect(navigation.test('/snowlight/?zip=02139')).toBe(true);
    expect(navigation.test('/?zip=02139')).toBe(false);
  });
});

describe('isRangeServed', () => {
  it.each([
    ['/data/schools/schools.pmtiles', true],
    [`${SITE}/data/schools/schools.pmtiles`, true],
    [`${SITE}/jsalcards/data/schools/schools.pmtiles?v=1`, true],
    ['schools.pmtiles', true],
    [`${SITE}/data/schools/schools.pmtiles.json`, false],
    [`${SITE}/data/schools/points.bin`, false],
    [`${SITE}/data/live/closings.json?x=.pmtiles`, false],
    [`${SITE}/data/live/closings.json#a.pmtiles`, false],
  ])('%s → %s', (url, expected) => {
    expect(isRangeServed(url)).toBe(expected);
  });

  it('lists plain extensions only', () => {
    for (const extension of RANGE_SERVED_EXTENSIONS) expect(extension).toMatch(/^[a-z\d]+$/);
  });
});

describe('normalizeBase', () => {
  it.each([
    ['/', '/'],
    ['', '/'],
    ['snow', '/snow/'],
    ['/snow', '/snow/'],
    ['/a/b/', '/a/b/'],
  ])('%j → %j', (base, normal) => {
    expect(normalizeBase(base)).toBe(normal);
  });
});

describe('limits', () => {
  it('keeps the tile cache small and bounded', () => {
    // About 5 MB at the 146 KB OpenFreeMap tiles averaged when measured.
    expect(CACHE_LIMITS.tiles.maxEntries).toBeLessThanOrEqual(32);
    expect(CACHE_LIMITS.tiles.maxAgeSeconds).toBeGreaterThan(0);
    expect(CACHE_LIMITS.staticData.maxAgeSeconds).toBeGreaterThan(0);
  });

  it('gives every cache its own versioned name', () => {
    const names = Object.values(CACHE_NAMES);
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) expect(name).toMatch(/^snowlight-[a-z-]+-v\d+$/);
  });

  it('never precaches data, source maps or icons', () => {
    for (const glob of PRECACHE_GLOBS) {
      expect(glob).not.toMatch(/data|\.map|icons|\*\*/);
    }
  });
});

describe('isCacheUpdatedMessage', () => {
  const message = {
    type: 'CACHE_UPDATED',
    meta: 'workbox-broadcast-update',
    payload: { cacheName: CACHE_NAMES.data, updatedURL: `${SITE}/data/live/closings.json` },
  };

  it('recognizes Workbox broadcast updates', () => {
    expect(isCacheUpdatedMessage(message)).toBe(true);
  });

  it.each([
    null,
    'CACHE_UPDATED',
    { ...message, type: 'SKIP_WAITING' },
    { ...message, meta: 'other' },
    { ...message, payload: null },
    { ...message, payload: { cacheName: 1, updatedURL: 'x' } },
  ])('rejects %j', (data) => {
    expect(isCacheUpdatedMessage(data)).toBe(false);
  });
});
