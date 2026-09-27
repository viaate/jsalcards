/**
 * Every school in the directory on the map, from schools.pmtiles (the
 * pipeline's directory build; its workers serve it, school-tiles.ts):
 *
 * - from zoom 11, a small gray dot at each school, under the glow and every
 *   label, so each school can be found on its street whatever it says today;
 * - from zoom 13, each school's name beside its dot, placed before every
 *   other label so no street or place name covers it, and never over another
 *   name: where names would collide, fewer are shown.
 *
 * A dot or a name says only where a school is. What a school is doing today
 * is the glow's to show.
 */
import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  SymbolLayerSpecification,
  VectorSourceSpecification,
} from 'maplibre-gl';

import { MAP_FONTS } from './fonts';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_TILES_PROTOCOL } from './ids';

/** Zoom levels the tileset holds (pipeline/snowlight/directory/tiles.py); deeper tiles are overzoomed. */
export const SCHOOL_TILES_MAX_ZOOM = 14;
/** Dots from this zoom. */
export const SCHOOL_DOTS_FROM = 11;
/** Names from this zoom. */
export const SCHOOL_NAMES_FROM = 13;

export interface SchoolColors {
  /** Dots, and names as they come in. */
  readonly dim: string;
  /** Dots and names up close. */
  readonly bright: string;
  /** Names up close. */
  readonly name: string;
  /** The ground: the ring around each dot and the halo behind each name. */
  readonly ground: string;
}

/** The URL template of an archive's tiles, for a style source. */
export function schoolTilesTemplate(archiveUrl: string): string {
  return `${SCHOOL_TILES_PROTOCOL}://${archiveUrl}/{z}/{x}/{y}`;
}

/** The source: tiles from zoom 11 only, so nothing is read further out. */
export function schoolSource(archiveUrl: string): VectorSourceSpecification {
  return {
    type: 'vector',
    tiles: [schoolTilesTemplate(archiveUrl)],
    minzoom: SCHOOL_DOTS_FROM,
    maxzoom: SCHOOL_TILES_MAX_ZOOM,
  };
}

function byZoom(...stops: (number | string)[]): ExpressionSpecification {
  return ['interpolate', ['linear'], ['zoom'], ...stops] as unknown as ExpressionSpecification;
}

/** A dot at every school: faint further out, a step brighter at street level. */
export function schoolDotLayer(colors: SchoolColors): CircleLayerSpecification {
  return {
    id: BASEMAP_IDS.schoolDots,
    type: 'circle',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_DOTS_FROM,
    paint: {
      'circle-radius': byZoom(SCHOOL_DOTS_FROM, 1.6, 13, 2.4, 15, 3.6, 17, 5),
      'circle-color': byZoom(12, colors.dim, 15, colors.bright),
      'circle-opacity': byZoom(SCHOOL_DOTS_FROM, 0, SCHOOL_DOTS_FROM + 0.25, 1),
      'circle-stroke-color': colors.ground,
      'circle-stroke-width': byZoom(SCHOOL_DOTS_FROM, 0.5, 15, 1),
      'circle-stroke-opacity': byZoom(SCHOOL_DOTS_FROM, 0, SCHOOL_DOTS_FROM + 0.25, 1),
      'circle-pitch-alignment': 'map',
    },
  };
}

/** Each school's name beside its dot, on whichever side has room. */
export function schoolNameLayer(colors: SchoolColors): SymbolLayerSpecification {
  return {
    id: BASEMAP_IDS.schoolNames,
    type: 'symbol',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_NAMES_FROM,
    layout: {
      'text-field': ['coalesce', ['get', 'name'], ''],
      'text-font': [MAP_FONTS.medium],
      'text-size': byZoom(SCHOOL_NAMES_FROM, 11, 16, 13),
      'text-variable-anchor': ['left', 'right', 'top', 'bottom'],
      'text-radial-offset': 0.7,
      'text-justify': 'auto',
      'text-max-width': 9,
      'text-line-height': 1.15,
      'text-letter-spacing': 0.01,
      'text-padding': 2,
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-optional': false,
    },
    paint: {
      'text-color': byZoom(SCHOOL_NAMES_FROM, colors.bright, 14.5, colors.name),
      'text-opacity': byZoom(SCHOOL_NAMES_FROM, 0, SCHOOL_NAMES_FROM + 0.25, 1),
      'text-halo-color': colors.ground,
      'text-halo-width': 1.4,
      'text-halo-blur': 0.4,
    },
  };
}
