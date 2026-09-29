/**
 * Every school in the directory on the map, from schools.pmtiles (the
 * pipeline's directory build; its workers serve it, school-tiles.ts):
 *
 * - from a metro's zoom (SCHOOL_DOTS_FROM), a dot at each school, under the
 *   glow and every label, so every school in a city is seen at once and each
 *   can be found on its street whatever it says today: white, the brightest
 *   mark on the map, each ringed in the ground so it stands clear of the
 *   streets under it and of the dot beside it;
 * - across a metro, a soft light around each dot, the way a town's lights
 *   read from orbit: where schools crowd, their light gathers. It is gone by
 *   the zoom names come in at, where each school's name takes its place;
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
 * Each class is fully drawn at the zoom it is named from, fading in before
 * it, so a view at that zoom shows it all.
 *
 * A dot or a name says only where a school is. What a school is doing today
 * is the glow's to show, in its colors: the dots and their light are white,
 * and a school the glow lights has neither (SCHOOL_LIT_STATE), so no white
 * shows through its light, the hole of its ring or the open half of its dot.
 * The school whose panel is open has a ring around its dot, a faint disc
 * edged in white, under the dot, so the one the panel is about is found at a
 * glance.
 */
import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  FilterSpecification,
  SymbolLayerSpecification,
  VariableAnchorOffsetCollectionSpecification,
  VectorSourceSpecification,
} from 'maplibre-gl';

import { MAP_FONTS } from './fonts';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE, SCHOOL_TILES_PROTOCOL } from './ids';

/**
 * Zoom levels the tileset holds (pipeline/snowlight/directory/tiles.py: 9 to
 * 14, every school at each); deeper tiles are overzoomed.
 */
export const SCHOOL_TILES_MIN_ZOOM = 9;
export const SCHOOL_TILES_MAX_ZOOM = 14;
/**
 * Dots, fully drawn from this zoom: a metro's whole area on a laptop's
 * screen, and wider. The dots fade in over SCHOOL_DOT_FADE before it, from
 * the first zoom the tileset holds.
 */
export const SCHOOL_DOTS_FROM = 9.5;
export const SCHOOL_DOT_FADE = 0.5;
/** The light around each dot: all of it until this zoom, gone by the zoom names come in at. */
export const SCHOOL_LIGHT_UNTIL = 12;
/** Names, fully drawn from this zoom. */
export const SCHOOL_NAMES_FROM = 13;
/** Zoom levels a class takes to fade in, before the zoom it is drawn from. */
export const SCHOOL_FADE = 0.25;
/** Clear space kept around each school's name, in CSS pixels. */
export const SCHOOL_NAME_PADDING = 5;
/** Where the campus part of a name starts: after a spaced dash. */
const CAMPUS_MARK = ' - ';

/**
 * A dot's radius and its ring's width in CSS pixels, by zoom: a point of
 * light across a metro, where a city's schools stand a few pixels apart,
 * growing to a mark beside a name up close.
 */
const DOT_RADIUS: readonly (readonly [zoom: number, px: number])[] = [
  [9, 1.7],
  [10, 2.4],
  [11, 2.7],
  [12, 2.9],
  [13, 3.1],
  [15, 4.5],
  [17, 6],
];
const DOT_RING: readonly (readonly [zoom: number, px: number])[] = [
  [9, 0.8],
  [11, 1],
  [15, 1.5],
];
/**
 * The light around a dot: its radius in CSS pixels, by zoom, and its
 * strength at the center, fading to nothing at its edge. Soft, so a lone
 * school reads as one point of light and a crowded district as a glow, and
 * well under the glow's own light, so a lit school outshines every dot.
 */
const LIGHT_RADIUS: readonly (readonly [zoom: number, px: number])[] = [
  [9, 7],
  [10, 9],
  [12, 11],
];
export const SCHOOL_LIGHT_OPACITY = 0.3;

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
  /** The campus line of a name. */
  readonly bright: string;
  /** Names, dots and the light around them. */
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
 * the dots' fade at zoom 9, the first zoom the tileset holds, so nothing is
 * read further out.
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

/** Whether the glow lights this school today (glow-mount.ts). */
const LIT: ExpressionSpecification = ['boolean', ['feature-state', SCHOOL_LIT_STATE], false];

/** An opacity by zoom, as [zoom, opacity] stops, and none for a school the glow lights. */
function unlessLit(
  ...stops: readonly (readonly [zoom: number, opacity: number])[]
): ExpressionSpecification {
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    ...stops.flatMap(([zoom, opacity]) => [zoom, ['case', LIT, 0, opacity]]),
  ] as unknown as ExpressionSpecification;
}

/** A dot's opacity by zoom: fading in over SCHOOL_DOT_FADE, fully drawn from SCHOOL_DOTS_FROM. */
const DOT_OPACITY: readonly (readonly [zoom: number, opacity: number])[] = [
  [SCHOOL_DOTS_FROM - SCHOOL_DOT_FADE, 0],
  [SCHOOL_DOTS_FROM, 1],
];
/** A name's opacity by zoom: fading in over SCHOOL_FADE, fully drawn from SCHOOL_NAMES_FROM. */
const NAME_OPACITY: readonly (readonly [zoom: number, opacity: number])[] = [
  [SCHOOL_NAMES_FROM - SCHOOL_FADE, 0],
  [SCHOOL_NAMES_FROM, 1],
];

/**
 * How the school layers draw an unlit school at a zoom, from the same curves
 * as the layers themselves, for what reads the map by what it shows (a click
 * on a school, map/school-taps.ts): how opaque its dot and its name are
 * (none before the layer's zoom), and its dot's radius on the screen, ring
 * and all, in CSS pixels.
 */
export function schoolDotOpacity(zoom: number): number {
  return zoom < (DOT_OPACITY[0]?.[0] ?? 0) ? 0 : at(DOT_OPACITY, zoom);
}
export function schoolNameOpacity(zoom: number): number {
  return zoom < (NAME_OPACITY[0]?.[0] ?? 0) ? 0 : at(NAME_OPACITY, zoom);
}
export function schoolDotRadius(zoom: number): number {
  return at(DOT_RADIUS, zoom) + at(DOT_RING, zoom);
}

/**
 * A dot at every school, white, each ringed in the ground color. Big and
 * bright enough across a metro to pick out every school in a city at a
 * glance, and never a status color: what a school is doing today is the
 * glow's, and a school it lights has no dot of its own.
 */
export function schoolDotLayer(colors: SchoolColors): CircleLayerSpecification {
  const fadeIn = unlessLit(...DOT_OPACITY);
  return {
    id: BASEMAP_IDS.schoolDots,
    type: 'circle',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_DOTS_FROM - SCHOOL_DOT_FADE,
    paint: {
      'circle-radius': byZoom(...DOT_RADIUS.flat()),
      'circle-color': colors.name,
      'circle-opacity': fadeIn,
      'circle-stroke-color': colors.ground,
      'circle-stroke-width': byZoom(...DOT_RING.flat()),
      'circle-stroke-opacity': fadeIn,
      'circle-pitch-alignment': 'map',
    },
  };
}

/**
 * The light around each dot across a metro (SCHOOL_LIGHT_UNTIL), under the
 * dots, fading in with them and out before the names come in; none around a
 * school the glow lights.
 */
export function schoolLightLayer(colors: SchoolColors): CircleLayerSpecification {
  const from = SCHOOL_DOTS_FROM - SCHOOL_DOT_FADE;
  return {
    id: BASEMAP_IDS.schoolLight,
    type: 'circle',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: from,
    maxzoom: SCHOOL_NAMES_FROM - SCHOOL_FADE,
    paint: {
      'circle-radius': byZoom(...LIGHT_RADIUS.flat()),
      'circle-color': colors.name,
      'circle-opacity': unlessLit(
        [from, 0],
        [SCHOOL_DOTS_FROM, SCHOOL_LIGHT_OPACITY],
        [SCHOOL_LIGHT_UNTIL, SCHOOL_LIGHT_OPACITY],
        [SCHOOL_NAMES_FROM - SCHOOL_FADE, 0],
      ),
      // Soft all the way from its center to its edge.
      'circle-blur': 1,
      'circle-pitch-alignment': 'map',
    },
  };
}

/** The ring's radius in CSS pixels, by zoom: a few pixels clear of the dot. */
const RING_RADIUS: readonly (readonly [zoom: number, px: number])[] = [
  [9, 5.5],
  [11, 6.5],
  [13, 7.5],
  [15, 9.5],
  [17, 12],
];

/** The filter that picks the school with this id, or none for null. */
export function selectedSchoolFilter(id: string | null): FilterSpecification {
  return ['==', ['get', 'id'], id ?? ''];
}

/**
 * A ring around one school's dot, the one whose panel is open: a white edge
 * and a faint disc, under the dot and every label. Monochrome: a status's
 * color is the glow's alone.
 */
export function schoolSelectedLayer(colors: SchoolColors): CircleLayerSpecification {
  return {
    id: BASEMAP_IDS.schoolSelected,
    type: 'circle',
    source: BASEMAP_IDS.schoolsSource,
    'source-layer': SCHOOLS_TILE_LAYER,
    minzoom: SCHOOL_DOTS_FROM - SCHOOL_DOT_FADE,
    filter: selectedSchoolFilter(null),
    paint: {
      'circle-radius': byZoom(...RING_RADIUS.flat()),
      'circle-color': colors.name,
      'circle-opacity': 0.14,
      'circle-stroke-color': colors.name,
      'circle-stroke-width': 1.25,
      'circle-stroke-opacity': 0.9,
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

/**
 * How far a name sits from its dot, in ems of its size, beside the dot and
 * under or over it. Under or over, it clears the dot's own space (and the
 * name's padding) with a pixel to spare at every zoom names are drawn at, so
 * a name with no room at either side, on a phone's narrow screen, still has
 * a place: its dot keeps the space a name must not cross.
 */
export const SCHOOL_NAME_BESIDE = 0.75;
export const SCHOOL_NAME_UNDER = 1;
/** Across, at a corner: less than beside, as the name is also moved down or up. */
const SCHOOL_NAME_CORNER = 0.5;

/** The sides a name tries, in turn, each with its offset from the dot in ems. */
export function schoolNameAnchors(): VariableAnchorOffsetCollectionSpecification {
  const beside = SCHOOL_NAME_BESIDE;
  const under = SCHOOL_NAME_UNDER;
  const corner = SCHOOL_NAME_CORNER;
  return [
    'left',
    [beside, 0],
    'right',
    [-beside, 0],
    'top',
    [0, under],
    'bottom',
    [0, -under],
    'bottom-left',
    [corner, -under],
    'bottom-right',
    [-corner, -under],
    'top-left',
    [corner, under],
    'top-right',
    [-corner, under],
  ];
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
      // Beside the dot first, then under or over it, then at a corner: wherever there is room.
      'text-variable-anchor-offset': schoolNameAnchors(),
      'text-justify': 'auto',
      'text-max-width': 11,
      'text-line-height': 1.2,
      'text-letter-spacing': 0.01,
      // Clear space around each name: where two would crowd, one yields, whole.
      'text-padding': SCHOOL_NAME_PADDING,
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-optional': false,
    },
    paint: {
      'text-color': colors.name,
      'text-opacity': byZoom(...NAME_OPACITY.flat()),
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
