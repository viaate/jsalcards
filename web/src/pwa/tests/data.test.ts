import { describe, expect, it, vi } from 'vitest';

import { dataRoot, evictStaticData, onDataUpdate } from '../data';
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
