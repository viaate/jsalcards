import type {
  ExpressionSpecification,
  FilterSpecification,
  LayerSpecification,
  StyleSpecification,
  SymbolLayerSpecification,
} from 'maplibre-gl';

import { copy } from '../../copy';
import { MAP_FONTS } from './fonts';
import { BASEMAP_IDS } from './ids';
import { schoolDotLayer, schoolNameLayer, schoolSource, schoolSpaceLayer } from './schools';
import { SHIELD_IMAGE } from './shield';
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
 * polygons, whose rings are the outline), "state" (the state lines) and
 * "city" (a city's name and rank, 0 for the largest, at its Census point).
 */
export interface UsLinesData {
  type: 'FeatureCollection';
  features: readonly unknown[];
}

export interface BasemapStyleOptions extends BasemapLook {
  /** The bundled continental US lines, already fetched and parsed, or their URL. */
  usLines: UsLinesData | string;
  /**
   * The school tiles' archive (schools.pmtiles) this build ships, as an
   * absolute URL, or null when it ships none: then no school is drawn.
   */
  schools?: string | null;
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

const KIND: ExpressionSpecification = ['get', 'kind'];

/**
 * City names of the national view, from the bundled Census places (ranked
 * by build-geo.mjs: the centres of the largest urban areas first, lifted
 * for a city that is the only one for its region). They come in from zoom
 * 3, where a tablet shows the whole country (a phone, smaller still, shows
 * only the country), and give way at the handover to the street tiles'
 * names. They come in by bands of rank, each from its own zoom, so the
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
/** Zoom levels a band of names takes to fade in, from its zoom. */
const CITY_NAME_FADE = 0.05;

/** The layer id of each band of national city names, the first band's being BASEMAP_IDS.usCityLabel. */
export function cityNameLayerId(band: number): string {
  return band === 0 ? BASEMAP_IDS.usCityLabel : `${BASEMAP_IDS.usCityLabel}-${String(band)}`;
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
  readonly width: readonly Stop[];
}

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
  ...new Set(
    ROAD_TIERS.flatMap((tier) => [tier.minzoom, tier.full, ...tier.width.map(([zoom]) => zoom)]),
  ),
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

/** Road color by class and zoom: up from the ground as each tier fades in, scaled by `strength`. */
function roadColor(ground: string, strength = 1): ExpressionSpecification {
  const stops = ROAD_ZOOMS.flatMap((zoom) => [
    zoom,
    byTier((tier) => {
      const shown = (zoom - tier.minzoom) / (tier.full - tier.minzoom);
      return mixColors(ground, tier.color, Math.min(1, Math.max(0, shown)) * strength);
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
/** Interstate badges from zoom 11, US and state routes from 12 (tile zooms, so whole levels). */
const SHIELDS_FROM = 11;
const STATE_SHIELDS_FROM = 12;

const NETWORK: ExpressionSpecification = ['coalesce', ['get', 'network'], ''];
/** OpenMapTiles route networks whose numbers go on badges. */
const ROUTE_NETWORKS = ['us-interstate', 'us-highway', 'us-state'];
/**
 * A route's number as it is signed: "I-35", "US 71", and a state route with
 * its state's code ("MO 9") when the tiles carry it, else the number alone.
 */
const ROUTE_NUMBER: ExpressionSpecification = [
  'let',
  'ref',
  ['to-string', ['get', 'ref']],
  'state',
  ['coalesce', ['get', 'route_1_network'], ''],
  [
    'match',
    NETWORK,
    'us-interstate',
    ['concat', copy.map.route.interstate, ['var', 'ref']],
    'us-highway',
    ['concat', copy.map.route.usHighway, ' ', ['var', 'ref']],
    [
      'case',
      [
        'all',
        ['==', ['index-of', 'US:', ['var', 'state']], 0],
        ['==', ['length', ['var', 'state']], 5],
      ],
      ['concat', ['slice', ['var', 'state'], 3], ' ', ['var', 'ref']],
      ['var', 'ref'],
    ],
  ],
];

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

/** The national city names, a layer per band of rank (CITY_NAME_BANDS), first band first. */
function cityNameLayers(colors: BasemapColors): SymbolLayerSpecification[] {
  return CITY_NAME_BANDS.map(({ zoom, names }, band) => {
    const from = CITY_NAME_BANDS[band - 1]?.names ?? 0;
    const rank: ExpressionSpecification = ['get', 'rank'];
    return {
      id: cityNameLayerId(band),
      type: 'symbol',
      source: BASEMAP_IDS.usCitySource,
      minzoom: zoom,
      maxzoom: HANDOVER_START,
      filter: [
        'all',
        ['==', KIND, 'city'],
        ['>=', rank, from],
        ...(Number.isFinite(names) ? [['<', rank, names] as ExpressionSpecification] : []),
      ] as FilterSpecification,
      layout: {
        ...LABEL_LAYOUT,
        'symbol-sort-key': rank,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': ['interpolate', ['linear'], ['zoom'], CITY_NAMES_FROM, 10.5, 6, 12],
        'text-letter-spacing': 0.02,
        'text-padding': CITY_NAME_PADDING,
        'text-anchor': 'center',
        'text-max-width': 10,
      },
      paint: {
        'text-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          4,
          mixColors(colors.labelDim, colors.label, 0.5),
          HANDOVER_START,
          colors.label,
        ],
        'text-opacity': ramp(zoom, zoom + CITY_NAME_FADE),
        // Wide enough to part a coastline or border running under a name.
        'text-halo-color': colors.land,
        'text-halo-width': 3,
        'text-halo-blur': 1,
      },
    };
  });
}

/**
 * The bundled file's city names apart from its land and lines, as two
 * GeoJSON sources' data. A URL is handed to both sources as it is.
 */
export function splitUsLines(
  usLines: UsLinesData | string,
): readonly [geometry: UsLinesData | string, cities: UsLinesData | string] {
  if (typeof usLines === 'string') return [usLines, usLines];
  const isCity = (feature: unknown): boolean =>
    (feature as { properties?: { kind?: unknown } } | null)?.properties?.kind === 'city';
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
 * fonts.ts, so the style names no glyph server, and highway numbers sit on a
 * badge drawn in code (shield.ts), so it names no sprite either. With the
 * school tiles, every school is drawn from zoom 11 and named from zoom 13
 * (schools.ts), over school grounds drawn a step off the ground.
 *
 * Up close the hierarchy runs, brightest first: school names; towns, suburbs
 * and route numbers; major road names; street names; neighbourhoods in small
 * spaced capitals, parks and rivers. Roads step up in width and tone from
 * local streets to highways.
 */
export function buildBasemapStyle({
  usLines,
  hairline,
  colors,
  schools = null,
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
      // ground takes over at the handover, where the sea and the land are one black.
      id: BASEMAP_IDS.usLand,
      type: 'fill',
      source: BASEMAP_IDS.usSource,
      maxzoom: HANDOVER_END,
      filter: ['==', KIND, 'land'],
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
        'fill-color': colors.building,
        'fill-outline-color': colors.buildingEdge,
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
    {
      id: BASEMAP_IDS.usStates,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: HANDOVER_END,
      filter: ['==', KIND, 'state'],
      layout: round,
      paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': fadeOut },
    },
    {
      // The land's rings: MapLibre draws a line layer on polygons along their edges.
      id: BASEMAP_IDS.usOutline,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: HANDOVER_END,
      filter: ['==', KIND, 'land'],
      layout: round,
      paint: { 'line-color': colors.outline, 'line-width': hairline, 'line-opacity': fadeOut },
    },
    // The national city names, the last band lowest (MapLibre places the top layer first),
    // under the glow, which goes right before the street tiles' labels: a city's lights
    // shine over its name, never cut by the name's halo.
    ...cityNameLayers(colors).reverse(),
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
        // Numbers go on badges (the shield layer); a ramp's exit number is left out.
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
      // Interstate, US and state route numbers on small upright badges along their road.
      id: BASEMAP_IDS.ofmRoadShield,
      type: 'symbol',
      ...ofm,
      'source-layer': 'transportation_name',
      minzoom: labelMinZoom(SHIELDS_FROM),
      filter: [
        'all',
        ['match', CLASS, ['motorway', 'trunk', 'primary', 'secondary'], true, false],
        ['match', NETWORK, ROUTE_NETWORKS, true, false],
        ['>=', ['zoom'], ['match', NETWORK, 'us-interstate', SHIELDS_FROM, STATE_SHIELDS_FROM]],
        ['has', 'ref'],
        // A route number, not a list of them run together.
        ['<=', ['length', ['to-string', ['get', 'ref']]], 4],
      ],
      layout: {
        ...LABEL_LAYOUT,
        'symbol-placement': 'line',
        'symbol-spacing': ['interpolate', ['linear'], ['zoom'], 11, 300, 13, 380, 16, 800],
        'symbol-sort-key': ['match', NETWORK, 'us-interstate', 0, 'us-highway', 1, 2],
        'text-field': ROUTE_NUMBER,
        'text-font': [MAP_FONTS.medium],
        'text-size': 10,
        'text-letter-spacing': 0.02,
        'text-rotation-alignment': 'viewport',
        'text-pitch-alignment': 'viewport',
        // Room around each badge, so the two carriageways of a highway show one number, not two.
        'text-padding': 14,
        'icon-padding': 14,
        'icon-image': SHIELD_IMAGE,
        'icon-text-fit': 'both',
        'icon-text-fit-padding': [2, 4, 2, 4],
        'icon-rotation-alignment': 'viewport',
        'icon-pitch-alignment': 'viewport',
        'icon-allow-overlap': false,
        'icon-ignore-placement': false,
      },
      paint: {
        'text-color': colors.label,
        'text-opacity': labelsFrom(SHIELDS_FROM),
        'icon-opacity': labelsFrom(SHIELDS_FROM),
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
      layers.findIndex((layer) => layer.id === BASEMAP_IDS.labels),
      0,
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
        data: geometry,
        // The bundled lines are only drawn below the handover, so deeper tiles are never cut.
        maxzoom: Math.ceil(HANDOVER_END),
        tolerance: 0.1,
      },
      [BASEMAP_IDS.usCitySource]: {
        type: 'geojson',
        data: cities,
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
