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
 *
 * What the page reads before the worker takes it over is put into these
 * caches as it is read (keep.ts), so the worker never downloads it again.
 * The worker expires only what it has cached or served itself, so the copies
 * a deploy leaves behind are dropped here (dropOldData).
 */

import { DETAILS_INDEX_PATH, SHARD_FILE } from '../data/details-format';
import { createDataFiles } from '../data/files';
import { plainPath } from '../data/paths';
import { CACHE_NAMES, DATA_DIR, isCacheUpdatedMessage } from './config';
import { keepsWritten } from './keep';

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
  const named = urls?.map((url) => new URL(url, host.location.href).href);
  // A copy on its way into the cache (keep.ts) lands first, so none is put back once dropped.
  await keepsWritten(named);
  if (storage === undefined || !(await storage.has(CACHE_NAMES.staticData))) return;
  const cache = await storage.open(CACHE_NAMES.staticData);
  const targets = named ?? (await cache.keys());
  await Promise.all(targets.map((target) => cache.delete(target)));
}

/**
 * The detail shards a kept copy of the shard index at `indexUrl` names, as
 * absolute URLs: none when no copy is kept, or it names none.
 */
async function shardsNamed(cache: Cache, indexUrl: string | null): Promise<string[]> {
  if (indexUrl === null) return [];
  try {
    const index = (await (await cache.match(indexUrl))?.json()) as { files?: unknown } | null;
    const names = Array.isArray(index?.files) ? (index.files as unknown[]) : [];
    return names
      .filter((name): name is string => typeof name === 'string' && SHARD_FILE.test(name))
      .map((name) => new URL(name, indexUrl).href);
  } catch {
    return [];
  }
}

/**
 * Drops from the worker's data caches each copy of a file under the data
 * folder of the site at `base` whose name carries a content hash
 * (src/data/paths.ts) and that this build does not ship: neither one of
 * `paths`, the build's list as published, nor a detail shard that a kept copy
 * of this build's shard index names. A deploy that changes the directory, the
 * search index or a shard publishes it under a new name, so this is what
 * clears out the old one. The worker's own limits (config.ts CACHE_LIMITS)
 * expire only the copies it has cached or served itself, never one the page
 * kept for it before it took the page over, or while none could (keep.ts).
 * A file with a plain name is replaced where it is, under that name. Resolves
 * to the number of copies dropped; never rejects.
 */
export async function dropOldData(
  paths: readonly string[],
  base: string = import.meta.env.BASE_URL,
  host: DataCacheHost = defaultHost(),
): Promise<number> {
  const storage = host.caches;
  let dropped = 0;
  try {
    if (storage === undefined) return 0;
    const root = dataRoot(base, host);
    const shipped = new Set(paths.map((path) => new URL(path, root).href));
    const indexUrl = createDataFiles(paths, root).url(DETAILS_INDEX_PATH);
    for (const name of [CACHE_NAMES.staticData, CACHE_NAMES.data]) {
      if (!(await storage.has(name))) continue;
      const cache = await storage.open(name);
      // Listed before the shard index is read, so a shard kept meanwhile, after it, stays.
      const held = await cache.keys();
      const shards = name === CACHE_NAMES.staticData ? await shardsNamed(cache, indexUrl) : [];
      const current = new Set([...shipped, ...shards]);
      for (const { url } of held) {
        const path = url.slice(root.length);
        if (!url.startsWith(root) || plainPath(path) === path || current.has(url)) continue;
        if (await cache.delete(url)) dropped += 1;
      }
    }
  } catch {
    // Cache Storage refused; the next visit tries again.
  }
  return dropped;
}
