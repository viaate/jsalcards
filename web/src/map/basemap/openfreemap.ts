import type { GetResourceResponse } from 'maplibre-gl';

import { backoffDelay, fetchBytes, retryAfterMs, sleep } from './retry';
import type { Backoff } from './retry';

/**
 * OpenFreeMap vector tiles, used from zoom 7 up.
 *
 * The public TileJSON points at a dated tile set that changes over time, so
 * tiles are requested through a custom protocol: the style names
 * `openfreemap://planet/{z}/{x}/{y}` and the TileJSON is only fetched when the
 * first zoom 7+ tile is needed. Below zoom 7 nothing leaves the site.
 *
 * The protocol is served in MapLibre's workers (street-tiles.ts), which cut
 * each tile to the US before MapLibre reads it. The page only ever asks for
 * tiles ahead of a flight (prefetch.ts), to have them cached, never to draw
 * them.
 *
 * A network can fail a tile, hold it without an answer, turn it away for a
 * while (a 429 or 503 asking the client to wait), or answer with something
 * that is not a tile (a block page). A worker tries each tile a few times,
 * waiting between tries, and fails it only after that; the page then asks
 * for it again, with longer waits, until it comes (heal.ts).
 */

/** The style's URL scheme for OpenFreeMap tiles. */
export const OPENFREEMAP_PROTOCOL = 'openfreemap';
const TILEJSON_URL = 'https://tiles.openfreemap.org/planet';

export const OPENFREEMAP_TILES = `${OPENFREEMAP_PROTOCOL}://planet/{z}/{x}/{y}`;
export const OPENFREEMAP_MIN_ZOOM = 7;
export const OPENFREEMAP_MAX_ZOOM = 14;

/** License-required credit for OpenFreeMap, OpenMapTiles and OpenStreetMap. */
export const OPENFREEMAP_ATTRIBUTION = [
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a>',
  '<a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">&copy; OpenMapTiles</a>',
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">&copy; OpenStreetMap contributors</a>',
].join(' ');

const TILE_PATH = /\/(\d+)\/(\d+)\/(\d+)$/;

/** Tries at a street tile within one load; after them the tile fails, and the page asks for it again (heal.ts). */
export const TILE_TRIES = 3;
/** Waits between those tries, in milliseconds. */
export const TILE_BACKOFF: Backoff = [400, 1600];
/**
 * How long a request for a street tile or the TileJSON may go with none of
 * its answer arriving, in milliseconds, before it is given up on and tried
 * again. An answer that keeps coming, however slowly, is waited for.
 */
export const TILE_STALL_MS = 12_000;

/**
 * How long the page's request for a tile ahead of a flight may take in all,
 * in milliseconds, before it is given up: the worker asks for the tile
 * itself, and waits for it as long as it keeps coming.
 */
export const PREFETCH_LIMIT_MS = 60_000;

/** The first byte of a vector tile with anything in it: field 3 (its layers), length-delimited. */
const VECTOR_TILE_FIRST_BYTE = 0x1a;

/**
 * No request to OpenFreeMap leaves this worker (or the page) before this
 * time: set by an answer asking the client to wait (a 429 or 503 with a
 * Retry-After).
 */
let resumeAt = 0;

/** Notes how long an answer asks the client to wait, for every request after it. */
function noteRetryAfter(response: Response): void {
  const wait = retryAfterMs(response);
  if (wait !== null) resumeAt = Math.max(resumeAt, Date.now() + wait);
}

/** Waits out a Retry-After, if one is still running. */
async function waitForTurn(signal?: AbortSignal): Promise<void> {
  const wait = resumeAt - Date.now();
  if (wait > 0) await sleep(wait, signal);
}

/**
 * An answer that is not a tile: HTML (a network's block page, a challenge),
 * or a body that is not a vector tile. It is never handed to MapLibre as one.
 */
export class NotATileError extends Error {
  constructor(url: string, why: string) {
    super(`OpenFreeMap: ${url} is not a tile (${why})`);
    this.name = 'NotATileError';
  }
}

/** Whether an answer is a vector tile: not text, and empty or starting with its layers. */
export function isVectorTile(contentType: string | null, bytes: Uint8Array): boolean {
  if (contentType !== null && /^\s*text\//i.test(contentType)) return false;
  return bytes.length === 0 || bytes[0] === VECTOR_TILE_FIRST_BYTE;
}

let template: Promise<string> | undefined;

async function fetchTemplate(): Promise<string> {
  await waitForTurn();
  const { response, bytes } = await fetchBytes(TILEJSON_URL, TILE_STALL_MS);
  noteRetryAfter(response);
  if (!response.ok) throw new Error(`OpenFreeMap TileJSON: HTTP ${String(response.status)}`);
  let tilejson: { tiles?: unknown };
  try {
    tilejson = JSON.parse(new TextDecoder().decode(bytes)) as { tiles?: unknown };
  } catch {
    throw new Error('OpenFreeMap TileJSON: not JSON');
  }
  const first: unknown = Array.isArray(tilejson.tiles) ? tilejson.tiles[0] : undefined;
  if (typeof first !== 'string' || !first.includes('{z}')) {
    throw new Error('OpenFreeMap TileJSON: no tile URL template');
  }
  return first;
}

/**
 * How long a failed TileJSON lookup stands, in milliseconds: every tile asking
 * meanwhile shares the failure, rather than asking again, a lookup each.
 */
export const TEMPLATE_RETRY_MS = 1000;

/** The current dated tile URL template; a failed lookup is tried again after TEMPLATE_RETRY_MS. */
function tileTemplate(): Promise<string> {
  if (template === undefined) {
    const lookup: Promise<string> = fetchTemplate().catch((error: unknown) => {
      setTimeout(() => {
        if (template === lookup) template = undefined;
      }, TEMPLATE_RETRY_MS);
      throw error;
    });
    template = lookup;
  }
  return template;
}

export function tileUrl(templateUrl: string, requestUrl: string): string {
  const match = TILE_PATH.exec(requestUrl);
  if (match === null) throw new Error(`OpenFreeMap: unexpected tile request ${requestUrl}`);
  const [, z = '', x = '', y = ''] = match;
  return templateUrl.replace('{z}', z).replace('{x}', x).replace('{y}', y);
}

/**
 * Asks OpenFreeMap for tiles ahead of the map, so the browser has them when a
 * worker asks (street-tiles.ts): the TileJSON and the tiles are cacheable, and
 * the page and its workers share one cache, so no tile goes over the network
 * twice. Nothing is read from them here, and a tile that fails is simply
 * asked for again by the worker. While OpenFreeMap asks the page to wait,
 * nothing is asked for ahead.
 */
export async function prefetchOpenFreeMapTiles(
  tiles: readonly (readonly [z: number, x: number, y: number])[],
): Promise<void> {
  if (tiles.length === 0 || resumeAt > Date.now()) return;
  let templateUrl: string;
  try {
    templateUrl = await tileTemplate();
  } catch {
    return;
  }
  await Promise.all(
    tiles.map(async ([z, x, y]) => {
      if (resumeAt > Date.now()) return;
      // Given up on with no answer in TILE_STALL_MS, or none whole in PREFETCH_LIMIT_MS.
      const controller = new AbortController();
      let timer = setTimeout(() => {
        controller.abort();
      }, TILE_STALL_MS);
      try {
        const response = await fetch(
          tileUrl(templateUrl, `/${String(z)}/${String(x)}/${String(y)}`),
          { signal: controller.signal },
        );
        noteRetryAfter(response);
        clearTimeout(timer);
        timer = setTimeout(() => {
          controller.abort();
        }, PREFETCH_LIMIT_MS);
        // Read to the end, by the browser rather than on the page's thread: only a whole
        // response is kept.
        await response.arrayBuffer();
      } catch {
        // The worker asks for it again.
      } finally {
        clearTimeout(timer);
      }
    }),
  );
}

/** One try at a tile: its answer, if it is one. `fresh` goes past the browser's cache. */
async function tryTile(
  requestUrl: string,
  signal: AbortSignal,
  fresh: boolean,
): Promise<GetResourceResponse<ArrayBuffer>> {
  await waitForTurn(signal);
  const init: RequestInit = fresh ? { cache: 'reload' } : {};
  let url = tileUrl(await tileTemplate(), requestUrl);
  let { response, bytes } = await fetchBytes(url, TILE_STALL_MS, signal, init);
  if (response.status === 404) {
    // The dated tile set was retired while the page was open: look up the current one once.
    template = undefined;
    url = tileUrl(await tileTemplate(), requestUrl);
    ({ response, bytes } = await fetchBytes(url, TILE_STALL_MS, signal, init));
  }
  noteRetryAfter(response);
  if (!response.ok) throw new Error(`OpenFreeMap tile: HTTP ${String(response.status)}`);
  const contentType = response.headers.get('content-type');
  if (!isVectorTile(contentType, bytes)) {
    throw new NotATileError(url, contentType ?? `${String(bytes.length)} bytes`);
  }
  return {
    data: bytes.buffer,
    cacheControl: response.headers.get('cache-control'),
    expires: response.headers.get('expires'),
  };
}

/**
 * The tile the style names `openfreemap://planet/z/x/y`, from the current
 * tile set. It is tried TILE_TRIES times, with a wait between tries (longer
 * when an answer asks for one); a request that stalls is given up on and made
 * again, and an answer that is not a tile is never taken for one: the try
 * after it goes past the browser's cache, which may hold it.
 */
export async function loadOpenFreeMapTile(
  requestUrl: string,
  signal: AbortSignal,
): Promise<GetResourceResponse<ArrayBuffer>> {
  let failure: unknown;
  let fresh = false;
  for (let attempt = 0; attempt < TILE_TRIES; attempt++) {
    if (attempt > 0) await sleep(backoffDelay(TILE_BACKOFF, attempt - 1), signal);
    try {
      return await tryTile(requestUrl, signal, fresh);
    } catch (error) {
      if (signal.aborted) throw error;
      failure = error;
      fresh = error instanceof NotATileError;
    }
  }
  throw failure;
}
