import type { AddProtocolAction, GetResourceResponse } from 'maplibre-gl';

import type { MapLibre } from './maplibre';

/**
 * OpenFreeMap vector tiles, used from zoom 7 up.
 *
 * The public TileJSON points at a dated tile set that changes over time, so
 * tiles are requested through a custom protocol: the style names
 * `openfreemap://planet/{z}/{x}/{y}` and the TileJSON is only fetched when the
 * first zoom 7+ tile is needed. Below zoom 7 nothing leaves the site.
 */

const PROTOCOL = 'openfreemap';
const TILEJSON_URL = 'https://tiles.openfreemap.org/planet';

export const OPENFREEMAP_TILES = `${PROTOCOL}://planet/{z}/{x}/{y}`;
export const OPENFREEMAP_MIN_ZOOM = 7;
export const OPENFREEMAP_MAX_ZOOM = 14;

/** License-required credit for OpenFreeMap, OpenMapTiles and OpenStreetMap. */
export const OPENFREEMAP_ATTRIBUTION = [
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a>',
  '<a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">&copy; OpenMapTiles</a>',
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">&copy; OpenStreetMap contributors</a>',
].join(' ');

const TILE_PATH = /\/(\d+)\/(\d+)\/(\d+)$/;

let template: Promise<string> | undefined;

async function fetchTemplate(): Promise<string> {
  const response = await fetch(TILEJSON_URL);
  if (!response.ok) throw new Error(`OpenFreeMap TileJSON: HTTP ${String(response.status)}`);
  const tilejson = (await response.json()) as { tiles?: unknown };
  const first: unknown = Array.isArray(tilejson.tiles) ? tilejson.tiles[0] : undefined;
  if (typeof first !== 'string' || !first.includes('{z}')) {
    throw new Error('OpenFreeMap TileJSON: no tile URL template');
  }
  return first;
}

/** The current dated tile URL template; a failed lookup is retried on the next tile. */
function tileTemplate(): Promise<string> {
  template ??= fetchTemplate().catch((error: unknown) => {
    template = undefined;
    throw error;
  });
  return template;
}

export function tileUrl(templateUrl: string, requestUrl: string): string {
  const match = TILE_PATH.exec(requestUrl);
  if (match === null) throw new Error(`OpenFreeMap: unexpected tile request ${requestUrl}`);
  const [, z = '', x = '', y = ''] = match;
  return templateUrl.replace('{z}', z).replace('{x}', x).replace('{y}', y);
}

const loadTile: AddProtocolAction = async (request, abortController) => {
  let url = tileUrl(await tileTemplate(), request.url);
  let response = await fetch(url, { signal: abortController.signal });
  if (response.status === 404) {
    // The dated tile set was retired while the page was open: look up the current one once.
    template = undefined;
    url = tileUrl(await tileTemplate(), request.url);
    response = await fetch(url, { signal: abortController.signal });
  }
  if (!response.ok) throw new Error(`OpenFreeMap tile: HTTP ${String(response.status)}`);
  const result: GetResourceResponse<ArrayBuffer> = {
    data: await response.arrayBuffer(),
    cacheControl: response.headers.get('cache-control'),
    expires: response.headers.get('expires'),
  };
  return result;
};

/** Lets the style's `openfreemap://` tile URLs load. Safe to call more than once. */
export function registerOpenFreeMap(maplibre: MapLibre): void {
  maplibre.addProtocol(PROTOCOL, loadTile);
}
