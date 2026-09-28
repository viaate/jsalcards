// @vitest-environment node
/**
 * The basemap style as MapLibre reads it: valid, drawn in the right order,
 * each road class, label class and the buildings coming in at the zoom they
 * are meant to, nothing asked of the network below zoom 7, and nothing
 * colored. Filters and paint values are evaluated with MapLibre's own
 * style-spec implementation, on features shaped like OpenMapTiles ones.
 */
import {
  expression,
  featureFilter,
  latest,
  validateStyleMin,
} from '@maplibre/maplibre-gl-style-spec';
import type {
  FilterSpecification,
  LayerSpecification,
  StyleSpecification,
  SymbolLayerSpecification,
} from '@maplibre/maplibre-gl-style-spec';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MAP_FONT_FILES, MAP_FONTS, addMapFonts } from '../fonts';
import { BASEMAP_IDS } from '../ids';
import { BORDER_LAYER, MASK_LAYER } from '../mask/format';
import { OPENFREEMAP_MIN_ZOOM } from '../openfreemap';
import { SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE, SCHOOL_TILES_PROTOCOL } from '../ids';
import { NEARBY_ZOOM } from '../limits';
import {
  SCHOOL_DOTS_FROM,
  SCHOOL_DOT_FADE,
  SCHOOL_FADE,
  SCHOOL_LIGHT_OPACITY,
  SCHOOL_LIGHT_UNTIL,
  SCHOOL_NAMES_FROM,
  SCHOOL_SPACE_IMAGE,
  SCHOOL_NAME_PADDING,
  SCHOOL_NAME_UNDER,
  SCHOOL_SPACE_SIZE,
  SCHOOL_TILES_MAX_ZOOM,
  SCHOOL_TILES_MIN_ZOOM,
  schoolSpaceImage,
  selectedSchoolFilter,
} from '../schools';
import {
  BUNDLED_LINES_UNTIL,
  CITY_NAME_BANDS,
  CITY_NAME_HALO,
  CITY_NAME_LETTER_SPACING,
  CITY_NAME_PADDING,
  CITY_NAMES_FROM,
  CLOSE_FROM,
  CLOSE_ZOOM,
  LABEL_FADE,
  METRO_PLACE_HALO,
  METRO_ROAD_TONE,
  ROAD_TIERS,
  SIMPLE_LINES_UNTIL,
  buildBasemapStyle,
  cityNameFilter,
  cityNameLayerId,
  cityNameOffset,
  cityNameSize,
  metroRoadTone,
  mixColors,
  splitUsLines,
  stageStyle,
} from '../style';
import type { BasemapColors, UsLinesData } from '../style';
import { CITY_NAMES_SET_OFF } from '../us-geo';

const COLORS: BasemapColors = {
  background: '#000',
  land: '#0a0a0a',
  outline: '#6b6b6b',
  state: '#2a2a2a',
  label: '#a3a3a3',
  labelDim: '#6b6b6b',
  labelBright: '#f5f5f5',
  building: '#111',
  buildingEdge: '#1f1f1f',
};
const US_LINES: UsLinesData = { type: 'FeatureCollection', features: [] };
const STYLE: StyleSpecification = buildBasemapStyle({
  usLines: US_LINES,
  hairline: 1,
  colors: COLORS,
});
const LAYERS: readonly LayerSpecification[] = STYLE.layers;
const SCHOOL_ARCHIVE = 'https://snowlight.test/data/schools/schools.0123456789.pmtiles';
/** The style of a build that ships the school tiles. */
const WITH_SCHOOLS: StyleSpecification = buildBasemapStyle({
  usLines: US_LINES,
  hairline: 1,
  colors: COLORS,
  schools: SCHOOL_ARCHIVE,
});

function layer(id: string): LayerSpecification {
  const found = [...LAYERS, ...WITH_SCHOOLS.layers].find((candidate) => candidate.id === id);
  if (found === undefined) throw new Error(`No layer ${id}`);
  return found;
}

function indexOf(id: string): number {
  const index = LAYERS.findIndex((candidate) => candidate.id === id);
  if (index < 0) throw new Error(`No layer ${id}`);
  return index;
}

type Properties = Record<string, string | number | readonly number[]>;

/** OpenMapTiles geometry types: 1 point, 2 line, 3 polygon. */
const GEOMETRY = { point: 1, line: 2, polygon: 3 } as const;

/** Whether the layer draws a feature with these properties at this (tile) zoom. */
function draws(id: string, zoom: number, properties: Properties, type: 1 | 2 | 3 = 2): boolean {
  const target = layer(id);
  if (zoom < (target.minzoom ?? 0) || zoom >= (target.maxzoom ?? 24)) return false;
  const { filter } = target as { filter?: FilterSpecification };
  if (filter === undefined) return true;
  return featureFilter(filter, 'filter').filter({ zoom }, { type, properties });
}

type Section = 'paint' | 'layout';

/** A paint or layout value of a layer, evaluated at a zoom for a feature. */
function value(
  id: string,
  section: Section,
  name: string,
  zoom: number,
  properties: Properties = {},
): unknown {
  return valueOf(layer(id), section, name, zoom, properties);
}

/** A paint or layout value of this layer, evaluated at a zoom for a feature. */
function valueOf(
  of: LayerSpecification,
  section: Section,
  name: string,
  zoom: number,
  properties: Properties = {},
): unknown {
  const id = of.id;
  const target = of as unknown as Record<Section, Record<string, unknown> | undefined> & {
    type: string;
  };
  const input = target[section]?.[name];
  if (input === undefined) throw new Error(`${id} has no ${section} ${name}`);
  const reference = latest as unknown as Record<string, Record<string, unknown>>;
  const spec = reference[`${section}_${target.type}`]?.[name];
  if (spec === undefined) throw new Error(`No spec for ${section} ${name}`);
  const parsed = expression.createPropertyExpression(input, name, spec as never);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  return parsed.value.evaluate({ zoom }, { type: GEOMETRY.line, properties });
}

function num(id: string, section: Section, name: string, zoom: number, p: Properties = {}): number {
  const result = value(id, section, name, zoom, p);
  if (typeof result !== 'number') throw new Error(`${id} ${name} is not a number`);
  return result;
}

/** A color value as 0-255 channels, alpha dropped. */
function rgb(id: string, name: string, zoom: number, p: Properties = {}): [number, number, number] {
  return channels(value(id, 'paint', name, zoom, p));
}

/** A color value MapLibre evaluated as 0-255 channels, alpha dropped. */
function channels(evaluated: unknown): [number, number, number] {
  const color = evaluated as { r: number; g: number; b: number; a: number };
  // Colors come back premultiplied by alpha, from 0 to 1.
  const scale = color.a === 0 ? 0 : 255 / color.a;
  return [color.r * scale, color.g * scale, color.b * scale].map(Math.round) as [
    number,
    number,
    number,
  ];
}

function hex(channels: readonly number[]): string {
  return `#${channels.map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

const ROAD = BASEMAP_IDS.ofmRoad;
const TUNNEL = BASEMAP_IDS.ofmRoadTunnel;
const BRIDGE = BASEMAP_IDS.ofmBridge;

describe('the basemap style', () => {
  it('is a valid MapLibre style', () => {
    expect(validateStyleMin(STYLE)).toEqual([]);
  });

  it('has every id other code places layers by', () => {
    const sources = Object.keys(WITH_SCHOOLS.sources);
    const layers = WITH_SCHOOLS.layers;
    for (const [key, id] of Object.entries(BASEMAP_IDS)) {
      // The glow layer is MapLibre's custom layer, put on the map by glow-mount.ts at its slot.
      if (id === BASEMAP_IDS.glow) continue;
      if (key.endsWith('Source')) expect(sources, key).toContain(id);
      else
        expect(
          layers.map((l) => l.id),
          key,
        ).toContain(id);
    }
    expect(new Set(layers.map((l) => l.id)).size).toBe(layers.length);
    expect(validateStyleMin(WITH_SCHOOLS)).toEqual([]);
  });

  it('draws no school, and reads no school tiles, when the build ships none', () => {
    expect(Object.keys(STYLE.sources)).not.toContain(BASEMAP_IDS.schoolsSource);
    const ids = LAYERS.map((l) => l.id);
    expect(ids).not.toContain(BASEMAP_IDS.schoolDots);
    expect(ids).not.toContain(BASEMAP_IDS.schoolNames);
  });
});

describe('layer order', () => {
  it('draws the ground, then fills, shores and roads, then the US mask and borders, then names', () => {
    const order = [
      BASEMAP_IDS.background,
      BASEMAP_IDS.usLand,
      BASEMAP_IDS.ofmPark,
      BASEMAP_IDS.ofmSchoolGrounds,
      BASEMAP_IDS.ofmSchoolGroundsEdge,
      BASEMAP_IDS.ofmWaterFill,
      BASEMAP_IDS.ofmWaterway,
      BASEMAP_IDS.ofmStates,
      BASEMAP_IDS.ofmWater,
      BASEMAP_IDS.ofmRoadTunnel,
      BASEMAP_IDS.ofmBuilding,
      BASEMAP_IDS.ofmRoad,
      BASEMAP_IDS.ofmBridgeCasing,
      BASEMAP_IDS.ofmBridge,
      BASEMAP_IDS.usMask,
      BASEMAP_IDS.usBorder,
      BASEMAP_IDS.usStatesSimple,
      BASEMAP_IDS.usStates,
      BASEMAP_IDS.usOutlineSimple,
      BASEMAP_IDS.usOutline,
      BASEMAP_IDS.labels,
      BASEMAP_IDS.schools,
    ];
    const indices = order.map(indexOf);
    expect(indices).toEqual([...indices].sort((a, b) => a - b));
  });

  it('draws the mask over every street, water, park and building layer, in the ground color', () => {
    const mask = indexOf(BASEMAP_IDS.usMask);
    const below = LAYERS.slice(0, mask).filter(
      (l) => 'source' in l && l.source === BASEMAP_IDS.openFreeMapSource,
    );
    expect(below.length).toBeGreaterThan(8);
    const above = LAYERS.slice(mask + 1);
    for (const drawn of above) {
      // Over the mask: only the border line, the bundled US lines, names, and the empty slots
      // of the glow layer and the schools.
      expect(
        drawn.type === 'symbol' ||
          drawn.id === BASEMAP_IDS.usBorder ||
          drawn.id === BASEMAP_IDS.glowSlot ||
          drawn.id === BASEMAP_IDS.schools ||
          ('source' in drawn && drawn.source === BASEMAP_IDS.usSource),
        drawn.id,
      ).toBe(true);
    }
    expect(layer(BASEMAP_IDS.usMask)).toMatchObject({
      type: 'fill',
      source: BASEMAP_IDS.openFreeMapSource,
      'source-layer': MASK_LAYER,
    });
    expect(value(BASEMAP_IDS.usMask, 'paint', 'fill-color', 12)).toMatchObject({
      r: 0,
      g: 0,
      b: 0,
      a: 1,
    });
    // Fully drawn from the first street tile: no zoom sees streets through it.
    expect(layer(BASEMAP_IDS.usMask).paint).not.toHaveProperty('fill-opacity');
    expect(draws(BASEMAP_IDS.usMask, 7, {}, GEOMETRY.polygon)).toBe(true);
  });

  it('draws the border line from the mask, in the outline tone', () => {
    expect(layer(BASEMAP_IDS.usBorder)).toMatchObject({
      type: 'line',
      source: BASEMAP_IDS.openFreeMapSource,
      'source-layer': BORDER_LAYER,
    });
    expect(hex(rgb(BASEMAP_IDS.usBorder, 'line-color', 12))).toBe(COLORS.outline);
    // No OpenFreeMap country line: those run past the US.
    for (const drawn of LAYERS) {
      const filter = JSON.stringify((drawn as { filter?: unknown }).filter ?? null);
      expect(filter, drawn.id).not.toContain('"admin_level"],2');
    }
  });

  it('puts every name above every line and fill, the least important names lowest', () => {
    const symbols = LAYERS.filter((l) => l.type === 'symbol').map((l) => l.id);
    const bands = CITY_NAME_BANDS.map((_band, index) => cityNameLayerId(index)).reverse();
    // The national city names and the state names (a phone's) come first, right over the
    // bundled lines: the glow, which goes on right over its slot before BASEMAP_IDS.labels,
    // shines over them. The street tiles' names follow.
    const firstSymbol = LAYERS.findIndex((l) => l.type === 'symbol');
    expect(LAYERS[firstSymbol - 1]?.id).toBe(BASEMAP_IDS.usOutline);
    expect(LAYERS[firstSymbol + bands.length + 1]?.id).toBe(BASEMAP_IDS.glowSlot);
    expect(LAYERS[firstSymbol + bands.length + 2]?.id).toBe(BASEMAP_IDS.labels);
    for (const drawn of LAYERS.slice(firstSymbol)) {
      expect(['symbol', 'background'], drawn.id).toContain(drawn.type);
    }
    // MapLibre places the top layer's labels first: cities win over towns, towns over route
    // numbers, route numbers over road names, and parks over the streets around them.
    expect(symbols).toEqual([
      // The national city names, the band of the largest cities on top, under the state names:
      // a state's name never gives way to a city's.
      ...bands,
      BASEMAP_IDS.usStateLabel,
      BASEMAP_IDS.ofmNeighbourhoodLabel,
      BASEMAP_IDS.ofmWaterLabel,
      BASEMAP_IDS.ofmStreetLabel,
      BASEMAP_IDS.ofmParkLabel,
      BASEMAP_IDS.ofmMajorRoadLabel,
      BASEMAP_IDS.ofmVillageLabel,
      BASEMAP_IDS.ofmTownLabel,
      BASEMAP_IDS.ofmCityLabel,
      // The states in view on a phone closer in, over every place name (state-areas.ts).
      BASEMAP_IDS.usStateAreaLabel,
    ]);
  });

  it('keeps an empty slot for the glow layer, right under the street tiles’ names', () => {
    const slot = layer(BASEMAP_IDS.glowSlot);
    expect(slot.type).toBe('background');
    expect(slot.layout).toEqual({ visibility: 'none' });
    expect(indexOf(BASEMAP_IDS.labels) - 1).toBe(indexOf(BASEMAP_IDS.glowSlot));
  });

  it('ends with an empty slot, so school layers added before it win every label collision', () => {
    const slot = LAYERS[LAYERS.length - 1];
    expect(slot?.id).toBe(BASEMAP_IDS.schools);
    expect(slot?.type).toBe('background');
    expect(slot?.layout).toEqual({ visibility: 'none' });
  });

  it('keeps tunnels under buildings and bridges over the roads they cross', () => {
    const tunnel = { class: 'primary', brunnel: 'tunnel' };
    const bridge = { class: 'primary', brunnel: 'bridge' };
    const ground = { class: 'primary' };
    expect(draws(TUNNEL, 12, tunnel)).toBe(true);
    expect(draws(ROAD, 12, tunnel)).toBe(false);
    expect(draws(BRIDGE, 12, bridge)).toBe(true);
    expect(draws(BASEMAP_IDS.ofmBridgeCasing, 12, bridge)).toBe(true);
    expect(draws(ROAD, 12, bridge)).toBe(false);
    expect(draws(ROAD, 12, ground)).toBe(true);
    expect(draws(TUNNEL, 12, ground) || draws(BRIDGE, 12, ground)).toBe(false);
    // A ford is still a road on the ground.
    expect(draws(ROAD, 12, { class: 'minor', brunnel: 'ford' })).toBe(true);
    // Tunnels draw unbroken, dimmer than the same road in the open.
    const open = rgb(ROAD, 'line-color', 14, ground);
    const under = rgb(TUNNEL, 'line-color', 14, tunnel);
    expect(under[0]).toBeGreaterThan(0);
    expect(under[0]).toBeLessThan(open[0]);
    // The casing is ground-colored and wider than the bridge, leaving a gap either side.
    expect(rgb(BASEMAP_IDS.ofmBridgeCasing, 'line-color', 14, bridge)).toEqual([0, 0, 0]);
    expect(num(BASEMAP_IDS.ofmBridgeCasing, 'paint', 'line-width', 14, bridge)).toBeGreaterThan(
      num(BRIDGE, 'paint', 'line-width', 14, bridge),
    );
  });
});

describe('the national view', () => {
  const LAND = { kind: 'land' };
  const SIMPLE_LAND = { kind: 'land-simple' };
  const SIMPLE_STATE = { kind: 'state-simple' };
  const city = (rank: number): Properties => ({ kind: 'city', name: 'A city', rank });
  /** The band layers that draw a city of this rank at this zoom. */
  const bandsDrawing = (rank: number, zoom: number): string[] =>
    CITY_NAME_BANDS.map((_band, index) => cityNameLayerId(index)).filter((id) =>
      draws(id, zoom, city(rank), GEOMETRY.point),
    );

  it('lifts the land a step off the ground, and hands it over with the lines', () => {
    expect(layer(BASEMAP_IDS.usLand)).toMatchObject({
      type: 'fill',
      source: BASEMAP_IDS.usSource,
      paint: { 'fill-antialias': false },
    });
    // The national view's own land, as the still fills it.
    expect(draws(BASEMAP_IDS.usLand, 4, SIMPLE_LAND, GEOMETRY.polygon)).toBe(true);
    expect(draws(BASEMAP_IDS.usLand, 4, LAND, GEOMETRY.polygon)).toBe(false);
    expect(draws(BASEMAP_IDS.usLand, 4, { kind: 'state' })).toBe(false);
    expect(draws(BASEMAP_IDS.usLand, 4, city(0), GEOMETRY.point)).toBe(false);
    expect(hex(rgb(BASEMAP_IDS.usLand, 'fill-color', 4))).toBe(COLORS.land);
    expect(num(BASEMAP_IDS.usLand, 'paint', 'fill-opacity', OPENFREEMAP_MIN_ZOOM)).toBe(1);
    expect(num(BASEMAP_IDS.usLand, 'paint', 'fill-opacity', OPENFREEMAP_MIN_ZOOM + 0.5)).toBe(0);
    expect(layer(BASEMAP_IDS.usLand).maxzoom).toBe(OPENFREEMAP_MIN_ZOOM + 0.5);
  });

  it("draws the outline along the land's edge, and the state lines apart from it", () => {
    for (const [outline, states, land, lines, zoom] of [
      [BASEMAP_IDS.usOutlineSimple, BASEMAP_IDS.usStatesSimple, SIMPLE_LAND, SIMPLE_STATE, 4],
      [BASEMAP_IDS.usOutline, BASEMAP_IDS.usStates, LAND, { kind: 'state' }, 6.5],
    ] as const) {
      expect(layer(outline).type).toBe('line');
      expect(draws(outline, zoom, land, GEOMETRY.polygon)).toBe(true);
      expect(draws(outline, zoom, lines)).toBe(false);
      expect(draws(states, zoom, lines)).toBe(true);
      expect(draws(states, zoom, land, GEOMETRY.polygon)).toBe(false);
      expect(hex(rgb(outline, 'line-color', zoom))).toBe(COLORS.outline);
      expect(hex(rgb(states, 'line-color', zoom))).toBe(COLORS.state);
    }
    // The state lines a step dimmer than the coast and the border, on every screen.
    for (const colors of [COLORS, { ...COLORS, outline: '#8f8f8f', state: '#4d4d4d' }]) {
      expect(Number.parseInt(colors.state.slice(1, 3), 16)).toBeLessThan(
        Number.parseInt(colors.outline.slice(1, 3), 16) * 0.6,
      );
    }
  });

  it('draws the simplified lines at the national view, the detailed ones closer in', () => {
    for (const id of [BASEMAP_IDS.usOutlineSimple, BASEMAP_IDS.usStatesSimple]) {
      expect(num(id, 'paint', 'line-opacity', 3)).toBe(1);
      expect(num(id, 'paint', 'line-opacity', SIMPLE_LINES_UNTIL - 0.25)).toBe(1);
      expect(num(id, 'paint', 'line-opacity', SIMPLE_LINES_UNTIL + 0.25)).toBe(0);
    }
    for (const id of [BASEMAP_IDS.usOutline, BASEMAP_IDS.usStates]) {
      expect(num(id, 'paint', 'line-opacity', 3)).toBe(0);
      expect(num(id, 'paint', 'line-opacity', SIMPLE_LINES_UNTIL - 0.25)).toBe(0);
      expect(num(id, 'paint', 'line-opacity', SIMPLE_LINES_UNTIL + 0.25)).toBe(1);
      expect(num(id, 'paint', 'line-opacity', OPENFREEMAP_MIN_ZOOM)).toBe(1);
      expect(num(id, 'paint', 'line-opacity', OPENFREEMAP_MIN_ZOOM + 0.5)).toBe(0);
    }
    // Above the home view of every screen up to 2560 px wide.
    expect(SIMPLE_LINES_UNTIL - 0.25).toBeGreaterThan(5);
  });

  it('keeps both sets of bundled lines in every tile up to the handover', () => {
    // A layer's zoom range cuts it out of the tiles outside it: a flight past zoom 6 faster than
    // the tiles there are cut draws the national view's tiles, which must carry the detailed lines.
    for (const id of [
      BASEMAP_IDS.usOutlineSimple,
      BASEMAP_IDS.usStatesSimple,
      BASEMAP_IDS.usOutline,
      BASEMAP_IDS.usStates,
    ]) {
      expect(layer(id).minzoom).toBeUndefined();
      expect(layer(id).maxzoom).toBe(BUNDLED_LINES_UNTIL);
    }
    expect(BUNDLED_LINES_UNTIL).toBe(OPENFREEMAP_MIN_ZOOM + 0.5);
  });

  it('sets the city names as build-geo.mjs set them off the outline', () => {
    const set = CITY_NAMES_SET_OFF;
    expect(set.halo).toBe(CITY_NAME_HALO);
    expect(set.padding).toBe(CITY_NAME_PADDING);
    // Kept clear of the names the map shows, band by band.
    expect(set.shown).toEqual(CITY_NAME_BANDS.slice(0, set.shown.length));
    expect(set.tracking).toBe(CITY_NAME_LETTER_SPACING);
    expect(set.simpleLinesUntil).toBe(SIMPLE_LINES_UNTIL);
    for (const zoom of [3, 4, 5, 6, 6.9]) {
      const { fromZoom, from, toZoom, to } = set.size;
      const t = Math.min(1, Math.max(0, (zoom - fromZoom) / (toZoom - fromZoom)));
      expect(from + (to - from) * t).toBeCloseTo(cityNameSize(zoom), 9);
    }
    // Checked from the first zoom names are drawn at to the handover, against the simplified
    // lines and then the detailed ones.
    expect(set.zooms[0]).toBe(CITY_NAMES_FROM);
    for (const zoom of set.zooms) expect(zoom).toBeLessThan(OPENFREEMAP_MIN_ZOOM);
    expect(set.zooms.some((zoom) => zoom < SIMPLE_LINES_UNTIL)).toBe(true);
    expect(set.zooms.some((zoom) => zoom >= SIMPLE_LINES_UNTIL)).toBe(true);
  });

  it('sets a city name where the file sets it off the outline, and on its point otherwise', () => {
    const feature = (rank: number, offset?: unknown): unknown => ({
      type: 'Feature',
      properties: { kind: 'city', name: `City ${String(rank)}`, rank, offset },
      geometry: { type: 'Point', coordinates: [-100, 40] },
    });
    const file: UsLinesData = {
      type: 'FeatureCollection',
      features: [
        feature(0, [0.4, -0.8]),
        feature(1),
        feature(2, [2.1, 0]),
        // Malformed or on the point: left there.
        feature(3, '[1,1]'),
        feature(4, [0, 0]),
        feature(5, [1, 'x']),
      ],
    };
    const styled = buildBasemapStyle({ usLines: file, hairline: 1, colors: COLORS });
    const offsetAt = (id: string, properties: Properties): unknown => {
      const target = styled.layers.find((candidate) => candidate.id === id) as
        { layout?: Record<string, unknown> } | undefined;
      const spec = (latest as unknown as Record<string, Record<string, unknown>>).layout_symbol?.[
        'text-offset'
      ];
      const parsed = expression.createPropertyExpression(
        target?.layout?.['text-offset'],
        'text-offset',
        spec as never,
      );
      if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
      return parsed.value.evaluate({ zoom: 4 }, { type: GEOMETRY.point, properties });
    };
    for (const [index] of CITY_NAME_BANDS.entries()) {
      const id = cityNameLayerId(index);
      expect(offsetAt(id, city(0)), id).toEqual([0.4, -0.8]);
      // By its rank, whatever MapLibre makes of the array in the tile it parses again.
      expect(offsetAt(id, { ...city(2), offset: '[2.1,0]' }), id).toEqual([2.1, 0]);
      for (const rank of [1, 3, 4, 5, 6]) expect(offsetAt(id, city(rank)), id).toEqual([0, 0]);
    }
    expect(cityNameOffset(file)).toEqual([
      'match',
      ['get', 'rank'],
      0,
      ['literal', [0.4, -0.8]],
      2,
      ['literal', [2.1, 0]],
      ['literal', [0, 0]],
    ]);
    // No names set off, or the file not read yet: every name on its point.
    expect(cityNameOffset(US_LINES)).toEqual([0, 0]);
    expect(cityNameOffset('https://snowlight.test/geo/us-lines.json')).toEqual([0, 0]);
    expect(validateStyleMin(styled)).toEqual([]);
  });

  it('names each city in exactly one band, the largest from the first zoom', () => {
    for (const rank of [0, 13, 14, 33, 34, 100, 211, 212, 255]) {
      expect(bandsDrawing(rank, 6.9), String(rank)).toHaveLength(1);
    }
    expect(bandsDrawing(0, CITY_NAMES_FROM)).toEqual([cityNameLayerId(0)]);
    expect(bandsDrawing(0, CITY_NAMES_FROM - 0.01)).toEqual([]);
    // Bands come in one after another, each with more names, all gone by the handover.
    let previous = { zoom: 0, names: 0 };
    CITY_NAME_BANDS.forEach((band, index) => {
      expect(band.zoom).toBeGreaterThan(previous.zoom);
      expect(band.names).toBeGreaterThan(previous.names);
      const id = cityNameLayerId(index);
      expect(layer(id).minzoom).toBe(band.zoom);
      expect(layer(id).maxzoom).toBe(OPENFREEMAP_MIN_ZOOM);
      expect(draws(id, band.zoom, city(previous.names), GEOMETRY.point)).toBe(true);
      expect(draws(id, band.zoom, city(previous.names - 1), GEOMETRY.point)).toBe(false);
      previous = band;
    });
    expect(bandsDrawing(0, OPENFREEMAP_MIN_ZOOM)).toEqual([]);
    expect(CITY_NAME_BANDS.at(-1)?.names).toBe(Infinity);
  });

  it('shows a few dozen names on a laptop and a dozen or so on a tablet', () => {
    const shown = (zoom: number): number =>
      CITY_NAME_BANDS.filter((band) => band.zoom <= zoom).at(-1)?.names ?? 0;
    // Zoom 3.85 fits the country into a 1280 px wide window; 4.03 into 1440; 3.14 into 820.
    expect(shown(3.85)).toBe(34);
    expect(shown(4.03)).toBe(34);
    expect(shown(3.14)).toBe(14);
    // A phone's national view shows the country only; its home view, 3.85 on a 390 x 844
    // phone held upright, names its part of the country like a laptop.
    expect(shown(2.3)).toBe(0);
  });

  it('leaves out the names it is told to, in every band, and only those', () => {
    const hidden = ['Boston', 'St. Louis'];
    const styled = buildBasemapStyle({
      usLines: US_LINES,
      hairline: 1,
      colors: COLORS,
      hiddenCityNames: hidden,
    });
    CITY_NAME_BANDS.forEach((band, index) => {
      const id = cityNameLayerId(index);
      const found = styled.layers.find((candidate) => candidate.id === id) as {
        filter: FilterSpecification;
      };
      expect(found.filter, id).toEqual(cityNameFilter(index, hidden));
      const rank = CITY_NAME_BANDS[index - 1]?.names ?? 0;
      const passes = (name: string): boolean =>
        featureFilter(found.filter, 'filter').filter(
          { zoom: band.zoom },
          { type: GEOMETRY.point, properties: { kind: 'city', rank, name } },
        );
      expect(passes('Boston'), id).toBe(false);
      expect(passes('St. Louis'), id).toBe(false);
      expect(passes('Chicago'), id).toBe(true);
    });
    // With none to leave out, the filter is the band's alone.
    expect(cityNameFilter(0, [])).toEqual(cityNameFilter(0));
    expect(JSON.stringify(cityNameFilter(0))).not.toContain('literal');
  });

  it('places the largest city first, with clear space around every name', () => {
    CITY_NAME_BANDS.forEach((_band, index) => {
      const id = cityNameLayerId(index);
      const layout = layer(id).layout as Record<string, unknown>;
      expect(layout['symbol-sort-key'], id).toEqual(['get', 'rank']);
      expect(layout['text-padding'], id).toBe(CITY_NAME_PADDING);
      expect(layout['text-font'], id).toEqual([MAP_FONTS.medium]);
      expect(layout['text-allow-overlap'], id).toBe(false);
      expect(layout['text-ignore-placement'], id).toBe(false);
    });
    // Band 0 is the top of the bands, right under the state names and the street tiles'
    // labels (which are gone below zoom 7), the glow's empty slot between: MapLibre places it
    // first of them.
    expect(indexOf(BASEMAP_IDS.usStateLabel) - 1).toBe(indexOf(cityNameLayerId(0)));
    expect(indexOf(BASEMAP_IDS.glowSlot) - 1).toBe(indexOf(BASEMAP_IDS.usStateLabel));
    expect(indexOf(BASEMAP_IDS.labels) - 1).toBe(indexOf(BASEMAP_IDS.glowSlot));
  });

  it('fades each band in quickly at its zoom, so a map at rest shows each name fully', () => {
    CITY_NAME_BANDS.forEach((band, index) => {
      const id = cityNameLayerId(index);
      expect(num(id, 'paint', 'text-opacity', band.zoom), id).toBe(0);
      expect(num(id, 'paint', 'text-opacity', band.zoom + 0.05), id).toBe(1);
      expect(num(id, 'paint', 'text-opacity', 6.9), id).toBe(1);
    });
  });

  it('sets the names quietly at the national view, up to the place grey at the handover', () => {
    const id = cityNameLayerId(0);
    const national = rgb(id, 'text-color', 4);
    expect(national[0]).toBeGreaterThan(Number.parseInt(COLORS.labelDim.slice(1, 3), 16));
    expect(national[0]).toBeLessThan(Number.parseInt(COLORS.label.slice(1, 3), 16));
    expect(hex(rgb(id, 'text-color', OPENFREEMAP_MIN_ZOOM))).toBe(COLORS.label);
    // A black halo a pixel wide parts a line running under a name, inside the space
    // MapLibre's glyphs keep around them (3 of 24 px, at 10.5 to 12 px under 1.5), so it
    // follows the letters and never fills each glyph's box.
    expect(hex(rgb(id, 'text-halo-color', 4))).toBe('#000000');
    expect(num(id, 'paint', 'text-halo-width', 4)).toBe(CITY_NAME_HALO);
    expect(CITY_NAME_HALO).toBe(1);
    for (const zoom of [CITY_NAMES_FROM, 4, 5, 6, 6.9]) {
      expect(num(id, 'layout', 'text-size', zoom), String(zoom)).toBeCloseTo(cityNameSize(zoom), 9);
    }
    expect(num(id, 'layout', 'text-size', 4)).toBeGreaterThanOrEqual(10.5);
    expect(num(id, 'layout', 'text-size', 4)).toBeLessThanOrEqual(12);
  });

  it('reads the names from a source of one tile, so they are placed strictly by rank', () => {
    expect(STYLE.sources[BASEMAP_IDS.usCitySource]).toMatchObject({ type: 'geojson', maxzoom: 1 });
    const land = { type: 'Feature', properties: { kind: 'land' }, geometry: null };
    const state = { type: 'Feature', properties: { kind: 'state' }, geometry: null };
    const newYork = { type: 'Feature', properties: { kind: 'city', rank: 0 }, geometry: null };
    const [geometry, cities] = splitUsLines({
      type: 'FeatureCollection',
      features: [land, state, newYork],
    });
    expect(geometry).toEqual({ type: 'FeatureCollection', features: [land, state] });
    expect(cities).toEqual({ type: 'FeatureCollection', features: [newYork] });
    expect(splitUsLines('geo/us-lines.json')).toEqual(['geo/us-lines.json', 'geo/us-lines.json']);
  });
});

describe('roads', () => {
  /** The first zoom each class is drawn at, and where it is fully in. */
  const COMES_IN: readonly [string, number, number][] = [
    ['motorway', 7, 8],
    ['trunk', 7, 8],
    ['primary', 7, 8],
    ['secondary', 9, 10],
    ['tertiary', 10, 11],
    ['minor', 12, 13],
    ['service', 14, 15],
  ];

  for (const [roadClass, from, full] of COMES_IN) {
    it(`draws ${roadClass} roads from zoom ${String(from)}, fading in by ${String(full)}`, () => {
      const road = { class: roadClass };
      if (from > OPENFREEMAP_MIN_ZOOM) expect(draws(ROAD, from - 1, road)).toBe(false);
      expect(draws(ROAD, from, road)).toBe(true);
      expect(draws(ROAD, 16, road)).toBe(true);
      // Up from the ground as it comes in.
      const start = rgb(ROAD, 'line-color', from, road);
      const middle = rgb(ROAD, 'line-color', (from + full) / 2, road);
      const end = rgb(ROAD, 'line-color', full, road);
      expect(start).toEqual([0, 0, 0]);
      expect(middle[0]).toBeGreaterThan(0);
      expect(middle[0]).toBeLessThan(end[0]);
    });
  }

  it('draws nothing below zoom 7 and leaves out paths, rail, ferries and driveways', () => {
    expect(draws(ROAD, 6, { class: 'motorway' })).toBe(false);
    for (const roadClass of [
      'path',
      'track',
      'rail',
      'transit',
      'ferry',
      'motorway_construction',
    ]) {
      expect(draws(ROAD, 14, { class: roadClass }), roadClass).toBe(false);
    }
    for (const service of ['driveway', 'parking_aisle']) {
      expect(draws(ROAD, 14, { class: 'service', service }), service).toBe(false);
    }
    expect(draws(ROAD, 14, { class: 'service', service: 'alley' })).toBe(true);
  });

  it('draws more important roads brighter and wider, at every zoom', () => {
    const classes = ['motorway', 'primary', 'secondary', 'tertiary', 'minor', 'service'];
    for (const zoom of [12, 14, 16]) {
      const shown = classes.filter((c) => draws(ROAD, zoom, { class: c }));
      const widths = shown.map((c) => num(ROAD, 'paint', 'line-width', zoom, { class: c }));
      const tones = shown.map((c) => rgb(ROAD, 'line-color', zoom, { class: c })[0]);
      expect(widths, `widths at ${String(zoom)}`).toEqual([...widths].sort((a, b) => b - a));
      expect(new Set(widths).size).toBe(widths.length);
      expect(tones, `tones at ${String(zoom)}`).toEqual([...tones].sort((a, b) => b - a));
    }
    // Widths grow with zoom.
    for (const roadClass of classes) {
      const road = { class: roadClass };
      expect(num(ROAD, 'paint', 'line-width', 16, road)).toBeGreaterThan(
        num(ROAD, 'paint', 'line-width', 14, road),
      );
    }
    // A ramp is narrower than its road.
    expect(num(ROAD, 'paint', 'line-width', 14, { class: 'motorway', ramp: 1 })).toBeLessThan(
      num(ROAD, 'paint', 'line-width', 14, { class: 'motorway' }),
    );
  });

  it('keeps every road tier in the dark grey range', () => {
    for (const tier of ROAD_TIERS) {
      const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) =>
        Number.parseInt(tier.color.slice(i, i + 2), 16),
      );
      expect(r === g && g === b, tier.color).toBe(true);
      expect(r).toBeGreaterThanOrEqual(0x11);
      // Below the dimmest text (#6b6b6b) by a wide margin: roads never read as labels.
      expect(r).toBeLessThanOrEqual(0x48);
    }
  });
});

describe('buildings, water and parks', () => {
  const BUILDING = BASEMAP_IDS.ofmBuilding;

  it('draws building footprints from zoom 13, most of the way in at once, fully by 14', () => {
    expect(draws(BUILDING, 12, {}, GEOMETRY.polygon)).toBe(false);
    expect(draws(BUILDING, 13, {}, GEOMETRY.polygon)).toBe(true);
    const opacity = [13, 13.25, 13.5, 14, 16].map((z) => num(BUILDING, 'paint', 'fill-opacity', z));
    // A view at zoom 13 already shows its blocks.
    expect(opacity[0]).toBeGreaterThanOrEqual(0.5);
    expect(opacity[0]).toBeLessThan(1);
    expect(opacity).toEqual([...opacity].sort((a, b) => a - b));
    expect(opacity[3]).toBe(1);
    expect(value(BUILDING, 'paint', 'fill-outline-color', 14)).toBeDefined();
  });

  it("steps the footprints and the local streets up a tone at a street's zoom, under the names", () => {
    const tone = (channels: readonly number[]): number => channels[0] ?? 0;
    const building = (zoom: number) => rgb(BUILDING, 'fill-color', zoom, {});
    const edge = (zoom: number) => rgb(BUILDING, 'fill-outline-color', zoom, {});
    const minor = (zoom: number) =>
      rgb(BASEMAP_IDS.ofmRoad, 'line-color', zoom, { class: 'minor' });
    // A step up from zoom 14 to 15, where the blocks and the local streets carry the map.
    expect(tone(building(15))).toBeGreaterThan(tone(building(CLOSE_FROM)));
    expect(tone(edge(15))).toBeGreaterThan(tone(edge(CLOSE_FROM)));
    expect(tone(minor(15))).toBeGreaterThan(tone(minor(CLOSE_FROM)));
    expect(CLOSE_ZOOM).toBe(15);
    // The hierarchy holds: blocks under the streets, the streets under every name, the school
    // names brightest.
    expect(tone(building(15))).toBeLessThan(tone(minor(15)));
    expect(tone(edge(15))).toBeLessThan(tone(minor(15)));
    for (const tier of ROAD_TIERS) {
      expect(Number.parseInt(tier.close.slice(1, 3), 16), tier.close).toBeLessThan(0x6b);
    }
    expect(Number.parseInt(COLORS.labelBright.slice(1, 3), 16)).toBeGreaterThan(
      Number.parseInt(COLORS.label.slice(1, 3), 16),
    );
  });

  it('leaves the sea unfilled, as ground, so the edge of US waters never shows', () => {
    expect(draws(BASEMAP_IDS.ofmWaterFill, 12, { class: 'ocean' }, 3)).toBe(false);
    for (const inland of ['lake', 'river', 'pond', 'dock']) {
      expect(draws(BASEMAP_IDS.ofmWaterFill, 12, { class: inland }, 3), inland).toBe(true);
    }
    // The coast is still drawn, as the shore line.
    expect(draws(BASEMAP_IDS.ofmWater, 12, { class: 'ocean' }, 3)).toBe(true);
  });

  it('fills water and parks a hair off the ground, and leaves out swimming pools', () => {
    const water = rgb(BASEMAP_IDS.ofmWaterFill, 'fill-color', 12, { class: 'lake' });
    const park = rgb(BASEMAP_IDS.ofmPark, 'fill-color', 12, { subclass: 'park' });
    for (const tone of [water, park]) {
      expect(tone[0]).toBeGreaterThan(0);
      expect(tone[0]).toBeLessThanOrEqual(0x10);
    }
    expect(draws(BASEMAP_IDS.ofmWaterFill, 12, { class: 'swimming_pool' }, 3)).toBe(false);
    expect(draws(BASEMAP_IDS.ofmWater, 12, { class: 'swimming_pool' }, 3)).toBe(false);
    expect(draws(BASEMAP_IDS.ofmPark, 12, { class: 'grass', subclass: 'park' }, 3)).toBe(true);
    expect(draws(BASEMAP_IDS.ofmPark, 12, { class: 'farmland', subclass: 'farmland' }, 3)).toBe(
      false,
    );
  });

  it('marks school grounds a step brighter than parks, under the buildings, with an edge up close', () => {
    const grounds = BASEMAP_IDS.ofmSchoolGrounds;
    const edge = BASEMAP_IDS.ofmSchoolGroundsEdge;
    for (const kind of ['school', 'kindergarten']) {
      expect(draws(grounds, 11, { class: kind }, 3), kind).toBe(false);
      expect(draws(grounds, 12, { class: kind }, 3), kind).toBe(true);
    }
    // K-12 grounds only: no college campuses, playgrounds or pitches.
    for (const other of ['college', 'university', 'playground', 'pitch']) {
      expect(draws(grounds, 14, { class: other }, 3), other).toBe(false);
    }
    const tone = rgb(grounds, 'fill-color', 13, { class: 'school' })[0];
    expect(tone).toBeGreaterThan(
      rgb(BASEMAP_IDS.ofmPark, 'fill-color', 13, { subclass: 'park' })[0],
    );
    expect(tone).toBeLessThan(0x11);
    expect(num(grounds, 'paint', 'fill-opacity', 13)).toBe(1);
    expect(indexOf(grounds)).toBeLessThan(indexOf(BASEMAP_IDS.ofmBuilding));
    expect(draws(edge, 13, { class: 'school' }, 3)).toBe(false);
    expect(draws(edge, 14, { class: 'school' }, 3)).toBe(true);
    expect(num(edge, 'paint', 'line-opacity', 14)).toBe(1);
    expect(num(edge, 'paint', 'line-width', 14)).toBe(1);
    // Dimmer than any road, so a campus never reads as a street.
    expect(rgb(edge, 'line-color', 14)[0]).toBeLessThan(
      rgb(ROAD, 'line-color', 14, { class: 'minor' })[0] + 3,
    );
  });

  it('dims lake shores below the coasts, and every shore once the streets are in', () => {
    const shore = (zoom: number, waterClass: string): number =>
      rgb(BASEMAP_IDS.ofmWater, 'line-color', zoom, { class: waterClass })[0];
    expect(hex([shore(7, 'ocean'), shore(7, 'ocean'), shore(7, 'ocean')])).toBe('#6b6b6b');
    expect(shore(7, 'lake')).toBeLessThan(shore(7, 'ocean'));
    expect(shore(12, 'ocean')).toBe(shore(12, 'lake'));
    // No brighter than the brightest road.
    expect(shore(12, 'lake')).toBeLessThanOrEqual(
      rgb(ROAD, 'line-color', 12, { class: 'motorway' })[0],
    );
  });
});

describe('names', () => {
  it('names streets along the line from zoom 13, and major roads from 12', () => {
    const street = BASEMAP_IDS.ofmStreetLabel;
    const major = BASEMAP_IDS.ofmMajorRoadLabel;
    expect(draws(street, 12, { class: 'tertiary', name: 'Gillham Road' })).toBe(false);
    expect(draws(street, 13, { class: 'tertiary', name: 'Gillham Road' })).toBe(true);
    expect(draws(street, 12, { class: 'minor', name: 'Wornall Road' })).toBe(false);
    expect(draws(street, 13, { class: 'minor', name: 'Wornall Road' })).toBe(true);
    expect(draws(street, 14, { class: 'service', name: 'Alley' })).toBe(false);
    expect(draws(street, 15, { class: 'service', name: 'Alley' })).toBe(true);
    expect(draws(major, 11, { class: 'primary', name: 'Ward Parkway' })).toBe(false);
    expect(draws(major, 12, { class: 'primary', name: 'Ward Parkway' })).toBe(true);
    for (const id of [street, major]) {
      expect(value(id, 'layout', 'symbol-placement', 14)).toBe('line');
    }
    // A highway's number and a ramp's exit number go nowhere.
    expect(draws(major, 13, { class: 'motorway', ref: '35', network: 'us-interstate' })).toBe(
      false,
    );
    expect(draws(major, 13, { class: 'motorway', ref: '2T' })).toBe(false);
  });

  it('names through streets before the side streets that cross them', () => {
    const key = (street: string): number =>
      num(BASEMAP_IDS.ofmStreetLabel, 'layout', 'symbol-sort-key', 15, { class: street });
    expect(key('tertiary')).toBeLessThan(key('minor'));
    expect(key('minor')).toBeLessThan(key('service'));
  });

  it('sets street names a step above the dimmest grey where they come in, and in the place grey up close', () => {
    const shade = (id: string, zoom: number): number => rgb(id, 'text-color', zoom)[0];
    const dim = 0x6b;
    const full = 0xa3;
    for (const id of [BASEMAP_IDS.ofmStreetLabel, BASEMAP_IDS.ofmMajorRoadLabel]) {
      expect(shade(id, 13), id).toBeGreaterThan(dim);
      expect(shade(id, 16), id).toBe(full);
      for (const zoom of [13, 14, 15]) {
        expect(shade(id, zoom + 1), id).toBeGreaterThanOrEqual(shade(id, zoom));
      }
    }
    // Major roads a step ahead of the streets off them.
    expect(shade(BASEMAP_IDS.ofmMajorRoadLabel, 13)).toBeGreaterThan(
      shade(BASEMAP_IDS.ofmStreetLabel, 13),
    );
    expect(num(BASEMAP_IDS.ofmStreetLabel, 'layout', 'text-size', 13)).toBeGreaterThanOrEqual(11);
  });

  it('sets school names larger than any street or road name at every zoom they share', () => {
    for (const zoom of [13, 13.5, 14, 15, 16, 17, 18]) {
      const school = num(BASEMAP_IDS.schoolNames, 'layout', 'text-size', zoom);
      for (const id of [
        BASEMAP_IDS.ofmStreetLabel,
        BASEMAP_IDS.ofmMajorRoadLabel,
        BASEMAP_IDS.ofmWaterLabel,
        BASEMAP_IDS.ofmParkLabel,
        BASEMAP_IDS.ofmNeighbourhoodLabel,
      ]) {
        expect(school, `${id} at ${String(zoom)}`).toBeGreaterThan(
          num(id, 'layout', 'text-size', zoom),
        );
      }
    }
  });

  it('leaves highway numbers off the map: no label reads a route number and none draws a badge', () => {
    for (const candidate of [...LAYERS, ...WITH_SCHOOLS.layers]) {
      if (candidate.type !== 'symbol') continue;
      const layout = (candidate.layout ?? {}) as Record<string, unknown>;
      expect(JSON.stringify(layout['text-field'] ?? ''), candidate.id).not.toContain('"ref"');
      // The only image is the blank space that keeps names clear of a school's dot.
      expect([undefined, SCHOOL_SPACE_IMAGE], candidate.id).toContain(layout['icon-image']);
    }
  });

  it('names rivers along their course from zoom 13, and parks from 14, quietly', () => {
    const water = BASEMAP_IDS.ofmWaterLabel;
    const park = BASEMAP_IDS.ofmParkLabel;
    expect(draws(water, 12, { class: 'river', name: 'Brush Creek' })).toBe(false);
    expect(draws(water, 13, { class: 'river', name: 'Brush Creek' })).toBe(true);
    expect(draws(water, 14, { class: 'stream', name: 'Rock Creek' })).toBe(false);
    expect(draws(water, 14, { class: 'river' })).toBe(false);
    expect(value(water, 'layout', 'symbol-placement', 14)).toBe('line');
    const loose = { class: 'park', name: 'Jacob L. Loose Memorial Park', rank: 1 };
    expect(draws(park, 13, loose, 1)).toBe(false);
    expect(draws(park, 14, loose, 1)).toBe(true);
    expect(draws(park, 14, { ...loose, rank: 20 }, 1)).toBe(false);
    expect(draws(park, 15, { ...loose, rank: 20 }, 1)).toBe(true);
    expect(draws(park, 14, { class: 'park', rank: 1 }, 1)).toBe(false);
    expect(draws(park, 14, { class: 'school', name: 'A school', rank: 1 }, 1)).toBe(false);
    for (const id of [water, park]) {
      expect(hex(rgb(id, 'text-color', 15)), id).toBe(COLORS.labelDim);
    }
  });

  it('sets neighbourhoods in small spaced capitals, under the street and place names', () => {
    const layout = layer(BASEMAP_IDS.ofmNeighbourhoodLabel).layout as Record<string, unknown>;
    expect(layout['text-transform']).toBe('uppercase');
    expect(layout['text-letter-spacing']).toBeGreaterThanOrEqual(0.1);
    expect(hex(rgb(BASEMAP_IDS.ofmNeighbourhoodLabel, 'text-color', 14))).toBe(COLORS.labelDim);
  });

  it('draws every name class in full at the zoom it is named from, so whole-zoom views miss none', () => {
    const symbols = WITH_SCHOOLS.layers.filter((l) => l.type === 'symbol');
    for (const symbol of symbols) {
      // The city names hand over with the lines, the national ones come in by band (tested
      // below), the state names state by state (state-names.test.ts), and a dot's space is
      // never seen.
      if (
        symbol.id === BASEMAP_IDS.ofmCityLabel ||
        symbol.id === BASEMAP_IDS.schoolSpace ||
        symbol.id === BASEMAP_IDS.usStateLabel ||
        symbol.id === BASEMAP_IDS.usStateAreaLabel ||
        symbol.id.startsWith(BASEMAP_IDS.usCityLabel)
      ) {
        continue;
      }
      const from = (symbol.minzoom ?? 0) + LABEL_FADE;
      expect(Number.isInteger(from), symbol.id).toBe(true);
      expect(num(symbol.id, 'paint', 'text-opacity', from), symbol.id).toBe(1);
      expect(num(symbol.id, 'paint', 'text-opacity', from - LABEL_FADE), symbol.id).toBe(0);
    }
    expect(SCHOOL_FADE).toBe(LABEL_FADE);
  });

  /** Each place class, the first zoom it is drawn at, and a feature of it. */
  const PLACES: readonly [string, string, number, Properties][] = [
    [BASEMAP_IDS.ofmCityLabel, 'city', 7, { class: 'city', rank: 3, name: 'Kansas City' }],
    [BASEMAP_IDS.ofmTownLabel, 'town', 9, { class: 'town', rank: 12, name: 'Raytown' }],
    [BASEMAP_IDS.ofmVillageLabel, 'village', 11, { class: 'village', name: 'Mission Woods' }],
    [BASEMAP_IDS.ofmVillageLabel, 'suburb', 11, { class: 'suburb', name: 'Westport' }],
    [
      BASEMAP_IDS.ofmNeighbourhoodLabel,
      'neighbourhood',
      13,
      { class: 'neighbourhood', name: 'Sunset Hill' },
    ],
  ];

  for (const [id, placeClass, from, place] of PLACES) {
    it(`names each ${placeClass} from zoom ${String(from)}`, () => {
      if (from > OPENFREEMAP_MIN_ZOOM) expect(draws(id, from - 1, place, 1)).toBe(false);
      expect(draws(id, from, place, 1)).toBe(true);
      if (id === BASEMAP_IDS.ofmCityLabel) {
        // Cities come in with the street tiles, over the half level the bundled lines hand over.
        expect(num(id, 'paint', 'text-opacity', from)).toBe(0);
        expect(num(id, 'paint', 'text-opacity', from + 0.5)).toBe(1);
      } else {
        expect(num(id, 'paint', 'text-opacity', from - LABEL_FADE)).toBe(0);
        expect(num(id, 'paint', 'text-opacity', from)).toBe(1);
      }
    });
  }

  it('brings cities in by rank, the largest first', () => {
    const city = (rank: number): Properties => ({ class: 'city', rank, name: 'A city' });
    expect(draws(BASEMAP_IDS.ofmCityLabel, 7, city(2), 1)).toBe(true);
    expect(draws(BASEMAP_IDS.ofmCityLabel, 7, city(12), 1)).toBe(false);
    expect(draws(BASEMAP_IDS.ofmCityLabel, 9, city(12), 1)).toBe(true);
    // Larger cities, larger names; cities larger than towns, towns than suburbs.
    const size = (id: string, p: Properties, zoom: number): number =>
      num(id, 'layout', 'text-size', zoom, p);
    expect(size(BASEMAP_IDS.ofmCityLabel, city(2), 10)).toBeGreaterThan(
      size(BASEMAP_IDS.ofmCityLabel, city(12), 10),
    );
    expect(size(BASEMAP_IDS.ofmCityLabel, city(12), 11)).toBeGreaterThan(
      size(BASEMAP_IDS.ofmTownLabel, { class: 'town' }, 11),
    );
    expect(size(BASEMAP_IDS.ofmTownLabel, { class: 'town' }, 12)).toBeGreaterThan(
      size(BASEMAP_IDS.ofmVillageLabel, { class: 'suburb' }, 12),
    );
  });

  it('sets every name in Geist, never overlapping another', () => {
    const fonts = new Set<string>(Object.values(MAP_FONTS));
    for (const symbol of LAYERS.filter((l) => l.type === 'symbol')) {
      const layout = symbol.layout as Record<string, unknown>;
      const textFont = layout['text-font'] as string[];
      expect(
        textFont.every((font) => fonts.has(font)),
        symbol.id,
      ).toBe(true);
      expect(layout['text-allow-overlap'], symbol.id).toBe(false);
      expect(layout['text-ignore-placement'], symbol.id).toBe(false);
    }
  });
});

describe('schools', () => {
  const layers = WITH_SCHOOLS.layers;
  const at = (id: string): number => layers.findIndex((l) => l.id === id);
  const schoolLayer = (id: string): LayerSpecification => {
    const found = layers.find((l) => l.id === id);
    if (found === undefined) throw new Error(`No layer ${id}`);
    return found;
  };

  it("come from the archive the build ships, through the workers, from a metro's zoom", () => {
    expect(WITH_SCHOOLS.sources[BASEMAP_IDS.schoolsSource]).toEqual({
      type: 'vector',
      tiles: [`${SCHOOL_TILES_PROTOCOL}://${SCHOOL_ARCHIVE}/{z}/{x}/{y}`],
      minzoom: SCHOOL_TILES_MIN_ZOOM,
      maxzoom: SCHOOL_TILES_MAX_ZOOM,
    });
    // The tileset holds zooms 9 to 14: the dots fade in from the first of them.
    expect(SCHOOL_TILES_MIN_ZOOM).toBe(9);
    expect(SCHOOL_DOTS_FROM - SCHOOL_DOT_FADE).toBe(SCHOOL_TILES_MIN_ZOOM);
    for (const id of [BASEMAP_IDS.schoolDots, BASEMAP_IDS.schoolNames, BASEMAP_IDS.schoolLight]) {
      expect(schoolLayer(id)).toMatchObject({
        source: BASEMAP_IDS.schoolsSource,
        'source-layer': SCHOOLS_TILE_LAYER,
      });
    }
    // Every school is drawn across a metro: at the zoom "Show my area" opens at, and wider.
    expect(SCHOOL_DOTS_FROM).toBe(9.5);
    expect(SCHOOL_DOTS_FROM).toBeLessThan(NEARBY_ZOOM);
    expect(SCHOOL_NAMES_FROM).toBe(13);
    // Each fully drawn at its zoom, fading in before it.
    expect(schoolLayer(BASEMAP_IDS.schoolDots).minzoom).toBe(SCHOOL_TILES_MIN_ZOOM);
    expect(schoolLayer(BASEMAP_IDS.schoolNames).minzoom).toBe(13 - SCHOOL_FADE);
    expect(num(BASEMAP_IDS.schoolDots, 'paint', 'circle-opacity', SCHOOL_TILES_MIN_ZOOM)).toBe(0);
    for (const zoom of [SCHOOL_DOTS_FROM, NEARBY_ZOOM, 11, 13, 16]) {
      expect(num(BASEMAP_IDS.schoolDots, 'paint', 'circle-opacity', zoom), String(zoom)).toBe(1);
      expect(num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-opacity', zoom)).toBe(1);
    }
    expect(num(BASEMAP_IDS.schoolNames, 'paint', 'text-opacity', 13)).toBe(1);
  });

  it('put a campus written after a spaced dash on a second, dimmer line', () => {
    const label = (name: string): unknown =>
      value(BASEMAP_IDS.schoolNames, 'layout', 'text-field', 15, { name });
    expect(label('The Pembroke Hill School - Wornall Campus')).toMatchObject({
      sections: [
        { text: 'The Pembroke Hill School', scale: null },
        { text: '\n' },
        { text: 'Wornall Campus', scale: 0.88 },
      ],
    });
    const campus = (label('Crossroads - Quality Hill') as { sections: { textColor: unknown }[] })
      .sections[2]?.textColor as { r: number; a: number };
    expect(Math.round((campus.r / campus.a) * 255)).toBe(0xa3);
    // Anything else is one name, as written.
    expect(label('Frontier School of Excellence-U')).toMatchObject({
      sections: [{ text: 'Frontier School of Excellence-U' }],
    });
    expect(label('Visitation Catholic School')).toMatchObject({
      sections: [{ text: 'Visitation Catholic School' }],
    });
  });

  it('draw a dot white at every zoom, over a dark ring, larger than the road it stands on', () => {
    for (const zoom of [SCHOOL_DOTS_FROM, 10.2, 11, 12, 13, 15]) {
      expect(hex(rgb(BASEMAP_IDS.schoolDots, 'circle-color', zoom)), String(zoom)).toBe(
        COLORS.labelBright,
      );
      expect(hex(rgb(BASEMAP_IDS.schoolDots, 'circle-stroke-color', zoom))).toBe('#000000');
    }
    const radii = [SCHOOL_DOTS_FROM, 10, 11, 12, 13, 15, 17].map((z) =>
      num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', z),
    );
    expect(radii).toEqual([...radii].sort((a, b) => a - b));
    expect(new Set(radii).size).toBe(radii.length);
    expect((radii[4] ?? 0) * 2).toBeGreaterThan(
      num(ROAD, 'paint', 'line-width', 15, { class: 'minor' }),
    );
  });

  it('leave a school the glow lights to its light: no white dot and no white light around it', () => {
    const opacity = (id: string, name: string, zoom: number, lit: boolean): unknown => {
      const paint = (schoolLayer(id) as { paint: Record<string, unknown> }).paint;
      const spec = (latest as unknown as Record<string, Record<string, unknown>>).paint_circle?.[
        name
      ];
      const parsed = expression.createPropertyExpression(paint[name], name, spec as never);
      if (parsed.result !== 'success') throw new Error(`${id} ${name}`);
      const state = lit ? { [SCHOOL_LIT_STATE]: true } : {};
      return parsed.value.evaluate({ zoom }, { type: GEOMETRY.point, properties: {} }, state);
    };
    const drawn: [string, string][] = [
      [BASEMAP_IDS.schoolDots, 'circle-opacity'],
      [BASEMAP_IDS.schoolDots, 'circle-stroke-opacity'],
      [BASEMAP_IDS.schoolLight, 'circle-opacity'],
    ];
    for (const [id, name] of drawn) {
      for (const zoom of [SCHOOL_DOTS_FROM, 10.2, 11, 12, 13, 15, 17]) {
        if (zoom > (schoolLayer(id).maxzoom ?? 24)) continue;
        const where = `${id} ${name} ${String(zoom)}`;
        expect(opacity(id, name, zoom, true), where).toBe(0);
        expect(opacity(id, name, zoom, false), where).toBe(num(id, 'paint', name, zoom));
        expect(opacity(id, name, zoom, false), where).toBeGreaterThan(0);
      }
    }
    // The ring around the school a panel is open for stays, lit or not.
    expect(JSON.stringify(schoolLayer(BASEMAP_IDS.schoolSelected))).not.toContain(SCHOOL_LIT_STATE);
  });

  it('put a dot at each school under every label, and each name over every other label', () => {
    // Right under the glow's slot, so the glow shines over the dots, and the labels over both.
    expect(at(BASEMAP_IDS.schoolDots)).toBe(at(BASEMAP_IDS.glowSlot) - 1);
    expect(at(BASEMAP_IDS.glowSlot)).toBe(at(BASEMAP_IDS.labels) - 1);
    expect(at(BASEMAP_IDS.schoolDots)).toBeGreaterThan(at(BASEMAP_IDS.usMask));
    // MapLibre places the top layer's labels first: each dot's space, then school names, then
    // street and place names.
    const symbols = layers.filter((l) => l.type === 'symbol').map((l) => l.id);
    expect(symbols.slice(-2)).toEqual([BASEMAP_IDS.schoolNames, BASEMAP_IDS.schoolSpace]);
    expect(at(BASEMAP_IDS.schoolSpace)).toBe(at(BASEMAP_IDS.schools) - 1);
    // Everything else is where it is without schools.
    const added: string[] = [
      BASEMAP_IDS.schoolLight,
      BASEMAP_IDS.schoolSelected,
      BASEMAP_IDS.schoolDots,
      BASEMAP_IDS.schoolNames,
      BASEMAP_IDS.schoolSpace,
    ];
    expect(layers.map((l) => l.id).filter((id) => !added.includes(id))).toEqual(
      LAYERS.map((l) => l.id),
    );
  });

  it('ring the school whose panel is open, under its dot, in white, and no school until one is', () => {
    expect(at(BASEMAP_IDS.schoolSelected)).toBe(at(BASEMAP_IDS.schoolDots) - 1);
    const ring = schoolLayer(BASEMAP_IDS.schoolSelected);
    expect(ring).toMatchObject({
      type: 'circle',
      source: BASEMAP_IDS.schoolsSource,
      'source-layer': SCHOOLS_TILE_LAYER,
      minzoom: SCHOOL_TILES_MIN_ZOOM,
      filter: selectedSchoolFilter(null),
    });
    expect(selectedSchoolFilter('A1902690')).toEqual(['==', ['get', 'id'], 'A1902690']);
    expect(hex(rgb(BASEMAP_IDS.schoolSelected, 'circle-stroke-color', 15))).toBe(
      COLORS.labelBright,
    );
    // Clear of the dot and its dark ring at every zoom, so the dot stands inside it.
    for (const z of [SCHOOL_DOTS_FROM, 10, 11, 13, 15, 17]) {
      const dot =
        num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', z) +
        num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-width', z);
      expect(num(BASEMAP_IDS.schoolSelected, 'paint', 'circle-radius', z)).toBeGreaterThan(dot + 2);
    }
  });

  it('keep each dot clear of every name up close, unseen', () => {
    const space = schoolLayer(BASEMAP_IDS.schoolSpace) as SymbolLayerSpecification;
    expect(space.minzoom).toBe(SCHOOL_NAMES_FROM - SCHOOL_FADE);
    expect(space.layout).toMatchObject({
      'icon-image': SCHOOL_SPACE_IMAGE,
      'icon-allow-overlap': true,
      'icon-ignore-placement': false,
    });
    expect(space.paint).toEqual({ 'icon-opacity': 0 });
    // As wide as the dot and its ring at each zoom.
    for (const zoom of [13, 15, 17]) {
      const across = num(BASEMAP_IDS.schoolSpace, 'layout', 'icon-size', zoom) * SCHOOL_SPACE_SIZE;
      const dot =
        2 *
        (num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', zoom) +
          num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-width', zoom));
      expect(across).toBeCloseTo(dot, 1);
    }
    const image = schoolSpaceImage();
    expect([image.width, image.height]).toEqual([SCHOOL_SPACE_SIZE, SCHOOL_SPACE_SIZE]);
    expect(image.data.every((byte) => byte === 0)).toBe(true);
  });

  it('name schools beside their dots, never over another name', () => {
    const names = schoolLayer(BASEMAP_IDS.schoolNames) as SymbolLayerSpecification;
    expect(names.layout).toMatchObject({
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-optional': false,
      'text-font': [MAP_FONTS.medium],
    });
    // Beside the dot first, then under or over it, then at a corner.
    const anchors = names.layout?.['text-variable-anchor-offset'] as unknown as unknown[];
    expect(anchors.filter((_value, i) => i % 2 === 0)).toEqual([
      'left',
      'right',
      'top',
      'bottom',
      'bottom-left',
      'bottom-right',
      'top-left',
      'top-right',
    ]);
    // Under or over, the name clears its dot's space and its own padding: a phone's narrow
    // screen, with no room at either side, still has a place for it.
    for (const zoom of [13, 14, 15, 16]) {
      const size = num(BASEMAP_IDS.schoolNames, 'layout', 'text-size', zoom);
      const space =
        (num(BASEMAP_IDS.schoolSpace, 'layout', 'icon-size', zoom) * SCHOOL_SPACE_SIZE) / 2;
      expect(SCHOOL_NAME_UNDER * size - SCHOOL_NAME_PADDING, String(zoom)).toBeGreaterThan(
        space + 1,
      );
    }
  });

  it('stand out across a metro: the brightest marks on the map, ringed, pixels apart', () => {
    for (const zoom of [SCHOOL_DOTS_FROM, 10, 10.2, 11, 12]) {
      const where = String(zoom);
      const dot = rgb(BASEMAP_IDS.schoolDots, 'circle-color', zoom)[0];
      // Brighter than every place name, and so than every road, street name and shore.
      expect(dot, where).toBeGreaterThan(Number.parseInt(COLORS.label.slice(1, 3), 16));
      expect(num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', zoom), where).toBeGreaterThan(
        zoom < 10 ? 1.7 : 2,
      );
      // Parted from the road under it and the dot beside it by a ring of the ground.
      expect(
        num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-width', zoom),
        where,
      ).toBeGreaterThanOrEqual(0.75);
    }
  });

  it('knock the dots out under a place name across a metro, with a wider halo there only', () => {
    const halo = (style: StyleSpecification, id: string, name: string, zoom: number): unknown => {
      const found = style.layers.find((l) => l.id === id);
      if (found === undefined) throw new Error(`No layer ${id}`);
      return valueOf(found, 'paint', name, zoom);
    };
    const places = [
      BASEMAP_IDS.ofmCityLabel,
      BASEMAP_IDS.ofmTownLabel,
      BASEMAP_IDS.ofmVillageLabel,
    ] as const;
    for (const id of places) {
      for (const zoom of [SCHOOL_DOTS_FROM, 10.2, 11, 12, SCHOOL_NAMES_FROM - SCHOOL_FADE]) {
        const where = `${id} ${String(zoom)}`;
        expect(halo(WITH_SCHOOLS, id, 'text-halo-width', zoom), where).toBe(METRO_PLACE_HALO);
        expect(halo(WITH_SCHOOLS, id, 'text-halo-color', zoom)).toEqual(
          halo(STYLE, id, 'text-halo-color', zoom),
        );
        // Wide enough to cover a dot and its ring between two letters.
        const dot =
          num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', zoom) +
          num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-width', zoom);
        expect(2 * METRO_PLACE_HALO, where).toBeGreaterThan(dot);
      }
      // The street tiles' own halo further out, up close, and without the schools.
      for (const zoom of [7, 8, SCHOOL_TILES_MIN_ZOOM, SCHOOL_NAMES_FROM, 15]) {
        const plain = halo(STYLE, id, 'text-halo-width', zoom);
        expect(plain).toBe(num(BASEMAP_IDS.ofmStreetLabel, 'paint', 'text-halo-width', zoom));
        expect(halo(WITH_SCHOOLS, id, 'text-halo-width', zoom), `${id} ${String(zoom)}`).toBe(
          plain,
        );
      }
      expect(halo(STYLE, id, 'text-halo-width', 10.2)).toBeLessThan(METRO_PLACE_HALO);
    }
  });

  it('step the roads back across a metro, and only there, where the schools are drawn', () => {
    const road = (style: StyleSpecification, id: string): LayerSpecification => {
      const found = style.layers.find((l) => l.id === id);
      if (found === undefined) throw new Error(`No layer ${id}`);
      return found;
    };
    const tone = (style: StyleSpecification, id: string, zoom: number, roadClass: string) =>
      channels(valueOf(road(style, id), 'paint', 'line-color', zoom, { class: roadClass }))[0];
    for (const id of [ROAD, BRIDGE, TUNNEL]) {
      for (const roadClass of ['motorway', 'primary', 'secondary']) {
        const what = `${id} ${roadClass}`;
        // Across a metro, METRO_ROAD_TONE of the tone they have without the schools.
        for (const zoom of [SCHOOL_DOTS_FROM, 10.2, 11, 12]) {
          const full = tone(STYLE, id, zoom, roadClass);
          expect(tone(WITH_SCHOOLS, id, zoom, roadClass), `${what} ${String(zoom)}`).toBeCloseTo(
            full * METRO_ROAD_TONE,
            -0.5,
          );
          expect(metroRoadTone(zoom)).toBe(METRO_ROAD_TONE);
        }
        // Their own tone further out, and up close from the zoom names come in at.
        for (const zoom of [7.5, 8, SCHOOL_TILES_MIN_ZOOM, SCHOOL_NAMES_FROM, 14, 16]) {
          expect(tone(WITH_SCHOOLS, id, zoom, roadClass), `${what} ${String(zoom)}`).toBe(
            tone(STYLE, id, zoom, roadClass),
          );
          expect(metroRoadTone(zoom)).toBe(1);
        }
      }
    }
    // Still in their order, and each under the schools' white.
    for (const zoom of [10.2, 12]) {
      const tones = ['motorway', 'primary', 'secondary'].map((c) =>
        tone(WITH_SCHOOLS, ROAD, zoom, c),
      );
      expect(tones).toEqual([...tones].sort((a, b) => b - a));
      expect(Math.max(...tones)).toBeLessThan(Number.parseInt(COLORS.label.slice(1, 3), 16) / 2);
    }
  });

  it('light each dot softly across a metro, under the dots, gone before the names come in', () => {
    const light = schoolLayer(BASEMAP_IDS.schoolLight);
    expect(at(BASEMAP_IDS.schoolLight)).toBe(at(BASEMAP_IDS.schoolSelected) - 1);
    expect(light).toMatchObject({ type: 'circle', minzoom: SCHOOL_TILES_MIN_ZOOM });
    expect(light.maxzoom).toBeLessThanOrEqual(SCHOOL_NAMES_FROM - SCHOOL_FADE);
    expect(num(BASEMAP_IDS.schoolLight, 'paint', 'circle-blur', 10)).toBe(1);
    expect(num(BASEMAP_IDS.schoolLight, 'paint', 'circle-opacity', SCHOOL_TILES_MIN_ZOOM)).toBe(0);
    expect(
      num(BASEMAP_IDS.schoolLight, 'paint', 'circle-opacity', SCHOOL_NAMES_FROM - SCHOOL_FADE),
    ).toBe(0);
    for (const zoom of [SCHOOL_DOTS_FROM, 10.2, 11, SCHOOL_LIGHT_UNTIL]) {
      const where = String(zoom);
      expect(hex(rgb(BASEMAP_IDS.schoolLight, 'circle-color', zoom))).toBe(COLORS.labelBright);
      // Soft: a lone school is a point of light, and only a crowd of them a glow.
      expect(num(BASEMAP_IDS.schoolLight, 'paint', 'circle-opacity', zoom), where).toBe(
        SCHOOL_LIGHT_OPACITY,
      );
      expect(SCHOOL_LIGHT_OPACITY).toBeLessThanOrEqual(0.35);
      // Past the dot and its ring, all round.
      const dot =
        num(BASEMAP_IDS.schoolDots, 'paint', 'circle-radius', zoom) +
        num(BASEMAP_IDS.schoolDots, 'paint', 'circle-stroke-width', zoom);
      expect(num(BASEMAP_IDS.schoolLight, 'paint', 'circle-radius', zoom), where).toBeGreaterThan(
        2 * dot,
      );
    }
  });

  it('are drawn in white on the ground, the names brightest up close', () => {
    const paint = (id: string) =>
      (schoolLayer(id) as { paint?: Record<string, unknown> }).paint ?? {};
    const colors = JSON.stringify([
      paint(BASEMAP_IDS.schoolLight),
      paint(BASEMAP_IDS.schoolSelected),
      paint(BASEMAP_IDS.schoolDots),
      paint(BASEMAP_IDS.schoolNames),
    ]).match(/#[0-9a-f]{3,6}/gi);
    expect(new Set(colors)).toEqual(new Set([COLORS.labelBright, COLORS.background]));
  });
});

describe('the network', () => {
  it('asks for nothing below zoom 7: no glyph server, no sprite, no font files, no tiles', () => {
    expect(STYLE.glyphs).toBeUndefined();
    expect(STYLE.sprite).toBeUndefined();
    expect(STYLE['font-faces']).toBeUndefined();
    const sources = STYLE.sources;
    expect(sources[BASEMAP_IDS.usSource]).toMatchObject({ type: 'geojson', data: US_LINES });
    expect(sources[BASEMAP_IDS.usCitySource]).toMatchObject({ type: 'geojson', data: US_LINES });
    const tiles = sources[BASEMAP_IDS.openFreeMapSource];
    expect(tiles).toMatchObject({ type: 'vector', minzoom: 7 });
    // The states in view start empty: the map fills them in on a phone, from the site's own file.
    expect(sources[BASEMAP_IDS.usStateAreaSource]).toEqual({
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });
    expect(Object.keys(sources).sort()).toEqual(
      [
        BASEMAP_IDS.usSource,
        BASEMAP_IDS.usCitySource,
        BASEMAP_IDS.usStateAreaSource,
        BASEMAP_IDS.openFreeMapSource,
      ].sort(),
    );
    for (const drawn of LAYERS) {
      if (!('source' in drawn)) continue;
      if (drawn.source === BASEMAP_IDS.openFreeMapSource) {
        expect(drawn.minzoom ?? 0, drawn.id).toBeGreaterThanOrEqual(OPENFREEMAP_MIN_ZOOM);
      } else if (drawn.type === 'symbol') {
        // Below zoom 7 only the national city and state names draw text, from the page's own
        // Geist faces (fonts.ts): no glyph file is asked for.
        expect([BASEMAP_IDS.usCitySource, BASEMAP_IDS.usStateAreaSource], drawn.id).toContain(
          drawn.source,
        );
      }
    }
  });
});

describe('colors', () => {
  /** Every color literal anywhere in the style. */
  function colorsIn(input: unknown, found: string[] = []): string[] {
    if (typeof input === 'string' && /^(#|rgb|hsl)/i.test(input)) found.push(input);
    else if (Array.isArray(input)) for (const item of input) colorsIn(item, found);
    else if (typeof input === 'object' && input !== null) {
      for (const item of Object.values(input)) colorsIn(item, found);
    }
    return found;
  }

  it('is monochrome: every color is a grey', () => {
    const colors = colorsIn(LAYERS);
    expect(colors.length).toBeGreaterThan(20);
    for (const color of colors) {
      const channels = mixColors(color, color, 0)
        .slice(1)
        .match(/../g)
        ?.map((c) => Number.parseInt(c, 16));
      expect(new Set(channels).size, color).toBe(1);
    }
  });

  it('mixes colors channel by channel', () => {
    expect(mixColors('#000', '#3a3a3a', 0)).toBe('#000000');
    expect(mixColors('#000', '#3a3a3a', 1)).toBe('#3a3a3a');
    expect(mixColors('#000000', '#404040', 0.5)).toBe('#202020');
    expect(mixColors('#000', '#fff', 2)).toBe('#ffffff');
    expect(() => mixColors('red', '#fff', 0.5)).toThrow();
  });
});

describe('label faces', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('registers Geist under each family the style names, loading nothing', () => {
    const made: FakeFontFace[] = [];
    class FakeFontFace {
      readonly family: string;
      readonly source: string;
      readonly descriptors: FontFaceDescriptors;
      constructor(family: string, source: string, descriptors: FontFaceDescriptors) {
        this.family = family;
        this.source = source;
        this.descriptors = descriptors;
        made.push(this);
      }
    }
    vi.stubGlobal('FontFace', FakeFontFace);
    const added: unknown[] = [];
    const fonts = { add: (face: unknown) => added.push(face) } as unknown as FontFaceSet;
    const faces = addMapFonts(fonts);
    expect(addMapFonts(fonts)).toBe(faces);
    expect(added).toHaveLength(Object.values(MAP_FONTS).length * MAP_FONT_FILES.length);
    expect(new Set(made.map((face) => face.family))).toEqual(new Set(Object.values(MAP_FONTS)));
    for (const face of made) {
      expect(face.source).toMatch(/geist-latin(-ext)?-wght-normal.*\.woff2/);
      expect(face.descriptors.weight).toBe('100 900');
    }
    // Both files answer MapLibre's font load, which asks for a space.
    for (const file of MAP_FONT_FILES) {
      expect(
        file.unicodeRange.split(',').some((range) => /^U\+(0000-00FF|0020)$/.test(range)),
      ).toBe(true);
    }
  });
});

describe('the bundled lines’ sources', () => {
  const URLS = {
    lines: 'https://snowlight.test/geo/us-lines.0123456789.json',
    names: 'https://snowlight.test/geo/us-names.0123456789.json',
  };
  const FROM_FILES = buildBasemapStyle({
    usLines: US_LINES,
    usLinesUrls: URLS,
    hairline: 1,
    colors: COLORS,
  });
  const keeps = (source: string, kind: string): boolean => {
    const { filter } = FROM_FILES.sources[source] as { filter?: FilterSpecification };
    if (filter === undefined) return true;
    return featureFilter(filter, 'filter').filter({ zoom: 0 }, { type: 1, properties: { kind } });
  };

  it('read the lines and their names from the files, for MapLibre’s workers to fetch', () => {
    expect(FROM_FILES.sources[BASEMAP_IDS.usSource]).toMatchObject({
      type: 'geojson',
      data: URLS.lines,
    });
    expect(FROM_FILES.sources[BASEMAP_IDS.usCitySource]).toMatchObject({
      type: 'geojson',
      data: URLS.names,
    });
    expect(validateStyleMin(FROM_FILES)).toEqual([]);
  });

  it('each keep their own kinds of feature, whatever the file holds', () => {
    for (const kind of ['land', 'state', 'land-simple', 'state-simple']) {
      expect(keeps(BASEMAP_IDS.usSource, kind), kind).toBe(true);
      expect(keeps(BASEMAP_IDS.usCitySource, kind), kind).toBe(false);
    }
    for (const kind of ['city', 'state-name']) {
      expect(keeps(BASEMAP_IDS.usSource, kind), kind).toBe(false);
      expect(keeps(BASEMAP_IDS.usCitySource, kind), kind).toBe(true);
    }
  });
});

describe('staging the style', () => {
  const ids = (layers: readonly LayerSpecification[]): string[] => layers.map((l) => l.id);
  const sourceOf = (l: LayerSpecification): string | null =>
    'source' in l && typeof l.source === 'string' ? l.source : null;
  /** Whether MapLibre draws the layer at the zoom: shown and in its zoom range. */
  const drawnAt = (l: LayerSpecification, zoom: number): boolean =>
    (l.layout as { visibility?: string } | undefined)?.visibility !== 'none' &&
    zoom >= (l.minzoom ?? 0) &&
    zoom < (l.maxzoom ?? 24);
  const ZOOMS = {
    'a phone’s whole country': 2.2,
    'a desktop’s national view': 3.93,
    'a metro view': 10,
    'a street view': 14.5,
  };

  for (const [view, zoom] of Object.entries(ZOOMS)) {
    it(`takes every layer once, in the full style’s order within each step (${view})`, () => {
      const staged = stageStyle(WITH_SCHOOLS, zoom);
      const all = [...staged.style.layers, ...staged.now, ...staged.later];
      expect(new Set(ids(all)).size).toBe(WITH_SCHOOLS.layers.length);
      expect(ids(all).sort()).toEqual(ids(WITH_SCHOOLS.layers).sort());
      expect(staged.order).toEqual(ids(WITH_SCHOOLS.layers));
      for (const step of [staged.style.layers, staged.now, staged.later]) {
        const at = ids(step).map((id) => staged.order.indexOf(id));
        expect(at).toEqual([...at].sort((a, b) => a - b));
      }
      // Every source is there from the start; the style is otherwise the full one.
      expect(staged.style.sources).toEqual(WITH_SCHOOLS.sources);
      expect({ ...staged.style, layers: [] }).toEqual({ ...WITH_SCHOOLS, layers: [] });
    });

    it(`creates the map with the ground and the slots, then the view’s sources (${view})`, () => {
      const staged = stageStyle(WITH_SCHOOLS, zoom);
      // No layer that reads a source: the ground, and the glow's and the schools' slots.
      expect(ids(staged.style.layers)).toEqual([
        BASEMAP_IDS.background,
        BASEMAP_IDS.glowSlot,
        BASEMAP_IDS.schools,
      ]);
      // Then every layer of each source a layer drawn at the zoom reads, all of them, so no
      // source has its tiles cut again for a layer that comes after: the rest read the others.
      const inView = new Set(WITH_SCHOOLS.layers.filter((l) => drawnAt(l, zoom)).map(sourceOf));
      inView.delete(null);
      expect(new Set(staged.now.map(sourceOf))).toEqual(inView);
      expect(staged.later.some((l) => inView.has(sourceOf(l)))).toBe(false);
      expect(staged.now.some((l) => drawnAt(l, zoom))).toBe(true);
    });
  }

  it('puts a phone’s whole country on the bundled lines alone, the names and streets after', () => {
    const staged = stageStyle(WITH_SCHOOLS, 2.2);
    expect(new Set(staged.now.map(sourceOf))).toEqual(new Set([BASEMAP_IDS.usSource]));
    expect(staged.later.map(sourceOf)).toContain(BASEMAP_IDS.usCitySource);
    expect(staged.later.map(sourceOf)).toContain(BASEMAP_IDS.openFreeMapSource);
  });

  it('puts a street view on the street and school tiles, the national lines after', () => {
    const staged = stageStyle(WITH_SCHOOLS, 14.5);
    expect(new Set(staged.now.map(sourceOf))).toEqual(
      new Set([BASEMAP_IDS.openFreeMapSource, BASEMAP_IDS.schoolsSource]),
    );
    expect(ids(staged.later)).toContain(BASEMAP_IDS.usOutline);
  });
});
