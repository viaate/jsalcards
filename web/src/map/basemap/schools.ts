/**
 * Every school in the directory on the map, from schools.pmtiles (the
 * pipeline's directory build; its workers serve it, school-tiles.ts):
 *
 * - from zoom 11, a dot at each school, under the glow and every label, so
 *   each school can be found on its street whatever it says today: light
 *   grey across a metro, white from the zoom names come in at, each ringed in
 *   the ground so it stands clear of the streets under it;
 * - from zoom 13, each school's name beside its dot in white, the brightest
 *   text on the map, placed before every other label so no street or place
 *   name covers it, and never over another name: where names would collide,
 *   fewer are shown. A campus written after the school's name ("The Pembroke
 *   Hill School - Wornall Campus") goes on a line of its own, a step dimmer.
 *
 * From the zoom names come in at, each dot also keeps its own space: an
 * unseen mark over every label, placed first, so no name, school or street,
 * is ever drawn across a school's dot.
 *
 * Each class is fully drawn at the zoom it is named from, fading in over the
 * quarter level before it, so a view at a whole zoom level shows it all.
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

/**
 * Zoom levels the tileset holds (pipeline/snowlight/directory/tiles.py: 9 to
 * 14, every school at each); deeper tiles are overzoomed.
 */
export const SCHOOL_TILES_MIN_ZOOM = 10;
export const SCHOOL_TILES_MAX_ZOOM = 14;
/** Dots, fully drawn from this zoom. */
export const SCHOOL_DOTS_FROM = 11;
/** Names, fully drawn from this zoom. */
export const SCHOOL_NAMES_FROM = 13;
/** Zoom levels a class takes to fade in, before the zoom it is drawn from. */
export const SCHOOL_FADE = 0.25;
/** Where the campus part of a name starts: after a spaced dash. */
const CAMPUS_MARK = ' - ';

/** A dot's radius and its ring's width in CSS pixels, by zoom. */
const DOT_RADIUS: readonly (readonly [zoom: number, px: number])[] = [
  [SCHOOL_DOTS_FROM, 2.4],
  [12, 2.9],
  [13, 3.1],
  [15, 4.5],
  [17, 6],
];
const DOT_RING: readonly (readonly [zoom: number, px: number])[] = [
  [SCHOOL_DOTS_FROM, 1],
  [15, 1.5],
];

/**
 * The image a dot's space is measured with (index.ts adds it when the map
 * asks for it): a square SCHOOL_SPACE_SIZE px across with nothing in it.
 */
export const SCHOOL_SPACE_IMAGE = 'snowlight-school-space';
export const SCHOOL_SPACE_SIZE = 16;

/** Its pixels: none drawn. */
export function schoolSpaceImage(): { width: number; height: number; data: Uint8Array } {
  const size = SCHOOL_SPACE_SIZE;
  return { width: size, height: size, data: new Uint8Array(size * size * 4) };
}

export interface SchoolColors {
  /** Dots across a metro, and the campus line of a name. */
  readonly bright: string;
  /** Names, and dots from the zoom names come in at. */
  readonly name: string;
  /** The ground: the ring around each dot and the halo behind each name. */
  readonly ground: string;
}

/** The URL template of an archive's tiles, for a style source. */
export function schoolTilesTemplate(archiveUrl: string): string {
  return `${SCHOOL_TILES_PROTOCOL}://${archiveUrl}/{z}/{x}/{y}`;
}

/**
 * The source. Its tiles are read only where a school layer is drawn, from
 * the dots' fade just below zoom 11, so nothing is read further out.
 */
export function schoolSource(archiveUrl: string): VectorSourceSpecification {
  return {
    type: 'vector',
    tiles: [schoolTilesTemplate(archiveUrl)],
    minzoom: SCHOOL_TILES_MIN_ZOOM,
    maxzoom: SCHOOL_TILES_MAX_ZOOM,
  };
}

function byZoom(...stops: (number | string)[]): ExpressionSpecification {
  return ['interpolate', ['linear'], ['zoom'], ...stops] as unknown as ExpressionSpecification;
}

/** MapLibre's linear interpolation between stops, at `zoom`. */
function at(stops: readonly (readonly [number, number])[], zoom: number): number {
  const first = stops[0];
  if (first === undefined) return 0;
  if (zoom <= first[0]) return first[1];
  for (let i = 1; i < stops.length; i++) {
    const [z0, v0] = stops[i - 1] ?? first;
    const [z1, v1] = stops[i] ?? first;
    if (zoom <= z1) return v0 + ((v1 - v0) * (zoom - z0)) / (z1 - z0);
  }
  return stops[stops.length - 1]?.[1] ?? 0;
}

/**
 * A dot at every school, light grey across a metro and white up close, each
 * ringed in the ground color. Big and bright enough at zoom 11 and 12 to pick
 * out every school in a city at a glance, and never a status color: what a
 * school is doing today is the glow's.
 */
export function schoolDotLayer(colors: SchoolColors): CircleLayerSpecification {
  const fadeIn = byZoom(SCHOOL_DOTS_FROM - SCHOOL_FADE, 0, SCHOOL_DOTS_FROM, 1);
  return {
    id: BASEMAP_IDS.schoolDots,
    type: 'circle',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_DOTS_FROM - SCHOOL_FADE,
    paint: {
      'circle-radius': byZoom(...DOT_RADIUS.flat()),
      // White from zoom 13, the zoom names come in at: a named school's dot matches its name.
      'circle-color': byZoom(SCHOOL_DOTS_FROM, colors.bright, SCHOOL_NAMES_FROM, colors.name),
      'circle-opacity': fadeIn,
      'circle-stroke-color': colors.ground,
      'circle-stroke-width': byZoom(...DOT_RING.flat()),
      'circle-stroke-opacity': fadeIn,
      'circle-pitch-alignment': 'map',
    },
  };
}

/**
 * A school's name as its label shows it: the name, and a campus written
 * after a spaced dash on a second line, smaller and dimmer.
 */
export function schoolLabel(colors: SchoolColors): ExpressionSpecification {
  const name: ExpressionSpecification = ['coalesce', ['get', 'name'], ''];
  return [
    'let',
    'name',
    name,
    'cut',
    ['index-of', CAMPUS_MARK, name],
    [
      'case',
      ['>', ['var', 'cut'], 0],
      [
        'format',
        ['slice', ['var', 'name'], 0, ['var', 'cut']],
        {},
        '\n',
        {},
        ['slice', ['var', 'name'], ['+', ['var', 'cut'], CAMPUS_MARK.length]],
        { 'font-scale': 0.88, 'text-color': colors.bright },
      ],
      ['format', ['var', 'name'], {}],
    ],
  ] as unknown as ExpressionSpecification;
}

/** Each school's name beside its dot, on whichever side has room. */
export function schoolNameLayer(colors: SchoolColors): SymbolLayerSpecification {
  return {
    id: BASEMAP_IDS.schoolNames,
    type: 'symbol',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_NAMES_FROM - SCHOOL_FADE,
    layout: {
      'text-field': schoolLabel(colors),
      'text-font': [MAP_FONTS.medium],
      // A size above every street name's at each zoom, so a school reads first.
      'text-size': byZoom(SCHOOL_NAMES_FROM, 12, 15, 13.5, 17, 15),
      // Beside the dot first, then above or below it, then at a corner: wherever there is room.
      'text-variable-anchor': [
        'left',
        'right',
        'top',
        'bottom',
        'bottom-left',
        'bottom-right',
        'top-left',
        'top-right',
      ],
      'text-radial-offset': 0.75,
      'text-justify': 'auto',
      'text-max-width': 11,
      'text-line-height': 1.2,
      'text-letter-spacing': 0.01,
      'text-padding': 1,
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-optional': false,
    },
    paint: {
      'text-color': colors.name,
      'text-opacity': byZoom(SCHOOL_NAMES_FROM - SCHOOL_FADE, 0, SCHOOL_NAMES_FROM, 1),
      'text-halo-color': colors.ground,
      'text-halo-width': 1.5,
      'text-halo-blur': 0.5,
    },
  };
}

/**
 * Each dot's space, from the zoom names come in at: an unseen square the size
 * of the dot and its ring, placed before every label (it goes over the school
 * names) and always, so names avoid every dot as they avoid each other.
 */
export function schoolSpaceLayer(): SymbolLayerSpecification {
  const zooms = [...new Set([SCHOOL_NAMES_FROM, ...DOT_RADIUS.map(([z]) => z)])]
    .filter((z) => z >= SCHOOL_NAMES_FROM)
    .sort((a, b) => a - b);
  const size = zooms.flatMap((z) => [
    z,
    Math.round(((2 * (at(DOT_RADIUS, z) + at(DOT_RING, z))) / SCHOOL_SPACE_SIZE) * 1000) / 1000,
  ]);
  return {
    id: BASEMAP_IDS.schoolSpace,
    type: 'symbol',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_NAMES_FROM - SCHOOL_FADE,
    layout: {
      'icon-image': SCHOOL_SPACE_IMAGE,
      'icon-size': byZoom(...size),
      'icon-allow-overlap': true,
      'icon-ignore-placement': false,
      'icon-padding': 0.5,
      'icon-rotation-alignment': 'viewport',
      'icon-pitch-alignment': 'viewport',
    },
    paint: { 'icon-opacity': 0 },
  };
}
