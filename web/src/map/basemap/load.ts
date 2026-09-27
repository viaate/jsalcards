/**
 * Loads everything the WebGL basemap needs, all at once, after first paint.
 *
 * The downloads start together, so none waits on another:
 *
 * - the basemap code (index.ts and its styles),
 * - MapLibre's page module (maplibre.ts),
 * - MapLibre's shared module (maplibre-shared.ts), which the page module
 *   imports and MapLibre's workers import too, so it downloads once,
 * - the worker's source (maplibre-worker.ts), a few KB,
 * - the street tiles code (street-tiles.ts), which the workers import to cut
 *   street tiles to the US, so it downloads once too,
 * - the school tiles code (school-tiles.ts), which the workers import to read
 *   the school directory's tiles, likewise,
 * - the bundled continental US lines, which the map is created with, so no
 *   worker has to fetch them after it boots.
 *
 * The US mask archive itself is read by the workers, a range at a time, only
 * once the map needs street tiles (zoom 7 and up); the school tiles, when
 * this build ships them, likewise from zoom 11.
 *
 * This module is small and ships in the entry chunk; the map code does not.
 */
import type { Basemap, BasemapOptions } from './index';
import type { UsLinesData } from './style';
import { US_LINES_FILE } from './us-geo';
import { US_MASK_FILE } from './us-mask';

export interface BasemapFactory {
  /** Creates the map. Synchronous: everything it needs is already here. */
  create(options: BasemapOptions): Basemap;
}

/** URL of a file in public/, resolved against the site base so it works under a GitHub Pages path. */
export function publicUrl(path: string): string {
  return new URL(`${import.meta.env.BASE_URL}${path}`, document.baseURI).href;
}

/** Fetches and parses the bundled continental US lines. */
export async function fetchUsLines(): Promise<UsLinesData> {
  const url = publicUrl(US_LINES_FILE);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${String(response.status)}`);
  const data: unknown = await response.json();
  if (!isUsLines(data)) throw new Error(`${url}: not a GeoJSON FeatureCollection`);
  return data;
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
  const [code, maplibre, shared, worker, streetTiles, schoolTiles, usLines] = await Promise.all([
    import('./index'),
    import('./maplibre'),
    import('./maplibre-shared'),
    import('./maplibre-worker'),
    import('./street-tiles'),
    import('./school-tiles'),
    fetchUsLines(),
  ]);
  const workerUrl = worker.workerUrl({
    shared: shared.SHARED_URL,
    streetTiles: streetTiles.STREET_TILES_URL,
    schoolTiles: schoolTiles.SCHOOL_TILES_URL,
    mask: publicUrl(US_MASK_FILE),
  });
  code.startWorkers(maplibre, workerUrl);
  const schools = code.schoolTilesArchive();
  return {
    create: (options) => code.createBasemap({ ...options, maplibre, workerUrl, usLines, schools }),
  };
}
