import type { CustomRenderMethodInput, Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { GlowLayer, GlowStatus } from '..';
import { glowStyleAtZoom } from '../curves';
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

  /** The frame layout is private; it needs no more of the map and the context than this. */
  function layOut(
    zoom: number,
    [cssWidth, cssHeight]: readonly [number, number],
    ratio: number,
    options: { lightResolution?: number; float?: boolean; maxTarget?: number } = {},
  ): {
    bloomWeights: readonly number[];
    targetPxPerCss: number;
    targetSize: readonly [number, number];
    blur: { weight: number } | null;
    denseShare: number;
    style: { blendSigmaPx: number; coreShare: number; blend: number };
  } {
    const { lightResolution, float = true, maxTarget = 16384 } = options;
    const layer = new GlowLayer(lightResolution === undefined ? {} : { lightResolution });
    const internals = layer as unknown as {
      map: unknown;
      beginFrame(gl: unknown, res: unknown): ReturnType<typeof layOut>;
    };
    internals.map = { getCanvas: () => ({ clientWidth: cssWidth }), getZoom: () => zoom };
    return internals.beginFrame(
      { drawingBufferWidth: cssWidth * ratio, drawingBufferHeight: cssHeight * ratio },
      { float, maxTarget: [maxTarget, maxTarget] },
    );
  }

  it('draws a smaller screen’s bloom and blend reaching no farther across the country than a desktop’s', () => {
    /**
     * The bloom levels and the blend the layer lays out for a frame, as their
     * energy-weighted RMS spread over the world's width. Each level spreads
     * light about as far as its texels are wide, a blurred blend as far as its
     * own standard deviation.
     */
    function drawnShare(
      zoom: number,
      size: readonly [number, number],
      ratio: number,
      lightResolution?: number,
    ): number {
      const frame = layOut(
        zoom,
        size,
        ratio,
        lightResolution === undefined ? {} : { lightResolution },
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
    // Light targets of the device's own resolution, and of one and two pixels per CSS pixel.
    for (const lightResolution of [undefined, 1, 2]) {
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

  it('lifts a lone school far out over the state lines the map draws, asking for them until it has them', () => {
    let lines: number | null = null;
    let asked = 0;
    const layer = new GlowLayer({
      lineGray: () => {
        asked += 1;
        return lines;
      },
    });
    const internals = layer as unknown as {
      map: unknown;
      beginFrame(gl: unknown, res: unknown): { style: { floorGain: number } };
    };
    internals.map = { getCanvas: () => ({ clientWidth: 390 }), getZoom: () => 2.12 };
    const floorGain = (): number =>
      internals.beginFrame(
        { drawingBufferWidth: 1170, drawingBufferHeight: 2532 },
        { float: true, maxTarget: [16384, 16384] },
      ).style.floorGain;
    const unknown = floorGain();
    expect(unknown).toBe(glowStyleAtZoom(2.12).floorGain);
    lines = 0x4d / 255;
    const phone = floorGain();
    expect(phone).toBe(glowStyleAtZoom(2.12, lines).floorGain);
    expect(phone).toBeGreaterThan(unknown);
    // Kept once known, as the map keeps its lines' color.
    lines = 0x2a / 255;
    expect(floorGain()).toBe(phone);
    expect(asked).toBe(2);
  });

  it('draws the light at the device’s resolution up to two pixels per CSS pixel, and at one on the 8-bit fallback', () => {
    expect(layOut(4, [1440, 900], 2).targetPxPerCss).toBe(2);
    expect(layOut(2.12, [390, 844], 3).targetPxPerCss).toBe(2);
    expect(layOut(4, [1280, 720], 1.5).targetPxPerCss).toBe(1.5);
    // The fallback runs on the weakest GPUs, where twice the resolution is four times the fill.
    expect(layOut(4, [1440, 900], 2, { float: false }).targetPxPerCss).toBe(1);
  });

  it('keeps the light target within what the GPU can allocate', () => {
    // A 2560 CSS px wide window at 2x would need a 5312 px target, past a 4096 px texture limit.
    const frame = layOut(4, [2560, 400], 2, { maxTarget: 4096 });
    expect(frame.targetSize[0]).toBeLessThanOrEqual(4096);
    expect(frame.targetPxPerCss).toBeCloseTo(4096 / (2560 + 96), 9);
    expect(layOut(4, [1440, 900], 2, { maxTarget: 4096 }).targetPxPerCss).toBe(2);
  });

  it('keeps the light target to about a 2x laptop’s pixels, a larger screen drawing it coarser', () => {
    const laptop = layOut(4, [1440, 900], 2);
    expect(laptop.targetPxPerCss).toBe(2);
    for (const size of [
      [1920, 1080],
      [2560, 1440],
    ] as const) {
      const frame = layOut(6, size, 2);
      expect(frame.targetPxPerCss).toBeLessThan(2);
      expect(frame.targetPxPerCss).toBeGreaterThan(1.2);
      expect(frame.targetSize[0] * frame.targetSize[1]).toBeLessThan(3200 * 2000 * 1.01);
      // A coarser target shows more of each core, so a lone light is as bright at its center.
      expect(frame.style.coreShare).toBeGreaterThan(layOut(6, [1440, 900], 2).style.coreShare);
      expect(frame.style).toEqual(glowStyleAtZoom(6, undefined, frame.targetPxPerCss));
    }
  });

  it('draws zoom 9 and up, and a 1x screen regionally, with no blend, grain or blur to pay for', () => {
    const screens = [
      [[1440, 900], 1],
      [[1440, 900], 2],
      [[820, 1180], 2],
      [[390, 844], 3],
    ] as const;
    for (const [size, ratio] of screens) {
      for (const zoom of [9, 10, 12, 15]) {
        const frame = layOut(zoom, size, ratio);
        expect(frame.style.blend).toBe(0);
        expect(frame.denseShare).toBe(0);
        expect(frame.blur).toBeNull();
      }
    }
    for (const zoom of [5.6, 7]) {
      const frame = layOut(zoom, [1440, 900], 1);
      expect(frame.style.blend).toBe(0);
      expect(frame.denseShare).toBe(0);
      expect(frame.blur).toBeNull();
    }
    // Nationally the grain and the blend are drawn.
    expect(layOut(3.7, [1440, 900], 1).denseShare).toBeGreaterThan(0);
    expect(layOut(3.7, [1440, 900], 1).blur).not.toBeNull();
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
