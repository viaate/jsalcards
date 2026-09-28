/**
 * Loads everything the WebGL basemap needs, all at once, after first paint.
 *
 * The downloads start together, a few a task, so none waits on another
 * (MapLibre's page module runs only once its shared module has, each in a
 * task of its own):
 *
 * - the basemap code (index.ts; its styles are in index.html),
 * - MapLibre's page module (maplibre.ts),
 * - MapLibre's shared module (maplibre-shared.ts), which the page module
 *   imports and MapLibre's workers import too, so it downloads once,
 * - the worker's source (maplibre-worker.ts), a few KB,
 * - the street tiles code (street-tiles.ts), which the workers import to cut
 *   street tiles to the US, so it downloads once too,
 * - the school tiles code (school-tiles.ts), which the workers import to read
 *   the school directory's tiles, likewise,
 * - the bundled continental US lines' city and state names, which the page
 *   reads to set the national view's names,
 * - the bundled lines themselves, which the page does not read: MapLibre's
 *   worker reads them from the browser's cache once the map asks for them,
 *   so it does not wait on the network then.
 *
 * The US mask archive itself is read by the workers, a range at a time, only
 * once the map needs street tiles (zoom 7 and up); the school tiles, when
 * this build ships them, likewise from zoom 9.
 *
 * This module is small and ships in the entry chunk; the map code does not.
 */
import MAPLIBRE_URL from 'virtual:snowlight/maplibre-url';

import type { Basemap, BasemapOptions } from './index';
import { yieldToMain } from './reveal';
import type { UsLinesData } from './style';
import { US_LINES_FILE, US_NAMES_FILE, US_STATES_FILE } from './us-geo';
import { US_MASK_FILE } from './us-mask';

export interface BasemapFactory {
  /** Creates the map: everything it needs is already here. */
  create(options: BasemapOptions): Promise<Basemap>;
}

/** URL of a file in public/, resolved against the site base so it works under a GitHub Pages path. */
export function publicUrl(path: string): string {
  return new URL(`${import.meta.env.BASE_URL}${path}`, document.baseURI).href;
}

/** Fetches and parses the bundled lines' city and state names. */
export async function fetchUsNames(): Promise<UsLinesData> {
  const url = publicUrl(US_NAMES_FILE);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${String(response.status)}`);
  const data: unknown = await response.json();
  if (!isUsLines(data)) throw new Error(`${url}: not a GeoJSON FeatureCollection`);
  return data;
}

/**
 * Downloads the bundled lines without reading them: MapLibre's worker reads
 * them, from the browser's cache, once the map asks for them.
 */
export async function fetchUsLines(): Promise<void> {
  const url = publicUrl(US_LINES_FILE);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${String(response.status)}`);
  await response.arrayBuffer();
}

/** Has the browser fetch and compile a module now, without running it (a module preload). */
export function preloadModule(url: string): void {
  if (document.querySelector(`link[rel="modulepreload"][href="${url}"]`) !== null) return;
  const link = document.createElement('link');
  link.rel = 'modulepreload';
  link.href = url;
  document.head.append(link);
}

function isUsLines(data: unknown): data is UsLinesData {
  if (typeof data !== 'object' || data === null) return false;
  const { type, features } = data as { type?: unknown; features?: unknown };
  return type === 'FeatureCollection' && Array.isArray(features);
}

/**
 * Starts every download the map needs and resolves once all have arrived, the
 * modules have run and MapLibre's workers are starting. Rejects if any
 * download fails; the still then stays.
 */
export async function loadBasemap(): Promise<BasemapFactory> {
  // MapLibre's two modules download together but run one after the other, each in a task of
  // its own: imported together, they arrive together and run in one long task. The page module
  // is preloaded (fetched and compiled, not run) and imported once the shared one has run.
  preloadModule(MAPLIBRE_URL);
  const sharedModule = import('./maplibre-shared');
  sharedModule.catch(() => undefined);
  // The rest are asked for in the tasks after, a few at a time: asking for a download is work
  // of its own on the page's main thread, some twenty of them at once a long task.
  await yieldToMain();
  const code = Promise.all([import('./index'), import('./maplibre-worker')]);
  code.catch(() => undefined);
  await yieldToMain();
  const rest = Promise.all([
    import('./street-tiles'),
    import('./school-tiles'),
    fetchUsNames(),
    fetchUsLines(),
  ]);
  // Held until they are awaited below: a download that fails at once is not left unhandled.
  rest.catch(() => undefined);
  const shared = await sharedModule;
  await yieldToMain();
  const maplibre = await import('./maplibre');
  await yieldToMain();
  const [[basemap, worker], [streetTiles, schoolTiles, usNames]] = await Promise.all([code, rest]);
  const workerUrl = worker.workerUrl({
    shared: shared.SHARED_URL,
    streetTiles: streetTiles.STREET_TILES_URL,
    schoolTiles: schoolTiles.SCHOOL_TILES_URL,
    mask: publicUrl(US_MASK_FILE),
  });
  basemap.startWorkers(maplibre, workerUrl);
  await yieldToMain();
  const schools = basemap.schoolTilesArchive();
  return {
    create: (options) =>
      basemap.createBasemap({
        ...options,
        maplibre,
        workerUrl,
        usNames,
        // MapLibre's workers read the lines and the names themselves: the page never hands
        // them over, a property at a time, on its main thread.
        usLinesUrls: { lines: publicUrl(US_LINES_FILE), names: publicUrl(US_NAMES_FILE) },
        schools,
        stateAreas: publicUrl(US_STATES_FILE),
      }),
  };
}
