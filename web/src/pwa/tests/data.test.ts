import { describe, expect, it, vi } from 'vitest';

import { dataRoot, dropOldData, evictStaticData, onDataUpdate } from '../data';
import { CACHE_NAMES } from '../config';
import { keepData } from '../keep';
import { FakeCaches, FakeWindow } from './fakes';

const CLOSINGS = 'https://snow.test/data/live/closings.json';

function update(cacheName: string, updatedURL: string) {
  return {
    type: 'CACHE_UPDATED',
    meta: 'workbox-broadcast-update',
    payload: { cacheName, updatedURL },
  };
}

describe('dataRoot', () => {
  it('resolves the data folder under the base', () => {
    const win = new FakeWindow();
    expect(dataRoot('/', win)).toBe('https://snow.test/data/');
    expect(dataRoot('/snowlight/', win)).toBe('https://snow.test/snowlight/data/');
  });
});

describe('onDataUpdate', () => {
  it('passes on updates to live data only', () => {
    const win = new FakeWindow();
    const listener = vi.fn();
    const stop = onDataUpdate(listener, win);
    win.container.message(update(CACHE_NAMES.data, CLOSINGS));
    win.container.message(update(CACHE_NAMES.tiles, 'https://tiles.openfreemap.org/planet/1/2/3'));
    win.container.message({ type: 'SKIP_WAITING' });
    win.container.message('noise');
    expect(listener.mock.calls).toEqual([[CLOSINGS]]);
    stop();
    win.container.message(update(CACHE_NAMES.data, CLOSINGS));
    expect(listener).toHaveBeenCalledOnce();
  });

  it('does nothing without service worker support', () => {
    const stop = onDataUpdate(vi.fn(), new FakeWindow({ serviceWorker: false }));
    expect(stop).not.toThrow();
  });
});

describe('evictStaticData', () => {
  class FakeCache {
    readonly deleted: string[] = [];
    constructor(readonly entries: string[]) {}
    keys(): Promise<Request[]> {
      return Promise.resolve(this.entries.map((url) => new Request(url)));
    }
    delete(request: string | Request): Promise<boolean> {
      this.deleted.push(typeof request === 'string' ? request : request.url);
      return Promise.resolve(true);
    }
  }

  function withCaches(win: FakeWindow, cache: FakeCache | null) {
    return Object.assign(win, {
      caches: {
        has: (name: string) => Promise.resolve(cache !== null && name === CACHE_NAMES.staticData),
        open: (name: string) => {
          if (name !== CACHE_NAMES.staticData || cache === null) throw new Error(name);
          return Promise.resolve(cache as unknown as Cache);
        },
      },
    });
  }

  it('drops the named files, or all of them', async () => {
    const cache = new FakeCache([
      'https://snow.test/data/schools/meta.json',
      'https://snow.test/data/search-index.bin',
    ]);
    const win = withCaches(new FakeWindow(), cache);
    await evictStaticData(['/data/schools/meta.json'], win);
    expect(cache.deleted).toEqual(['https://snow.test/data/schools/meta.json']);
    await evictStaticData(undefined, win);
    expect(cache.deleted).toHaveLength(3);
  });

  it('drops a copy on its way into the cache once it is in, so none is put back after', async () => {
    const caches = new FakeCaches();
    const win = Object.assign(new FakeWindow(), { caches });
    const meta = 'https://snow.test/data/schools/meta.json';
    let send!: () => void;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        send = () => {
          controller.enqueue(new TextEncoder().encode('{}'));
          controller.close();
        };
      },
    });
    // The page read the directory before the worker took over; its copy is still being written.
    const kept = keepData(meta, new Response(body, { status: 200 }), '/', { caches });
    const evicted = evictStaticData([meta], win);
    send();
    await Promise.all([kept, evicted]);
    expect(await caches.text(CACHE_NAMES.staticData, meta)).toBeUndefined();
  });

  it('does nothing before the cache exists or without Cache Storage', async () => {
    await expect(evictStaticData(undefined, withCaches(new FakeWindow(), null))).resolves.toBe(
      undefined,
    );
    await expect(evictStaticData(undefined, new FakeWindow())).resolves.toBe(undefined);
  });
});

describe('dropOldData', () => {
  const ROOT = 'https://snow.test/data/';
  /** This build's files, as published: two hashed, one shard index, one live file. */
  const SHIPS = [
    'live/closings.json',
    'schools/details/index.1111111111.json',
    'schools/meta.bbbbbbbbbb.json',
    'search-index.bbbbbbbbbb.bin',
  ];

  async function holding(entries: Record<string, readonly string[]>): Promise<FakeCaches> {
    const caches = new FakeCaches();
    for (const [name, urls] of Object.entries(entries)) {
      const cache = await caches.open(name);
      for (const url of urls) await cache.put(url, new Response(url));
    }
    return caches;
  }

  function left(caches: FakeCaches): Record<string, string[]> {
    return Object.fromEntries(
      [...caches.stores].map(([name, store]) => [name, [...store.keys()].sort()]),
    );
  }

  it('drops the copies of hashed files this build no longer ships, and nothing else', async () => {
    const caches = await holding({
      [CACHE_NAMES.staticData]: [
        `${ROOT}search-index.aaaaaaaaaa.bin`,
        `${ROOT}search-index.bbbbbbbbbb.bin`,
        `${ROOT}schools/meta.aaaaaaaaaa.json`,
        `${ROOT}schools/meta.bbbbbbbbbb.json`,
        // A plain name is replaced where it is: never a second copy.
        `${ROOT}schools/meta.json`,
        // Not this site's data.
        'https://snow.test/elsewhere/meta.aaaaaaaaaa.json',
      ],
      [CACHE_NAMES.data]: [`${ROOT}live/closings.json`, `${ROOT}live/gone.aaaaaaaaaa.json`],
      [CACHE_NAMES.tiles]: ['https://tiles.openfreemap.org/planet/aaaaaaaaaa.pbf'],
    });
    const win = Object.assign(new FakeWindow(), { caches });
    await expect(dropOldData(SHIPS, '/', win)).resolves.toBe(3);
    expect(left(caches)).toEqual({
      [CACHE_NAMES.staticData]: [
        `${ROOT}schools/meta.bbbbbbbbbb.json`,
        `${ROOT}schools/meta.json`,
        `${ROOT}search-index.bbbbbbbbbb.bin`,
        'https://snow.test/elsewhere/meta.aaaaaaaaaa.json',
      ],
      [CACHE_NAMES.data]: [`${ROOT}live/closings.json`],
      [CACHE_NAMES.tiles]: ['https://tiles.openfreemap.org/planet/aaaaaaaaaa.pbf'],
    });
  });

  it('keeps the detail shards a kept copy of this build’s shard index names, and drops the rest', async () => {
    const index = `${ROOT}schools/details/index.1111111111.json`;
    const caches = await holding({
      [CACHE_NAMES.staticData]: [
        `${ROOT}schools/details/0.aaaaaaaaaa.json`,
        `${ROOT}schools/details/1.cccccccccc.json`,
        `${ROOT}schools/details/2.dddddddddd.json`,
        `${ROOT}schools/details/index.2222222222.json`,
      ],
    });
    const cache = await caches.open(CACHE_NAMES.staticData);
    await cache.put(
      index,
      new Response(JSON.stringify({ files: ['0.aaaaaaaaaa.json', '1.bbbbbbbbbb.json', '../x'] })),
    );
    const win = Object.assign(new FakeWindow(), { caches });
    await expect(dropOldData(SHIPS, '/', win)).resolves.toBe(3);
    expect(left(caches)).toEqual({
      [CACHE_NAMES.staticData]: [`${ROOT}schools/details/0.aaaaaaaaaa.json`, index],
    });
  });

  it('keeps the area shards a kept copy of this build’s area index names, beside the detail shards', async () => {
    const details = `${ROOT}schools/details/index.1111111111.json`;
    const areas = `${ROOT}schools/areas/index.3333333333.json`;
    const caches = await holding({
      [CACHE_NAMES.staticData]: [
        `${ROOT}schools/details/0.aaaaaaaaaa.json`,
        `${ROOT}schools/areas/0.aaaaaaaaaa.json`,
        `${ROOT}schools/areas/1.eeeeeeeeee.json`,
      ],
    });
    const cache = await caches.open(CACHE_NAMES.staticData);
    await cache.put(details, new Response(JSON.stringify({ files: ['0.aaaaaaaaaa.json'] })));
    await cache.put(areas, new Response(JSON.stringify({ files: ['0.aaaaaaaaaa.json'] })));
    const win = Object.assign(new FakeWindow(), { caches });
    await expect(
      dropOldData([...SHIPS, 'schools/areas/index.3333333333.json'], '/', win),
    ).resolves.toBe(1);
    expect(left(caches)).toEqual({
      [CACHE_NAMES.staticData]: [
        `${ROOT}schools/areas/0.aaaaaaaaaa.json`,
        areas,
        `${ROOT}schools/details/0.aaaaaaaaaa.json`,
        details,
      ],
    });
  });

  it('drops every hashed shard when no copy of this build’s shard index is kept, or it names none', async () => {
    const shards = [`${ROOT}schools/details/0.aaaaaaaaaa.json`, `${ROOT}schools/details/1.json`];
    const none = await holding({ [CACHE_NAMES.staticData]: shards });
    await expect(
      dropOldData(SHIPS, '/', Object.assign(new FakeWindow(), { caches: none })),
    ).resolves.toBe(1);
    expect(left(none)).toEqual({
      [CACHE_NAMES.staticData]: [`${ROOT}schools/details/1.json`],
    });
    const broken = await holding({ [CACHE_NAMES.staticData]: shards });
    await (
      await broken.open(CACHE_NAMES.staticData)
    ).put(
      `${ROOT}schools/details/index.1111111111.json`,
      new Response('{"files": "0.aaaaaaaaaa.json"'),
    );
    await expect(
      dropOldData(SHIPS, '/', Object.assign(new FakeWindow(), { caches: broken })),
    ).resolves.toBe(1);
  });

  it('reads the data folder under the site’s base', async () => {
    const caches = await holding({
      [CACHE_NAMES.staticData]: [
        'https://snow.test/snowlight/data/search-index.aaaaaaaaaa.bin',
        `${ROOT}search-index.aaaaaaaaaa.bin`,
      ],
    });
    const win = Object.assign(new FakeWindow(), { caches });
    await expect(dropOldData(SHIPS, '/snowlight/', win)).resolves.toBe(1);
    expect(left(caches)).toEqual({
      [CACHE_NAMES.staticData]: [`${ROOT}search-index.aaaaaaaaaa.bin`],
    });
  });

  it('opens no cache that is not there, and never rejects', async () => {
    const caches = new FakeCaches();
    await expect(
      dropOldData(SHIPS, '/', Object.assign(new FakeWindow(), { caches })),
    ).resolves.toBe(0);
    expect(caches.stores.size).toBe(0);
    await expect(dropOldData(SHIPS, '/', new FakeWindow())).resolves.toBe(0);
    const refusing = {
      has: () => Promise.resolve(true),
      open: () => Promise.reject(new DOMException('The operation is insecure.', 'SecurityError')),
    };
    await expect(
      dropOldData(SHIPS, '/', Object.assign(new FakeWindow(), { caches: refusing })),
    ).resolves.toBe(0);
  });
});
