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
} from '@maplibre/maplibre-gl-style-spec';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MAP_FONT_FILES, MAP_FONTS, addMapFonts } from '../fonts';
import { BASEMAP_IDS } from '../ids';
import { BORDER_LAYER, MASK_LAYER } from '../mask/format';
import { OPENFREEMAP_MIN_ZOOM } from '../openfreemap';
import { ROAD_TIERS, buildBasemapStyle, mixColors } from '../style';
import type { BasemapColors, UsLinesData } from '../style';

const COLORS: BasemapColors = {
  background: '#000',
  outline: '#6b6b6b',
  state: '#2a2a2a',
  label: '#a3a3a3',
  labelDim: '#6b6b6b',
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

function layer(id: string): LayerSpecification {
  const found = LAYERS.find((candidate) => candidate.id === id);
  if (found === undefined) throw new Error(`No layer ${id}`);
  return found;
}

function indexOf(id: string): number {
  const index = LAYERS.findIndex((candidate) => candidate.id === id);
  if (index < 0) throw new Error(`No layer ${id}`);
  return index;
}

type Properties = Record<string, string | number>;

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
  const target = layer(id) as unknown as Record<Section, Record<string, unknown> | undefined> & {
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
  const color = value(id, 'paint', name, zoom, p) as { r: number; g: number; b: number; a: number };
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
    const sources = Object.keys(STYLE.sources);
    for (const [key, id] of Object.entries(BASEMAP_IDS)) {
      if (key.endsWith('Source')) expect(sources, key).toContain(id);
      else
        expect(
          LAYERS.map((l) => l.id),
          key,
        ).toContain(id);
    }
    expect(new Set(LAYERS.map((l) => l.id)).size).toBe(LAYERS.length);
  });
});

describe('layer order', () => {
  it('draws the ground, then fills, shores and roads, then the US mask and borders, then names', () => {
    const order = [
      BASEMAP_IDS.background,
      BASEMAP_IDS.ofmPark,
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
      BASEMAP_IDS.usStates,
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
      // Over the mask: only the border line, the bundled US lines, names and the schools slot.
      expect(
        drawn.type === 'symbol' ||
          drawn.id === BASEMAP_IDS.usBorder ||
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
    const firstSymbol = LAYERS.findIndex((l) => l.type === 'symbol');
    expect(LAYERS[firstSymbol]?.id).toBe(BASEMAP_IDS.labels);
    for (const drawn of LAYERS.slice(firstSymbol)) {
      expect(['symbol', 'background'], drawn.id).toContain(drawn.type);
    }
    // MapLibre places the top layer's labels first: cities win over towns, towns over streets.
    expect(symbols).toEqual([
      BASEMAP_IDS.ofmNeighbourhoodLabel,
      BASEMAP_IDS.ofmStreetLabel,
      BASEMAP_IDS.ofmMajorRoadLabel,
      BASEMAP_IDS.ofmVillageLabel,
      BASEMAP_IDS.ofmTownLabel,
      BASEMAP_IDS.ofmCityLabel,
    ]);
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
      expect(r).toBeLessThanOrEqual(0x3a);
    }
  });
});

describe('buildings, water and parks', () => {
  const BUILDING = BASEMAP_IDS.ofmBuilding;

  it('draws building footprints from zoom 13, fading in by 14', () => {
    expect(draws(BUILDING, 12, {}, GEOMETRY.polygon)).toBe(false);
    expect(draws(BUILDING, 13, {}, GEOMETRY.polygon)).toBe(true);
    const opacity = [13, 13.25, 13.5, 14, 16].map((z) => num(BUILDING, 'paint', 'fill-opacity', z));
    expect(opacity[0]).toBe(0);
    expect(opacity).toEqual([...opacity].sort((a, b) => a - b));
    expect(opacity[3]).toBe(1);
    expect(value(BUILDING, 'paint', 'fill-outline-color', 14)).toBeDefined();
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
    expect(draws(street, 12, { class: 'minor', name: 'Wornall Road' })).toBe(false);
    expect(draws(street, 13, { class: 'minor', name: 'Wornall Road' })).toBe(true);
    expect(draws(street, 14, { class: 'service', name: 'Alley' })).toBe(false);
    expect(draws(street, 15, { class: 'service', name: 'Alley' })).toBe(true);
    expect(draws(major, 11, { class: 'primary', name: 'Ward Parkway' })).toBe(false);
    expect(draws(major, 12, { class: 'primary', name: 'Ward Parkway' })).toBe(true);
    for (const id of [street, major]) {
      expect(value(id, 'layout', 'symbol-placement', 14)).toBe('line');
    }
    // A highway with no name goes by its number.
    expect(
      value(major, 'layout', 'text-field', 13, { class: 'motorway', ref: 'I 35' }),
    ).toMatchObject({ sections: [{ text: 'I 35' }] });
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
      expect(num(id, 'paint', 'text-opacity', from)).toBe(0);
      expect(num(id, 'paint', 'text-opacity', from + 0.5)).toBe(1);
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

describe('the network', () => {
  it('asks for nothing below zoom 7: no glyph server, no sprite, no font files, no tiles', () => {
    expect(STYLE.glyphs).toBeUndefined();
    expect(STYLE.sprite).toBeUndefined();
    expect(STYLE['font-faces']).toBeUndefined();
    const sources = STYLE.sources;
    expect(sources[BASEMAP_IDS.usSource]).toMatchObject({ type: 'geojson', data: US_LINES });
    const tiles = sources[BASEMAP_IDS.openFreeMapSource];
    expect(tiles).toMatchObject({ type: 'vector', minzoom: 7 });
    expect(Object.keys(sources).sort()).toEqual(
      [BASEMAP_IDS.usSource, BASEMAP_IDS.openFreeMapSource].sort(),
    );
    for (const drawn of LAYERS) {
      if (!('source' in drawn)) continue;
      if (drawn.source === BASEMAP_IDS.openFreeMapSource) {
        expect(drawn.minzoom ?? 0, drawn.id).toBeGreaterThanOrEqual(OPENFREEMAP_MIN_ZOOM);
      } else {
        // The bundled lines draw no text, so they never need a glyph.
        expect(drawn.type, drawn.id).not.toBe('symbol');
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
