/**
 * MapLibre's shared module under its own export names, for MapLibre's worker.
 *
 * MapLibre 6 ships three files: the page module, a shared module and a small
 * worker module. The page and worker modules both import the shared one by
 * the relative name './maplibre-gl-shared.mjs', using its published export
 * names. The bundler renames the exports of an ordinary shared chunk, so this
 * module is an entry of its own (load.ts imports it) that keeps those names.
 * maplibre.ts imports it too, which puts it in the same chunk as the shared
 * module itself: one file that the page imports for MapLibre and each worker
 * imports in place of './maplibre-gl-shared.mjs', downloaded once.
 */

export * from 'maplibre-gl/dist/maplibre-gl-shared.mjs';

/** URL of this chunk: what the worker imports in place of './maplibre-gl-shared.mjs'. */
export const SHARED_URL: string = import.meta.url;
