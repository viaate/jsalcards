import type {
  ExpressionSpecification,
  FilterSpecification,
  LayerSpecification,
  StyleSpecification,
  SymbolLayerSpecification,
} from 'maplibre-gl';

import { MAP_FONTS } from './fonts';
import { BASEMAP_IDS } from './ids';
import { schoolDotLayer, schoolNameLayer, schoolSource } from './schools';
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
 * The bundled continental US lines as parsed from public/geo: a GeoJSON
 * FeatureCollection whose features carry `kind`, "outline" or "state".
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

/**
 * Zoom levels a label class takes to fade in from the zoom it starts at:
 * quick, so a map at rest never shows half-faded names.
 */
const LABEL_FADE = 0.25;

/** A label class's opacity: none below `zoom`, all of it a moment later. */
function labelsFrom(zoom: number): ExpressionSpecification {
  return ramp(zoom, zoom + LABEL_FADE);
}

/**
 * Building footprints come in at zoom 13 and are fully drawn by 14. They are
 * most of the way in a quarter level after they start, so a neighbourhood
 * view just past 13 already shows its blocks.
 */
const BUILDINGS_FROM = 13;
const BUILDINGS_FULL = 14;
const buildingOpacity: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  BUILDINGS_FROM,
  0,
  BUILDINGS_FROM + 0.25,
  0.6,
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
const PARK_FILL = '#090909';
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

/** Road classes, bottom to top: width and brightness grow with importance. */
export const ROAD_TIERS: readonly RoadTier[] = Object.freeze([
  {
    classes: ['service'],
    minzoom: 14,
    full: 15,
    color: '#1c1c1c',
    width: [
      [14, 0.5],
      [16, 2.5],
    ],
  },
  {
    classes: ['minor'],
    minzoom: 12,
    full: 13,
    color: '#262626',
    width: [
      [12, 0.5],
      [14, 1.5],
      [16, 5],
    ],
  },
  {
    classes: ['tertiary'],
    minzoom: 10,
    full: 11,
    color: '#2b2b2b',
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
    color: '#2f2f2f',
    width: [
      [9, 0.4],
      [12, 1.1],
      [14, 2.6],
      [16, 7.5],
    ],
  },
  {
    classes: ['primary'],
    minzoom: 7,
    full: 8,
    color: '#343434',
    width: [
      [7, 0.5],
      [12, 1.4],
      [14, 3],
      [16, 8.5],
    ],
  },
  {
    classes: ['motorway', 'trunk'],
    minzoom: 7,
    full: 8,
    color: '#3a3a3a',
    width: [
      [7, 0.6],
      [12, 1.8],
      [14, 3.6],
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
 * The basemap style, built in code. At the initial view it needs nothing but
 * the bundled GeoJSON: no glyphs, sprites or tiles from anywhere else. From
 * zoom 7 it draws OpenFreeMap's streets, water, parks, buildings and names
 * (the OpenMapTiles schema), cut to the continental US and DC: the street
 * tiles arrive without anything outside the US that could be drawn, placed
 * or queried (street-tiles.ts), and carry the US mask, drawn in the ground
 * color over every street, water, park and building layer, and the border
 * line along its edge. Labels are drawn by MapLibre from the Geist faces in
 * fonts.ts, so the style names no glyph server. With the school tiles, every
 * school is drawn from zoom 11 and named from zoom 13 (schools.ts).
 */
export function buildBasemapStyle({
  usLines,
  hairline,
  colors,
  schools = null,
}: BasemapStyleOptions): StyleSpecification {
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
      id: BASEMAP_IDS.ofmPark,
      type: 'fill',
      ...ofm,
      'source-layer': 'landcover',
      minzoom: 10,
      filter: ['match', ['get', 'subclass'], PARK_SUBCLASSES, true, false],
      paint: { 'fill-color': PARK_FILL, 'fill-opacity': ramp(10, 11), 'fill-antialias': false },
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
      filter: ['==', ['get', 'kind'], 'state'],
      layout: round,
      paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': fadeOut },
    },
    {
      id: BASEMAP_IDS.usOutline,
      type: 'line',
      source: BASEMAP_IDS.usSource,
      maxzoom: HANDOVER_END,
      filter: ['==', ['get', 'kind'], 'outline'],
      layout: round,
      paint: { 'line-color': colors.outline, 'line-width': hairline, 'line-opacity': fadeOut },
    },
    // Labels, lowest priority first: MapLibre places the top layer's labels first.
    {
      id: BASEMAP_IDS.ofmNeighbourhoodLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: 13,
      filter: ['match', CLASS, ['neighbourhood', 'hamlet'], true, false],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 11, 16, 12.5],
        'text-letter-spacing': 0.04,
      },
      paint: { 'text-color': colors.labelDim, 'text-opacity': labelsFrom(13), ...halo },
    },
    {
      id: BASEMAP_IDS.ofmStreetLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'transportation_name',
      minzoom: 13,
      filter: [
        'all',
        ['match', CLASS, ['tertiary', 'minor', 'service'], true, false],
        ['>=', ['zoom'], ['match', CLASS, 'service', 15, 13]],
      ],
      layout: {
        ...ROAD_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10.5, 16, 12.5],
      },
      paint: {
        'text-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          13.5,
          colors.labelDim,
          15,
          colors.label,
        ],
        'text-opacity': labelsFrom(13),
        ...halo,
      },
    },
    {
      id: BASEMAP_IDS.ofmMajorRoadLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'transportation_name',
      minzoom: 12,
      filter: [
        'all',
        ['match', CLASS, ['motorway', 'trunk', 'primary', 'secondary'], true, false],
        ['!=', ['coalesce', ['get', 'subclass'], ''], 'junction'],
      ],
      layout: {
        ...ROAD_LABEL_LAYOUT,
        // Highways without a name go by their number.
        'text-field': ['coalesce', ['get', 'name'], ['get', 'ref'], ''],
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 12, 11, 16, 13],
      },
      paint: {
        'text-color': [
          'interpolate',
          ['linear'],
          ['zoom'],
          12.5,
          colors.labelDim,
          14,
          colors.label,
        ],
        'text-opacity': labelsFrom(12),
        ...halo,
      },
    },
    {
      id: BASEMAP_IDS.ofmVillageLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: 11,
      filter: ['match', CLASS, ['village', 'suburb', 'quarter'], true, false],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.regular],
        'text-size': ['interpolate', ['linear'], ['zoom'], 11, 11.5, 15, 13.5],
      },
      paint: { 'text-color': colors.label, 'text-opacity': labelsFrom(11), ...halo },
    },
    {
      id: BASEMAP_IDS.ofmTownLabel,
      type: 'symbol',
      ...ofm,
      'source-layer': 'place',
      minzoom: 9,
      filter: ['==', CLASS, 'town'],
      layout: {
        ...PLACE_LABEL_LAYOUT,
        'text-field': NAME,
        'text-font': [MAP_FONTS.medium],
        'text-size': ['interpolate', ['linear'], ['zoom'], 9, 11.5, 13, 14],
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
      dim: colors.labelDim,
      bright: colors.label,
      name: colors.labelBright,
      ground: colors.background,
    };
    // Dots under every label (and under the glow, which goes right before the labels); names over them all.
    layers.splice(
      layers.findIndex((layer) => layer.id === BASEMAP_IDS.labels),
      0,
      schoolDotLayer(schoolColors),
    );
    layers.splice(
      layers.findIndex((layer) => layer.id === BASEMAP_IDS.schools),
      0,
      schoolNameLayer(schoolColors),
    );
  }
  return {
    version: 8,
    name: 'Snowlight',
    sources: {
      ...(schools === null ? {} : { [BASEMAP_IDS.schoolsSource]: schoolSource(schools) }),
      [BASEMAP_IDS.usSource]: {
        type: 'geojson',
        data: usLines,
        // The bundled lines are only drawn below the handover, so deeper tiles are never cut.
        maxzoom: Math.ceil(HANDOVER_END),
        tolerance: 0.1,
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
