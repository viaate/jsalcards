// @vitest-environment node
/**
 * The later-day rings on the map's style (map/later-rings.ts ringLayers) and
 * the school dots that give way to them (basemap/schools.ts): across a county
 * a ring yields to every label and takes no room of its own, closer in every
 * ring is drawn; a ringed school's dot gives way only where its ring is drawn.
 * Values are evaluated with MapLibre's own style-spec implementation, and as
 * the map draws them: a paint value that reads the zoom alone at the zoom the
 * map is at; one that reads the zoom and the feature (its properties or its
 * state) only at the tile's whole zoom and the next, blended between them
 * (maplibre-gl data/program_configuration.ts CompositeExpressionBinder).
 */
import { expression, featureFilter, latest } from '@maplibre/maplibre-gl-style-spec';
import { describe, expect, it } from 'vitest';

import { SCHOOL_DOT_RADIUS, dotAt } from '../basemap/dots';
import { SCHOOL_LATER_STATE, SCHOOL_LIT_STATE } from '../basemap/ids';
import {
  RINGED_DOT,
  RINGED_LIGHT,
  SCHOOL_FADE,
  SCHOOL_NAMES_FROM,
  schoolDotLayer,
  schoolDotOpacity,
  schoolLightLayer,
} from '../basemap/schools';
import {
  LATER_RINGS,
  LATER_RINGS_ALWAYS,
  LATER_RINGS_CLOSE,
  LATER_RINGS_FROM,
  LATER_RINGS_NEAR,
  LATER_RINGS_WHOLE,
  RING_GROUND_RADIUS,
  lightClearZoom,
  lightReachPx,
  ringFeatures,
  ringLayers,
  ringRadiusPx,
} from '../later-rings';
import type { RingLayer } from '../later-rings';
import { NEAR_REACH } from '../../data/later-days';
import type { LaterMark } from '../../data/later-days';
import { MAX_ZOOM } from '../basemap/bounds';
import { fallbackHalo, glowReachPx, glowStyleAtZoom } from '../glow/curves';

const COLORS = { bright: '#fff', name: '#ddd', ground: '#000' };

/**
 * A paint value as the map draws it at `zoom`: at that zoom if it reads the
 * zoom alone, else as it is at the whole zoom under it and the next, blended
 * between them by the zoom's fraction.
 */
function drawn(
  kind: 'paint_circle' | 'paint_symbol',
  value: unknown,
  name: string,
  zoom: number,
  properties: Record<string, unknown> = {},
  state: Record<string, boolean | number> = {},
): number {
  const spec = (latest as unknown as Record<string, Record<string, unknown>>)[kind]?.[name];
  const parsed = expression.createPropertyExpression(value, name, spec as never);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  const at = (z: number): number => {
    const out: unknown = parsed.value.evaluate(
      { zoom: z },
      { type: 1, properties } as never,
      state,
    );
    if (typeof out !== 'number') throw new Error(`${name} is not a number`);
    return out;
  };
  if (parsed.value.kind !== 'composite') return at(zoom);
  const whole = Math.floor(zoom);
  return at(whole) + (at(whole + 1) - at(whole)) * (zoom - whole);
}

/** A circle paint value as the map draws it at a zoom, for a school in this feature state. */
function circle(
  paint: Record<string, unknown>,
  name: string,
  zoom: number,
  state: Record<string, boolean | number> = {},
): number {
  return drawn('paint_circle', paint[name], name, zoom, {}, state);
}

/** The same, as its expression reads at the zoom itself: the curve an unringed school's keeps. */
function circleAt(paint: Record<string, unknown>, name: string, zoom: number): number {
  const spec = (latest as unknown as Record<string, Record<string, unknown>>).paint_circle?.[name];
  const parsed = expression.createPropertyExpression(paint[name], name, spec as never);
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  const value: unknown = parsed.value.evaluate({ zoom }, { type: 1, properties: {} } as never);
  if (typeof value !== 'number') throw new Error(`${name} is not a number`);
  return value;
}

/** The ring layers that draw a ring drawn whole from `clear` at a zoom: by their zooms and filter. */
function layersFor(zoom: number, clear: number): RingLayer[] {
  return ringLayers().filter((layer) => {
    if (zoom < layer.minzoom || (layer.maxzoom !== undefined && zoom >= layer.maxzoom)) {
      return false;
    }
    if (layer.filter === undefined) return true;
    const filter = featureFilter(layer.filter, `layers.${layer.id}.filter`);
    return filter.filter({ zoom }, { type: 1, properties: { clear } } as never);
  });
}

/** A ring's opacity as the map draws it at a zoom, for a ring drawn whole from `clear`. */
function ringOpacity(zoom: number, clear: number): number {
  const layers = layersFor(zoom, clear);
  if (layers.length > 1) throw new Error(`${String(layers.length)} layers draw it`);
  const layer = layers[0];
  if (layer === undefined) return 0;
  return drawn('paint_symbol', layer.paint['icon-opacity'], 'icon-opacity', zoom, { clear });
}

/** The id of the ring layer that draws a ring drawn whole from `clear` at a zoom. */
function layerAt(zoom: number, clear: number): string | undefined {
  return layersFor(zoom, clear)[0]?.id;
}

/** The map's metres to its pixel at zoom 0 at Bath County's latitude (512 pixels to the world). */
const METRES_PER_PX = (2 * Math.PI * 6378137 * Math.cos((38.1 * Math.PI) / 180)) / 512;

/** Zooms from the rings' first to the map's closest, a 64th apart. */
const ZOOMS = Array.from(
  { length: (MAX_ZOOM - LATER_RINGS_FROM) * 64 + 1 },
  (_, i) => LATER_RINGS_FROM + i / 64,
);

/** The radius of a ring's ground on the screen at a zoom, CSS px, from its layer's icon-size. */
function ringGroundRadius(zoom: number): number {
  const layer = ringLayers().find((one) => one.id === LATER_RINGS_CLOSE);
  const spec = (latest as unknown as Record<string, Record<string, unknown>>).layout_symbol?.[
    'icon-size'
  ];
  const parsed = expression.createPropertyExpression(
    layer?.layout['icon-size'],
    'icon-size',
    spec as never,
  );
  if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
  const size: unknown = parsed.value.evaluate({ zoom }, { type: 1, properties: {} } as never);
  if (typeof size !== 'number') throw new Error('icon-size is not a number');
  return RING_GROUND_RADIUS * size;
}

/** The white of a school's dot, its radius on the screen at a zoom, CSS px. */
function dotWhiteRadius(zoom: number): number {
  return dotAt(SCHOOL_DOT_RADIUS, zoom);
}

describe('the later-day ring layers', () => {
  const [far, near, close] = ringLayers();

  it('come in at a county’s zoom, and hand over where the school names come in', () => {
    expect(LATER_RINGS_FROM).toBe(9.75);
    expect(LATER_RINGS_WHOLE).toBe(10);
    expect(LATER_RINGS_ALWAYS).toBe(SCHOOL_NAMES_FROM - SCHOOL_FADE);
    expect(far?.id).toBe(LATER_RINGS);
    expect([far?.minzoom, far?.maxzoom]).toEqual([LATER_RINGS_FROM, LATER_RINGS_ALWAYS]);
    expect(near?.id).toBe(LATER_RINGS_NEAR);
    expect([near?.minzoom, near?.maxzoom]).toEqual([LATER_RINGS_WHOLE, LATER_RINGS_ALWAYS]);
    expect(close?.id).toBe(LATER_RINGS_CLOSE);
    expect([close?.minzoom, close?.maxzoom]).toEqual([LATER_RINGS_ALWAYS, undefined]);
  });

  it('draw each ring on one layer at a time: by its zoom, and further out by a light near', () => {
    for (const zoom of ZOOMS) {
      expect(layerAt(zoom, LATER_RINGS_WHOLE), String(zoom)).toBe(
        zoom < LATER_RINGS_ALWAYS ? LATER_RINGS : LATER_RINGS_CLOSE,
      );
      for (const clear of [11, 12, 13, 16]) {
        expect(layerAt(zoom, clear), `${String(clear)} at ${String(zoom)}`).toBe(
          zoom < LATER_RINGS_WHOLE
            ? undefined
            : zoom < LATER_RINGS_ALWAYS
              ? LATER_RINGS_NEAR
              : LATER_RINGS_CLOSE,
        );
      }
    }
  });

  it('fade a ring with no light near in by the zoom alone, as the map draws it at that zoom', () => {
    const fade = far?.paint['icon-opacity'];
    const spec = (latest as unknown as Record<string, Record<string, unknown>>).paint_symbol?.[
      'icon-opacity'
    ];
    const parsed = expression.createPropertyExpression(fade, 'icon-opacity', spec as never);
    if (parsed.result !== 'success') throw new Error(JSON.stringify(parsed.value));
    expect(parsed.value.kind).toBe('camera');
    expect(ringOpacity(LATER_RINGS_FROM, LATER_RINGS_WHOLE)).toBe(0);
    expect(ringOpacity((LATER_RINGS_FROM + LATER_RINGS_WHOLE) / 2, LATER_RINGS_WHOLE)).toBe(0.5);
    for (const zoom of ZOOMS.filter((z) => z >= LATER_RINGS_WHOLE)) {
      expect(ringOpacity(zoom, LATER_RINGS_WHOLE), String(zoom)).toBe(1);
    }
  });

  it('across a county, give way to every label and take no label’s room', () => {
    for (const layer of [far, near]) {
      expect(layer?.layout['icon-allow-overlap']).toBe(false);
      expect(layer?.layout['icon-ignore-placement']).toBe(true);
      expect(layer?.layout['icon-padding']).toBe(0);
    }
  });

  it('closer in, draw every ring and take no label’s room either', () => {
    expect(close?.layout['icon-allow-overlap']).toBe(true);
    expect(close?.layout['icon-ignore-placement']).toBe(true);
  });

  it('draw each ring from its status’s image, at the same size either side of the hand-over', () => {
    for (const layer of [near, close]) {
      expect(far?.layout['icon-image']).toEqual(layer?.layout['icon-image']);
      expect(far?.layout['icon-size']).toEqual(layer?.layout['icon-size']);
    }
  });
});

describe('a ringed school’s dot', () => {
  const dot = schoolDotLayer(COLORS).paint as Record<string, unknown>;
  const light = schoolLightLayer(COLORS).paint as Record<string, unknown>;
  // A ring with no light near: drawn whole from the zoom the rings are.
  const ringed = { [SCHOOL_LATER_STATE]: LATER_RINGS_WHOLE };

  it('shows as any school’s further out than the rings are drawn, its light to the zoom before', () => {
    for (const zoom of [9, 9.25, 9.5, LATER_RINGS_FROM]) {
      for (const name of ['circle-opacity', 'circle-stroke-opacity']) {
        expect(circle(dot, name, zoom, ringed), `${name} ${String(zoom)}`).toBeCloseTo(
          circle(dot, name, zoom),
          5,
        );
      }
    }
    // The light around its dot gives way over the zoom before the rings come in, as the map
    // blends whole zooms: none of it around the ring, which has no light of its own.
    const [lightFrom, lightWhole] = RINGED_LIGHT;
    expect(lightWhole).toBe(LATER_RINGS_WHOLE);
    expect(circle(light, 'circle-opacity', lightFrom, ringed)).toBeCloseTo(
      circle(light, 'circle-opacity', lightFrom),
      5,
    );
    for (const zoom of ZOOMS) {
      expect(circle(light, 'circle-opacity', zoom, ringed), String(zoom)).toBeLessThanOrEqual(
        circle(light, 'circle-opacity', zoom) * (1 - ringOpacity(zoom, LATER_RINGS_WHOLE)) + 1e-9,
      );
    }
  });

  it('keeps its dot where its ring may give way to a label, under the ring’s ground', () => {
    // Across a county a ring that runs into a label is not drawn: the school keeps its dot.
    for (const zoom of [LATER_RINGS_WHOLE, 11, 12, 12.5, LATER_RINGS_ALWAYS, 12.9]) {
      for (const name of ['circle-opacity', 'circle-stroke-opacity']) {
        expect(circle(dot, name, zoom, ringed), `${name} ${String(zoom)}`).toBeCloseTo(
          circle(dot, name, zoom),
          5,
        );
      }
    }
    // Where its ring is drawn, the ring’s ground is wider than the dot and drawn whole over it.
    for (const zoom of [LATER_RINGS_WHOLE, 11, 12, LATER_RINGS_ALWAYS, 14, 15]) {
      expect(ringGroundRadius(zoom), String(zoom)).toBeGreaterThan(dotWhiteRadius(zoom));
    }
    for (const zoom of ZOOMS.filter((z) => z >= LATER_RINGS_WHOLE)) {
      expect(ringOpacity(zoom, LATER_RINGS_WHOLE), String(zoom)).toBe(1);
    }
  });

  it('gives way to its ring over the first whole zoom every ring is drawn at, under its ground', () => {
    const [from, whole] = RINGED_DOT;
    expect(from).toBe(Math.ceil(LATER_RINGS_ALWAYS));
    expect(whole).toBe(from + 1);
    for (const zoom of [whole, 14.5, 15, MAX_ZOOM]) {
      expect(circle(dot, 'circle-opacity', zoom, ringed), String(zoom)).toBe(0);
      expect(circle(dot, 'circle-stroke-opacity', zoom, ringed), String(zoom)).toBe(0);
    }
    for (const zoom of [LATER_RINGS_WHOLE, 11, 12]) {
      expect(circle(light, 'circle-opacity', zoom, ringed), String(zoom)).toBe(0);
    }
    // The dot fading out under the ring's ground over the zoom before `whole`.
    const fading = whole - 0.5;
    expect(circle(dot, 'circle-opacity', fading, ringed)).toBeGreaterThan(0);
    expect(circle(dot, 'circle-opacity', fading, ringed)).toBeLessThan(
      circle(dot, 'circle-opacity', fading),
    );
  });

  it('leaves every other school’s dot as it was, and a lit school’s gone at every zoom', () => {
    for (const zoom of [9, 9.5, 9.8, 10, 11, 13, 15]) {
      expect(circleAt(dot, 'circle-opacity', zoom), String(zoom)).toBeCloseTo(
        schoolDotOpacity(zoom),
        5,
      );
      expect(circle(dot, 'circle-opacity', zoom, { [SCHOOL_LIT_STATE]: true }), String(zoom)).toBe(
        0,
      );
    }
  });
});

describe('a ring near today’s light', () => {
  const dot = schoolDotLayer(COLORS).paint as Record<string, unknown>;
  const light = schoolLightLayer(COLORS).paint as Record<string, unknown>;
  /** Whether a ring this near a light, at this zoom, runs into the light's glow as it is drawn. */
  const overlaps = (near: number, zoom: number): boolean =>
    near * 2 ** zoom < lightReachPx(zoom) + ringRadiusPx(zoom);

  it('takes the light’s drawn glow at the zoom as its footprint, on either glow path', () => {
    for (const zoom of [LATER_RINGS_FROM, 10, 11, 12, 14, MAX_ZOOM]) {
      const style = glowStyleAtZoom(zoom);
      expect(lightReachPx(zoom), String(zoom)).toBeGreaterThanOrEqual(7);
      expect(lightReachPx(zoom), String(zoom)).toBeGreaterThanOrEqual(glowReachPx(zoom));
      expect(lightReachPx(zoom), String(zoom)).toBeGreaterThanOrEqual(style.haloRadiusPx);
      // The 8-bit fallback's halo, wider than the float path's from 9.75 to 11.
      expect(lightReachPx(zoom), String(zoom)).toBeGreaterThanOrEqual(
        fallbackHalo(style, zoom).radiusPx,
      );
      expect(ringRadiusPx(zoom), String(zoom)).toBeGreaterThanOrEqual(4.5);
    }
    // The bloom's faint haze around a lone light in the dark look, measured from a picture at
    // 9.75 (20 px out, where it meets the ground), is inside the footprint.
    expect(lightReachPx(LATER_RINGS_FROM)).toBeGreaterThan(20);
  });

  it('is not held back by a light past the reach a light is looked for in', () => {
    expect(lightClearZoom(Infinity)).toBe(LATER_RINGS_WHOLE);
    expect(lightClearZoom(NEAR_REACH)).toBe(LATER_RINGS_WHOLE);
    for (const zoom of ZOOMS) expect(overlaps(NEAR_REACH, zoom), String(zoom)).toBe(false);
  });

  it('a ring near today’s light is drawn, as the map draws it, only once the zoom parts them', () => {
    // SYNTHETIC: a school lit today and a ringed one this far off, at Bath County's latitude:
    // the storm's nearest pairs (130 to 150 m), and the pairs a whole-zoom blend once drew a
    // ring through a light's glow at (200, 368, 673, 725, 798 m), and further.
    for (const metres of [130, 136, 150, 200, 368, 400, 673, 725, 798, 1000, 1500, 2500]) {
      const near = metres / METRES_PER_PX;
      const clear = lightClearZoom(near);
      // Whole zooms only, or none: the map blends a ring's opacity between whole zooms.
      if (clear !== Infinity) expect(Number.isInteger(clear), String(metres)).toBe(true);
      for (const zoom of ZOOMS) {
        const at = `${String(metres)} m at ${String(zoom)}`;
        const shown = ringOpacity(zoom, clear);
        // Never drawn, not even faintly, where it would run into the light's glow.
        if (overlaps(near, zoom)) expect(shown, at).toBe(0);
        // Whole from its zoom on.
        if (zoom >= clear) expect(shown, at).toBe(1);
        // Until the zoom before it, not drawn, and the school's dot and light as any school's.
        if (zoom <= clear - 1) {
          expect(shown, at).toBe(0);
          const state = { [SCHOOL_LATER_STATE]: clear };
          for (const [paint, name] of [
            [dot, 'circle-opacity'],
            [dot, 'circle-stroke-opacity'],
            [light, 'circle-opacity'],
          ] as const) {
            expect(circle(paint, name, zoom, state), `${name} ${at}`).toBeCloseTo(
              circle(paint, name, zoom),
              5,
            );
          }
        }
      }
    }
    // 130 m apart: held back across the zooms the glow is around it (to 13 and past it).
    expect(lightClearZoom(130 / METRES_PER_PX)).toBeGreaterThan(13);
    expect(lightClearZoom(130 / METRES_PER_PX)).toBeLessThanOrEqual(MAX_ZOOM);
    // 673 m apart: none of it drawn at 10.25 to 10.5, where a blend once drew it a quarter to half.
    for (const zoom of [10.25, 10.33, 10.375, 10.5, 10.75]) {
      expect(ringOpacity(zoom, lightClearZoom(673 / METRES_PER_PX)), String(zoom)).toBe(0);
    }
    // 2.5 km apart: a county's view already parts them.
    expect(lightClearZoom(2500 / METRES_PER_PX)).toBe(LATER_RINGS_WHOLE);
  });

  it('a ring too near today’s light at every zoom is not drawn, and its school keeps its dot', () => {
    const near = 4 / METRES_PER_PX;
    expect(lightClearZoom(near)).toBe(Infinity);
    const marks: LaterMark[] = [
      { school: 0, day: '2026-11-13', status: 0, near },
      { school: 1, day: '2026-11-13', status: 1, near: 130 / METRES_PER_PX },
      { school: 2, day: '2026-11-13', status: 2, near: Infinity },
    ];
    const directory = {
      lngLat: Float64Array.from([-83.7, 38.1, -83.7, 38.1, -83.6, 38.2]),
      meta: { ids: ['a', 'b', 'c'] },
    } as unknown as Parameters<typeof ringFeatures>[1];
    const features = ringFeatures(marks, directory).features;
    expect(features.map((feature) => feature.properties.id)).toEqual(['b', 'c']);
    expect(features.map((feature) => feature.properties.clear)).toEqual([
      lightClearZoom(130 / METRES_PER_PX),
      LATER_RINGS_WHOLE,
    ]);
  });
});
