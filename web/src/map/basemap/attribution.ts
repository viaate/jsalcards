import type { AttributionControl, AttributionControlOptions } from 'maplibre-gl';

import type { MapLibre } from './maplibre';

const COMPACT = 'maplibregl-compact';
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
