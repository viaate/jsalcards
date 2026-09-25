// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_QUERY_TIMEOUT_MS,
  SearchUnavailableError,
  createSearchClient,
  isAbortError,
} from '../client';
import type { ClientOptions, WorkerLike } from '../client';
import { encodeIndex } from '../encode';
import { serve } from '../server';
import type { LoadedBytes } from '../server';
import type { WorkerRequest, WorkerResponse } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

const INDEX = encodeIndex(SYNTHETIC_RECORDS).bytes;

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

/**
 * The real worker-side server on one end of a MessageChannel and the client
 * on the other, with every message the page sends recorded.
 */
function setup(options: { gate?: Promise<LoadedBytes>; onQueryTime?: (ms: number) => void } = {}) {
  const channel = new MessageChannel();
  const fetcher = () =>
    options.gate ?? Promise.resolve({ bytes: INDEX, transferred: INDEX.length, phases: {} });
  serve(channel.port2, fetcher);
  channel.port2.start();
  const sent: WorkerRequest[] = [];
  const terminate = vi.fn(() => {
    channel.port1.close();
    channel.port2.close();
  });
  const worker: WorkerLike = {
    postMessage(message) {
      sent.push(message);
      channel.port1.postMessage(message);
    },
    addEventListener(type: string, listener: (event: never) => void) {
      channel.port1.addEventListener(type, listener as unknown as EventListener);
    },
    terminate,
  };
  const client = createSearchClient('test://index', {
    worker,
    ...(options.onQueryTime ? { onQueryTime: options.onQueryTime } : {}),
  });
  channel.port1.start();
  const queries = () => sent.filter((m) => m.type === 'query');
  return { client, sent, queries, terminate, close: terminate };
}

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected a rejection');
}

describe('search client', () => {
  it('loads the index and resolves ready', async () => {
    const { client, sent, close } = setup();
    const info = await client.ready;
    expect(info.records).toBe(SYNTHETIC_RECORDS.length);
    expect(sent[0]).toEqual({ type: 'load', url: 'test://index' });
    close();
  });

  it('resolves grouped results', async () => {
    const { client, close } = setup();
    const r = await client.search('lancaster pa');
    expect(r.query).toBe('lancaster pa');
    expect(r.cities[0]?.id).toBe('SYNC01');
    expect(r.schools.length).toBeGreaterThan(0);
    expect(r.order).toHaveLength(3);
    close();
  });

  it('supersedes an older search with a newer one', async () => {
    const { client, close } = setup();
    await client.ready;
    const older = client.search('lanc');
    const newer = client.search('lancaster');
    const error = await rejection(older);
    expect(isAbortError(error)).toBe(true);
    expect((await newer).query).toBe('lancaster');
    close();
  });

  it('resolves only the newest search of a burst, one query in flight at a time', async () => {
    const { client, queries, close } = setup();
    await client.ready;
    const text = 'lancaster pennsylvania';
    const all = Array.from({ length: text.length }, (_, i) => client.search(text.slice(0, i + 1)));
    const settled = await Promise.allSettled(all);
    const fulfilled = settled.filter((s) => s.status === 'fulfilled');
    expect(fulfilled).toHaveLength(1);
    expect(settled.at(-1)?.status).toBe('fulfilled');
    for (const s of settled.slice(0, -1)) {
      expect(s.status === 'rejected' && isAbortError(s.reason)).toBe(true);
    }
    // The first keystroke went out at once; the rest waited, and only the
    // newest of them was sent.
    expect(queries().map((q) => q.q)).toEqual(['l', text]);
    close();
  });

  it('sends only the newest search made before the index is ready', async () => {
    const gate = deferred<LoadedBytes>();
    const { client, queries, close } = setup({ gate: gate.promise });
    const a = client.search('a');
    const b = client.search('spring');
    expect(queries()).toEqual([]);
    gate.resolve({ bytes: INDEX, transferred: INDEX.length, phases: {} });
    expect(isAbortError(await rejection(a))).toBe(true);
    expect((await b).cities[0]?.name).toBe('Springfield');
    expect(queries().map((q) => q.q)).toEqual(['spring']);
    close();
  });

  it('asks the worker to cancel a superseded query in flight', async () => {
    const { client, sent, close } = setup();
    await client.ready;
    const first = client.search('lancaster');
    const second = client.search('springfield');
    await rejection(first);
    await second;
    expect(sent.some((m) => m.type === 'cancel' && m.id === 1)).toBe(true);
    close();
  });

  it('resolves whitespace at once, without the worker, and supersedes', async () => {
    const { client, queries, close } = setup();
    await client.ready;
    const pending = client.search('lancaster');
    const blank = await client.search('   ');
    expect(blank).toEqual({
      query: '   ',
      schools: [],
      cities: [],
      zips: [],
      order: ['schools', 'cities', 'zips'],
    });
    expect(isAbortError(await rejection(pending))).toBe(true);
    expect(queries()).toHaveLength(1);
    close();
  });

  it('handles emoji and very long input through the worker', async () => {
    const { client, close } = setup();
    const emoji = await client.search('🙂');
    expect(emoji.schools).toEqual([]);
    const long = await client.search('lancaster '.repeat(500));
    expect(long.query).toHaveLength(5000);
    close();
  });

  it('aborts a search through its signal', async () => {
    const gate = deferred<LoadedBytes>();
    const { client, queries, close } = setup({ gate: gate.promise });
    const controller = new AbortController();
    const pending = client.search('lancaster', { signal: controller.signal });
    controller.abort();
    expect(isAbortError(await rejection(pending))).toBe(true);
    gate.resolve({ bytes: INDEX, transferred: INDEX.length, phases: {} });
    await client.ready;
    expect(queries()).toEqual([]);
    close();
  });

  it('refuses a search whose signal is already aborted', async () => {
    const { client, close } = setup();
    const controller = new AbortController();
    controller.abort();
    expect(isAbortError(await rejection(client.search('x', { signal: controller.signal })))).toBe(
      true,
    );
    close();
  });

  it('ignores an abort after the search resolved', async () => {
    const { client, close } = setup();
    const controller = new AbortController();
    const r = await client.search('springfield', { signal: controller.signal });
    controller.abort();
    expect(r.cities.length).toBeGreaterThan(0);
    close();
  });

  it('clamps the limit', async () => {
    const { client, queries, close } = setup();
    await client.search('school', { limit: 500 });
    await client.search('school', { limit: -3 });
    await client.search('school', { limit: 2.7 });
    expect(queries().map((q) => q.limit)).toEqual([50, 1, 2]);
    close();
  });

  it('reports worker time per query', async () => {
    const times: number[] = [];
    const { client, close } = setup({ onQueryTime: (ms) => times.push(ms) });
    await client.search('lancaster');
    expect(times).toHaveLength(1);
    expect(times[0]).toBeGreaterThanOrEqual(0);
    close();
  });

  it('stops for good when destroyed', async () => {
    const gate = deferred<LoadedBytes>();
    const { client, terminate } = setup({ gate: gate.promise });
    const pending = client.search('lancaster');
    client.destroy();
    client.destroy();
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(isAbortError(await rejection(pending))).toBe(true);
    expect(isAbortError(await rejection(client.ready))).toBe(true);
    expect(isAbortError(await rejection(client.search('x')))).toBe(true);
  });

  it('rejects ready and every search when the index cannot load', async () => {
    const gate = deferred<LoadedBytes>();
    const { client, close } = setup({ gate: gate.promise });
    const pending = client.search('lancaster');
    gate.reject(new Error('index request failed with HTTP 404'));
    await expect(client.ready).rejects.toThrow('HTTP 404');
    await expect(client.ready).rejects.toBeInstanceOf(SearchUnavailableError);
    const error = await rejection(pending);
    expect(isAbortError(error)).toBe(false);
    expect(String(error)).toContain('HTTP 404');
    await expect(client.search('x')).rejects.toThrow('HTTP 404');
    close();
  });

  it('rejects a search the worker could not answer', async () => {
    const listeners: ((event: MessageEvent<unknown>) => void)[] = [];
    const reply = (data: WorkerResponse) => {
      for (const l of listeners) l({ data } as MessageEvent<unknown>);
    };
    const worker: WorkerLike = {
      postMessage(message) {
        if (message.type === 'load') {
          queueMicrotask(() => {
            reply({
              type: 'ready',
              info: { records: 0, tokens: 0, bytes: 0, loadMs: 0, phases: {} },
            });
          });
        }
        if (message.type === 'query') {
          const id = message.id;
          queueMicrotask(() => {
            reply({ type: 'query-error', id, message: 'boom' });
          });
        }
      },
      addEventListener(type: string, listener: (event: never) => void) {
        if (type === 'message') listeners.push(listener as (event: MessageEvent<unknown>) => void);
      },
    };
    const client = createSearchClient('test://index', { worker });
    const error = await rejection(client.search('x'));
    expect(isAbortError(error)).toBe(false);
    expect(String(error)).toContain('boom');
    // Messages that are not responses are ignored.
    for (const l of listeners) l({ data: null } as MessageEvent<unknown>);
    for (const l of listeners) l({ data: 'noise' } as MessageEvent<unknown>);
  });

  it('knows abort errors', () => {
    expect(isAbortError(new DOMException('x', 'AbortError'))).toBe(true);
    expect(isAbortError(new Error('x'))).toBe(false);
    expect(isAbortError('AbortError')).toBe(false);
  });
});

/**
 * A stand-in for a Worker that the test drives by hand: it records what the
 * page sends and fires whatever events the test asks for, including the
 * `error` a real Worker fires when its script fails to load.
 */
class FakeWorker implements WorkerLike {
  readonly sent: WorkerRequest[] = [];
  terminated = 0;
  private readonly events = new EventTarget();
  /** Called for each message the page sends, after it is recorded. */
  onPost: (message: WorkerRequest) => void = () => undefined;

  postMessage(message: WorkerRequest): void {
    this.sent.push(message);
    this.onPost(message);
  }

  addEventListener(type: string, listener: (event: never) => void): void {
    this.events.addEventListener(type, listener as unknown as EventListener);
  }

  terminate(): void {
    this.terminated++;
  }

  reply(data: WorkerResponse): void {
    this.events.dispatchEvent(new MessageEvent('message', { data }));
  }

  /** A plain `error` Event, as for a worker script that failed to load. */
  fireError(extra: { message?: string; error?: unknown } = {}): void {
    this.events.dispatchEvent(Object.assign(new Event('error'), extra));
  }

  fireMessageError(): void {
    this.events.dispatchEvent(new MessageEvent('messageerror', { data: null }));
  }

  queries(): Extract<WorkerRequest, { type: 'query' }>[] {
    return this.sent.filter((m) => m.type === 'query');
  }
}

const INFO = { records: 1, tokens: 1, bytes: 1, loadMs: 1, phases: {} };

function answer(id: number, q: string): WorkerResponse {
  return {
    type: 'result',
    id,
    ms: 0.1,
    results: { query: q, schools: [], cities: [], zips: [], order: ['schools', 'cities', 'zips'] },
  };
}

/** A fake worker that becomes ready at once and answers queries only if told to. */
function readyFake(options: Omit<ClientOptions, 'worker'> & { answers?: boolean } = {}) {
  const worker = new FakeWorker();
  worker.onPost = (m) => {
    if (m.type === 'load') {
      queueMicrotask(() => {
        worker.reply({ type: 'ready', info: INFO });
      });
    }
    if (m.type === 'query' && options.answers !== false) {
      queueMicrotask(() => {
        worker.reply(answer(m.id, m.q));
      });
    }
  };
  const client = createSearchClient('test://index', { ...options, worker });
  return { worker, client };
}

describe('search client, when the worker fails', () => {
  it('rejects ready, waiting searches and later searches when the worker script fails to load', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    const first = client.search('lancaster');
    const second = client.search('springfield');
    worker.fireError();

    const readyError = await rejection(client.ready);
    expect(readyError).toBeInstanceOf(SearchUnavailableError);
    expect(isAbortError(readyError)).toBe(false);
    expect(String(readyError)).toContain('search worker failed to start');
    // The first search was superseded by the second before the failure.
    expect(isAbortError(await rejection(first))).toBe(true);
    expect(await rejection(second)).toBe(readyError);
    expect(await rejection(client.search('later'))).toBe(readyError);
    expect(worker.terminated).toBe(1);
    expect(worker.queries()).toEqual([]);
  });

  it('settles ready within a task of the error event', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    let state = 'pending';
    client.ready.then(
      () => (state = 'resolved'),
      () => (state = 'rejected'),
    );
    worker.fireError();
    await Promise.resolve();
    await Promise.resolve();
    expect(state).toBe('rejected');
  });

  it('carries the message and thrown value of an error event', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    const thrown = new SyntaxError('Unexpected token');
    worker.fireError({ message: 'Uncaught SyntaxError: Unexpected token', error: thrown });
    const error = await rejection(client.ready);
    expect(String(error)).toContain('Uncaught SyntaxError: Unexpected token');
    expect((error as Error).cause).toBe(thrown);
  });

  it('treats an unreadable message before ready as a failure to start', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    const pending = client.search('lancaster');
    worker.fireMessageError();
    const error = await rejection(client.ready);
    expect(error).toBeInstanceOf(SearchUnavailableError);
    expect(await rejection(pending)).toBe(error);
    expect(await rejection(client.search('x'))).toBe(error);
    expect(worker.terminated).toBe(1);
  });

  it('ignores a ready message that arrives after the failure', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    worker.fireError();
    worker.reply({ type: 'ready', info: INFO });
    await expect(client.ready).rejects.toBeInstanceOf(SearchUnavailableError);
    await expect(client.search('x')).rejects.toBeInstanceOf(SearchUnavailableError);
  });

  it('ignores error events after a load error and after destroy', async () => {
    const worker = new FakeWorker();
    const client = createSearchClient('test://index', { worker });
    worker.reply({ type: 'load-error', message: 'index request failed with HTTP 404' });
    worker.fireError({ message: 'later' });
    const error = await rejection(client.ready);
    expect(String(error)).toContain('HTTP 404');
    expect(String(error)).not.toContain('later');
    expect(worker.terminated).toBe(1);

    const other = new FakeWorker();
    const destroyed = createSearchClient('test://index', { worker: other });
    destroyed.destroy();
    other.fireError();
    other.fireMessageError();
    expect(isAbortError(await rejection(destroyed.ready))).toBe(true);
    expect(other.terminated).toBe(1);
  });

  it('rejects only the query in flight when the worker errors after ready', async () => {
    const { worker, client } = readyFake({ answers: false });
    await client.ready;
    const lost = client.search('lancaster');
    expect(worker.queries()).toHaveLength(1);
    worker.fireError({ message: 'Uncaught RangeError: boom' });
    const error = await rejection(lost);
    expect(isAbortError(error)).toBe(false);
    expect(error).not.toBeInstanceOf(SearchUnavailableError);
    expect(String(error)).toContain('RangeError: boom');
    expect(worker.terminated).toBe(0);

    // The worker still runs, so the next search goes out and resolves.
    const next = client.search('springfield');
    const sent = worker.queries().at(-1);
    expect(sent?.q).toBe('springfield');
    if (sent) worker.reply(answer(sent.id, sent.q));
    expect((await next).query).toBe('springfield');
  });

  it('drops a late answer to a query lost to an error', async () => {
    const { worker, client } = readyFake({ answers: false });
    await client.ready;
    const lost = client.search('lancaster');
    const lostId = worker.queries()[0]?.id ?? -1;
    worker.fireError();
    await rejection(lost);
    const next = client.search('springfield');
    const nextId = worker.queries().at(-1)?.id ?? -1;
    worker.reply(answer(lostId, 'lancaster'));
    worker.reply(answer(nextId, 'springfield'));
    expect((await next).query).toBe('springfield');
  });

  it('sends a query that was waiting behind one lost to an error', async () => {
    const { worker, client } = readyFake({ answers: false });
    await client.ready;
    const first = client.search('lanc');
    const second = client.search('lancaster');
    // One query in flight: the superseded first still holds the worker.
    expect(worker.queries().map((q) => q.q)).toEqual(['lanc']);
    worker.fireError();
    expect(isAbortError(await rejection(first))).toBe(true);
    const sent = worker.queries().at(-1);
    expect(sent?.q).toBe('lancaster');
    if (sent) worker.reply(answer(sent.id, sent.q));
    expect((await second).query).toBe('lancaster');
  });

  it('rejects the query in flight on an unreadable answer after ready', async () => {
    const { worker, client } = readyFake({ answers: false });
    await client.ready;
    const lost = client.search('lancaster');
    worker.fireMessageError();
    const error = await rejection(lost);
    expect(isAbortError(error)).toBe(false);
    expect(String(error)).toContain('unreadable answer');
    await expect(client.ready).resolves.toEqual(INFO);
  });

  it('shrugs off an error after ready with nothing in flight', async () => {
    const { worker, client } = readyFake();
    await client.ready;
    worker.fireError();
    worker.fireMessageError();
    expect((await client.search('springfield')).query).toBe('springfield');
  });

  it('rejects a query the worker leaves unanswered, then carries on', async () => {
    const { worker, client } = readyFake({ answers: false, queryTimeoutMs: 20 });
    await client.ready;
    const started = performance.now();
    const error = await rejection(client.search('lancaster'));
    expect(performance.now() - started).toBeGreaterThanOrEqual(15);
    expect(isAbortError(error)).toBe(false);
    expect(String(error)).toContain('did not answer in time');
    expect(worker.sent.some((m) => m.type === 'cancel' && m.id === 1)).toBe(true);

    const next = client.search('springfield');
    const sent = worker.queries().at(-1);
    expect(sent?.q).toBe('springfield');
    if (sent) worker.reply(answer(sent.id, sent.q));
    expect((await next).query).toBe('springfield');
  });

  it('frees a query waiting behind a superseded one the worker never answers', async () => {
    const { worker, client } = readyFake({ answers: false, queryTimeoutMs: 20 });
    await client.ready;
    // This worker hangs on "lanc" and answers anything else.
    worker.onPost = (m) => {
      if (m.type === 'query' && m.q !== 'lanc') {
        queueMicrotask(() => {
          worker.reply(answer(m.id, m.q));
        });
      }
    };
    const first = client.search('lanc');
    const second = client.search('lancaster');
    expect(isAbortError(await rejection(first))).toBe(true);
    expect(worker.queries().map((q) => q.q)).toEqual(['lanc']);
    // Only after the first query's time runs out does the second go out.
    expect((await second).query).toBe('lancaster');
    expect(worker.queries().map((q) => q.q)).toEqual(['lanc', 'lancaster']);
    expect(worker.sent.filter((m) => m.type === 'cancel').map((m) => m.id)).toEqual([1]);
  });

  it('does not time out a query that is answered', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const { client } = readyFake();
      await client.ready;
      const r = await client.search('lancaster');
      vi.advanceTimersByTime(DEFAULT_QUERY_TIMEOUT_MS * 2);
      expect(r.query).toBe('lancaster');
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears its timer when destroyed with a query in flight', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const { client } = readyFake({ answers: false });
      await client.ready;
      const pending = client.search('lancaster');
      expect(vi.getTimerCount()).toBe(1);
      client.destroy();
      expect(vi.getTimerCount()).toBe(0);
      expect(isAbortError(await rejection(pending))).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('fails cleanly when the worker cannot be constructed', async () => {
    // `new Worker(...)` throws, as it does for a blocked or invalid URL.
    vi.stubGlobal('Worker', function BlockedWorker(): never {
      throw new DOMException('Worker blocked', 'SecurityError');
    });
    try {
      const client = createSearchClient('test://index');
      const error = await rejection(client.ready);
      expect(error).toBeInstanceOf(SearchUnavailableError);
      expect(String(error)).toContain('could not start');
      expect((error as Error).cause).toBeInstanceOf(DOMException);
      expect(await rejection(client.search('lancaster'))).toBe(error);
      client.destroy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('fails cleanly when the load message cannot be posted', async () => {
    const worker = new FakeWorker();
    worker.onPost = () => {
      throw new DOMException('could not clone', 'DataCloneError');
    };
    const client = createSearchClient('test://index', { worker });
    await expect(client.ready).rejects.toBeInstanceOf(SearchUnavailableError);
    await expect(client.search('x')).rejects.toBeInstanceOf(SearchUnavailableError);
    expect(worker.terminated).toBe(1);
  });

  it('fails when the real worker end goes away before ready', async () => {
    // The page end of a MessageChannel whose worker end fires `error`, as
    // Chromium does for a worker chunk that answers 404.
    const channel = new MessageChannel();
    const events = new EventTarget();
    const worker: WorkerLike = {
      postMessage(message) {
        channel.port1.postMessage(message);
      },
      addEventListener(type: string, listener: (event: never) => void) {
        if (type === 'error') events.addEventListener(type, listener as unknown as EventListener);
        else channel.port1.addEventListener(type, listener as unknown as EventListener);
      },
      terminate() {
        channel.port1.close();
        channel.port2.close();
      },
    };
    channel.port1.start();
    const client = createSearchClient('test://index', { worker });
    const pending = client.search('lancaster');
    setTimeout(() => events.dispatchEvent(new Event('error')), 5);
    const error = await rejection(client.ready);
    expect(error).toBeInstanceOf(SearchUnavailableError);
    expect(await rejection(pending)).toBe(error);
  });
});

describe('search client options and edge cases', () => {
  it('rejects a query the worker cannot take, and carries on', async () => {
    const { worker, client } = readyFake();
    await client.ready;
    const onPost = worker.onPost;
    worker.onPost = (m) => {
      if (m.type === 'query' && m.q === 'bad') throw new DOMException('no', 'DataCloneError');
      onPost(m);
    };
    const error = await rejection(client.search('bad'));
    expect(isAbortError(error)).toBe(false);
    expect(String(error)).toContain('could not take the query');
    expect((await client.search('springfield')).query).toBe('springfield');
  });

  it.each([Number.NaN, -1, 0])('uses the default timeout for %s', async (ms) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const { client } = readyFake({ answers: false, queryTimeoutMs: ms });
      await client.ready;
      const pending = rejection(client.search('lancaster'));
      vi.advanceTimersByTime(DEFAULT_QUERY_TIMEOUT_MS - 1);
      let settled = false;
      void pending.then(() => (settled = true));
      await Promise.resolve();
      expect(settled).toBe(false);
      vi.advanceTimersByTime(1);
      expect(String(await pending)).toContain('did not answer in time');
    } finally {
      vi.useRealTimers();
    }
  });

  it('never times out with an infinite timeout', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const { worker, client } = readyFake({
        answers: false,
        queryTimeoutMs: Number.POSITIVE_INFINITY,
      });
      await client.ready;
      const pending = client.search('lancaster');
      expect(vi.getTimerCount()).toBe(0);
      vi.advanceTimersByTime(60 * 60 * 1000);
      const sent = worker.queries()[0];
      if (sent) worker.reply(answer(sent.id, sent.q));
      expect((await pending).query).toBe('lancaster');
    } finally {
      vi.useRealTimers();
    }
  });

  it('caps a huge timeout so it does not fire at once', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const { client } = readyFake({ answers: false, queryTimeoutMs: 1e12 });
      await client.ready;
      const pending = rejection(client.search('lancaster'));
      let settled = false;
      void pending.then(() => (settled = true));
      vi.advanceTimersByTime(24 * 60 * 60 * 1000);
      await Promise.resolve();
      expect(settled).toBe(false);
      client.destroy();
      expect(isAbortError(await pending)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
