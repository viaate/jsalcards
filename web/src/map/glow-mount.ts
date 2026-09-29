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
 *
 * Further out than the school tiles reach, the layer draws every school as
 * dust, the same dot dimmed and shrunk (basemap/dots.ts), from the
 * directory's own positions: read the first time the map is at a zoom that
 * shows dust, so the national view reads nothing for it. The dust shows the
 * kinds of school the menu shows, as the dots do, and a tap on a speck finds
 * its school as a tap on a dot does (school-taps.ts), once every school's
 * name is in: read from the directory right after the positions.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { LitSchools } from '../data/closings';
import type { Positions } from '../data/directory';
import type { SchoolId } from '../types/generated';
import {
  SCHOOL_DOT_OPACITY,
  SCHOOL_DOT_RADIUS,
  SCHOOL_DOT_SOFTNESS,
  SCHOOL_DUST_FROM,
  SCHOOL_DUST_TAPS_FROM,
  SCHOOL_DUST_UNTIL,
  dotAt,
} from './basemap/dots';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE } from './basemap/ids';
import { GlowLayer } from './glow';
import { glowStyleAtZoom } from './glow/curves';
import type { DustStyle } from './glow/dust';

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

/**
 * How far a speck of dust reaches as a mark at a zoom, in CSS pixels, for a
 * tap on it (school-taps.ts): its own radius, from the zoom the dust is half
 * faded in (SCHOOL_DUST_TAPS_FROM) until the tiles' dots draw alone; null
 * where no speck takes taps.
 */
export function dustRadius(zoom: number): number | null {
  if (!(zoom >= SCHOOL_DUST_TAPS_FROM && zoom < SCHOOL_DUST_UNTIL)) return null;
  return dotAt(SCHOOL_DOT_RADIUS, zoom);
}

/**
 * The dots' white: the page's --text-1 (src/styles/global.css), which the
 * basemap draws the school dots in. A constant, so putting the glow on the
 * map reads no style from the page.
 */
export const DOT_COLOR = '#f5f5f5';

/** Who each school is, in directory order: its id, and its name as the directory writes it. */
export interface SchoolNames {
  readonly ids: readonly SchoolId[];
  readonly names: readonly string[];
}

/** Where the dust comes from: every school, and then who each is. Null when there are none. */
export interface DustSource {
  positions(): Promise<Positions | null>;
  names(): Promise<SchoolNames | null>;
}

/** The schools drawn as dust, for a tap on a speck (school-taps.ts). */
export interface DustSpots extends SchoolNames {
  /** Every school's longitude and latitude in degrees, in directory order. */
  readonly lngLat: Float64Array;
  /**
   * The schools whose specks are drawn within `reach` Web Mercator units of
   * (x, y) each way, by their places in the directory.
   */
  near(x: number, y: number, reach: number): readonly number[];
}

export interface Glow {
  /** Shows these schools, replacing the ones shown before. */
  light(lit: LitSchools): void;
  /** The schools shown now, or null before any are: what a tap on a light finds (school-taps.ts). */
  readonly lit: LitSchools | null;
  /**
   * Shows every school as dust further out than the school tiles reach, from
   * `source`, read once: the first time the map is at a zoom that shows dust.
   */
  dust(source: DustSource): void;
  /**
   * Shows as dust only the schools whose kind flags `shows` keeps: the kinds
   * the menu's filter shows (state/filter.ts showsSchool), as the dots show.
   */
  showSchools(shows: (flags: number) => boolean): void;
  /** The dust, for a tap on a speck; null until every school's name is in. */
  readonly specks: DustSpots | null;
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

/** A #rrggbb color as sRGB channels 0..1, or null for anything else. */
export function srgbChannels(hex: string): [number, number, number] | null {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (match === null) return null;
  const channel = (i: number): number => Number.parseInt(match[i] ?? '0', 16) / 255;
  return [channel(1), channel(2), channel(3)];
}

/** The dust: the dots' curves (basemap/dots.ts) in the dots' white. */
export function dustStyle(): DustStyle {
  return {
    from: SCHOOL_DUST_FROM,
    until: SCHOOL_DUST_UNTIL,
    radius: SCHOOL_DOT_RADIUS,
    opacity: SCHOOL_DOT_OPACITY,
    softness: SCHOOL_DOT_SOFTNESS,
    color: srgbChannels(DOT_COLOR) ?? [1, 1, 1],
  };
}

/** Whether the map is at a zoom that shows dust. */
export function showsDust(zoom: number): boolean {
  return zoom > SCHOOL_DUST_FROM && zoom < SCHOOL_DUST_UNTIL;
}

export function mountGlow(map: MapLibreMap): Glow {
  const layer = new GlowLayer({ id: GLOW_LAYER_ID, dust: dustStyle() });
  const dots = markLitDots(map);
  let removed = false;
  // A function, so each check reads it afresh after an await.
  const gone = (): boolean => removed;
  let dustAsked = false;
  /** Where to read the dust from, until the map first shows it. */
  let pending: DustSource | null = null;
  let specks: DustSpots | null = null;
  const watchZoom = (): void => {
    if (pending === null || !showsDust(map.getZoom())) return;
    const source = pending;
    pending = null;
    map.off('zoom', watchZoom);
    void (async () => {
      const positions = await source.positions().catch(() => null);
      if (gone() || positions === null) return;
      layer.setDust(positions.lngLat, positions.kind);
      // Then who each school is, for a tap on its speck.
      const names = await source.names().catch(() => null);
      const count = positions.kind.length;
      if (gone() || names?.ids.length !== count) return;
      specks = {
        lngLat: positions.lngLat,
        ids: names.ids,
        names: names.names,
        near: (x, y, reach) => layer.dustNear(x, y, reach),
      };
    })();
  };
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
      layer.hideDust(lit.schools);
    },
    dust(source) {
      if (removed || dustAsked) return;
      dustAsked = true;
      pending = source;
      map.on('zoom', watchZoom);
      watchZoom();
    },
    showSchools(shows) {
      layer.filterDust(shows);
    },
    get lit() {
      return shown;
    },
    get specks() {
      return specks;
    },
    remove() {
      removed = true;
      pending = null;
      map.off('style.load', add);
      map.off('zoom', watchZoom);
      try {
        if (map.getLayer(GLOW_LAYER_ID) !== undefined) map.removeLayer(GLOW_LAYER_ID);
      } catch {
        // The map is gone already, and the layer with it.
      }
    },
  };
}
