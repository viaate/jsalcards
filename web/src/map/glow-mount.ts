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
 *
 * Each school it lights loses its quiet white dot (basemap/schools.ts), so
 * its light shows in its status's color alone.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { LitSchools } from '../data/closings';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE } from './basemap/ids';
import { GlowLayer } from './glow';
import { glowStyleAtZoom } from './glow/curves';

export const GLOW_LAYER_ID = BASEMAP_IDS.glow;

/**
 * How far a lit school's light reaches as a mark at a zoom, in CSS pixels,
 * for a click on it (school-taps.ts): its glyph once glyphs are drawn, else
 * its bright core, most of whose light is within two standard deviations.
 *
 * Still to do: once the far-out glow blends lone lights into a smooth glow
 * (G1), a lone light reads about 16 to 44 px across at zooms 4.5 to 6, two
 * of the blend's spreads (4 to 11 px) each way. This must then follow that
 * spread: here it is about 2 px there, so such a light takes a mouse's click
 * only about 8 px out from its center, and a finger's about 18 px.
 */
export function litRadius(zoom: number): number {
  const style = glowStyleAtZoom(zoom);
  return style.glyphOpacity >= 0.5 ? style.glyphRadiusPx : 2 * style.coreSigmaPx;
}

export interface Glow {
  /** Shows these schools, replacing the ones shown before. */
  light(lit: LitSchools): void;
  /** The schools shown now, or null before any are: what a tap on a light finds (school-taps.ts). */
  readonly lit: LitSchools | null;
  remove(): void;
}

/** The lit schools' dots, marked by their feature ids: each school's place in the directory. */
interface LitDots {
  /** Marks these schools, and no others. */
  mark(schools: ReadonlySet<number>): void;
  /** Marks them once the style is in, where it was not before. */
  update(): void;
}

function markLitDots(map: MapLibreMap): LitDots {
  let marked: ReadonlySet<number> = new Set();
  let wanted: ReadonlySet<number> = marked;
  const update = (): void => {
    // A build without the school tiles draws no dots, and a map with no style yet none so far.
    if (wanted === marked || map.getSource(BASEMAP_IDS.schoolsSource) === undefined) return;
    const source = { source: BASEMAP_IDS.schoolsSource, sourceLayer: SCHOOLS_TILE_LAYER };
    for (const id of marked) {
      if (!wanted.has(id)) map.removeFeatureState({ ...source, id }, SCHOOL_LIT_STATE);
    }
    for (const id of wanted) {
      if (!marked.has(id)) map.setFeatureState({ ...source, id }, { [SCHOOL_LIT_STATE]: true });
    }
    marked = wanted;
  };
  return {
    mark(schools) {
      wanted = schools;
      update();
    },
    update,
  };
}

export function mountGlow(map: MapLibreMap): Glow {
  const layer = new GlowLayer({ id: GLOW_LAYER_ID });
  const dots = markLitDots(map);
  const add = (): void => {
    dots.update();
    if (map.getLayer(GLOW_LAYER_ID) !== undefined) return;
    // Right over its slot, whichever layers the map has on so far (index.ts adds them in turn).
    const order = map.getLayersOrder();
    const slot = order.indexOf(BASEMAP_IDS.glowSlot);
    map.addLayer(layer, slot < 0 ? undefined : order[slot + 1]);
  };
  if (map.isStyleLoaded() === true) add();
  else map.once('style.load', add);
  let shown: LitSchools | null = null;
  return {
    light(lit) {
      shown = lit;
      layer.setData(
        lit.bornAt === undefined
          ? { lngLat: lit.lngLat, status: lit.status }
          : { lngLat: lit.lngLat, status: lit.status, bornAt: lit.bornAt },
      );
      dots.mark(lit.schools);
    },
    get lit() {
      return shown;
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
