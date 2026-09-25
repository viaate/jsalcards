import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl';

import {
  OPENFREEMAP_ATTRIBUTION,
  OPENFREEMAP_MAX_ZOOM,
  OPENFREEMAP_MIN_ZOOM,
  OPENFREEMAP_TILES,
} from './openfreemap';

/** Source and layer ids other map code can place layers relative to. */
export const BASEMAP_IDS = {
  usSource: 'us-lines',
  openFreeMapSource: 'openfreemap',
  background: 'background',
  usStates: 'us-states',
  usOutline: 'us-outline',
  ofmWater: 'ofm-water-edge',
  ofmStates: 'ofm-state-lines',
  ofmCountries: 'ofm-country-lines',
} as const;

export interface BasemapLook {
  /** Line width in CSS pixels, the same as the still's stroke. */
  hairline: number;
  colors: BasemapColors;
}

export interface BasemapColors {
  /** Map ground. */
  background: string;
  /** Coasts, lake shores and national borders. */
  outline: string;
  /** State lines. */
  state: string;
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
}

/**
 * Handover from the bundled lines to OpenFreeMap around zoom 7: the bundled
 * lines fade out over the same half zoom level the tile lines fade in.
 */
const HANDOVER_START = OPENFREEMAP_MIN_ZOOM;
const HANDOVER_END = OPENFREEMAP_MIN_ZOOM + 0.5;

const fadeOut: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  HANDOVER_START,
  1,
  HANDOVER_END,
  0,
];
const fadeIn: ExpressionSpecification = [
  'interpolate',
  ['linear'],
  ['zoom'],
  HANDOVER_START,
  0,
  HANDOVER_END,
  1,
];

/**
 * The basemap style, built in code. At the initial view it needs nothing but
 * the bundled GeoJSON: no glyphs, sprites or tiles from anywhere else.
 */
export function buildBasemapStyle({
  usLines,
  hairline,
  colors,
}: BasemapStyleOptions): StyleSpecification {
  const round = { 'line-join': 'round', 'line-cap': 'round' } as const;
  return {
    version: 8,
    name: 'Snowlight',
    sources: {
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
    layers: [
      {
        id: BASEMAP_IDS.background,
        type: 'background',
        paint: { 'background-color': colors.background },
      },
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
      {
        id: BASEMAP_IDS.ofmStates,
        type: 'line',
        source: BASEMAP_IDS.openFreeMapSource,
        'source-layer': 'boundary',
        minzoom: OPENFREEMAP_MIN_ZOOM,
        filter: ['all', ['==', ['get', 'admin_level'], 4], ['!=', ['get', 'maritime'], 1]],
        layout: round,
        paint: { 'line-color': colors.state, 'line-width': hairline, 'line-opacity': fadeIn },
      },
      {
        id: BASEMAP_IDS.ofmWater,
        type: 'line',
        source: BASEMAP_IDS.openFreeMapSource,
        'source-layer': 'water',
        minzoom: OPENFREEMAP_MIN_ZOOM,
        layout: round,
        paint: { 'line-color': colors.outline, 'line-width': hairline, 'line-opacity': fadeIn },
      },
      {
        id: BASEMAP_IDS.ofmCountries,
        type: 'line',
        source: BASEMAP_IDS.openFreeMapSource,
        'source-layer': 'boundary',
        minzoom: OPENFREEMAP_MIN_ZOOM,
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1]],
        layout: round,
        paint: { 'line-color': colors.outline, 'line-width': hairline, 'line-opacity': fadeIn },
      },
    ],
  };
}
