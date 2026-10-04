/**
 * The data files the page reads before a service worker controls it, kept
 * where the worker keeps them.
 *
 * On a first visit the page reads its data straight from the network: the
 * worker is registered only once the page has loaded (register.ts), and takes
 * the page over (and its search worker) whenever its install is done, before,
 * during or after any of the page's reads. Each whole data file read before
 * that is put, as it arrives, into the cache the worker's route for it uses
 * (config.ts). The worker finds it there from then on and never downloads it
 * again, and the next visit has it offline. Whichever downloads a file, the
 * page before the take-over or the worker after it, does so once.
 *
 * Nothing here fetches. A read that fails or is cut off keeps nothing (a cache
 * takes a file whole or not at all), and the next read of that file, through
 * the worker or not, is kept as any other: no file is ever taken for kept
 * that is not in the cache.
 */

import { CACHE_NAMES, routeFor } from './config';

/** The caches the worker keeps whole data files in, by its route for them. */
const DATA_CACHES: Readonly<Record<string, string | undefined>> = {
  staticData: CACHE_NAMES.staticData,
  data: CACHE_NAMES.data,
};

/** Where Cache Storage is: the page or a web worker, none on an insecure origin. */
export interface KeepHost {
  readonly caches?: Pick<CacheStorage, 'open'>;
}

/** The keeps still being written, by URL, the last of each. */
const writing = new Map<string, Promise<boolean>>();

/** `url` as an absolute URL, or null when it is not one. */
function absolute(url: string): string | null {
  try {
    return new URL(url).href;
  } catch {
    return null;
  }
}

/** When a response was sent, from its Date header: NaN without one. */
function sentAt(response: Response): number {
  return Date.parse(response.headers.get('date') ?? '');
}

function discard(response: Response): void {
  response.body?.cancel().catch(() => undefined);
}

async function put(
  url: string,
  response: Response,
  name: string,
  storage: Pick<CacheStorage, 'open'>,
): Promise<boolean> {
  try {
    const cache = await storage.open(name);
    let file = response;
    if (name === CACHE_NAMES.data) {
      // A live file changes under its name. It is read whole before it is set against what
      // the cache holds, so a copy the worker put while it downloaded counts too.
      file = new Response(await response.arrayBuffer(), {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    }
    // A copy sent no earlier is kept as it is: the worker's own, or an earlier read's that came
    // back first. One sent later than it replaces it. (A cache-first file is the same file
    // under its name whichever copy it is, so it goes in as it downloads.)
    const held = await cache.match(url);
    if (held !== undefined && !(sentAt(file) > sentAt(held))) {
      discard(file);
      return false;
    }
    await cache.put(url, file);
    return true;
  } catch {
    discard(response);
    return false;
  }
}

/**
 * Puts `response`, a file just read from the network for `url`, into the
 * cache the worker keeps that file in, unless that cache holds a copy sent no
 * earlier. Only a 200 is kept, and only for a file under the data folder of
 * the site at `base` that the worker caches whole: never a school tile file,
 * read in ranges. Resolves to whether it was put, once it is written; never
 * rejects. Keeps of one URL are written in the order they were asked for.
 */
export function keepData(
  url: string,
  response: Response,
  base: string = import.meta.env.BASE_URL,
  host: KeepHost = globalThis,
): Promise<boolean> {
  const storage = host.caches;
  const href = absolute(url);
  const name = href === null ? undefined : DATA_CACHES[routeFor(href, base) ?? ''];
  if (href === null || name === undefined || storage === undefined || response.status !== 200) {
    discard(response);
    return Promise.resolve(false);
  }
  const previous = writing.get(href) ?? Promise.resolve(false);
  const kept = previous.then(() => put(href, response, name, storage));
  writing.set(href, kept);
  void kept.then(() => {
    if (writing.get(href) === kept) writing.delete(href);
  });
  return kept;
}

/**
 * Resolves once the keeps being written for `urls` (absolute URLs), or for
 * every file when none are given, are done, so a file dropped from a cache is
 * not put back just after by a keep that was on its way.
 */
export async function keepsWritten(urls?: readonly string[]): Promise<void> {
  const pending = urls === undefined ? [...writing.values()] : urls.map((url) => writing.get(url));
  await Promise.all(pending.filter((keep) => keep !== undefined));
}
