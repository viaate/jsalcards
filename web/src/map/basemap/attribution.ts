import type { AttributionControl, AttributionControlOptions } from 'maplibre-gl';

import type { MapLibre } from './maplibre';

const COMPACT = 'maplibregl-compact';

/**
 * License-required credit for the school heights the chances read for alerts that name
 * heights (pipeline/config/elevation.yaml): Mapzen's Terrain Tiles and the elevation data
 * they are made from in the states.
 */
export const TERRAIN_ATTRIBUTION =
  '<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md" target="_blank" rel="noopener">Terrain Tiles by Mapzen: USGS 3DEP, SRTM and GMTED2010, NOAA ETOPO1</a>';
const EXPANDED = 'maplibregl-compact-show';

/**
 * MapLibre's own attribution control, collapsed to its button from the start.
 *
 * In compact mode MapLibre opens the control the first time it turns compact.
 * This closes it again at that moment, so it stays a small button until it is
 * used; MapLibre's toggle then works unchanged (expanded means the
 * `maplibregl-compact-show` class plus the `open` attribute on the details).
 */
export function collapsedAttribution(
  maplibre: MapLibre,
  options: AttributionControlOptions,
): AttributionControl {
  const control = new maplibre.AttributionControl({ ...options, compact: true });
  const updateCompact = control._updateCompact;
  control._updateCompact = () => {
    const container = control._container;
    const wasCompact = container.classList.contains(COMPACT);
    updateCompact();
    if (!wasCompact && container.classList.contains(COMPACT)) {
      container.classList.remove(EXPANDED);
      container.removeAttribute('open');
    }
  };
  return control;
}
