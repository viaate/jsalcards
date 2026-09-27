// @vitest-environment node
/**
 * The state names a phone's map draws (state-names.ts, style.ts): each from
 * the zoom its name fits inside its state at, in one layer under the city
 * names, spaced as build-geo.mjs placed them, and only where the page asks for
 * a phone's names.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { expression, featureFilter, latest } from '@maplibre/maplibre-gl-style-spec';
import type { FilterSpecification, LayerSpecification } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import type { MapView } from '../bounds';
import { stateNamesCutByEdges } from '../home-names';
import type { MeasureText } from '../home-names';
import { BASEMAP_IDS } from '../ids';
import { OPENFREEMAP_MIN_ZOOM } from '../openfreemap';
import {
  STATE_NAMES_UNTIL,
  namedStates,
  stateNameFrom,
  stateNameShown,
  stateNameSize,
  stateNamesAt,
  stateNamesOf,
} from '../state-names';
import type { StateName } from '../state-names';
import {
  CITY_NAME_BANDS,
  CITY_NAME_LETTER_SPACING,
  CITY_NAME_PADDING,
  CITY_NAME_PHONE_PADDING,
  STATE_NAME_PADDING,
  buildBasemapStyle,
  cityNameLayerId,
  cityNameSize,
  stateNameFilter,
} from '../style';
import type { BasemapColors, UsLinesData } from '../style';
import { STATE_NAME_SIZE, STATE_NAMES_CLEAR_OF, US_LINES_FILE } from '../us-geo';

const US_LINES = JSON.parse(
  readFileSync(
    fileURLToPath(new URL(`../../../../public/${US_LINES_FILE}`, import.meta.url)),
    'utf8',
  ),
) as UsLinesData;

const COLORS: BasemapColors = {
  background: '#000',
  land: '#000',
  outline: '#8f8f8f',
  state: '#4d4d4d',
  label: '#a3a3a3',
  labelDim: '#6b6b6b',
  labelBright: '#f5f5f5',
  building: '#111',
  buildingEdge: '#1f1f1f',
};

const STATES = stateNamesOf(US_LINES);
const NAMED = namedStates(STATES);
/** The names a 390 x 844 phone's home view fits. */
const AT_HOME = stateNamesAt(NAMED, 3.85);
const PHONE = buildBasemapStyle({
  usLines: US_LINES,
  hairline: 1,
  colors: COLORS,
  phoneNames: true,
  stateNames: AT_HOME,
});
const WIDE = buildBasemapStyle({ usLines: US_LINES, hairline: 1, colors: COLORS });

/** The one layer of state names in a style. */
function stateLayer(layers: readonly LayerSpecification[]): LayerSpecification {
  const found = layers.filter((layer) => layer.id.startsWith(BASEMAP_IDS.usStateLabel));
  expect(found).toHaveLength(1);
  const [layer] = found;
  if (layer === undefined) throw new Error('no state names');
  return layer;
}

/** A layout or paint value of a layer at a zoom. */
function evaluate(
  layer: LayerSpecification,
  section: 'layout' | 'paint',
  name: string,
  zoom: number,
): unknown {
  const input = (layer as unknown as Record<string, Record<string, unknown> | undefined>)[
    section
  ]?.[name];
  const reference = latest as unknown as Record<string, Record<string, unknown>>;
  const spec = reference[`${section}_${layer.type}`]?.[name];
  const parsed = expression.createPropertyExpression(input, name, spec as never);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  return parsed.value.evaluate({ zoom }, { type: 1, properties: {} });
}

describe('the state names in the bundled file', () => {
  it('are read whole, and anything else or malformed is left out', () => {
    expect(STATES).toHaveLength(48);
    const kansas = STATES.find((state) => state.name === 'Kansas');
    expect(kansas).toMatchObject({ name: 'Kansas', label: 'Kansas' });
    expect(kansas?.fit).toBeGreaterThan(1);
    expect(
      stateNamesOf({
        features: [
          { properties: { kind: 'city', name: 'Topeka' }, geometry: { type: 'Point' } },
          { properties: { kind: 'state-name', name: 'Nowhere', label: 'Nowhere', fit: 1 } },
          {
            properties: { kind: 'state-name', name: 'Nofit', label: 'Nofit', fit: 0 },
            geometry: { type: 'Point', coordinates: [-100, 40] },
          },
          {
            properties: { kind: 'state-name', name: 'Halfway', label: 'Halfway', fit: 1 },
            geometry: { type: 'Point', coordinates: ['a', 40] },
          },
          null,
        ],
      }),
    ).toEqual([]);
  });
});

describe('when a state is named', () => {
  it('from the zoom its name fits at, in hundredths, and never before the size starts', () => {
    for (const { name, fit } of STATES) {
      const from = stateNameFrom(fit);
      if (!Number.isFinite(from)) continue;
      expect(from, name).toBeGreaterThanOrEqual(STATE_NAME_SIZE.fromZoom);
      expect(Math.round(from * 100) / 100, name).toBe(from);
      // It fits there, and a hundredth before it (unless it fits from the start) it does not.
      expect(stateNameSize(from), name).toBeLessThanOrEqual(fit * 2 ** from + 1e-9);
      if (from > STATE_NAME_SIZE.fromZoom) {
        const before = from - 0.01;
        expect(stateNameSize(before), name).toBeGreaterThan(fit * 2 ** before);
      }
    }
    // Texas fits long before a phone opens; Rhode Island only just before the street map.
    expect(stateNameFrom(STATES.find((s) => s.name === 'Texas')?.fit ?? NaN)).toBe(3);
    const rhodeIsland = stateNameFrom(STATES.find((s) => s.name === 'Rhode Island')?.fit ?? NaN);
    expect(rhodeIsland).toBeGreaterThan(6);
    expect(rhodeIsland).toBeLessThan(STATE_NAMES_UNTIL);
    // A name too long for its state before the street map takes over is never named here.
    expect(stateNameFrom(0.01)).toBe(Infinity);
  });

  it('from that zoom, until the street map takes over', () => {
    const fit = STATES.find((state) => state.name === 'Iowa')?.fit ?? NaN;
    const from = stateNameFrom(fit);
    expect(stateNameShown(fit, from)).toBe(true);
    expect(stateNameShown(fit, from - 0.01)).toBe(false);
    expect(stateNameShown(fit, OPENFREEMAP_MIN_ZOOM - 0.01)).toBe(true);
    expect(stateNameShown(fit, OPENFREEMAP_MIN_ZOOM)).toBe(false);
    expect(STATE_NAMES_UNTIL).toBe(OPENFREEMAP_MIN_ZOOM);
    expect(NAMED.every((state) => state.from < STATE_NAMES_UNTIL)).toBe(true);
    expect(NAMED).toHaveLength(48);
  });

  it('lists the names that fit at a zoom, in order, less the ones left out', () => {
    for (const zoom of [2.5, 3, 3.85, 4.4, 5.5, 6.9, 7, 9]) {
      const expected = STATES.filter((state) => stateNameShown(state.fit, zoom)).map((s) => s.name);
      expect(stateNamesAt(NAMED, zoom), String(zoom)).toEqual(expected);
    }
    expect(stateNamesAt(NAMED, 3.85)).toContain('Kansas');
    expect(stateNamesAt(NAMED, 3.85, ['Kansas'])).not.toContain('Kansas');
    expect(stateNamesAt(NAMED, 3.85, ['Kansas'])).toHaveLength(AT_HOME.length - 1);
    expect(stateNamesAt(NAMED, 7)).toEqual([]);
  });

  it('names most of the country where phones open', () => {
    // A 390 x 844 phone opens at about 3.85, a 430 x 932 one at about 4.
    expect(stateNamesAt(NAMED, 3.85).length).toBeGreaterThanOrEqual(30);
    expect(stateNamesAt(NAMED, 4.05).length).toBeGreaterThanOrEqual(35);
    expect(stateNamesAt(NAMED, 6.9)).toHaveLength(48);
  });
});

describe("the style's state names", () => {
  it('are one layer, drawn only on a phone, of the names it is given', () => {
    const phone = stateLayer(PHONE.layers);
    const wide = stateLayer(WIDE.layers);
    expect(phone.id).toBe(BASEMAP_IDS.usStateLabel);
    expect((phone.layout as { visibility?: string }).visibility).toBe('visible');
    expect((wide.layout as { visibility?: string }).visibility).toBe('none');
    expect(phone.minzoom).toBe(STATE_NAME_SIZE.fromZoom);
    expect(phone.maxzoom).toBe(STATE_NAMES_UNTIL);
    expect((phone as { filter: FilterSpecification }).filter).toEqual(stateNameFilter(AT_HOME));
    // Given none, it draws none.
    expect((wide as { filter: FilterSpecification }).filter).toEqual(stateNameFilter([]));
  });

  it('draws the states it names, and no other name', () => {
    const passes = (filter: FilterSpecification, name: string, kind = 'state-name'): boolean =>
      featureFilter(filter, 'filter').filter({ zoom: 4 }, { type: 1, properties: { kind, name } });
    const filter = stateNameFilter(['Kansas', 'Iowa']);
    expect(passes(filter, 'Kansas')).toBe(true);
    expect(passes(filter, 'Iowa')).toBe(true);
    expect(passes(filter, 'Nebraska')).toBe(false);
    expect(passes(filter, 'Kansas', 'city')).toBe(false);
    expect(passes(stateNameFilter([]), 'Kansas')).toBe(false);
  });

  it('sets them in quiet spaced capitals under the city names, at the size they were fitted at', () => {
    const ids = PHONE.layers.map((layer) => layer.id);
    const firstCity = Math.min(
      ...CITY_NAME_BANDS.map((_band, band) => ids.indexOf(cityNameLayerId(band))),
    );
    const layer = stateLayer(PHONE.layers);
    expect(ids.indexOf(layer.id)).toBeLessThan(firstCity);
    expect(evaluate(layer, 'layout', 'text-transform', 4)).toBe('uppercase');
    expect(evaluate(layer, 'layout', 'text-padding', 4)).toBe(STATE_NAME_PADDING);
    for (const zoom of [3, 3.85, 4.5, 6, 6.9]) {
      expect(evaluate(layer, 'layout', 'text-size', zoom) as number).toBeCloseTo(
        stateNameSize(zoom),
        9,
      );
    }
    // The dim label grey: quieter than the city names, never a status color.
    const color = evaluate(layer, 'paint', 'text-color', 4) as { r: number; g: number };
    expect(Math.round(color.r * 255)).toBe(0x6b);
    expect(color.r).toBe(color.g);
  });

  it('spaces the city names closer on a phone, as the state names were placed clear of', () => {
    for (const [style, padding] of [
      [PHONE, CITY_NAME_PHONE_PADDING],
      [WIDE, CITY_NAME_PADDING],
    ] as const) {
      CITY_NAME_BANDS.forEach((_band, band) => {
        const layer = style.layers.find((l) => l.id === cityNameLayerId(band));
        expect((layer?.layout as { 'text-padding'?: number })['text-padding']).toBe(padding);
      });
    }
    // build-geo.mjs placed the state names clear of the city names as a phone sets them.
    const clear = STATE_NAMES_CLEAR_OF;
    expect(CITY_NAME_BANDS.find((band) => band.zoom === clear.zoom)?.names).toBe(clear.cities);
    expect(clear.padding).toBe(CITY_NAME_PHONE_PADDING);
    expect(clear.tracking).toBe(CITY_NAME_LETTER_SPACING);
    expect(clear.ownPadding).toBe(STATE_NAME_PADDING);
    for (const zoom of [3, 3.8, 4.5, 6, 6.9]) {
      const { fromZoom, from, toZoom, to } = clear.size;
      const t = Math.min(1, Math.max(0, (zoom - fromZoom) / (toZoom - fromZoom)));
      expect(from + (to - from) * t).toBeCloseTo(cityNameSize(zoom), 9);
    }
  });
});

describe('state names cut by the edges', () => {
  const SCREEN = { width: 400, height: 800 };
  const VIEW: MapView = { lat: 38, lon: -95, zoom: 5 };
  /** Every letter as wide as its size: a generous measure. */
  const EM: MeasureText = (text, size) => text.length * size;

  /** A state name whose middle sits at a screen point of VIEW. */
  function stateAt(name: string, x: number, y: number, label = name): StateName {
    const scale = 512 * 2 ** VIEW.zoom;
    const worldX = mercatorXFromLng(VIEW.lon) + (x - SCREEN.width / 2) / scale;
    const worldY = mercatorYFromLat(VIEW.lat) + (y - SCREEN.height / 2) / scale;
    const lon = worldX * 360 - 180;
    const lat = (Math.atan(Math.sinh(Math.PI * (1 - 2 * worldY))) * 180) / Math.PI;
    return { name, label, fit: 1, lon, lat };
  }

  it('leaves out a name an edge runs through, and keeps one wholly on or off the screen', () => {
    const states = [
      stateAt('Westland', 10, 400),
      stateAt('Midland', 200, 400),
      stateAt('Eastland', SCREEN.width - 10, 300),
      stateAt('Farland', -400, 300),
      stateAt('North Topland', 200, 4, 'North\nTopland'),
    ];
    expect(stateNamesCutByEdges(states, VIEW, SCREEN, EM)).toEqual([
      'Westland',
      'Eastland',
      'North Topland',
    ]);
    // Not yet named at this zoom: nothing to cut.
    const small = [{ ...stateAt('Westland', 10, 400), fit: 0.01 }];
    expect(stateNamesCutByEdges(small, VIEW, SCREEN, EM)).toEqual([]);
  });

  it('measures a two-line name by its longer line, in capitals', () => {
    const measured: string[] = [];
    const spy: MeasureText = (text, size) => {
      measured.push(text);
      return EM(text, size);
    };
    stateNamesCutByEdges([stateAt('South Edge', 12, 400, 'South\nEdge')], VIEW, SCREEN, spy);
    expect(measured).toEqual(['SOUTH', 'EDGE']);
  });
});
