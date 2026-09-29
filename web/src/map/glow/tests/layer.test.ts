import type { CustomRenderMethodInput, Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { GlowLayer, GlowStatus } from '..';
import { dustStyle } from '../../glow-mount';
import { mercatorXFromLng, mercatorYFromLat } from '../mercator';

/**
 * Enough of a map to put the layer on and take it off, as MapLibre does, with
 * its context lost and restored. It draws no frame.
 */
function fakeMap() {
  const listeners = new Map<string, (() => void)[]>();
  const listen = (type: string, listener: () => void): void => {
    listeners.set(type, [...(listeners.get(type) ?? []), listener]);
  };
  const unlisten = (type: string, listener: () => void): void => {
    listeners.set(
      type,
      (listeners.get(type) ?? []).filter((l) => l !== listener),
    );
  };
  const fire = (type: string): void => {
    for (const listener of listeners.get(type) ?? []) listener();
  };
  const gl = {} as WebGL2RenderingContext;
  let on: GlowLayer | null = null;
  const map = {
    getCanvasContainer: () => ({ addEventListener: listen, removeEventListener: unlisten }),
    on: listen,
    off: unlisten,
    getLayer: (id: string) => (on?.id === id ? on : undefined),
    getLayersOrder: () => (on === null ? [] : [on.id]),
    addLayer: (layer: GlowLayer) => {
      on = layer;
      layer.onAdd(map, gl);
    },
    removeLayer: () => {
      const layer = on;
      on = null;
      layer?.onRemove(map, gl);
    },
    triggerRepaint: () => undefined,
  } as unknown as MapLibreMap;
  return {
    add: (layer: GlowLayer) => {
      map.addLayer(layer);
    },
    lose: () => {
      fire('webglcontextlost');
    },
    restore: () => {
      fire('webglcontextrestored');
    },
  };
}

describe('GlowLayer', () => {
  it('is a 2D MapLibre custom layer', () => {
    const layer = new GlowLayer({ id: 'glow' });
    expect(layer.id).toBe('glow');
    expect(layer.type).toBe('custom');
    expect(layer.renderingMode).toBe('2d');
    expect(typeof layer.prerender).toBe('function');
    expect(typeof layer.render).toBe('function');
  });

  it('takes data before it is on a map and reports what it holds', () => {
    const layer = new GlowLayer();
    layer.setData({
      lngLat: new Float32Array([-93, 45, -88, 42, -71, 42, 0, 95]),
      status: new Uint8Array([
        GlowStatus.Closed,
        GlowStatus.Open,
        GlowStatus.Remote,
        GlowStatus.Delayed,
      ]),
    });
    expect(layer.stats).toMatchObject({
      mode: 'none',
      frames: 0,
      count: 3,
      glowCount: 2,
      dropped: 1,
      bornClamped: 0,
    });
  });

  it('draws a smaller screen’s bloom and blend reaching no farther across the country than a desktop’s', () => {
    /**
     * The bloom levels and the blend the layer lays out for a frame: a map
     * `cssWidth` x `cssHeight` CSS px at `ratio` device px per CSS px, at
     * `zoom`, as their energy-weighted RMS spread over the world's width. Each
     * level spreads light about as far as its texels are wide, a blurred blend
     * as far as its own standard deviation.
     */
    function drawnShare(
      zoom: number,
      [cssWidth, cssHeight]: readonly [number, number],
      ratio: number,
      lightResolution?: number,
    ): number {
      const layer = new GlowLayer(lightResolution === undefined ? {} : { lightResolution });
      // The frame layout is private; it needs no more of the map and the context than this.
      const internals = layer as unknown as {
        map: unknown;
        beginFrame(
          gl: unknown,
          res: unknown,
        ): {
          bloomWeights: readonly number[];
          targetPxPerCss: number;
          blur: { weight: number } | null;
          style: { blendSigmaPx: number };
        };
      };
      internals.map = { getCanvas: () => ({ clientWidth: cssWidth }), getZoom: () => zoom };
      const frame = internals.beginFrame(
        { drawingBufferWidth: cssWidth * ratio, drawingBufferHeight: cssHeight * ratio },
        { float: true },
      );
      let energy = 0;
      let moment = 0;
      frame.bloomWeights.forEach((weight, i) => {
        const texelPx = 2 ** (i + 1) / frame.targetPxPerCss;
        energy += weight;
        moment += weight * texelPx * texelPx;
      });
      if (frame.blur !== null) {
        energy += frame.blur.weight;
        moment += frame.blur.weight * frame.style.blendSigmaPx ** 2;
      }
      return Math.sqrt(moment / energy) / (512 * 2 ** zoom);
    }
    const screens = [
      // 320 x 640 phone at its national view and its widest zoom, 390 x 844 likewise, a tablet.
      [1.81, [320, 640], 2],
      [1.51, [320, 640], 2],
      [2.12, [390, 844], 3],
      [1.82, [390, 844], 3],
      [3.14, [820, 1180], 2],
    ] as const;
    // Light targets of one and two pixels per CSS pixel.
    for (const lightResolution of [undefined, 2]) {
      const desktop = drawnShare(4.03, [1440, 900], 2, lightResolution);
      for (const [zoom, size, ratio] of screens) {
        expect(drawnShare(zoom, size, ratio, lightResolution)).toBeLessThan(desktop * 1.15);
      }
    }
  });

  it('holds every school as dust, leaving out the ones the glow lights and the kinds not shown', () => {
    const layer = new GlowLayer({ dust: dustStyle() });
    fakeMap().add(layer);
    // Lit before the dust is in: left out as soon as it is.
    layer.hideDust(new Set([1, 7]));
    expect(layer.stats).toMatchObject({ dust: 0, dustHidden: 0, dustDrawn: false });
    // Kansas City, beside it, Boston; the second private.
    layer.setDust(
      new Float64Array([-94.6, 39.1, -94.5, 39.0, -71.1, 42.4]),
      new Uint8Array([0, 1, 2]),
    );
    // School 7 is not in the list: nothing to leave out for it.
    expect(layer.stats).toMatchObject({ dust: 3, dustHidden: 1 });
    layer.hideDust(new Set([0, 2]));
    expect(layer.stats.dustHidden).toBe(2);
    layer.hideDust(new Set());
    expect(layer.stats.dustHidden).toBe(0);
    // Found near a point by their places in the list, as drawn.
    const near = (): number[] =>
      [...layer.dustNear(mercatorXFromLng(-94.55), mercatorYFromLat(39.05), 0.001)].sort();
    expect(near()).toEqual([0, 1]);
    // Public schools only: the private one is left out, drawn and found no longer.
    layer.filterDust((kind) => (kind & 1) === 0);
    expect(layer.stats.dustHidden).toBe(1);
    expect(near()).toEqual([0]);
    layer.hideDust(new Set([0]));
    expect(near()).toEqual([]);
    expect(layer.stats.dustHidden).toBe(2);
    layer.filterDust(() => true);
    layer.hideDust(new Set());
    expect(near()).toEqual([0, 1]);
    // Holding dust draws nothing and counts no glowing points.
    expect(layer.stats).toMatchObject({ count: 0, glowCount: 0, mode: 'none' });
    layer.setDust(null);
    expect(layer.stats.dust).toBe(0);
    expect(layer.dustNear(0.5, 0.5, 1)).toEqual([]);
  });

  it('keeps the open school as dust whatever its kind, though not over its light', () => {
    const layer = new GlowLayer({ dust: dustStyle() });
    fakeMap().add(layer);
    // Kept before the dust is in: kept as soon as it is.
    layer.keepDust(1);
    layer.filterDust((kind) => (kind & 1) === 0);
    layer.setDust(
      new Float64Array([-94.6, 39.1, -94.5, 39.0, -71.1, 42.4]),
      new Uint8Array([0, 1, 1]),
    );
    const near = (): number[] =>
      [...layer.dustNear(mercatorXFromLng(-94.55), mercatorYFromLat(39.05), 0.001)].sort();
    // Public schools only: Boston's private school is left out, the open one beside Kansas City not.
    expect(layer.stats.dustHidden).toBe(1);
    expect(near()).toEqual([0, 1]);
    // Another school open, or none: the one before is left out as its kind is.
    layer.keepDust(2);
    expect(layer.stats.dustHidden).toBe(1);
    expect(near()).toEqual([0]);
    layer.keepDust(null);
    expect(layer.stats.dustHidden).toBe(2);
    // Lit, the open school gives way to its light.
    layer.keepDust(1);
    layer.hideDust(new Set([1]));
    expect(near()).toEqual([0]);
    layer.hideDust(new Set());
    expect(near()).toEqual([0, 1]);
    // A place not in the list keeps nothing.
    layer.keepDust(7);
    expect(layer.stats.dustHidden).toBe(2);
  });

  it('finds no speck while it is off the map, as after a lost context, nor without a dust style', () => {
    const layer = new GlowLayer({ dust: dustStyle() });
    const schools = new Float64Array([-94.6, 39.1]);
    layer.setDust(schools, new Uint8Array([0]));
    const near = (): number[] =>
      layer.dustNear(mercatorXFromLng(-94.6), mercatorYFromLat(39.1), 0.001);
    // Not on a map yet: nothing drawn.
    expect(near()).toEqual([]);
    const map = fakeMap();
    map.add(layer);
    expect(near()).toEqual([0]);
    // The context lost: the layer steps off the map and draws nothing until it is back.
    map.lose();
    expect(near()).toEqual([]);
    map.restore();
    expect(near()).toEqual([0]);
    // Without a dust style, it draws none.
    const plain = new GlowLayer();
    plain.setDust(schools, new Uint8Array([0]));
    fakeMap().add(plain);
    expect(plain.dustNear(mercatorXFromLng(-94.6), mercatorYFromLat(39.1), 0.001)).toEqual([]);
  });

  it('finds no speck where the GPU could not run the dust: none is drawn', () => {
    const layer = new GlowLayer({ dust: dustStyle() });
    layer.setDust(new Float64Array([-94.6, 39.1]), new Uint8Array([0]));
    const near = (): number[] =>
      layer.dustNear(mercatorXFromLng(-94.6), mercatorYFromLat(39.1), 0.001);
    // Across Kansas City at zoom 7, on a GPU that cannot build the dust's program.
    const map = {
      getCanvasContainer: () => ({ addEventListener: () => undefined }),
      on: () => undefined,
      off: () => undefined,
      getZoom: () => 7,
      getBounds: () => ({
        getWest: () => -96,
        getEast: () => -93,
        getNorth: () => 40,
        getSouth: () => 38,
      }),
      triggerRepaint: () => undefined,
    } as unknown as MapLibreMap;
    const gl = {
      getParameter: () => new Float32Array([1, 64]),
      createShader: () => {
        throw new Error('no shader');
      },
    } as unknown as WebGL2RenderingContext;
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    layer.onAdd(map, gl);
    expect(near()).toEqual([0]);
    layer.render(gl, { shaderData: { variantName: 'mercator' } } as CustomRenderMethodInput);
    expect(error).toHaveBeenCalledOnce();
    error.mockRestore();
    expect(layer.stats.dustDrawn).toBe(false);
    expect(near()).toEqual([]);
  });

  it('counts born times later than now, as from a skewed clock or epoch milliseconds', () => {
    const layer = new GlowLayer();
    const now = layer.now();
    layer.setData({
      lngLat: new Float32Array([-93, 45, -88, 42, -71, 42]),
      status: new Uint8Array([GlowStatus.Closed, GlowStatus.Delayed, GlowStatus.Remote]),
      bornAt: new Float64Array([now + 5_000, Date.now(), now - 100]),
    });
    expect(layer.stats.bornClamped).toBe(2);
  });
});
