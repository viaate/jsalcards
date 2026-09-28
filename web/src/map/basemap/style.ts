import type {
  ExpressionSpecification,
  FilterSpecification,
  LayerSpecification,
  StyleSpecification,
  SymbolLayerSpecification,
} from 'maplibre-gl';

import { MAP_FONTS } from './fonts';
import { BASEMAP_IDS } from './ids';
import {
  schoolDotLayer,
  schoolNameLayer,
  schoolSelectedLayer,
  schoolSource,
  schoolSpaceLayer,
} from './schools';
import { STATE_AREAS_UNTIL } from './state-areas';
import {
  STATE_NAME_LEADING,
  STATE_NAME_SMALL,
  STATE_NAME_TRACKING,
  STATE_NAMES_UNTIL,
} from './state-names';
import { STATE_NAME_SIZE } from './us-geo';
import { BORDER_LAYER, MASK_LAYER } from './mask/format';
import {
  OPENFREEMAP_ATTRIBUTION,
  OPENFREEMAP_MAX_ZOOM,
  OPENFREEMAP_MIN_ZOOM,
  OPENFREEMAP_TILES,
} from './openfreemap';

export { BASEMAP_IDS } from './ids';

export interface BasemapLook {
  /** Line width in CSS pixels, the same as the still's stroke. */
  hairline: number;
  colors: BasemapColors;
  /**
   * Names set for a phone's small screen (a phone held either way): the
   * states named (state-names.ts), and the city names closer together, so
   * both fit. Off unless set.
   */
  phoneNames?: boolean;
}

export interface BasemapColors {
  /** Map ground; also the halo behind labels and the gap around bridges. */
  background: string;
  /** The continental US at the national view, a step off the ground. */
  land: string;
  /** Coasts, lake shores and national borders. */
  outline: string;
  /** State lines. */
  state: string;
  /** Place names, and street names up close. */
  label: string;
  /** Neighbourhood names, and street names until they are close. */
  labelDim: string;
  /** School names up close. */
  labelBright: string;
  /** Building footprints. */
  building: string;
  /** Their hairline edge. */
  buildingEdge: string;
}

/**
 * The bundled continental US geometry as parsed from public/geo: a GeoJSON
 * FeatureCollection whose features carry `kind`: "land" (the country as
 * polygons, whose rings are the outline), "state" (the state lines), each
 * also simplified for the national view ("land-simple", "state-simple"),
 * "city" (a city's name and rank, 0 for the largest, at its Census point,
 * and `offset`, where its name goes from there in ems, where it is set off
 * the outline)
 * and "state-name" (a state's name, its `label` as set, broken over two
 * lines where that fits it larger, and `fit`, the largest size in CSS pixels
 * at zoom 0 it fits inside its state at, where it is placed).
 */
export interface UsLinesData {
  type: 'FeatureCollection';
  features: readonly unknown[];
}

export interface BasemapStyleOptions extends BasemapLook {
  /** The bundled continental US lines, already fetched and parsed, or their URL. */
  usLines: UsLinesData | string;
  /**
   * Where the two GeoJSON sources read the lines and the names from (the
   * bundled file, and its names alone), or null to hand them `usLines`,
   * parsed: MapLibre's workers then fetch and parse the files themselves, and
   * the page never copies the parsed lines over to them.
   */
  usLinesUrls?: { readonly lines: string; readonly names: string } | null;
  /**
   * The school tiles' archive (schools.pmtiles) this build ships, as an
   * absolute URL, or null when it ships none: then no school is drawn.
   */
  schools?: string | null;
  /** National city names to leave out: the ones the screen's edges would cut at the home view. */
  hiddenCityNames?: readonly string[];
  /**
   * The state names to draw at the start (state-names.ts stateNamesAt): the
   * ones that fit at the zoom the map opens at. The map keeps the layer's
   * filter to the ones that fit as it zooms (index.ts).
   */
  stateNames?: readonly string[];
  /** Of those, the ones that fit only at the small size (state-names.ts smallStateNamesAt). */
  smallStateNames?: readonly string[];
}

/**
 * Handover from the bundled lines to OpenFreeMap around zoom 7: the bundled
 * lines fade out over the same half zoom level the tile lines fade in.
 */
const HANDOVER_START = OPENFREEMAP_MIN_ZOOM;
const HANDOVER_END = OPENFREEMAP_MIN_ZOOM + 0.5;

/** 0 to 1 between two zoom levels, by the camera's zoom. */
function ramp(from: number, to: number, low = 0, high = 1): ExpressionSpecification {
  return ['interpolate', ['linear'], ['zoom'], from, low, to, high];
}

const fadeOut = ramp(HANDOVER_START, HANDOVER_END, 1, 0);
const fadeIn = ramp(HANDOVER_START, HANDOVER_END);

/**
 * The national view draws its own lines (build-geo.mjs): the outline and the
 * state lines simplified, so the coast reads as one hairline at zoom 3 to 5,
 * the still in index.html drawn from them too. They give way to the detailed
 * lines over the half zoom level around SIMPLE_LINES_UNTIL, above every
 * screen's home view.
 *
 * The two sets part by their opacity alone, never by their layers' zoom
 * ranges: MapLibre cuts a layer out of every tile below its minzoom (and from
 * its maxzoom up), and a flight that passes zoom 6 before the tiles there are
 * cut draws the tiles it has, the national view's. Each of those carries both
 * sets, so it draws whichever set the zoom calls for (BUNDLED_LINES_UNTIL).
 */
export const SIMPLE_LINES_UNTIL = 5.75;
const SIMPLE_FADE = 0.25;
const simpleFadeOut = ramp(
  SIMPLE_LINES_UNTIL - SIMPLE_FADE,
  SIMPLE_LINES_UNTIL + SIMPLE_FADE,
  1,
  0,
);
/** The detailed lines: in as the simplified ones go, out at the handover to the street tiles. */
const detailedLines: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  SIMPLE_LINES_UNTIL - SIMPLE_FADE,
  0,
  SIMPLE_LINES_UNTIL + SIMPLE_FADE,
  1,
  HANDOVER_START,
  1,
  HANDOVER_END,
  0,
];

/**
 * Where the bundled lines' four layers end, the simplified and the detailed
 * alike: the handover to the street tiles, where the detailed ones have faded
 * out and the simplified ones long since.
 */
export const BUNDLED_LINES_UNTIL = HANDOVER_END;

const KIND: ExpressionSpecification = ['get', 'kind'];
/** The kinds of feature in the bundled lines that are names: the rest is land and lines. */
const NAME_KINDS = ['city', 'state-name'];

/**
 * City names of the national view, from the bundled Census places (ranked
 * by build-geo.mjs: the centres of the largest urban areas first, lifted
 * for a city that is the only one for its region). They come in from zoom
 * 3, where a tablet shows the whole country and a phone held upright shows
 * its part of it at the home view (a phone's national view, smaller still,
 * shows only the country), and give way at the handover to the street
 * tiles' names. They come in by bands of rank, each from its own zoom, so the
 * country carries a few dozen names at any screen size and more come in as
 * the map closes in; each is shown where it keeps clear of every name
 * placed before it, and MapLibre places the lowest rank first.
 *
 * Each band is a layer of its own: a layer's zoom range follows the camera
 * exactly, where a paint value that depends on both the zoom and the
 * feature is sampled at whole zoom levels and would leave names half faded
 * between them.
 */
export const CITY_NAME_BANDS: readonly { readonly zoom: number; readonly names: number }[] =
  Object.freeze([
    // A tablet's national view.
    { zoom: 3, names: 14 },
    { zoom: 3.3, names: 21 },
    // A laptop's or desktop's national view (1280 px wide and up).
    { zoom: 3.8, names: 34 },
    { zoom: 4.3, names: 54 },
    { zoom: 4.8, names: 85 },
    { zoom: 5.3, names: 134 },
    { zoom: 5.8, names: 212 },
    { zoom: 6.3, names: Infinity },
  ]);
/** The first zoom national city names are drawn at. */
export const CITY_NAMES_FROM = CITY_NAME_BANDS[0]?.zoom ?? 3;
/** Clear space around each national city name, in CSS pixels. */
export const CITY_NAME_PADDING = 12;
/** The national city names' size in CSS pixels: `from` at CITY_NAMES_FROM, growing to `to` at `zoom`. */
const CITY_NAME_SIZE = { from: 10.5, zoom: 6, to: 12 } as const;
/** Space added between a national city name's letters, in ems. */
export const CITY_NAME_LETTER_SPACING = 0.02;
/**
 * The black halo that parts a line running under a city name, in CSS
 * pixels: a pixel. MapLibre draws a label's glyphs with about a pixel of
 * their distance field to spare around them at this size: a wider halo fills
 * every glyph's whole box and shows as a block around the name. Names are
 * set off the outline besides (build-geo.mjs): a state line, a step dimmer,
 * may still pass under one.
 */
export const CITY_NAME_HALO = 1;

/**
 * The national city names' color: halfway from the neighbourhood grey to the
 * place grey up to CITY_NAME_QUIET_UNTIL, the place grey by the handover.
 */
const CITY_NAME_QUIET_UNTIL = 4;

/** A national city name's color at `zoom`, as the style draws it. */
export function cityNameColor(colors: BasemapColors, zoom: number): string {
  const quiet = mixColors(colors.labelDim, colors.label, 0.5);
  const t = (zoom - CITY_NAME_QUIET_UNTIL) / (HANDOVER_START - CITY_NAME_QUIET_UNTIL);
  return mixColors(quiet, colors.label, t);
}

/** A national city name's size in CSS pixels at `zoom`, as the style draws it. */
export function cityNameSize(zoom: number): number {
  const { from, to } = CITY_NAME_SIZE;
  const t = Math.min(
    1,
    Math.max(0, (zoom - CITY_NAMES_FROM) / (CITY_NAME_SIZE.zoom - CITY_NAMES_FROM)),
  );
  return from + (to - from) * t;
}

/**
 * The filter of a band of national city names: the band's ranks, less any
 * name in `hidden` (the ones the screen's edges would cut at the home view).
 */
export function cityNameFilter(band: number, hidden: readonly string[] = []): FilterSpecification {
  const from = CITY_NAME_BANDS[band - 1]?.names ?? 0;
  const names = CITY_NAME_BANDS[band]?.names ?? Infinity;
  const rank: ExpressionSpecification = ['get', 'rank'];
  return [
    'all',
    ['==', KIND, 'city'],
    ['>=', rank, from],
    ...(Number.isFinite(names) ? [['<', rank, names] as ExpressionSpecification] : []),
    ...(hidden.length === 0
      ? []
      : [['!', ['in', NAME, ['literal', [...hidden]]]] as ExpressionSpecification]),
  ] as FilterSpecification;
}
/** Zoom levels a band of names takes to fade in, from its zoom. */
const CITY_NAME_FADE = 0.05;
/**
 * Where each national city name goes from its point, in ems: the `offset`
 * the bundled file gives the city (build-geo.mjs set it off the outline), by
 * the city's rank, and [0, 0] for the rest. Read here rather than by
 * ['get', 'offset'] on the map: once MapLibre parses a GeoJSON tile again (a
 * layout change, such as a phone's padding), an array property reaches the
 * layout as JSON text, and the name would fall back to its point.
 */
export function cityNameOffset(
  cities: UsLinesData | string,
): ExpressionSpecification | [number, number] {
  if (typeof cities === 'string') return [0, 0];
  const cases: (number | ExpressionSpecification)[] = [];
  const ranks = new Set<number>();
  for (const feature of cities.features) {
    const properties = (feature as { properties?: Record<string, unknown> } | null)?.properties;
    if (properties?.kind !== 'city') continue;
    const { rank, offset } = properties;
    if (typeof rank !== 'number' || !Number.isInteger(rank) || ranks.has(rank)) continue;
    if (!Array.isArray(offset) || offset.length !== 2) continue;
    const [x, y] = offset as unknown[];
    if (typeof x !== 'number' || typeof y !== 'number') continue;
    if (!Number.isFinite(x) || !Number.isFinite(y) || (x === 0 && y === 0)) continue;
    ranks.add(rank);
    cases.push(rank, ['literal', [x, y]]);
  }
  if (cases.length === 0) return [0, 0];
  // A match of one label or more: the spec's type spells out only its first.
  const match: unknown = ['match', ['get', 'rank'], ...cases, ['literal', [0, 0]]];
  return match as ExpressionSpecification;
}

/** The layer id of each band of national city names, the first band's being BASEMAP_IDS.usCityLabel. */
export function cityNameLayerId(band: number): string {
  return band === 0 ? BASEMAP_IDS.usCityLabel : `${BASEMAP_IDS.usCityLabel}-${String(band)}`;
}

/**
 * Clear space around each national city name on a phone, in CSS pixels:
 * closer than elsewhere, so the city and state names both fit its small
 * screen. build-geo.mjs places the state names clear of the city names
 * spaced so (us-geo.ts STATE_NAMES_CLEAR_OF).
 */
export const CITY_NAME_PHONE_PADDING = 8;

/** Clear space around each state name, in CSS pixels. */
export const STATE_NAME_PADDING = 3;

/**
 * The state names' size: STATE_NAME_SIZE by zoom, and STATE_NAME_SMALL of it
 * for the states in `small`, whose names fit only so at the map's zoom
 * (state-names.ts smallStateNamesAt). Linear between the size's two zooms,
 * so MapLibre sets each name at exactly this size at every zoom.
 */
export function stateNameSizeExpression(small: readonly string[]): ExpressionSpecification {
  const scale: ExpressionSpecification = [
    'case',
    ['in', NAME, ['literal', [...small]]],
    STATE_NAME_SMALL,
    1,
  ];
  return stateNameSizeScaled(scale);
}

/** STATE_NAME_SIZE by zoom, times `scale`. */
function stateNameSizeScaled(scale: ExpressionSpecification): ExpressionSpecification {
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    STATE_NAME_SIZE.fromZoom,
    ['*', STATE_NAME_SIZE.from, scale],
    STATE_NAME_SIZE.toZoom,
    ['*', STATE_NAME_SIZE.to, scale],
  ];
}

/**
 * The size of a name in the states-in-view layer: STATE_NAME_SIZE by zoom,
 * times the `scale` its feature carries (1 when it carries none), so a name
 * that layer takes over from the bundled layer keeps its size there.
 */
export const STATE_AREA_SIZE: ExpressionSpecification = stateNameSizeScaled([
  'to-number',
  ['coalesce', ['get', 'scale'], 1],
]);

/**
 * The filter of the state names' layer: the states in `names` alone, the
 * ones whose names fit at the map's zoom (state-names.ts stateNamesAt). One
 * layer holds them all, where a layer per state would cost the map a
 * placement and a draw for each one, every frame.
 */
export function stateNameFilter(names: readonly string[]): FilterSpecification {
  return [
    'all',
    ['==', KIND, 'state-name'],
    ['in', NAME, ['literal', [...names]]],
  ] as FilterSpecification;
}

/**
 * The zoom of the city names' one tile: at zoom 1 the continental US lies in
 * a single tile, which MapLibre scales up for every closer view.
 */
const CITY_SOURCE_MAX_ZOOM = 1;

/**
 * Zoom levels a label class takes to fade in before the zoom it is named
 * from: quick, so a map at rest never shows half-faded names, and over by
 * that zoom, so a view at a whole zoom level shows every name it should.
 */
export const LABEL_FADE = 0.25;

/** A label class's opacity: fading in just below `zoom`, all of it from `zoom` on. */
function labelsFrom(zoom: number): ExpressionSpecification {
  return ramp(zoom - LABEL_FADE, zoom);
}

/** The layer zoom a label class named from `zoom` starts at: where its fade begins. */
function labelMinZoom(zoom: number): number {
  return zoom - LABEL_FADE;
}

/**
 * Building footprints come in with the first tiles that carry them, at zoom
 * 13, half drawn, so a neighbourhood view at 13 already shows its blocks as a
 * quiet texture under the streets; they are fully drawn by 14.
 */
const BUILDINGS_FROM = 13;
const BUILDINGS_FULL = 14;
/**
 * Up close, where the blocks are what a person finds their way by, the
 * footprints and their edges step up a tone (CLOSE_FROM to CLOSE_ZOOM),
 * still well under the streets between them.
 */
const BUILDING_CLOSE = '#191919';
const BUILDING_EDGE_CLOSE = '#282828';
const buildingOpacity: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  BUILDINGS_FROM,
  0.55,
  BUILDINGS_FULL,
  1,
];

/**
 * Water and park fills: tone shifts a hair off the ground, never a color.
 * The sea takes no fill: it is ground, as at the national view, so the US
 * mask's edge out at sea (3 nautical miles off the coast, 9 off Texas and
 * western Florida) never shows. The coast is the shore line. Lakes and
 * rivers shared with Canada or Mexico keep the tone on the US side up to the
 * border, where the border line is drawn along the mask's edge.
 */
const WATER_FILL = '#0c0c0c';
const PARK_FILL = '#0d0d0d';
/**
 * School grounds: the campus around a school, a step brighter than a park so
 * the block a school stands on reads at a glance, with a hairline edge up
 * close. Buildings draw over them.
 */
const SCHOOL_GROUNDS_FILL = '#0f0f0f';
const SCHOOL_GROUNDS_EDGE = '#262626';
const SCHOOL_GROUNDS_FROM = 12;
const SCHOOL_GROUNDS_EDGE_FROM = 14;
/** OpenMapTiles `landuse` classes of school grounds: K-12 schools and kindergartens. */
const SCHOOL_GROUNDS = ['school', 'kindergarten'];
/** Streams and rivers drawn as lines: a step above the water's fill, so they still read. */
const WATERWAY = '#161616';

/**
 * Sea coasts keep the national outline's tone out to zoom 8, where they carry
 * the map. Lake and river shores start a step down, level with the brightest
 * roads, so reservoirs never outshine the cities. By zoom 11, where the
 * streets carry the map, every shore is down to CITY_SHORE.
 */
const INLAND_SHORE = '#3a3a3a';
const CITY_SHORE = '#333333';
const SHORE_DIM_START = 8;
const SHORE_DIM_END = 11;

/** OpenMapTiles `water` classes left out: pools would speckle every suburb with shorelines. */
const HIDDEN_WATER = ['swimming_pool'];
/** Water classes with no fill: the sea. */
const UNFILLED_WATER = [...HIDDEN_WATER, 'ocean'];

/** Green space from OpenMapTiles `landcover`, drawn as the park tone. */
const PARK_SUBCLASSES = ['park', 'recreation_ground', 'golf_course'];

/** Service roads left out altogether; the rest of the service roads are drawn sparingly. */
const HIDDEN_SERVICE = ['driveway', 'parking_aisle', 'drive-through'];

type Stop = readonly [zoom: number, value: number];

/**
 * One class of road. Each is drawn from `minzoom` (a tile zoom, so whole
 * levels), fading up from the ground color to `color` by `full`, at the
 * widths `width` gives in CSS pixels. Earlier tiers draw underneath.
 */
interface RoadTier {
  /** OpenMapTiles `transportation` classes. */
  readonly classes: readonly string[];
  readonly minzoom: number;
  readonly full: number;
  readonly color: string;
  /**
   * The tier's color up close, a step brighter, reached at CLOSE_ZOOM: at a
   * street's zoom the grid of local streets carries the map and must read
   * against the blocks between them.
   */
  readonly close: string;
  readonly width: readonly Stop[];
}

/** Roads and buildings step up from their tone to their close-up tone between these zooms. */
export const CLOSE_FROM = 14;
export const CLOSE_ZOOM = 15;

/**
 * Road classes, bottom to top: width and brightness grow with importance, so
 * the highways and arterials a person steers by stand out from the grid of
 * local streets at every zoom.
 */
export const ROAD_TIERS: readonly RoadTier[] = Object.freeze([
  {
    classes: ['service'],
    minzoom: 14,
    full: 15,
    color: '#1a1a1a',
    close: '#222222',
    width: [
      [14, 0.5],
      [16, 2.5],
    ],
  },
  {
    classes: ['minor'],
    minzoom: 12,
    full: 13,
    color: '#242424',
    close: '#303030',
    width: [
      [12, 0.4],
      [13, 0.7],
      [14, 1.4],
      [16, 5],
    ],
  },
  {
    classes: ['tertiary'],
    minzoom: 10,
    full: 11,
    color: '#2c2c2c',
    close: '#383838',
    width: [
      [10, 0.4],
      [12, 0.9],
      [14, 2.2],
      [16, 6.5],
    ],
  },
  {
    classes: ['secondary'],
    minzoom: 9,
    full: 10,
    color: '#333333',
    close: '#3e3e3e',
    width: [
      [9, 0.4],
      [12, 1.2],
      [14, 2.8],
      [16, 7.5],
    ],
  },
  {
    classes: ['primary'],
    minzoom: 7,
    full: 8,
    color: '#3a3a3a',
    close: '#444444',
    width: [
      [7, 0.5],
      [12, 1.5],
      [14, 3.2],
      [16, 8.5],
    ],
  },
  {
    classes: ['motorway', 'trunk'],
    minzoom: 7,
    full: 8,
    color: '#454545',
    close: '#4d4d4d',
    width: [
      [7, 0.6],
      [12, 2],
      [14, 4],
      [16, 10],
    ],
  },
]);

/** Road widths grow exponentially with zoom, as the ground they cover does. */
const WIDTH_BASE = 1.5;
/** Ramps (motorway links and the like) are drawn this much narrower than their class. */
const RAMP_WIDTH = 0.6;
/** Tunnels are drawn at this share of their class's brightness, unbroken. */
const TUNNEL_STRENGTH = 0.5;
/** The dark gap around a bridge, in CSS pixels on each side combined, by zoom. */
const BRIDGE_GAP: readonly Stop[] = [
  [12, 1],
  [14, 1.5],
  [16, 3],
];

/** MapLibre's exponential interpolation between two stops. */
function interpolate(stops: readonly Stop[], zoom: number, base: number): number {
  const first = stops[0];
  if (first === undefined || zoom < first[0]) return 0;
  for (let i = 1; i < stops.length; i++) {
    const [z0, v0] = stops[i - 1] ?? first;
    const [z1, v1] = stops[i] ?? first;
    if (zoom <= z1) {
      const t =
        base === 1 ? (zoom - z0) / (z1 - z0) : (base ** (zoom - z0) - 1) / (base ** (z1 - z0) - 1);
      return v0 + (v1 - v0) * t;
    }
  }
  return stops[stops.length - 1]?.[1] ?? 0;
}

function hexToRgb(hex: string): [number, number, number] {
  let digits = hex.replace('#', '');
  if (digits.length === 3) digits = digits.replace(/./g, (d) => d + d);
  const value = Number.parseInt(digits, 16);
  if (digits.length !== 6 || Number.isNaN(value)) throw new Error(`Not a hex color: ${hex}`);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** Whether two colors are the same, as hex colors; any other notation counts as different. */
export function sameColor(a: string, b: string): boolean {
  try {
    return hexToRgb(a).every((channel, i) => channel === hexToRgb(b)[i]);
  } catch {
    return false;
  }
}

/** `from` moved `share` of the way to `to`, as a hex color. */
export function mixColors(from: string, to: string, share: number): string {
  const a = hexToRgb(from);
  const b = hexToRgb(to);
  const t = Math.min(1, Math.max(0, share));
  return `#${a
    .map((channel, i) =>
      Math.round(channel + ((b[i] ?? channel) - channel) * t)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;
}

const CLASS: ExpressionSpecification = ['get', 'class'];
const ROAD_CLASSES = ROAD_TIERS.flatMap((tier) => tier.classes);
/** Every zoom level a road curve changes at: where the expressions put their stops. */
const ROAD_ZOOMS = [
  ...new Set([
    CLOSE_FROM,
    CLOSE_ZOOM,
    ...ROAD_TIERS.flatMap((tier) => [tier.minzoom, tier.full, ...tier.width.map(([zoom]) => zoom)]),
  ]),
].sort((a, b) => a - b);

/** A `match` on the road class, one branch per tier. */
function byTier(value: (tier: RoadTier) => unknown, fallback: unknown): ExpressionSpecification {
  const branches = ROAD_TIERS.flatMap((tier) => [[...tier.classes], value(tier)]);
  return ['match', CLASS, ...branches, fallback] as unknown as ExpressionSpecification;
}

/** Road width by class and zoom; ramps narrower; `extra` pixels added (a bridge's gap). */
function roadWidth(extra: readonly Stop[] = []): ExpressionSpecification {
  const narrowRamps: ExpressionSpecification = ['case', ['==', ['get', 'ramp'], 1], RAMP_WIDTH, 1];
  const stops = ROAD_ZOOMS.flatMap((zoom) => {
    const width: ExpressionSpecification = [
      '*',
      byTier((tier) => hundredths(interpolate(tier.width, zoom, WIDTH_BASE)), 0),
      narrowRamps,
    ];
    const add = hundredths(interpolate(extra, zoom, 1));
    return [zoom, add > 0 ? ['+', width, add] : width];
  });
  return [
    'interpolate',
    ['exponential', WIDTH_BASE],
    ['zoom'],
    ...stops,
  ] as unknown as ExpressionSpecification;
}

/** A tier's color at `zoom` once it is fully drawn: its own, stepping up to its close-up tone. */
function tierTone(tier: RoadTier, zoom: number): string {
  return mixColors(tier.color, tier.close, (zoom - CLOSE_FROM) / (CLOSE_ZOOM - CLOSE_FROM));
}

/** Road color by class and zoom: up from the ground as each tier fades in, scaled by `strength`. */
function roadColor(ground: string, strength = 1): ExpressionSpecification {
  const stops = ROAD_ZOOMS.flatMap((zoom) => [
    zoom,
    byTier((tier) => {
      const shown = (zoom - tier.minzoom) / (tier.full - tier.minzoom);
      return mixColors(ground, tierTone(tier, zoom), Math.min(1, Math.max(0, shown)) * strength);
    }, ground),
  ]);
  return ['interpolate', ['linear'], ['zoom'], ...stops] as unknown as ExpressionSpecification;
}

function hundredths(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Roads of the drawn classes, each from its own zoom, on the ground, in tunnels or on bridges. */
function roadFilter(level: 'tunnel' | 'ground' | 'bridge'): FilterSpecification {
  const brunnel: ExpressionSpecification = ['coalesce', ['get', 'brunnel'], ''];
  return [
    'all',
    ['match', CLASS, ROAD_CLASSES, true, false],
    ['>=', ['zoom'], byTier((tier) => tier.minzoom, 99)],
    ['match', ['coalesce', ['get', 'service'], ''], HIDDEN_SERVICE, false, true],
    level === 'ground'
      ? ['match', brunnel, ['tunnel', 'bridge'], false, true]
      : ['==', brunnel, level],
  ] as FilterSpecification;
}

/** Major roads above minor ones, a ramp just under its own class. */
const ROAD_SORT_KEY = [
  '+',
  ['*', 2, byTier((tier) => ROAD_TIERS.indexOf(tier), 0)],
  ['case', ['==', ['get', 'ramp'], 1], 0, 1],
] as ExpressionSpecification;

const NAME: ExpressionSpecification = ['coalesce', ['get', 'name'], ''];
const RANK: ExpressionSpecification = ['coalesce', ['get', 'rank'], 99];

/** Zoom levels each class of name is fully drawn from. */
const NEIGHBOURHOODS_FROM = 13;
const STREET_NAMES_FROM = 13;
const MAJOR_ROAD_NAMES_FROM = 12;
const WATER_NAMES_FROM = 13;
const PARK_NAMES_FROM = 14;
/** Text laid out the same way for every label: collision-aware, never overlapping. */
const LABEL_LAYOUT = {
  'text-allow-overlap': false,
  'text-ignore-placement': false,
  'text-optional': false,
  'text-padding': 3,
} satisfies SymbolLayerSpecification['layout'];

/** Street names follow their street. */
const ROAD_LABEL_LAYOUT = {
  ...LABEL_LAYOUT,
  'symbol-placement': 'line',
  'text-rotation-alignment': 'map',
  'text-pitch-alignment': 'viewport',
  'text-max-angle': 30,
  'symbol-spacing': 320,
  'text-letter-spacing': 0.02,
} satisfies SymbolLayerSpecification['layout'];

/** Place names sit on their point, wrapped when long. */
const PLACE_LABEL_LAYOUT = {
  ...LABEL_LAYOUT,
  'text-anchor': 'center',
  'text-max-width': 8,
  'text-line-height': 1.15,
  'symbol-sort-key': RANK,
} satisfies SymbolLayerSpecification['layout'];

/**
 * The state names: one layer, drawing the states in `names` (the ones that
 * fit at the map's zoom), and only when `shown`. Quieter than the city names,
 * and placed before them: where the two meet, the city's name gives way.
 */
function stateNameLayer(
  colors: BasemapColors,
  names: readonly string[],
  small: readonly string[],
  shown: boolean,
): SymbolLayerSpecification {
  return {
    id: BASEMAP_IDS.usStateLabel,
    type: 'symbol',
    source: BASEMAP_IDS.usCitySource,
    minzoom: STATE_NAME_SIZE.fromZoom,
    maxzoom: STATE_NAMES_UNTIL,
    filter: stateNameFilter(names),
    layout: stateNameLayout(small, shown),
    paint: stateNamePaint(colors),
  };
}

/** How a state's name is set: quiet spaced capitals, broken where its label breaks. */
function stateNameLayout(
  small: readonly string[],
  shown: boolean,
): NonNullable<SymbolLayerSpecification['layout']> {
  return {
    ...LABEL_LAYOUT,
    visibility: shown ? 'visible' : 'none',
    'text-field': ['get', 'label'],
    'text-font': [MAP_FONTS.medium],
    'text-transform': 'uppercase',
    'text-size': stateNameSizeExpression(small),
    'text-letter-spacing': STATE_NAME_TRACKING,
    'text-line-height': STATE_NAME_LEADING,
    'text-padding': STATE_NAME_PADDING,
    // The label carries its own line break; MapLibre breaks nothing else.
    'text-max-width': 40,
    'text-anchor': 'center',
    'text-justify': 'center',
  };
}

function stateNamePaint(colors: BasemapColors): NonNullable<SymbolLayerSpecification['paint']> {
  return {
    'text-color': colors.labelDim,
    'text-halo-color': colors.background,
    'text-halo-width': CITY_NAME_HALO,
    'text-halo-blur': 0.4,
  };
}

/**
 * The states in view on a phone closer in (state-areas.ts): named alike, from
 * the source the map fills as it comes to rest, over every place name, so
 * MapLibre places them before any: a state's name never gives way to a
 * city's, and the map sets it off the city names where the state has room.
 * Once filled, it names every state the map names there, the bundled layer
 * none (index.ts): a state's name is drawn once.
 */
function stateAreaLayer(colors: BasemapColors, shown: boolean): SymbolLayerSpecification {
  return {
    id: BASEMAP_IDS.usStateAreaLabel,
    type: 'symbol',
    source: BASEMAP_IDS.usStateAreaSource,
    minzoom: STATE_NAME_SIZE.fromZoom,
    maxzoom: STATE_AREAS_UNTIL,
    layout: { ...stateNameLayout([], shown), 'text-size': STATE_AREA_SIZE },
    paint: stateNamePaint(colors),
  };
}

/** Nothing yet: the map fills the states in view as it comes to rest. */
function noStateAreas(): { type: 'FeatureCollection'; features: [] } {
  return { type: 'FeatureCollection', features: [] };
}

/**
 * The national city names, a layer per band of rank (CITY_NAME_BANDS), first
 * band first, leaving out the names in `hidden`.
 */
function cityNameLayers(
  colors: BasemapColors,
  hidden: readonly string[],
  padding: number,
  offset: ExpressionSpecification | [number, number],
): SymbolLayerSpecification[] {
  return CITY_NAME_BANDS.map(({ zoom }, band) => {
    const rank: ExpressionSpecification = ['get', 'rank'];
    return {
      id: cityNameLayerId(band),
      type: 'symbol',
      source: BASEMAP_IDS.usCitySource,
      minzoom: zoom,
      maxzoom: HANDOVER_START,
      filter: cityNameFilter(band, hidden),
      layout: {
        ...LABEL_LAYOUT,
        'symbol-sort-key': rank,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': [
          'interpolate',
          ['linear'],
          ['zoom'],
          CITY_NAMES_FROM,
          CITY_NAME_SIZE.from,
          CITY_NAME_SIZE.zoom,
          CITY_NAME_SIZE.to,
        ],
        'text-letter-spacing': CITY_NAME_LETTER_SPACING,
        'text-padding': padding,
        'text-anchor': 'center',
        // Set off the outline where it runs under the city's point (build-geo.mjs).
        'text-offset': offset,
        'text-max-width': 10,
      },
      paint: {
        'text-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          CITY_NAME_QUIET_UNTIL,
          cityNameColor(colors, CITY_NAME_QUIET_UNTIL),
          HANDOVER_START,
          cityNameColor(colors, HANDOVER_START),
        ],
        'text-opacity': ramp(zoom, zoom + CITY_NAME_FADE),
        // Parts a line running under a name.
        'text-halo-color': colors.background,
        'text-halo-width': CITY_NAME_HALO,
        'text-halo-blur': 0.4,
      },
    };
  });
}

/**
 * The bundled file's city and state names apart from its land and lines, as
 * two GeoJSON sources' data. A URL is handed to both sources as it is.
 */
export function splitUsLines(
  usLines: UsLinesData | string,
): readonly [geometry: UsLinesData | string, cities: UsLinesData | string] {
  if (typeof usLines === 'string') return [usLines, usLines];
  const isCity = (feature: unknown): boolean => {
    const kind = (feature as { properties?: { kind?: unknown } } | null)?.properties?.kind;
    return typeof kind === 'string' && NAME_KINDS.includes(kind);
  };
  return [
    { type: 'FeatureCollection', features: usLines.features.filter((f) => !isCity(f)) },
    { type: 'FeatureCollection', features: usLines.features.filter(isCity) },
  ];
}

/**
 * The basemap style, built in code. At the initial view it needs nothing but
 * the bundled GeoJSON (the land a step off the ground, its outline, the state
 * lines and the largest cities' names) and the page's own Geist faces: no
 * glyphs, sprites or tiles from anywhere else. From zoom 7 it draws
 * OpenFreeMap's streets, water, parks, buildings and names
 * (the OpenMapTiles schema), cut to the continental US and DC: the street
 * tiles arrive without anything outside the US that could be drawn, placed
 * or queried (street-tiles.ts), and carry the US mask, drawn in the ground
 * color over every street, water, park and building layer, and the border
 * line along its edge. Labels are drawn by MapLibre from the Geist faces in
 * fonts.ts, so the style names no glyph server, and it draws no icons, so it
 * names no sprite either. Highway numbers are left off the map. With the
 * school tiles, every school is drawn from zoom 11 and named from zoom 13
 * (schools.ts), over school grounds drawn a step off the ground.
 *
 * Up close the hierarchy runs, brightest first: school names; towns and
 * suburbs; major road names; street names; neighbourhoods in small
 * spaced capitals, parks and rivers. Roads step up in width and tone from
 * local streets to highways.
 */
export function buildBasemapStyle({
  usLines,
  usLinesUrls = null,
  hairline,
  colors,
  schools = null,
  hiddenCityNames = [],
  stateNames = [],
  smallStateNames = [],
  phoneNames = false,
}: BasemapStyleOptions): StyleSpecification {
  const [geometry, cities] = splitUsLines(usLines);
  const round = { 'line-join': 'round', 'line-cap': 'round' } as const;
  const ofm = { source: BASEMAP_IDS.openFreeMapSource, minzoom: OPENFREEMAP_MIN_ZOOM } as const;
  const halo = {
    'text-halo-color': colors.background,
    'text-halo-width': 1.4,
    'text-halo-blur': 0.4,
  } as const;
  const layers: LayerSpecification[] = [
    {
      id: BASEMAP_IDS.background,
      type: 'background',
      paint: { 'background-color': colors.background },
    },
    {
      // The country a step off the ground at the national view; the street tiles' own
      // ground takes over at the handover, where the sea and the land are one black. A land
      // in the ground's own color is not drawn: filling most of a phone's screen with the
      // color already there costs every frame and shows nothing.
      id: BASEMAP_IDS.usLand,
      type: 'fill',
      source: BASEMAP_IDS.usSource,
      maxzoom: HANDOVER_END,
      // The still fills the same shape.
      filter: ['==', KIND, 'land-simple'],
      layout: { visibility: sameColor(colors.land, colors.background) ? 'none' : 'visible' },
      paint: { 'fill-color': colors.land, 'fill-opacity': fadeOut, 'fill-antialias': false },
    },
    {
      id: BASEMAP_IDS.ofmPark,
      type: 'fill',
      ...ofm,
      'source-layer': 'landcover',
      minzoom: 10,
      filter: ['match', ['get', 'subclass'], PARK_SUBCLASSES, true, false],
      paint: { 'fill-color': PARK_FILL, 'fill-opacity': ramp(10, 11), 'fill-antialias': false },
    },
    {
      id: BASEMAP_IDS.ofmSchoolGrounds,
      type: 'fill',
      ...ofm,
      'source-layer': 'landuse',
      minzoom: SCHOOL_GROUNDS_FROM,
      filter: ['match', CLASS, SCHOOL_GROUNDS, true, false],
      paint: {
        'fill-color': SCHOOL_GROUNDS_FILL,
        'fill-opacity': ramp(SCHOOL_GROUNDS_FROM, SCHOOL_GROUNDS_FROM + 1),
        'fill-antialias': false,
      },
    },
    {
      id: BASEMAP_IDS.ofmSchoolGroundsEdge,
      type: 'line',
      ...ofm,
      'source-layer': 'landuse',
      minzoom: SCHOOL_GROUNDS_EDGE_FROM - 0.5,
      filter: ['match', CLASS, SCHOOL_GROUNDS, true, false],
      layout: round,
      paint: {
        'line-color': SCHOOL_GROUNDS_EDGE,
        'line-width': hairline,
        'line-opacity': ramp(SCHOOL_GROUNDS_EDGE_FROM - 0.5, SCHOOL_GROUNDS_EDGE_FROM),
      },
    },
    {
      id: BASEMAP_IDS.ofmWaterFill,
      type: 'fill',
      ...ofm,
      'source-layer': 'water',
      filter: ['match', CLASS, UNFILLED_WATER, false, true],
      paint: { 'fill-color': WATER_FILL, 'fill-opacity': fadeIn, 'fill-antialias': false },
    },
    {
      // Rivers and streams too narrow for a shore of their own, in the water's tone.
      id: BASEMAP_IDS.ofmWaterway,
      type: 'line',
      ...ofm,
      'source-layer': 'waterway',
      minzoom: 9,
      filter: [
        'all',
        ['match', CLASS, ['river', 'canal', 'stream'], true, false],
        ['!=', ['coalesce', ['get', 'brunnel'], ''], 'tunnel'],
        ['>=', ['zoom'], ['match', CLASS, 'stream', 13, 9]],
      ],
      layout: round,
      paint: {
        'line-color': WATERWAY,
        'line-width': [
          'interpolate',
          ['exponential', WIDTH_BASE],
          ['zoom'],
          9,
          ['match', CLASS, 'stream', 0, 0.6],
          13,
          ['match', CLASS, 'stream', 0.6, 1.5],
          16,
          ['match', CLASS, 'stream', 2, 5],
        ],
      },
    },
    {
      id: BASEMAP_IDS.ofmStates,
      type: 'line',
      ...ofm,
      'source-layer': 'boundary',
      filter: ['all', ['==', ['get', 'admin_level'], 4], ['!=', ['get', 'maritime'], 1]],
      layout: round,
      paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': fadeIn },
    },
    {
      id: BASEMAP_IDS.ofmWater,
      type: 'line',
      ...ofm,
      'source-layer': 'water',
      filter: ['match', CLASS, HIDDEN_WATER, false, true],
      layout: round,
      paint: {
        'line-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          SHORE_DIM_START,
          ['match', CLASS, 'ocean', colors.outline, INLAND_SHORE],
          SHORE_DIM_END,
          CITY_SHORE,
        ],
        'line-width': hairline,
        'line-opacity': fadeIn,
      },
    },
    {
      id: BASEMAP_IDS.ofmRoadTunnel,
      type: 'line',
      ...ofm,
      'source-layer': 'transportation',
      filter: roadFilter('tunnel'),
      layout: { ...round, 'line-sort-key': ROAD_SORT_KEY },
      paint: {
        'line-color': roadColor(colors.background, TUNNEL_STRENGTH),
        'line-width': roadWidth(),
      },
    },
    {
      id: BASEMAP_IDS.ofmBuilding,
      type: 'fill',
      ...ofm,
      'source-layer': 'building',
      minzoom: BUILDINGS_FROM,
      paint: {
        'fill-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          CLOSE_FROM,
          colors.building,
          CLOSE_ZOOM,
          BUILDING_CLOSE,
        ],
        'fill-outline-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          CLOSE_FROM,
          colors.buildingEdge,
          CLOSE_ZOOM,
          BUILDING_EDGE_CLOSE,
        ],
        'fill-opacity': buildingOpacity,
      },
    },
    {
      id: BASEMAP_IDS.ofmRoad,
      type: 'line',
      ...ofm,
      'source-layer': 'transportation',
      filter: roadFilter('ground'),
      layout: { ...round, 'line-sort-key': ROAD_SORT_KEY },
      paint: { 'line-color': roadColor(colors.background), 'line-width': roadWidth() },
    },
    {
      // A dark gap either side of a bridge, so the road it crosses passes under it.
      id: BASEMAP_IDS.ofmBridgeCasing,
      type: 'line',
      ...ofm,
      'source-layer': 'transportation',
      minzoom: 12,
      filter: roadFilter('bridge'),
      layout: { 'line-join': 'round', 'line-cap': 'butt', 'line-sort-key': ROAD_SORT_KEY },
      paint: { 'line-color': colors.background, 'line-width': roadWidth(BRIDGE_GAP) },
    },
    {
      id: BASEMAP_IDS.ofmBridge,
      type: 'line',
      ...ofm,
      'source-layer': 'transportation',
      filter: roadFilter('bridge'),
      layout: { ...round, 'line-sort-key': ROAD_SORT_KEY },
      paint: { 'line-color': roadColor(colors.background), 'line-width': roadWidth() },
    },
    {
      // The ground over everything outside the US: street tiles carry it (street-tiles.ts).
      id: BASEMAP_IDS.usMask,
      type: 'fill',
      ...ofm,
      'source-layer': MASK_LAYER,
      paint: { 'fill-color': colors.background },
    },
    {
      id: BASEMAP_IDS.usBorder,
      type: 'line',
      ...ofm,
      'source-layer': BORDER_LAYER,
      layout: round,
      paint: { 'line-color': colors.outline, 'line-width': hairline, 'line-opacity': fadeIn },
    },
    // The bundled lines are the US's own, so they draw over the mask while they hand over.
    // Simplified at the national view, detailed from SIMPLE_LINES_UNTIL (build-geo.mjs).
    {
      id: BASEMAP_IDS.usStatesSimple,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: BUNDLED_LINES_UNTIL,
      filter: ['==', KIND, 'state-simple'],
      layout: round,
      paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': simpleFadeOut },
    },
    {
      id: BASEMAP_IDS.usStates,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: BUNDLED_LINES_UNTIL,
      filter: ['==', KIND, 'state'],
      layout: round,
      paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': detailedLines },
    },
    {
      // The land's rings: MapLibre draws a line layer on polygons along their edges.
      id: BASEMAP_IDS.usOutlineSimple,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: BUNDLED_LINES_UNTIL,
      filter: ['==', KIND, 'land-simple'],
      layout: round,
      paint: {
        'line-color': colors.outline,
        'line-width': hairline,
        'line-opacity': simpleFadeOut,
      },
    },
    {
      id: BASEMAP_IDS.usOutline,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: BUNDLED_LINES_UNTIL,
      filter: ['==', KIND, 'land'],
      layout: round,
      paint: {
        'line-color': colors.outline,
        'line-width': hairline,
        'line-opacity': detailedLines,
      },
    },
    // The national city names, the last band lowest (MapLibre places the top layer first),
    // under the glow, which goes right before the street tiles' labels: a city's lights
    // shine over its name, never cut by the name's halo.
    ...cityNameLayers(
      colors,
      hiddenCityNames,
      phoneNames ? CITY_NAME_PHONE_PADDING : CITY_NAME_PADDING,
      cityNameOffset(cities),
    ).reverse(),
    // The state names over the city names, so MapLibre places them first: a state named where
    // its name fits is never left unnamed for a city's name, which goes instead.
    stateNameLayer(colors, stateNames, smallStateNames, phoneNames),
    {
      // Empty: the glow layer goes right over it (BASEMAP_IDS.glowSlot).
      id: BASEMAP_IDS.glowSlot,
      type: 'background',
      layout: { visibility: 'none' },
    },
    // Labels, lowest priority first: MapLibre places the top layer's labels first.
    {
      // Neighbourhoods in small spaced capitals, a quiet layer under the street names.
      id: BASEMAP_IDS.ofmNeighbourhoodLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: labelMinZoom(NEIGHBOURHOODS_FROM),
      filter: ['match', CLASS, ['neighbourhood', 'hamlet'], true, false],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-transform': 'uppercase',
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10, 16, 11.5],
        'text-letter-spacing': 0.12,
        'text-max-width': 9,
      },
      paint: {
        'text-color': colors.labelDim,
        'text-opacity': labelsFrom(NEIGHBOURHOODS_FROM),
        ...halo,
      },
    },
    {
      // Rivers and creeks along their course.
      id: BASEMAP_IDS.ofmWaterLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'waterway',
      minzoom: labelMinZoom(WATER_NAMES_FROM),
      filter: ['all', ['==', CLASS, 'river'], ['has', 'name']],
      layout: {
        ...ROAD_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10.5, 16, 12],
        'text-letter-spacing': 0.08,
        'symbol-spacing': 480,
      },
      paint: {
        'text-color': colors.labelDim,
        'text-opacity': labelsFrom(WATER_NAMES_FROM),
        ...halo,
      },
    },
    {
      id: BASEMAP_IDS.ofmStreetLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'transportation_name',
      minzoom: labelMinZoom(STREET_NAMES_FROM),
      filter: [
        'all',
        ['match', CLASS, ['tertiary', 'minor', 'service'], true, false],
        ['>=', ['zoom'], ['match', CLASS, 'service', 15, 'minor', STREET_NAMES_FROM, 12]],
      ],
      layout: {
        ...ROAD_LABEL_LAYOUT,
        // Through streets are named before the side streets that cross them.
        'symbol-sort-key': ['match', CLASS, 'tertiary', 0, 'minor', 1, 2],
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 11, 16, 13],
      },
      paint: {
        'text-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          12.5,
          colors.labelDim,
          16,
          colors.label,
        ],
        'text-opacity': labelsFrom(STREET_NAMES_FROM),
        ...halo,
      },
    },
    {
      // Parks by name up close, the landmarks between the streets.
      id: BASEMAP_IDS.ofmParkLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'poi',
      minzoom: labelMinZoom(PARK_NAMES_FROM),
      filter: [
        'all',
        ['==', CLASS, 'park'],
        ['has', 'name'],
        ['<=', RANK, ['step', ['zoom'], 3, 15, 99]],
      ],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 14, 11, 16, 12.5],
        'text-max-width': 7,
        'text-letter-spacing': 0.02,
      },
      paint: {
        'text-color': colors.labelDim,
        'text-opacity': labelsFrom(PARK_NAMES_FROM),
        ...halo,
      },
    },
    {
      id: BASEMAP_IDS.ofmMajorRoadLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'transportation_name',
      minzoom: labelMinZoom(MAJOR_ROAD_NAMES_FROM),
      filter: [
        'all',
        ['match', CLASS, ['motorway', 'trunk', 'primary', 'secondary'], true, false],
        ['!=', ['coalesce', ['get', 'subclass'], ''], 'junction'],
        // Named roads only: route numbers and a ramp's exit number are left out.
        ['has', 'name'],
      ],
      layout: {
        ...ROAD_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': ['interpolate', ['linear'], ['zoom'], 12, 11, 16, 13.5],
      },
      paint: {
        'text-color': ['interpolate', ['linear'], ['zoom'], 12, colors.labelDim, 14, colors.label],
        'text-opacity': labelsFrom(MAJOR_ROAD_NAMES_FROM),
        ...halo,
      },
    },
    {
      id: BASEMAP_IDS.ofmVillageLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: labelMinZoom(11),
      filter: ['match', CLASS, ['village', 'suburb', 'quarter'], true, false],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': ['interpolate', ['linear'], ['zoom'], 11, 11.5, 15, 14],
      },
      paint: { 'text-color': colors.label, 'text-opacity': labelsFrom(11), ...halo },
    },
    {
      id: BASEMAP_IDS.ofmTownLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: labelMinZoom(9),
      filter: ['==', CLASS, 'town'],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': ['interpolate', ['linear'], ['zoom'], 9, 11.5, 13, 14.5],
      },
      paint: { 'text-color': colors.label, 'text-opacity': labelsFrom(9), ...halo },
    },
    {
      // The largest cities from zoom 7, more of them level by level.
      id: BASEMAP_IDS.ofmCityLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      filter: ['all', ['==', CLASS, 'city'], ['<=', RANK, ['step', ['zoom'], 8, 8, 10, 9, 99]]],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': [
          'interpolate',
          ['linear'],
          ['zoom'],
          7,
          ['step', RANK, 14, 5, 13, 9, 12],
          12,
          ['step', RANK, 17, 5, 16, 9, 15],
        ],
      },
      paint: { 'text-color': colors.label, 'text-opacity': fadeIn, ...halo },
    },
    stateAreaLayer(colors, phoneNames),
    {
      // Empty: the school layers are added before it (BASEMAP_IDS.schools).
      id: BASEMAP_IDS.schools,
      type: 'background',
      layout: { visibility: 'none' },
    },
  ];
  if (schools !== null) {
    const schoolColors = {
      bright: colors.label,
      name: colors.labelBright,
      ground: colors.background,
    };
    // Dots under every label (and under the glow, which goes right before the labels); names
    // over them all, and over the names the space each dot keeps, placed first.
    layers.splice(
      layers.findIndex((layer) => layer.id === BASEMAP_IDS.glowSlot),
      0,
      schoolSelectedLayer(schoolColors),
      schoolDotLayer(schoolColors),
    );
    layers.splice(
      layers.findIndex((layer) => layer.id === BASEMAP_IDS.schools),
      0,
      schoolNameLayer(schoolColors),
      schoolSpaceLayer(),
    );
  }
  return {
    version: 8,
    name: 'Snowlight',
    sources: {
      ...(schools === null ? {} : { [BASEMAP_IDS.schoolsSource]: schoolSource(schools) }),
      [BASEMAP_IDS.usSource]: {
        type: 'geojson',
        data: usLinesUrls?.lines ?? geometry,
        // The land and lines alone: the file at a URL has the names too.
        filter: ['match', KIND, NAME_KINDS, false, true],
        // The bundled lines are only drawn below the handover, so deeper tiles are never cut.
        maxzoom: Math.ceil(HANDOVER_END),
        tolerance: 0.1,
      },
      [BASEMAP_IDS.usStateAreaSource]: { type: 'geojson', data: noStateAreas() },
      [BASEMAP_IDS.usCitySource]: {
        type: 'geojson',
        data: usLinesUrls?.names ?? cities,
        // The names alone, whatever the data holds.
        filter: ['match', KIND, NAME_KINDS, true, false],
        // One tile holds every city, so MapLibre places the names strictly in rank order: names
        // in separate tiles would be placed tile by tile, and a small city could take a large
        // one's place. Drawn from it up to zoom 7, a unit of that tile is under 3 pixels.
        maxzoom: CITY_SOURCE_MAX_ZOOM,
      },
      [BASEMAP_IDS.openFreeMapSource]: {
        type: 'vector',
        tiles: [OPENFREEMAP_TILES],
        minzoom: OPENFREEMAP_MIN_ZOOM,
        maxzoom: OPENFREEMAP_MAX_ZOOM,
        attribution: OPENFREEMAP_ATTRIBUTION,
      },
    },
    layers,
  };
}

/** Whether MapLibre draws `layer` at `zoom`: shown, and within its zoom range. */
function drawnAt(layer: LayerSpecification, zoom: number): boolean {
  const visibility = (layer.layout as { visibility?: unknown } | undefined)?.visibility;
  return visibility !== 'none' && zoom >= (layer.minzoom ?? 0) && zoom < (layer.maxzoom ?? 24);
}

/** A style as the map is created with it, and the layers it takes on after. */
export interface StagedStyle {
  /** The style to create the map with: every source, and the layers without one. */
  readonly style: StyleSpecification;
  /**
   * The layers of each source a layer drawn at the zoom the map opens at
   * reads, in the full style's order: the first to add.
   */
  readonly now: readonly LayerSpecification[];
  /** The rest, drawn only further in or out, in the full style's order: added after. */
  readonly later: readonly LayerSpecification[];
  /** Every layer of the full style, in order: where each goes as it is added. */
  readonly order: readonly string[];
}

/**
 * Splits `style` into the style a map opening at `zoom` is created with and
 * the layers it takes on once that style is in, a few at a time (index.ts):
 * setting up a layer is MapLibre's work on the page's main thread, and all
 * of it at once would hold the page up.
 *
 * The map is created with the layers without a source (the ground and the
 * glow layer's place). A source loads no tiles until a layer on it is drawn,
 * and a layer added to a source whose tiles are in has them all cut again:
 * so the layers of each source a layer drawn at `zoom` reads go on first,
 * all of them before the map next draws, and the rest after.
 */
export function stageStyle(style: StyleSpecification, zoom: number): StagedStyle {
  const sourceOf = (layer: LayerSpecification): string | null =>
    'source' in layer && typeof layer.source === 'string' ? layer.source : null;
  const inUse = new Set(
    style.layers.flatMap((layer) => {
      const source = sourceOf(layer);
      return source !== null && drawnAt(layer, zoom) ? [source] : [];
    }),
  );
  const stage = (layer: LayerSpecification): 'first' | 'now' | 'later' => {
    const source = sourceOf(layer);
    if (source === null) return 'first';
    return inUse.has(source) ? 'now' : 'later';
  };
  return {
    style: { ...style, layers: style.layers.filter((layer) => stage(layer) === 'first') },
    now: style.layers.filter((layer) => stage(layer) === 'now'),
    later: style.layers.filter((layer) => stage(layer) === 'later'),
    order: style.layers.map((layer) => layer.id),
  };
}
