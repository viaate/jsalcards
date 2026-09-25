/**
 * The worker side of the search protocol (see types.ts for the messages).
 *
 * The page sends `load` once, then queries. Queries that arrive before the
 * index is ready wait in order; a `cancel` drops a waiting query, which is
 * answered with `cancelled`. Every query gets exactly one answer.
 */
import { loadIndex } from './decode';
import { DEFAULT_LIMIT, SearchEngine } from './engine';
import type { IndexInfo, WorkerRequest, WorkerResponse } from './types';

/** Where messages come from and go to: the worker global, or a MessagePort in tests. */
export interface Endpoint {
  postMessage(message: WorkerResponse): void;
  addEventListener(type: 'message', listener: (event: MessageEvent<unknown>) => void): void;
}

/** Fetched index bytes, uncompressed, with how many bytes came over the wire. */
export interface LoadedBytes {
  readonly bytes: Uint8Array;
  readonly transferred: number;
  /** Milliseconds per step, merged into IndexInfo.phases. */
  readonly phases: Readonly<Record<string, number>>;
}

export type IndexFetcher = (url: string) => Promise<LoadedBytes>;

/**
 * Fetches an index and inflates it as it downloads. The file is stored
 * gzip-compressed; if a server already undid that (Content-Encoding), the
 * bytes arrive plain and pass through.
 */
export async function fetchIndex(url: string): Promise<LoadedBytes> {
  const t0 = performance.now();
  const response = await fetch(url);
  if (!response.ok || !response.body) {
    throw new Error(`index request failed with HTTP ${String(response.status)}`);
  }
  const reader = response.body.getReader();
  // Read until the first two bytes are known, to tell gzip from plain.
  const head: Uint8Array<ArrayBuffer>[] = [];
  let headBytes = 0;
  while (headBytes < 2) {
    const { done, value } = await reader.read();
    if (done) break;
    head.push(value);
    headBytes += value.length;
  }
  const t1 = performance.now();
  const first = head[0];
  const gzip = first?.[0] === 0x1f && (first[1] ?? head[1]?.[0]) === 0x8b;
  let transferred = headBytes;
  const body = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      for (const chunk of head) controller.enqueue(chunk);
    },
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) controller.close();
      else {
        transferred += value.length;
        controller.enqueue(value);
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
  const stream = gzip ? body.pipeThrough(new DecompressionStream('gzip')) : body;
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  const t2 = performance.now();
  return { bytes, transferred, phases: { response: t1 - t0, download: t2 - t1 } };
}

interface Pending {
  readonly id: number;
  readonly q: string;
  readonly limit: number;
}

function isRequest(data: unknown): data is WorkerRequest {
  if (typeof data !== 'object' || data === null) return false;
  const m = data as Record<string, unknown>;
  switch (m.type) {
    case 'load':
      return typeof m.url === 'string';
    case 'query':
      return typeof m.id === 'number' && typeof m.q === 'string' && typeof m.limit === 'number';
    case 'cancel':
      return typeof m.id === 'number';
    default:
      return false;
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Answers search requests arriving at `endpoint`. */
export function serve(endpoint: Endpoint, fetcher: IndexFetcher = fetchIndex): void {
  let engine: SearchEngine | null = null;
  let loading = false;
  let failed: string | null = null;
  const waiting: Pending[] = [];

  const answer = (p: Pending): void => {
    if (!engine) return;
    try {
      const t0 = performance.now();
      const results = engine.search(p.q, p.limit);
      endpoint.postMessage({ type: 'result', id: p.id, results, ms: performance.now() - t0 });
    } catch (error) {
      endpoint.postMessage({ type: 'query-error', id: p.id, message: message(error) });
    }
  };

  const load = async (url: string): Promise<void> => {
    const t0 = performance.now();
    try {
      const fetched = await fetcher(url);
      const phases: Record<string, number> = { ...fetched.phases };
      const index = loadIndex(fetched.bytes, phases);
      engine = new SearchEngine(index);
      const info: IndexInfo = {
        records: index.recordCount,
        tokens: index.dict.count,
        bytes: fetched.transferred,
        loadMs: performance.now() - t0,
        phases,
      };
      endpoint.postMessage({ type: 'ready', info });
      for (const p of waiting.splice(0)) answer(p);
    } catch (error) {
      failed = message(error);
      endpoint.postMessage({ type: 'load-error', message: failed });
      for (const p of waiting.splice(0)) {
        endpoint.postMessage({ type: 'query-error', id: p.id, message: failed });
      }
    }
  };

  endpoint.addEventListener('message', (event) => {
    const data = event.data;
    if (!isRequest(data)) return;
    switch (data.type) {
      case 'load':
        if (loading || engine || failed !== null) return;
        loading = true;
        void load(data.url);
        return;
      case 'query': {
        const p = { id: data.id, q: data.q, limit: data.limit || DEFAULT_LIMIT };
        if (failed !== null) {
          endpoint.postMessage({ type: 'query-error', id: p.id, message: failed });
        } else if (engine) answer(p);
        else waiting.push(p);
        return;
      }
      case 'cancel': {
        const at = waiting.findIndex((p) => p.id === data.id);
        if (at >= 0) {
          waiting.splice(at, 1);
          endpoint.postMessage({ type: 'cancelled', id: data.id });
        }
        return;
      }
    }
  });
}
