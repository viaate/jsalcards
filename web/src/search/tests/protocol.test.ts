// @vitest-environment node
import { gzipSync } from 'node:zlib';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { encodeIndex } from '../encode';
import { fetchIndex, serve } from '../server';
import type { IndexFetcher, LoadedBytes } from '../server';
import type { WorkerResponse } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

const INDEX = encodeIndex(SYNTHETIC_RECORDS).bytes;

function loaded(bytes: Uint8Array = INDEX): LoadedBytes {
  return { bytes, transferred: bytes.length, phases: { download: 1 } };
}

/** A worker-side endpoint on one end of a channel; the test talks through the other. */
function harness(fetcher: IndexFetcher) {
  const channel = new MessageChannel();
  serve(channel.port2, fetcher);
  channel.port2.start();
  const received: WorkerResponse[] = [];
  let wake: (() => void) | null = null;
  channel.port1.addEventListener('message', (event: MessageEvent<WorkerResponse>) => {
    received.push(event.data);
    wake?.();
  });
  channel.port1.start();
  /** Sends anything, so malformed messages can be tried. */
  const send = (message: unknown): void => {
    channel.port1.postMessage(message);
  };
  /** Resolves once `count` responses have arrived. */
  const until = async (count: number): Promise<WorkerResponse[]> => {
    while (received.length < count) {
      await new Promise<void>((resolve) => {
        wake = resolve;
      });
    }
    return received;
  };
  const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
  const close = (): void => {
    channel.port1.close();
    channel.port2.close();
  };
  return { send, until, received, settle, close };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  // The code under test attaches its own handler later; this keeps a
  // rejection made before then from counting as unhandled.
  promise.catch(() => undefined);
  return { promise, resolve, reject };
}

describe('worker protocol', () => {
  it('loads, reports, then answers', async () => {
    const h = harness(() => Promise.resolve(loaded()));
    h.send({ type: 'load', url: 'test://index' });
    const [ready] = await h.until(1);
    expect(ready?.type).toBe('ready');
    if (ready?.type !== 'ready') throw new Error('expected ready');
    expect(ready.info.records).toBe(SYNTHETIC_RECORDS.length);
    expect(ready.info.tokens).toBeGreaterThan(0);
    expect(ready.info.bytes).toBe(INDEX.length);
    expect(ready.info.phases).toHaveProperty('tokenize');
    expect(ready.info.phases).toHaveProperty('download');

    h.send({ type: 'query', id: 7, q: 'lancaster pa', limit: 5 });
    const [, result] = await h.until(2);
    expect(result?.type).toBe('result');
    if (result?.type !== 'result') throw new Error('expected result');
    expect(result.id).toBe(7);
    expect(result.ms).toBeGreaterThanOrEqual(0);
    expect(result.results.cities[0]?.name).toBe('Lancaster');
    expect(result.results.schools[0]?.name).toBe('School District of Lancaster');
    expect(result.results.schools[0]?.highlight).toEqual([[19, 28]]);
    h.close();
  });

  it('answers queries sent before the index is ready, in order', async () => {
    const gate = deferred<LoadedBytes>();
    const h = harness(() => gate.promise);
    h.send({ type: 'load', url: 'x' });
    h.send({ type: 'query', id: 1, q: 'lancaster', limit: 5 });
    h.send({ type: 'query', id: 2, q: '176', limit: 5 });
    await h.settle();
    expect(h.received).toEqual([]);
    gate.resolve(loaded());
    const out = await h.until(3);
    expect(out.map((m) => m.type)).toEqual(['ready', 'result', 'result']);
    expect(out.map((m) => ('id' in m ? m.id : null))).toEqual([null, 1, 2]);
    h.close();
  });

  it('cancels a waiting query', async () => {
    const gate = deferred<LoadedBytes>();
    const h = harness(() => gate.promise);
    h.send({ type: 'load', url: 'x' });
    h.send({ type: 'query', id: 1, q: 'lancaster', limit: 5 });
    h.send({ type: 'query', id: 2, q: 'springfield', limit: 5 });
    h.send({ type: 'cancel', id: 1 });
    const [cancelled] = await h.until(1);
    expect(cancelled).toEqual({ type: 'cancelled', id: 1 });
    gate.resolve(loaded());
    const out = await h.until(3);
    expect(out.slice(1).map((m) => [m.type, 'id' in m ? m.id : null])).toEqual([
      ['ready', null],
      ['result', 2],
    ]);
    h.close();
  });

  it('ignores a cancel for a query it already answered', async () => {
    const h = harness(() => Promise.resolve(loaded()));
    h.send({ type: 'load', url: 'x' });
    await h.until(1);
    h.send({ type: 'query', id: 3, q: 'lancaster', limit: 5 });
    await h.until(2);
    h.send({ type: 'cancel', id: 3 });
    h.send({ type: 'cancel', id: 999 });
    await h.settle();
    expect(h.received).toHaveLength(2);
    h.close();
  });

  it.each([
    null,
    'hello',
    42,
    { type: 'query' },
    { type: 'query', id: '1', q: 'a', limit: 5 },
    { type: 'query', id: 1, q: 5, limit: 5 },
    { type: 'load' },
    { type: 'drop-table' },
  ])('ignores the malformed message %j', async (message) => {
    const h = harness(() => Promise.resolve(loaded()));
    h.send(message);
    await h.settle();
    expect(h.received).toEqual([]);
    h.close();
  });

  it('loads only once', async () => {
    const fetcher = vi.fn(() => Promise.resolve(loaded()));
    const h = harness(fetcher);
    h.send({ type: 'load', url: 'a' });
    h.send({ type: 'load', url: 'b' });
    await h.until(1);
    await h.settle();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(h.received).toHaveLength(1);
    h.close();
  });

  it('reports a failed load to the page and to every waiting query', async () => {
    const h = harness(() => Promise.reject(new Error('index request failed with HTTP 404')));
    h.send({ type: 'query', id: 1, q: 'a', limit: 5 });
    h.send({ type: 'load', url: 'x' });
    const out = await h.until(2);
    expect(out[0]).toEqual({ type: 'load-error', message: 'index request failed with HTTP 404' });
    expect(out[1]).toMatchObject({ type: 'query-error', id: 1 });
    h.send({ type: 'query', id: 2, q: 'b', limit: 5 });
    const later = await h.until(3);
    expect(later[2]).toMatchObject({ type: 'query-error', id: 2 });
    h.close();
  });

  it('reports a corrupt index as a failed load', async () => {
    const h = harness(() => Promise.resolve(loaded(INDEX.subarray(0, 100))));
    h.send({ type: 'load', url: 'x' });
    const [out] = await h.until(1);
    expect(out?.type).toBe('load-error');
    h.close();
  });

  it('uses the default limit for a zero limit', async () => {
    const h = harness(() => Promise.resolve(loaded()));
    h.send({ type: 'load', url: 'x' });
    await h.until(1);
    h.send({ type: 'query', id: 1, q: 'school', limit: 0 });
    const [, result] = await h.until(2);
    if (result?.type !== 'result') throw new Error('expected result');
    expect(result.results.schools).toHaveLength(5);
    h.close();
  });
});

describe('fetchIndex', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('inflates a gzip-compressed index as it downloads', async () => {
    const gz = gzipSync(INDEX);
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(new Blob([gz]))));
    const got = await fetchIndex('test://index');
    expect(got.bytes).toEqual(INDEX);
    expect(got.transferred).toBe(gz.length);
    expect(Object.keys(got.phases)).toEqual(['response', 'download']);
  });

  it('passes through an index a server already inflated', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(new Blob([INDEX.slice()]))));
    const got = await fetchIndex('test://index');
    expect(got.bytes).toEqual(INDEX);
  });

  it('copes with a first chunk of one byte', async () => {
    const gz = gzipSync(INDEX);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(gz.subarray(0, 1));
        controller.enqueue(gz.subarray(1, 1000));
        controller.enqueue(gz.subarray(1000));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(body)));
    expect((await fetchIndex('test://index')).bytes).toEqual(INDEX);
  });

  it('fails on an HTTP error', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('nope', { status: 404 })));
    await expect(fetchIndex('test://index')).rejects.toThrow('HTTP 404');
  });

  it('fails on a damaged download', async () => {
    const gz = gzipSync(INDEX);
    gz[gz.length - 5] = (gz[gz.length - 5] ?? 0) ^ 0xff;
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(new Blob([gz]))));
    await expect(fetchIndex('test://index')).rejects.toThrow();
  });
});
