/**
 * MapLibre for the page. load.ts imports this module at run time, after first
 * paint; everything else in the map code imports only its types, so MapLibre
 * stays out of every chunk but its own.
 *
 * Importing maplibre-shared.ts here, as well as on its own from load.ts, puts
 * MapLibre's shared module and that entry's names in one chunk: the chunk
 * MapLibre's workers import. See maplibre-shared.ts.
 */
import type * as MapLibreModule from 'maplibre-gl';

export * from 'maplibre-gl';
export { SHARED_URL } from './maplibre-shared';

/** The parts of the MapLibre module the map code uses at run time. */
export type MapLibre = Pick<
  typeof MapLibreModule,
  | 'AttributionControl'
  | 'LngLat'
  | 'LngLatBounds'
  | 'Map'
  | 'addProtocol'
  | 'prewarm'
  | 'setWorkerCount'
  | 'setWorkerUrl'
>;
