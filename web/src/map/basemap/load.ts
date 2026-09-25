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
 * - the bundled continental US lines, which the map is created with, so no
 *   worker has to fetch them after it boots.
 *
 * This module is small and ships in the entry chunk; the map code does not.
 */
import type { Basemap, BasemapOptions } from './index';
import type { UsLinesData } from './style';
import { US_LINES_FILE } from './us-geo';

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
  const [code, maplibre, shared, worker, usLines] = await Promise.all([
    import('./index'),
    import('./maplibre'),
    import('./maplibre-shared'),
    import('./maplibre-worker'),
    fetchUsLines(),
  ]);
  const workerUrl = worker.workerUrl(shared.SHARED_URL);
  code.startWorkers(maplibre, workerUrl);
  return {
    create: (options) => code.createBasemap({ ...options, maplibre, workerUrl, usLines }),
  };
}
