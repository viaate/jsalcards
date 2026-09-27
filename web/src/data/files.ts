/**
 * Where the page reads its data, and whether this build has a file at all.
 *
 * The build lists the data files it ships (tools/data-files.ts); a file that
 * is not on the list is never requested, so a build without data asks the
 * server for nothing and logs nothing. Reads that fail anyway (offline, a
 * deploy in flight, a file that does not parse) come back as null, quietly:
 * the page then shows nothing for that file rather than anything false.
 */

import { DATA_DIR } from '../pwa/config';

/** Published files that are not JSON documents (pipeline/snowlight/schemas/registry.py). */
export const DATA_PATHS = Object.freeze({
  points: 'schools/points.bin',
  searchIndex: 'search-index.bin',
} as const);

export interface DataFiles {
  /** Whether this build ships `path` (relative to data/, such as "live/closings.json"). */
  has(path: string): boolean;
  /** The absolute URL of a file this build ships, or null. */
  url(path: string): string | null;
}

/** The files in `paths`, served from the absolute URL `root` (ending in a slash). */
export function createDataFiles(paths: readonly string[], root: string): DataFiles {
  const shipped = new Set(paths);
  return {
    has: (path) => shipped.has(path),
    url: (path) => (shipped.has(path) ? new URL(path, root).href : null),
  };
}

/** The data folder of a site at `base` ("/" or "/repo/"), as an absolute URL. */
export function dataRootFor(base: string, pageHref: string): string {
  return new URL(`${base}${DATA_DIR}`, pageHref).href;
}

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * Fetches a file this build ships. Null when it does not ship it, the request
 * fails or the answer is not a success. An abort still rejects, so callers
 * that cancel can tell.
 */
export async function fetchData(
  files: DataFiles,
  path: string,
  init: RequestInit = {},
  fetchImpl: Fetch = (input, options) => fetch(input, options),
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
