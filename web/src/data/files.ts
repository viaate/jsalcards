/**
 * Where the page reads its data, and whether this build has a file at all.
 *
 * The build lists the data files it ships (tools/data-files.ts); a file that
 * is not on the list is never requested, so a build without data asks the
 * server for nothing and logs nothing. Reads that fail anyway (offline, a
 * deploy in flight, a file that does not parse) come back as null, quietly:
 * the page then shows nothing for that file rather than anything false.
 *
 * Every data file is fetched with fetchFile, which keeps what it reads before
 * the service worker takes the page over in the worker's cache, so the worker
 * never downloads it a second time (pwa/keep.ts).
 */

import { DATA_DIR } from '../pwa/config';
import { plainPath } from './paths';

/** Published files that are not JSON documents (pipeline/snowlight/schemas/registry.py). */
export const DATA_PATHS = Object.freeze({
  points: 'schools/points.bin',
  schoolTiles: 'schools/schools.pmtiles',
  searchIndex: 'search-index.bin',
} as const);

export interface DataFiles {
  /** Whether this build ships `path` (relative to data/, such as "live/closings.json"). */
  has(path: string): boolean;
  /** The absolute URL of a file this build ships, or null. */
  url(path: string): string | null;
}

/**
 * The files in `paths`, as published (a name may carry a content hash; see
 * paths.ts), served from the absolute URL `root` (ending in a slash). Each
 * is asked for by its plain name.
 */
export function createDataFiles(paths: readonly string[], root: string): DataFiles {
  const shipped = new Map(paths.map((path) => [plainPath(path), path]));
  return {
    has: (path) => shipped.has(path),
    url: (path) => {
      const published = shipped.get(path);
      return published === undefined ? null : new URL(published, root).href;
    },
  };
}

/** The data folder of a site at `base` ("/" or "/repo/"), as an absolute URL. */
export function dataRootFor(base: string, pageHref: string): string {
  return new URL(`${base}${DATA_DIR}`, pageHref).href;
}

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * Whether a data file read now comes straight from the network, in a build
 * whose service worker will want it: a production build in a browser with
 * service workers, before one controls the page.
 */
export function readsPastWorker(): boolean {
  return (
    import.meta.env.PROD &&
    'caches' in globalThis &&
    'serviceWorker' in navigator &&
    navigator.serviceWorker.controller === null
  );
}

/**
 * Fetches a data file, as `fetch` does. Read before a service worker controls
 * the page, a whole file is also put into the cache the worker keeps it in as
 * it arrives (pwa/keep.ts), so the worker, once it takes over, finds it there
 * instead of downloading it again, and the next visit has it offline.
 */
export const fetchFile: Fetch = async (input, init) => {
  const keep = readsPastWorker();
  const response = await fetch(input, init);
  if (keep && response.status === 200) {
    const copy = response.clone();
    void import('../pwa/keep').then(
      ({ keepData }) => keepData(input, copy),
      () => copy.body?.cancel(),
    );
  }
  return response;
};

/**
 * Fetches a file this build ships. Null when it does not ship it, the request
 * fails or the answer is not a success. An abort still rejects, so callers
 * that cancel can tell.
 */
export async function fetchData(
  files: DataFiles,
  path: string,
  init: RequestInit = {},
  fetchImpl: Fetch = fetchFile,
): Promise<Response | null> {
  const url = files.url(path);
  if (url === null) return null;
  try {
    const response = await fetchImpl(url, init);
    if (response.ok) return response;
    await response.body?.cancel().catch(() => undefined);
    return null;
  } catch (error) {
    if (init.signal?.aborted === true) throw error;
    return null;
  }
}

/** A shipped JSON file, parsed; null when it is missing, unreachable or not JSON. */
export async function fetchJson(
  files: DataFiles,
  path: string,
  init: RequestInit = {},
  fetchImpl?: Fetch,
): Promise<unknown> {
  const response = await fetchData(files, path, init, fetchImpl);
  if (response === null) return null;
  try {
    return (await response.json()) as unknown;
  } catch (error) {
    if (init.signal?.aborted === true) throw error;
    return null;
  }
}

/** A shipped binary file; null when it is missing or unreachable. */
export async function fetchBytes(
  files: DataFiles,
  path: string,
  init: RequestInit = {},
  fetchImpl?: Fetch,
): Promise<ArrayBuffer | null> {
  const response = await fetchData(files, path, init, fetchImpl);
  if (response === null) return null;
  try {
    return await response.arrayBuffer();
  } catch (error) {
    if (init.signal?.aborted === true) throw error;
    return null;
  }
}
