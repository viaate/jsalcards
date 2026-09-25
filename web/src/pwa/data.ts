/**
 * The page's view of the service worker's data caches.
 *
 * Live files are served stale-while-revalidate: a fetch gets the last copy at
 * once and the worker refreshes it in the background. `onDataUpdate` says when
 * that refresh brought a different file, so the page can fetch it again (it
 * then comes from the cache, already new).
 *
 * Poll live files with `fetch(url, { cache: 'no-cache' })`. GitHub Pages sends
 * max-age=600, so without it the worker's refresh would be answered by the
 * browser's HTTP cache for up to ten minutes instead of by the server.
 */

import { CACHE_NAMES, DATA_DIR, isCacheUpdatedMessage, isRangeServed } from './config';

/** The parts of `window` these helpers use, so tests can hand them fakes. */
export interface DataCacheHost {
  readonly location: { readonly href: string };
  readonly navigator: {
    readonly serviceWorker?: Pick<
      ServiceWorkerContainer,
      'addEventListener' | 'removeEventListener'
    >;
  };
  readonly caches?: Pick<CacheStorage, 'open' | 'has'>;
  readonly performance?: Pick<Performance, 'getEntriesByType'>;
  fetch(input: string, init?: RequestInit): Promise<Response>;
}

function defaultHost(): DataCacheHost {
  return window;
}

/** The absolute URL of the data folder for a site at `base`. */
export function dataRoot(base: string, host: DataCacheHost = defaultHost()): string {
  return new URL(`${base}${DATA_DIR}`, host.location.href).href;
}

/**
 * Calls `listener` with the absolute URL of each data file the worker has just
 * replaced with a different copy. Returns the function that stops it.
 */
export function onDataUpdate(
  listener: (url: string) => void,
  host: DataCacheHost = defaultHost(),
): () => void {
  const container = host.navigator.serviceWorker;
  if (container === undefined) return () => undefined;
  const onMessage = (event: Event): void => {
    const { data } = event as MessageEvent<unknown>;
    if (isCacheUpdatedMessage(data) && data.payload.cacheName === CACHE_NAMES.data) {
      listener(data.payload.updatedURL);
    }
  };
  container.addEventListener('message', onMessage);
  return () => {
    container.removeEventListener('message', onMessage);
  };
}

/** `url` resolved against the page, or null when it is not a URL. */
function absolute(url: string, host: DataCacheHost): string | null {
  try {
    return new URL(url, host.location.href).href;
  } catch {
    return null;
  }
}

/**
 * Fetches again, now through the worker, the data files this page loaded
 * before the worker controlled it, so the first visit already works offline.
 * `extra` adds files loaded elsewhere, such as by a web worker. Range-served
 * files (the school tiles) are left out: the page reads them a few kilobytes at
 * a time, and fetching one whole would download all of it for nothing. Resolves
 * to the number of files requested; failures are ignored.
 */
export async function warmDataCache(
  base: string,
  extra: readonly string[] = [],
  host: DataCacheHost = defaultHost(),
): Promise<number> {
  const root = dataRoot(base, host);
  const loaded = (host.performance?.getEntriesByType('resource') ?? []).map((entry) => entry.name);
  const urls = new Set(
    [...loaded, ...extra]
      .map((url) => absolute(url, host))
      .filter((url): url is string => url?.startsWith(root) === true && !isRangeServed(url)),
  );
  await Promise.all(
    [...urls].map((url) =>
      host.fetch(url, { credentials: 'same-origin' }).then(
        (response) => response.body?.cancel(),
        () => undefined,
      ),
    ),
  );
  return urls.size;
}

/**
 * Drops cached copies of cache-first data (the school directory, the search
 * index), all of them or just `urls`, so the next fetch goes to the network.
 * For when a live file points at a newer directory than the cached one.
 */
export async function evictStaticData(
  urls?: readonly string[],
  host: DataCacheHost = defaultHost(),
): Promise<void> {
  const storage = host.caches;
  if (storage === undefined || !(await storage.has(CACHE_NAMES.staticData))) return;
  const cache = await storage.open(CACHE_NAMES.staticData);
  const targets =
    urls === undefined
      ? await cache.keys()
      : urls.map((url) => new URL(url, host.location.href).href);
  await Promise.all(targets.map((target) => cache.delete(target)));
}
