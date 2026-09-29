/**
 * Asking again, with growing waits: how the map gets what it needs from the
 * network (the US mask, the street tiles, the school tiles) every time, even
 * on a network that fails some requests, holds some without an answer, or
 * turns them all away for a while. Used in MapLibre's workers and on the
 * page: it must not touch the DOM.
 */

/** Waits before each new try, in milliseconds: the first before the second, the last repeated. */
export type Backoff = readonly number[];

/**
 * The wait before retry `retry` (0 for the first), give or take a quarter, so
 * that tiles failed together are not all asked for again at the same moment.
 */
export function backoffDelay(backoff: Backoff, retry: number, random = Math.random): number {
  const base = backoff[Math.min(Math.max(0, retry), backoff.length - 1)] ?? 0;
  return Math.round(base * (0.75 + 0.5 * random()));
}

/** The reason a signal gives for aborting, as an error to throw. */
function abortReason(signal: AbortSignal): Error {
  const reason: unknown = signal.reason;
  return reason instanceof Error ? reason : new DOMException('Aborted', 'AbortError');
}

/** Resolves after `ms`, or rejects at once with the signal's reason when it aborts. */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal === undefined) {
    return new Promise((resolve) => {
      setTimeout(resolve, Math.max(0, ms));
    });
  }
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    const done = (): void => {
      signal.removeEventListener('abort', aborted);
      resolve();
    };
    const timer = setTimeout(done, Math.max(0, ms));
    const aborted = (): void => {
      clearTimeout(timer);
      reject(abortReason(signal));
    };
    signal.addEventListener('abort', aborted, { once: true });
  });
}

/**
 * A wait that can be cut short: retries sleep on it, and news that the
 * network may be back (the browser coming online, the map asking again)
 * rings it, so the next try is made at once instead of at the end of a long
 * wait.
 */
export class Alarm {
  private readonly waiting = new Set<() => void>();

  /** Resolves after `ms`, or as soon as the alarm rings. */
  sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const done = (): void => {
        clearTimeout(timer);
        this.waiting.delete(done);
        resolve();
      };
      const timer = setTimeout(done, Math.max(0, ms));
      this.waiting.add(done);
    });
  }

  /** Ends every wait now. */
  ring(): void {
    for (const done of [...this.waiting]) done();
  }
}

/**
 * The longest wait an answer's Retry-After is honored for, in milliseconds:
 * OpenFreeMap is a free community host, and a client asked to wait waits.
 */
export const MAX_RETRY_AFTER_MS = 5 * 60_000;

/**
 * How long a 429 or 503 answer asks the client to wait (its Retry-After, in
 * seconds or as a date), in milliseconds and at most MAX_RETRY_AFTER_MS; null
 * for any other answer, or one that does not say.
 */
export function retryAfterMs(response: Response, now = Date.now()): number | null {
  if (response.status !== 429 && response.status !== 503) return null;
  const value = response.headers.get('retry-after')?.trim();
  if (value === undefined || value === '') return null;
  const seconds = /^\d+$/.test(value) ? Number(value) * 1000 : Date.parse(value) - now;
  if (!Number.isFinite(seconds)) return null;
  return Math.min(MAX_RETRY_AFTER_MS, Math.max(0, seconds));
}

/** A request that went this long with none of its answer arriving: given up on, and made again. */
export class StalledError extends Error {
  constructor(url: string, ms: number) {
    super(`${url}: no answer for ${String(Math.round(ms / 1000))} s`);
    this.name = 'StalledError';
  }
}

/** How a request is made: the platform's fetch, or a test's. */
export type Fetch = (url: string, init: RequestInit) => Promise<Response>;

const platformFetch: Fetch = (url, init) => fetch(url, init);

/**
 * Fetches `url` (with `get`, the platform's fetch unless told otherwise) and
 * reads its answer whole, giving up (StalledError) once `stallMs` pass with
 * none of it arriving: before the headers, or between two pieces of the
 * body. A slow answer that keeps coming is waited for. Aborting `signal`
 * aborts the request.
 */
export async function fetchBytes(
  url: string,
  stallMs: number,
  signal?: AbortSignal,
  init: RequestInit = {},
  get: Fetch = platformFetch,
): Promise<{ response: Response; bytes: Uint8Array<ArrayBuffer> }> {
  if (signal?.aborted === true) throw abortReason(signal);
  const controller = new AbortController();
  const aborted = (): void => {
    if (signal !== undefined) controller.abort(abortReason(signal));
  };
  signal?.addEventListener('abort', aborted, { once: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const arm = (): void => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      controller.abort(new StalledError(url, stallMs));
    }, stallMs);
  };
  try {
    arm();
    const response = await get(url, { ...init, signal: controller.signal });
    arm();
    const reader = response.body?.getReader();
    if (reader === undefined) {
      return { response, bytes: new Uint8Array(await response.arrayBuffer()) };
    }
    const parts: Uint8Array[] = [];
    let length = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      arm();
      parts.push(value);
      length += value.length;
    }
    const bytes = new Uint8Array(length);
    let at = 0;
    for (const part of parts) {
      bytes.set(part, at);
      at += part.length;
    }
    return { response, bytes };
  } catch (error) {
    // Whichever gave up first says why: the caller's abort, or the stall.
    throw controller.signal.aborted ? (controller.signal.reason as unknown) : error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', aborted);
  }
}
