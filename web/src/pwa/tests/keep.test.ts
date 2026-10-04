import { describe, expect, it } from 'vitest';

import { CACHE_NAMES } from '../config';
import { keepData, keepsWritten } from '../keep';
import { FakeCaches } from './fakes';

const SITE = 'https://snow.test';
const INDEX = `${SITE}/data/search-index.0123456789.bin`;
const META = `${SITE}/data/schools/meta.0123456789.json`;
const CLOSINGS = `${SITE}/data/live/closings.json`;
const EARLY = 'Sun, 04 Oct 2026 12:00:00 GMT';
const LATER = 'Sun, 04 Oct 2026 12:05:00 GMT';

function file(body: string, date = EARLY, status = 200): Response {
  return new Response(body, { status, headers: { date } });
}

/** A file whose download is cut off after its first bytes. */
function cutOff(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"half'));
      controller.error(new TypeError('network error'));
    },
  });
  return new Response(stream, { status: 200, headers: { date: EARLY } });
}

describe('keepData', () => {
  it('puts a file read past the worker into the cache the worker keeps it in', async () => {
    const caches = new FakeCaches();
    await expect(keepData(INDEX, file('index'), '/', { caches })).resolves.toBe(true);
    await expect(keepData(META, file('meta'), '/', { caches })).resolves.toBe(true);
    await expect(keepData(CLOSINGS, file('closings'), '/', { caches })).resolves.toBe(true);
    // The directory and the index are cache-first, live files stale-while-revalidate.
    expect(await caches.text(CACHE_NAMES.staticData, INDEX)).toBe('index');
    expect(await caches.text(CACHE_NAMES.staticData, META)).toBe('meta');
    expect(await caches.text(CACHE_NAMES.data, CLOSINGS)).toBe('closings');
    expect(await caches.text(CACHE_NAMES.data, INDEX)).toBeUndefined();
  });

  it('keeps to the data folder of the site at its base', async () => {
    const caches = new FakeCaches();
    const onPath = `${SITE}/snowlight/data/live/closings.json`;
    await expect(keepData(onPath, file('closings'), '/snowlight/', { caches })).resolves.toBe(true);
    expect(await caches.text(CACHE_NAMES.data, onPath)).toBe('closings');
    await expect(keepData(CLOSINGS, file('closings'), '/snowlight/', { caches })).resolves.toBe(
      false,
    );
  });

  it('keeps nothing the worker would not hold whole', async () => {
    const caches = new FakeCaches();
    const keeps = await Promise.all([
      // The school tiles, read in ranges.
      keepData(`${SITE}/data/schools/schools.0123456789.pmtiles`, file('tiles'), '/', { caches }),
      // Not a data file, not on the site's path, not a 200, not a URL.
      keepData(`${SITE}/assets/index-abc.js`, file('code'), '/', { caches }),
      keepData(`${SITE}/other/data/live/closings.json`, file('x'), '/', { caches }),
      keepData(CLOSINGS, file('', EARLY, 404), '/', { caches }),
      keepData('data/live/closings.json', file('x'), '/', { caches }),
      // No Cache Storage at all, as on an insecure origin.
      keepData(CLOSINGS, file('x'), '/', {}),
    ]);
    expect(keeps).toEqual([false, false, false, false, false, false]);
    expect(caches.stores.size).toBe(0);
  });

  it('never puts back an older copy over one sent later, and replaces an older one', async () => {
    const caches = new FakeCaches();
    // The worker's own copy of the live file, from a read made after it took over.
    await keepData(CLOSINGS, file('newer', LATER), '/', { caches });
    // A read made before the take-over, whose download ended after.
    await expect(keepData(CLOSINGS, file('older', EARLY), '/', { caches })).resolves.toBe(false);
    expect(await caches.text(CACHE_NAMES.data, CLOSINGS)).toBe('newer');
    await expect(keepData(CLOSINGS, file('same', LATER), '/', { caches })).resolves.toBe(false);
    await expect(
      keepData(CLOSINGS, file('newest', 'Sun, 04 Oct 2026 12:10:00 GMT'), '/', { caches }),
    ).resolves.toBe(true);
    expect(await caches.text(CACHE_NAMES.data, CLOSINGS)).toBe('newest');
  });

  it('never puts a live file over a copy the worker put while it downloaded', async () => {
    const caches = new FakeCaches();
    let send!: () => void;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        send = () => {
          controller.enqueue(new TextEncoder().encode('older'));
          controller.close();
        };
      },
    });
    const response = new Response(body, { status: 200, headers: { date: EARLY } });
    const kept = keepData(CLOSINGS, response, '/', { caches });
    await new Promise((resolve) => setTimeout(resolve, 10));
    // The worker took over meanwhile, and a read through it put a copy sent later.
    await (await caches.open(CACHE_NAMES.data)).put(CLOSINGS, file('newer', LATER));
    send();
    await expect(kept).resolves.toBe(false);
    expect(await caches.text(CACHE_NAMES.data, CLOSINGS)).toBe('newer');
  });

  it('writes the keeps of one file in the order they were asked for', async () => {
    const caches = new FakeCaches();
    const first = keepData(CLOSINGS, file('first', EARLY), '/', { caches });
    const second = keepData(CLOSINGS, file('second', LATER), '/', { caches });
    expect(await Promise.all([first, second])).toEqual([true, true]);
    expect(await caches.text(CACHE_NAMES.data, CLOSINGS)).toBe('second');
  });

  it('keeps nothing of a download cut off, and keeps the next read whole', async () => {
    const caches = new FakeCaches();
    await expect(keepData(META, cutOff(), '/', { caches })).resolves.toBe(false);
    expect(await caches.text(CACHE_NAMES.staticData, META)).toBeUndefined();
    await expect(keepData(META, file('meta'), '/', { caches })).resolves.toBe(true);
    expect(await caches.text(CACHE_NAMES.staticData, META)).toBe('meta');
  });

  it('never rejects when the cache cannot take the file, and the next read is kept', async () => {
    const caches = new FakeCaches();
    caches.failPut = true;
    await expect(keepData(INDEX, file('index'), '/', { caches })).resolves.toBe(false);
    caches.failPut = false;
    await expect(keepData(INDEX, file('index'), '/', { caches })).resolves.toBe(true);
    expect(await caches.text(CACHE_NAMES.staticData, INDEX)).toBe('index');
  });
});

describe('keepsWritten', () => {
  it('waits for the keeps on their way, of the files named or of all', async () => {
    const caches = new FakeCaches();
    let send!: () => void;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        send = () => {
          controller.enqueue(new TextEncoder().encode('meta'));
          controller.close();
        };
      },
    });
    const kept = keepData(META, new Response(body, { status: 200 }), '/', { caches });
    let written = false;
    void keepsWritten([META]).then(() => {
      written = true;
    });
    await expect(keepsWritten([INDEX])).resolves.toBeUndefined();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(written).toBe(false);
    send();
    await keepsWritten();
    expect(written).toBe(true);
    await expect(kept).resolves.toBe(true);
  });
});
