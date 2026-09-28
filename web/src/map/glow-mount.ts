/**
 * Puts the glow layer on the map, right over the style's slot for it
 * (BASEMAP_IDS.glowSlot): over the ground, the lines and the national view's
 * city names, so a city's lights shine over its name; under every label from
 * zoom 7, so street and place names stay crisp above the light up close.
 *
 * This module loads with the map's own code, after the first paint, and the
 * layer goes on the map with its style, before the map's first frame: adding
 * it later would make the map draw every frame again. Until schools are lit
 * it holds no points, draws nothing and compiles nothing on the GPU.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { LitSchools } from '../data/closings';
import { BASEMAP_IDS } from './basemap/ids';
import { GlowLayer } from './glow';

export const GLOW_LAYER_ID = BASEMAP_IDS.glow;

export interface Glow {
  /** Shows these schools, replacing the ones shown before. */
  light(lit: LitSchools): void;
  remove(): void;
}

export function mountGlow(map: MapLibreMap): Glow {
  const layer = new GlowLayer({ id: GLOW_LAYER_ID });
  const add = (): void => {
    if (map.getLayer(GLOW_LAYER_ID) !== undefined) return;
    // Right over its slot, whichever layers the map has on so far (index.ts adds them in turn).
    const order = map.getLayersOrder();
    const slot = order.indexOf(BASEMAP_IDS.glowSlot);
    map.addLayer(layer, slot < 0 ? undefined : order[slot + 1]);
  };
  if (map.isStyleLoaded() === true) add();
  else map.once('style.load', add);
  return {
    light(lit) {
      layer.setData(
        lit.bornAt === undefined
          ? { lngLat: lit.lngLat, status: lit.status }
          : { lngLat: lit.lngLat, status: lit.status, bornAt: lit.bornAt },
      );
    },
    remove() {
      map.off('style.load', add);
      try {
        if (map.getLayer(GLOW_LAYER_ID) !== undefined) map.removeLayer(GLOW_LAYER_ID);
      } catch {
        // The map is gone already, and the layer with it.
      }
    },
  };
}
