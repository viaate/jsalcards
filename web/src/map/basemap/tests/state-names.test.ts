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
  STATE_NAME_SMALL,
  STATE_NAMES_UNTIL,
  namedStates,
  smallStateNamesAt,
  stateNameFrom,
  stateNameShown,
  stateNameSize,
  stateNameSizeFor,
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
  stateNameSizeExpression,
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

/** A layout or paint value of a layer at a zoom, for a feature with these properties. */
function evaluate(
  layer: LayerSpecification,
  section: 'layout' | 'paint',
  name: string,
  zoom: number,
  properties: Record<string, unknown> = {},
): unknown {
  const input = (layer as unknown as Record<string, Record<string, unknown> | undefined>)[
    section
  ]?.[name];
  const reference = latest as unknown as Record<string, Record<string, unknown>>;
  const spec = reference[`${section}_${layer.type}`]?.[name];
  const parsed = expression.createPropertyExpression(input, name, spec as never);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  return parsed.value.evaluate({ zoom }, { type: 1, properties });
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

  it('carry the zoom a name is clear at its usual size from, where it is only small before', () => {
    expect(
      stateNamesOf({
        features: [
          {
            properties: { kind: 'state-name', name: 'Small', label: 'Small', fit: 1, usualFrom: 4 },
            geometry: { type: 'Point', coordinates: [-100, 40] },
          },
          {
            properties: {
              kind: 'state-name',
              name: 'Usual',
              label: 'Usual',
              fit: 1,
              usualFrom: 'x',
            },
            geometry: { type: 'Point', coordinates: [-90, 40] },
          },
        ],
      }),
    ).toEqual([
      { name: 'Small', label: 'Small', fit: 1, lon: -100, lat: 40, usualFrom: 4 },
      { name: 'Usual', label: 'Usual', fit: 1, lon: -90, lat: 40 },
    ]);
    // Only a name build-geo.mjs cleared only at the small size carries it.
    const carrying = STATES.filter((state) => state.usualFrom !== undefined);
    expect(carrying.map((state) => state.name)).toContain('Pennsylvania');
    for (const state of carrying) {
      expect(state.usualFrom, state.name).toBeGreaterThan(stateNameFrom(state.fit));
      expect(state.usualFrom, state.name).toBeLessThanOrEqual(STATE_NAMES_UNTIL);
    }
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

  it("names every state a phone's opening view holds, smaller where only that fits", () => {
    // A 390 x 844 phone opens at about 3.85; Pennsylvania is clear of New York's name at the
    // usual size only closer in, North Carolina fits it only closer in.
    const pennsylvania = NAMED.find((state) => state.name === 'Pennsylvania');
    expect(pennsylvania?.usualFrom).toBeGreaterThan(3.85);
    expect(pennsylvania?.from).toBe(pennsylvania?.usualFrom);
    expect(pennsylvania?.fromSmall).toBeLessThanOrEqual(3.85);
    const northCarolina = NAMED.find((state) => state.name === 'North Carolina');
    expect(stateNameFrom(northCarolina?.fit ?? NaN)).toBeGreaterThan(3.85);
    const small = smallStateNamesAt(NAMED, 3.85);
    for (const name of ['Pennsylvania', 'North Carolina']) {
      expect(AT_HOME, name).toContain(name);
      expect(small, name).toContain(name);
    }
    // Texas is at its usual size; the small ones are a share of it, and still fit inside.
    expect(small).not.toContain('Texas');
    for (const state of NAMED.filter((named) => small.includes(named.name))) {
      const size = stateNameSizeFor(state, 3.85);
      expect(size, state.name).toBeCloseTo(STATE_NAME_SMALL * stateNameSize(3.85), 9);
      expect(size, state.name).toBeLessThanOrEqual(state.fit * 2 ** 3.85 + 1e-9);
    }
    // At its usual size from the zoom that fits, clear.
    const from = pennsylvania?.from ?? NaN;
    expect(smallStateNamesAt(NAMED, from)).not.toContain('Pennsylvania');
    expect(smallStateNamesAt(NAMED, from - 0.01)).toContain('Pennsylvania');
    expect(stateNameSizeFor(pennsylvania ?? { fit: NaN }, from)).toBe(stateNameSize(from));
    expect(stateNameSizeFor({ fit: pennsylvania?.fit ?? NaN }, from - 0.01)).toBe(
      stateNameSize(from - 0.01),
    );
    expect(STATE_NAME_SMALL).toBeGreaterThanOrEqual(0.8);
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

  it('sets them in quiet spaced capitals over the city names, at the size they were fitted at', () => {
    const ids = PHONE.layers.map((layer) => layer.id);
    const lastCity = Math.max(
      ...CITY_NAME_BANDS.map((_band, band) => ids.indexOf(cityNameLayerId(band))),
    );
    const layer = stateLayer(PHONE.layers);
    // Over them all, so MapLibre places them first: a state's name never gives way to a city's.
    expect(ids.indexOf(layer.id)).toBeGreaterThan(lastCity);
    expect(evaluate(layer, 'layout', 'text-transform', 4)).toBe('uppercase');
    expect(evaluate(layer, 'layout', 'text-padding', 4)).toBe(STATE_NAME_PADDING);
    for (const zoom of [3, 3.85, 4.5, 6, 6.9]) {
      expect(evaluate(layer, 'layout', 'text-size', zoom) as number).toBeCloseTo(
        stateNameSize(zoom),
        9,
      );
    }
    // The states named small at the small size, the rest at the usual one.
    const sized = (small: readonly string[], name: string, zoom: number): number => {
      const parsed = expression.createPropertyExpression(
        stateNameSizeExpression(small),
        'text-size',
        (latest as unknown as Record<string, Record<string, unknown>>).layout_symbol?.[
          'text-size'
        ] as never,
      );
      if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
      return parsed.value.evaluate({ zoom }, { type: 1, properties: { name } }) as number;
    };
    for (const zoom of [3, 3.85, 4.5, 6]) {
      expect(sized(['Pennsylvania'], 'Pennsylvania', zoom)).toBeCloseTo(
        STATE_NAME_SMALL * stateNameSize(zoom),
        9,
      );
      expect(sized(['Pennsylvania'], 'Texas', zoom)).toBeCloseTo(stateNameSize(zoom), 9);
      expect(sized([], 'Pennsylvania', zoom)).toBeCloseTo(stateNameSize(zoom), 9);
    }
    // The dim label grey: quieter than the city names, never a status color.
    const color = evaluate(layer, 'paint', 'text-color', 4) as { r: number; g: number };
    expect(Math.round(color.r * 255)).toBe(0x6b);
    expect(color.r).toBe(color.g);
  });

  it('sets the states named in view just as the bundled names, a small one kept small', () => {
    const bundled = stateLayer(PHONE.layers);
    const inView = PHONE.layers.find((layer) => layer.id === BASEMAP_IDS.usStateAreaLabel);
    if (inView === undefined) throw new Error('no states in view');
    // Over every place name, and over the bundled names: MapLibre places them first.
    const ids = PHONE.layers.map((layer) => layer.id);
    expect(ids.indexOf(inView.id)).toBeGreaterThan(ids.indexOf(bundled.id));
    const layout = (layer: LayerSpecification): Record<string, unknown> => layer.layout ?? {};
    for (const name of [
      'text-font',
      'text-transform',
      'text-letter-spacing',
      'text-line-height',
      'text-padding',
      'text-anchor',
      'text-field',
    ]) {
      expect(layout(inView)[name], name).toEqual(layout(bundled)[name]);
    }
    for (const zoom of [3, 3.85, 4.5, 6, 9]) {
      // A name the layer takes over from the bundled one keeps its size, small or usual.
      expect(
        evaluate(inView, 'layout', 'text-size', zoom, { name: 'Iowa', scale: 1 }) as number,
      ).toBeCloseTo(stateNameSize(zoom), 9);
      expect(evaluate(inView, 'layout', 'text-size', zoom, { name: 'Iowa' }) as number).toBeCloseTo(
        stateNameSize(zoom),
        9,
      );
      expect(
        evaluate(inView, 'layout', 'text-size', zoom, {
          name: 'Pennsylvania',
          scale: STATE_NAME_SMALL,
        }) as number,
      ).toBeCloseTo(STATE_NAME_SMALL * stateNameSize(zoom), 9);
    }
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
