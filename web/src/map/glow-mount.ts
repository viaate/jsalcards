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
 * dust, the same dot dimmed and shrunk (basemap/dots.ts), from the directory:
 * read the first time the map is at a zoom that shows dust, so the national
 * view reads nothing for it, and followed to the copy the live file's places
 * point into whenever schools light. The dust shows the kinds of school the
 * menu shows, and the open school whatever its kind, as the dots do
 * (basemap/schools.ts schoolKindFilter), and a tap on a speck finds its
 * school as a tap on a dot does (school-taps.ts): where each school is and
 * who it is come from the one directory, so no speck shows that a tap could
 * not open, or that would open another school.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { LitSchools } from '../data/closings';
import type { SchoolId } from '../types/generated';
import {
  SCHOOL_DOT_OPACITY,
  SCHOOL_DOT_RADIUS,
  SCHOOL_DOT_SOFTNESS,
  SCHOOL_DUST_FROM,
  SCHOOL_DUST_UNTIL,
} from './basemap/dots';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE } from './basemap/ids';
import { GlowLayer } from './glow';
import { glowStyleAtZoom } from './glow/curves';
import type { DustStyle } from './glow/dust';

export const GLOW_LAYER_ID = BASEMAP_IDS.glow;

/**
 * How far a lit school's light reaches as a mark at a zoom, in CSS pixels,
 * for a click on it (school-taps.ts): its glyph once glyphs are drawn, else
 * two standard deviations of its bright core or, far out, of the blend that
 * carries its light. The blend's reach falls with the square of its share, as
 * its faint wash stops reading as the school's own once its core shows.
 */
export function litRadius(zoom: number): number {
  const style = glowStyleAtZoom(zoom);
  if (style.glyphOpacity >= 0.5) return style.glyphRadiusPx;
  const blend = 1 - style.coreShare;
  return Math.max(2 * style.coreSigmaPx, 2 * style.blendSigmaPx * blend * blend);
}

/**
 * The dots' white: the page's --text-1 (src/styles/global.css), which the
 * basemap draws the school dots in. A constant, so putting the glow on the
 * map reads no style from the page.
 */
export const DOT_COLOR = '#f5f5f5';

/** Every school as the dust draws it, in directory order: where each is, its kind and who it is. */
export interface DustSchools {
  /** Longitude and latitude in degrees, interleaved. */
  readonly lngLat: Float64Array;
  readonly kind: Uint8Array;
  readonly ids: readonly SchoolId[];
  /** Each one's name as the directory writes it. */
  readonly names: readonly string[];
}

/**
 * Where the dust comes from: every school, from the directory the page reads
 * now, the one a lit school's place points into. Null when there is none.
 */
export type DustSource = () => Promise<DustSchools | null>;

/** The schools drawn as dust, for a tap on a speck (school-taps.ts). */
export interface DustSpots extends Omit<DustSchools, 'kind'> {
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
   * `source`: read the first time the map is at a zoom that shows dust, then
   * again each time schools light, and drawn again only if it gives another
   * directory, so a lit school's place always means the same school in both.
   */
  dust(source: DustSource): void;
  /**
   * Shows as dust only the schools whose kind flags `shows` keeps: the kinds
   * the menu's filter shows (state/filter.ts showsSchool), as the dots show.
   */
  showSchools(shows: (flags: number) => boolean): void;
  /** Shows this school as dust whatever its kind, as the dots show the open one; null, none. */
  select(id: SchoolId | null): void;
  /** The dust, for a tap on a speck; null until it is drawn. */
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
  /** And from then on, with the reads made so far, the last of which the dust follows. */
  let followed: DustSource | null = null;
  let reads = 0;
  let specks: DustSpots | null = null;
  let selected: SchoolId | null = null;
  /** The open school's speck kept, once the dust knows who each school is. */
  const keepSelected = (): void => {
    const school = selected === null ? -1 : (specks?.ids.indexOf(selected) ?? -1);
    layer.keepDust(school < 0 ? null : school);
  };
  /** Reads the dust, and draws it unless a later read is on its way or it is the one drawn. */
  const readDust = (from: DustSource): void => {
    const read = ++reads;
    void (async () => {
      const schools = await from().catch(() => null);
      if (gone() || read !== reads || schools === null) return;
      if (schools.lngLat === specks?.lngLat) return;
      layer.setDust(schools.lngLat, schools.kind);
      specks = {
        lngLat: schools.lngLat,
        ids: schools.ids,
        names: schools.names,
        near: (x, y, reach) => layer.dustNear(x, y, reach),
      };
      keepSelected();
    })();
  };
  const watchZoom = (): void => {
    if (pending === null || !showsDust(map.getZoom())) return;
    followed = pending;
    pending = null;
    map.off('zoom', watchZoom);
    readDust(followed);
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
      // Its places are in the directory read against the live file's stamp, which can replace
      // an older copy the dust was read from: the dust follows it there.
      if (followed !== null) readDust(followed);
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
    select(id) {
      if (id === selected) return;
      selected = id;
      keepSelected();
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
