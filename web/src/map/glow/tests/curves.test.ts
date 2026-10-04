import { describe, expect, it } from 'vitest';

import { STATUS_HEX, hexToLinear, linearToSrgb } from '../color';

import {
  BLEND_LEVEL_PX,
  BLEND_MIN_SIGMA_PX,
  BLOOM_KNEE,
  BLOOM_LIMIT,
  BLOOM_SCALES_PX,
  BLOOM_SOURCE_GLSL,
  BLOOM_WEIGHT_STOPS,
  CORE_EDGE_D2,
  CORE_FOCUS_STOPS,
  CORE_SIGMA_STOPS,
  FALLBACK_ALPHA_STOPS,
  FALLBACK_BLOOM_FOLD,
  FALLBACK_FINE_GAIN,
  FALLBACK_GLSL,
  FALLBACK_HALO_RADIUS_STOPS,
  FALLBACK_MIN_TRANSMITTANCE,
  FLOOR_FADE,
  FULL_SIZE_ZOOM,
  GAIN_STOPS,
  type GlowFrameStyle,
  HALO_ENERGY_STOPS,
  HALO_RADIUS_STOPS,
  HALO_SIGMA_SHARE,
  GLYPH_FADE_END,
  GLYPH_FADE_START,
  MIN_BLOOM_WEIGHT,
  PULSE_SECONDS,
  blendCutAtScale,
  blendFloor,
  blendPlan,
  blendShareOfScale,
  bloomLevels,
  bloomPlan,
  bloomSourceScale,
  bloomWeights,
  fallbackDecode,
  fallbackEncode,
  fallbackFloor,
  fallbackHalo,
  fieldPeak,
  glowReachPx,
  glowStyleAtZoom,
  interpolateStops,
  kernelAt,
  kernelUniforms,
  pulseAt,
  smoothstep,
  windowedGaussianIntegral,
} from '../curves';
import { statusLight, toneMap } from '../tonemap';

import { compositeLight, displayed } from './pipeline';

/** Integral of a radial kernel over the plane, by the midpoint rule, in units of radius^2. */
function energy(kernel: (d: number) => number): number {
  const steps = 4000;
  let sum = 0;
  for (let i = 0; i < steps; i++) {
    const d = (i + 0.5) / steps;
    sum += kernel(d) * 2 * Math.PI * d * (1 / steps);
  }
  return sum;
}

describe('zoom curves', () => {
  it('interpolate linearly between stops and hold the ends', () => {
    const stops = [
      [3, 10],
      [5, 20],
      [9, 0],
    ] as const;
    expect(interpolateStops(stops, 0)).toBe(10);
    expect(interpolateStops(stops, 4)).toBe(15);
    expect(interpolateStops(stops, 7)).toBe(10);
    expect(interpolateStops(stops, 12)).toBe(0);
    expect(() => interpolateStops([], 3)).toThrow();
  });

  it('glow radius: wide and steady nationally, tightening from zoom 6, small from zoom 11', () => {
    const national = [4, 5, 6].map(glowReachPx);
    // At zoom 5 the floor puts more of a lone school's light in its narrow blend.
    for (const reach of national) expect(reach).toBeGreaterThan(36);
    expect(Math.max(...national) / Math.min(...national)).toBeLessThan(1.15);
    let previous = Infinity;
    for (let zoom = 6; zoom <= 11; zoom += 0.25) {
      const reach = glowReachPx(zoom);
      expect(reach).toBeLessThan(previous);
      previous = reach;
    }
    for (const zoom of [11, 13, 16]) expect(glowReachPx(zoom)).toBeLessThan(12);
  });

  it('bloom carries the wide light below zoom 11 and is off from zoom 11', () => {
    expect(bloomWeights(4).reduce((a, b) => a + b)).toBeGreaterThan(1.4);
    expect(bloomWeights(11).every((w) => w === 0)).toBe(true);
    expect(bloomWeights(15).every((w) => w === 0)).toBe(true);
    // The widest scales fade first as the map zooms in.
    const last = BLOOM_SCALES_PX.length - 1;
    expect(bloomWeights(9)[last]).toBeLessThan(bloomWeights(6)[last] ?? 0);
  });

  it('reads bloom weights by CSS-pixel scale, independent of target resolution', () => {
    const style = glowStyleAtZoom(5);
    for (const targetPxPerCss of [0.5, 1, 2, 4]) {
      bloomLevels(style, targetPxPerCss, 4000).forEach((weight, i) => {
        const scale = BLOOM_SCALES_PX.indexOf(2 ** (i + 1) / targetPxPerCss);
        expect(weight).toBe(scale < 0 ? 0 : style.bloom[scale]);
      });
    }
    // A scale between two levels is shared out so that together they keep its mean square spread.
    const eight = { ...style, bloom: [0, 1, 0, 0, 0] };
    const targetPxPerCss = Math.SQRT1_2;
    const levels = bloomLevels(eight, targetPxPerCss, 4000);
    const texelPx = (i: number): number => 2 ** (i + 1) / targetPxPerCss;
    expect(levels.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 12);
    expect(levels.reduce((sum, w, i) => sum + w * texelPx(i) ** 2, 0)).toBeCloseTo(64, 9);
    expect(levels.filter((w) => w > 0)).toHaveLength(2);
  });

  it('draws the full-size bloom from zoom 4 up as it always has, on light targets of whole powers of two', () => {
    /** The layer's bloom levels as 0cacc6a laid them out (GlowLayer.beginFrame then). */
    function levelsBefore(
      bloom: readonly number[],
      targetPxPerCss: number,
      sizePx: number,
    ): number[] {
      const weights: number[] = [];
      let size = sizePx;
      for (let level = 1; ; level++) {
        const scale = 2 ** level / targetPxPerCss;
        size = Math.ceil(size / 2);
        if (scale > 64 * 1.01 || size < 2) break;
        const position = Math.log2(scale / 4);
        if (position < -1e-6 || position > bloom.length - 1 + 1e-6) {
          weights.push(0);
          continue;
        }
        const lo = Math.floor(position + 1e-6);
        const t = Math.max(0, position - lo);
        weights.push((bloom[lo] ?? 0) * (1 - t) + (bloom[lo + 1] ?? 0) * t);
      }
      while (weights.length > 0 && (weights[weights.length - 1] ?? 0) < 1e-3) weights.pop();
      return weights;
    }
    // Half, one, two and four light pixels per CSS pixel.
    for (const targetPxPerCss of [0.5, 1, 2, 4]) {
      for (let zoom = FULL_SIZE_ZOOM; zoom <= 12; zoom += 1 / 4) {
        const style = glowStyleAtZoom(zoom);
        expect(bloomLevels(style, targetPxPerCss, 1000)).toEqual(
          levelsBefore(bloomWeights(zoom), targetPxPerCss, 1000),
        );
      }
    }
  });

  it('keeps all of the bloom’s light in the levels it draws, at any light-target resolution', () => {
    // A browser zoomed out gives light targets between powers of two.
    for (const targetPxPerCss of [0.5, 0.67, 0.8, 0.9, 1, 1.25, 2]) {
      for (const zoom of [1.51, 1.7, 2.12, 2.6, 3.14, 3.81, 3.99, 4, 4.03, 6, 9]) {
        const style = glowStyleAtZoom(zoom);
        const total = style.bloom.reduce((a, b) => a + b, 0);
        // A light target with room for every level, and one too small for the coarsest.
        for (const sizePx of [1000, 40]) {
          const drawn = bloomLevels(style, targetPxPerCss, sizePx).reduce((a, b) => a + b, 0);
          // Only trailing levels too faint to draw are left out.
          expect(Math.abs(drawn - total)).toBeLessThan(2 * MIN_BLOOM_WEIGHT);
        }
      }
    }
  });

  it('fades glyphs in between zoom 10.5 and 11', () => {
    expect(glowStyleAtZoom(GLYPH_FADE_START - 0.01).glyphOpacity).toBe(0);
    expect(glowStyleAtZoom(GLYPH_FADE_END).glyphOpacity).toBe(1);
    const mid = glowStyleAtZoom((GLYPH_FADE_START + GLYPH_FADE_END) / 2).glyphOpacity;
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1);
  });
});

/** Kilometers a CSS px spans at `zoom` on the Mercator map, at 39°N (Kansas City). */
function kmPerPx(zoom: number): number {
  return (40075.017 * Math.cos((39 * Math.PI) / 180)) / (512 * 2 ** zoom);
}

const SIZE = 256;

/**
 * Light the composite shows `r` CSS px right of a lone point in the middle of a
 * light target of `t` pixels per CSS pixel, over state lines of `lineGray`.
 */
function lonePoint(zoom: number, t = 1, lineGray?: number): (r: number) => number {
  const light = compositeLight([[128.5, 128.5]], glowStyleAtZoom(zoom, lineGray), SIZE, t);
  return (r) => light[128 * SIZE + 128 + Math.round(r * t)] ?? 0;
}

/** Farthest distance at which `light` shows above `level` of 255, CSS px. */
function reachAbove(light: (r: number) => number, level: number): number {
  let reach = 0;
  for (let r = 0; r < SIZE / 2; r++) if (displayed(light(r)) > level) reach = r;
  return reach;
}

/**
 * Brightest and dimmest displayed value over the middle of a square grid of
 * points `spacing` CSS px apart, on a light target of `t` pixels per CSS pixel.
 */
function gridRange(zoom: number, spacing: number, t = 1): [min: number, max: number] {
  const points: [number, number][] = [];
  for (let y = 128 - 72; y <= 128 + 72; y += spacing * t) {
    for (let x = 128 - 72; x <= 128 + 72; x += spacing * t) points.push([x + 0.3, y + 0.6]);
  }
  const light = compositeLight(points, glowStyleAtZoom(zoom), SIZE, t);
  let min = Infinity;
  let max = 0;
  for (let y = 108; y < 148; y++) {
    for (let x = 108; x < 148; x++) {
      const value = displayed(light[y * SIZE + x] ?? 0);
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  return [min, max];
}

/** Values from before the national blend, zoom 9 and up, to the last bit. */
const BEFORE_BLEND = [
  [
    9,
    {
      style: {
        coreSigmaPx: 1.5,
        gain: 0.95,
        haloRadiusPx: 16,
        haloEnergy: 0.19999999999999998,
        bloom: [0.25, 0.26, 0.185, 0.08, 0.02],
        glyphOpacity: 0,
        glyphRadiusPx: 4.5,
        openRadiusPx: 2,
      },
      kernel: {
        radius: 16,
        coreFalloff: 51.2,
        coreWeight: 0.9,
        haloFalloff: 3.858024691358025,
        haloWeight: 0.022121420126506787,
        hole: 0,
      },
      fallback: {
        radius: 27,
        coreFalloff: 145.8,
        coreWeight: 0.9,
        haloFalloff: 6.210705723104546,
        haloWeight: 0.044268052585697396,
        hole: 0,
      },
      reach: 21.969471641587702,
    },
  ],
  [
    9.75,
    {
      style: {
        coreSigmaPx: 1.65,
        gain: 0.93125,
        haloRadiusPx: 14.5,
        haloEnergy: 0.5,
        bloom: [
          0.21250000000000002, 0.17, 0.08374999999999999, 0.01999999999999999,
          0.0049999999999999975,
        ],
        glyphOpacity: 0,
        glyphRadiusPx: 4.5,
        openRadiusPx: 2,
      },
      kernel: {
        radius: 14.5,
        coreFalloff: 35.36585365853659,
        coreWeight: 0.9158957106812448,
        haloFalloff: 3.858024691358025,
        haloWeight: 0.08147837215679837,
        hole: 0,
      },
      fallback: {
        radius: 23.666666666666668,
        coreFalloff: 94.21549387907675,
        coreWeight: 0.9158957106812448,
        haloFalloff: 5.094003598403757,
        haloWeight: 0.06792187290901235,
        hole: 0,
      },
      reach: 13.670075363800207,
    },
  ],
  [
    10.5,
    {
      style: {
        coreSigmaPx: 1.7999999999999998,
        gain: 0.9125,
        haloRadiusPx: 13,
        haloEnergy: 0.8999999999999999,
        bloom: [0.1, 0.07, 0.025, 0, 0],
        glyphOpacity: 0,
        glyphRadiusPx: 4.5,
        openRadiusPx: 2,
      },
      kernel: {
        radius: 13,
        coreFalloff: 24.21203438395416,
        coreWeight: 0.9283667621776505,
        haloFalloff: 3.8580246913580254,
        haloWeight: 0.21714071845834068,
        hole: 0,
      },
      fallback: {
        radius: 16.666666666666668,
        coreFalloff: 39.796243234638666,
        coreWeight: 0.9283667621776505,
        haloFalloff: 4.251186330971156,
        haloWeight: 0.16848731562201322,
        hole: 0,
      },
      reach: 8.22501684788374,
    },
  ],
  [
    13,
    {
      style: {
        coreSigmaPx: 2.06,
        gain: 0.9,
        haloRadiusPx: 12.8,
        haloEnergy: 1.2,
        bloom: [0, 0, 0, 0, 0],
        glyphOpacity: 1,
        glyphRadiusPx: 5.166666666666667,
        openRadiusPx: 2.3333333333333335,
      },
      kernel: {
        radius: 12.8,
        coreFalloff: 18.23037208474275,
        coreWeight: 0,
        haloFalloff: 3.858024691358026,
        haloWeight: 0.3911435768701842,
        hole: 0.4036458333333333,
      },
      fallback: {
        radius: 12.8,
        coreFalloff: 18.23037208474275,
        coreWeight: 0,
        haloFalloff: 3.858024691358026,
        haloWeight: 0.3911435768701842,
        hole: 0.4036458333333333,
      },
      reach: 7.35143731153674,
    },
  ],
] as const;

describe('national blend', () => {
  it('shows no lone core up to zoom 4.5 and every core from zoom 8, more of them at each step between', () => {
    for (let zoom = 2; zoom <= 4.5; zoom += 0.25) {
      const style = glowStyleAtZoom(zoom);
      expect(style.coreShare).toBe(0);
      // The blend carries the cores' light, cut on a phone, and cores that pile up show as grain.
      expect(style.blend).toBeGreaterThan(blendCutAtScale(style.sizeScale));
      expect(style.denseShare).toBeGreaterThan(0);
    }
    let previous = 0;
    for (let zoom = 4.75; zoom < 8; zoom += 0.25) {
      const share = glowStyleAtZoom(zoom).coreShare;
      expect(share).toBeGreaterThan(previous);
      expect(share - previous).toBeLessThanOrEqual(0.1 + 1e-12);
      previous = share;
    }
    for (let zoom = 5.5; zoom <= 22; zoom += 0.25) expect(glowStyleAtZoom(zoom).denseShare).toBe(0);
    for (let zoom = 8; zoom <= 22; zoom += 0.25) {
      const style = glowStyleAtZoom(zoom);
      expect(style.coreShare).toBe(1);
      expect(style.blend).toBe(0);
    }
  });

  it('keeps each point’s light whatever share of it is sharp', () => {
    for (let zoom = 2; zoom <= 12; zoom += 0.125) {
      const style = glowStyleAtZoom(zoom);
      const own = BLOOM_SCALES_PX.reduce(
        (sum, _, i) =>
          sum +
          interpolateStops(
            BLOOM_WEIGHT_STOPS.map(([z, weights]) => [z, weights[i] ?? 0] as const),
            zoom,
          ),
        0,
      );
      const shown = style.coreShare + style.bloom.reduce((a, b) => a + b, 0) + style.blend;
      // Below zoom 4 the bloom's light is cut by more than the cores' (glowSizeScale), and the
      // blend's share of the cores' light as well (blendCutAtScale).
      const cut = blendCutAtScale(style.sizeScale);
      const cores = style.coreShare + (1 - style.coreShare) * cut;
      expect(shown).toBeCloseTo(cores + style.sizeScale ** 1.5 * own, 12);
      // A lone school, whose blend stands on its floor, shows at least all of its light.
      if (style.blend > 0) {
        const uncut = style.blend + (1 - style.coreShare) * (1 - cut);
        // All but 2% of the knee's own light.
        expect(fieldPeak(style) / style.floorKnee).toBeGreaterThanOrEqual(
          uncut / style.blend - 0.021,
        );
      }
    }
  });

  it('turns a lone point at national zoom into soft light that never vanishes', () => {
    for (const t of [1, 2, 3]) {
      for (const zoom of [2.12, 3, 3.14, 4, 4.5]) {
        const light = lonePoint(zoom, t);
        // No speck: 4 px out the light is still above half its peak, where a core's is 2% of it.
        // Below zoom 4 the blend shrinks with the map down to 3 px, and the probe with it.
        const out = Math.min(4, Math.round(glowStyleAtZoom(zoom).blendSigmaPx));
        expect(light(0) / light(out)).toBeLessThan(1.75);
        expect(displayed(light(0))).toBeGreaterThan(20);
      }
    }
    // From zoom 8 a school is a point of its own again.
    const street = lonePoint(9);
    expect(street(0) / street(4)).toBeGreaterThan(10);
  }, 60_000);

  it('shows a lone school regionally as a crisp small light over a soft wash, sharper on a sharper screen', () => {
    for (const zoom of [5.5, 6, 7]) {
      const sharp = lonePoint(zoom, 2);
      // A core: 2 px out a fifth of its peak at most, and the wash still lit 4 px out.
      expect(sharp(2) / sharp(0)).toBeLessThan(0.2);
      expect(displayed(sharp(4))).toBeGreaterThan(20);
      // Drawn at the device's resolution the core is narrower than on a target of CSS pixels.
      const soft = lonePoint(zoom, 1);
      expect(sharp(1) / sharp(0)).toBeLessThan(0.85 * (soft(1) / soft(0)));
      expect(displayed(sharp(0))).toBeGreaterThan(displayed(soft(0)));
    }
    expect(interpolateStops(CORE_FOCUS_STOPS, 9)).toBe(1);
  }, 60_000);

  it('merges schools about 15 km apart into one even field', () => {
    for (const zoom of [2.12, 3, 4, 4.5]) {
      const spacing = Math.max(4, Math.round(15 / kmPerPx(zoom)));
      const [min, max] = gridRange(zoom, spacing);
      expect((max - min) / max).toBeLessThan(0.05);
    }
    // Regionally, on a high-density screen, the same schools are points over the blend's wash,
    // which keeps the gaps lit.
    for (const zoom of [5.5, 6]) {
      const [min, max] = gridRange(zoom, Math.round(15 / kmPerPx(zoom)), 2);
      expect(min / max).toBeLessThan(0.5);
      expect(min).toBeGreaterThan(30);
    }
    // Where the blend is gone, points in a dark field.
    const [min, max] = gridRange(9, Math.round(15 / kmPerPx(9)));
    expect(min / max).toBeLessThan(0.5);
  });

  it('keeps the light close to its schools', () => {
    // The blend spreads a point over about 15 km at most, well inside the bloom's own reach.
    for (let zoom = 4; zoom <= 6; zoom += 0.25) {
      expect(glowStyleAtZoom(zoom).blendSigmaPx * kmPerPx(zoom)).toBeLessThan(16);
    }
    // At zoom 4 a lone school lights no farther than it did with its core shown: one display
    // step within 25 px (95 km), above 8 of 255 within 10 px (38 km).
    const light = lonePoint(4);
    expect(reachAbove(light, 1)).toBeLessThanOrEqual(25);
    expect(reachAbove(light, 8)).toBeLessThanOrEqual(10);
    expect(glowReachPx(4)).toBeLessThan(44);
  });

  it('blurs nothing nationally but floors its level, and blurs a finely sampled level beyond', () => {
    for (let zoom = FULL_SIZE_ZOOM; zoom <= 4.5; zoom += 0.125) {
      expect(blendPlan(glowStyleAtZoom(zoom), 1).radius).toBe(0);
      expect(bloomPlan(glowStyleAtZoom(zoom), 1, 1000).blur).toMatchObject({ level: 2, radius: 0 });
    }
    // Below zoom 4, where the blend shrinks under the 4 px level's own spread: the 2 px level, a
    // quarter of the light target, blurred where the blend is wider, and on its floor.
    for (let zoom = 1.5; zoom < FULL_SIZE_ZOOM; zoom += 0.125) {
      const style = glowStyleAtZoom(zoom);
      const small = blendPlan(style, 1);
      expect(small.level).toBe(1);
      expect(small.radius).toBeLessThanOrEqual(6);
      expect(bloomPlan(style, 1, 1000).blur).not.toBeNull();
    }
    const plan = blendPlan(glowStyleAtZoom(6), 1);
    expect(2 ** plan.level).toBe(BLEND_LEVEL_PX);
    expect(plan.sigmaTexels).toBeGreaterThan(2);
    expect(plan.radius).toBe(Math.ceil(3 * plan.sigmaTexels));
    // The same level in CSS px on a light target of two pixels per CSS px.
    expect(2 ** blendPlan(glowStyleAtZoom(6), 2).level / 2).toBe(BLEND_LEVEL_PX);
  });

  it('spreads the blend as wide as asked on any light target, between powers of two too', () => {
    // A level coarser than the blend, as a 150% screen took at zoom 4 to 4.7, drew it wider.
    for (const t of [0.8, 1, 1.25, 1.5, 1.75, 2]) {
      for (let zoom = 1.5; zoom <= 6; zoom += 0.25) {
        const style = glowStyleAtZoom(zoom);
        const plan = blendPlan(style, t);
        const texelPx = 2 ** plan.level / t;
        // The finest level, 2 light-target pixels, is the narrowest there is.
        expect(texelPx).toBeLessThanOrEqual(Math.max(style.blendSigmaPx, 2 / t) + 1e-9);
        if (texelPx <= style.blendSigmaPx) {
          expect(Math.hypot(texelPx, plan.sigmaTexels * texelPx)).toBeCloseTo(
            style.blendSigmaPx,
            9,
          );
        }
      }
    }
    // And the bloom reaches a level as wide as its widest scale, where it fell a level short.
    for (const t of [0.8, 1.25, 1.5, 1.75]) {
      const weights = bloomLevels(glowStyleAtZoom(4), t, 4000);
      expect(2 ** weights.length / t).toBeGreaterThanOrEqual(64);
    }
  });

  it('takes a bloom scale into the blend gradually as the blend widens', () => {
    expect(blendShareOfScale(8, 8)).toBe(1);
    expect(blendShareOfScale(8, 8 / Math.SQRT2)).toBeCloseTo(0, 12);
    let previous = 0;
    for (let sigma = 5; sigma <= 9; sigma += 0.05) {
      const share = blendShareOfScale(8, sigma);
      expect(share).toBeGreaterThanOrEqual(previous);
      expect(share - previous).toBeLessThan(0.05);
      previous = share;
    }
  });

  it('carries the blend in the fallback’s halo, as bright and as soft as the float path', () => {
    for (const zoom of [4, 5.6]) {
      const style = glowStyleAtZoom(zoom);
      const k = kernelUniforms(style, 1, fallbackHalo(style, zoom), style.coreShare);
      const fallback = (r: number): number => style.gain * kernelAt(k, r / k.radius);
      const float = lonePoint(zoom);
      if (style.coreShare === 0) expect(fallback(0) / fallback(4)).toBeLessThan(1.7);
      for (const r of [0, 4]) {
        expect(displayed(fallback(r))).toBeGreaterThan(0.9 * displayed(float(r)));
        expect(displayed(fallback(r))).toBeLessThan(1.5 * displayed(float(r)));
      }
    }
  });

  it('leaves zoom 9 and up as it was', () => {
    for (let zoom = 8; zoom <= 22; zoom += 0.25) {
      expect(bloomWeights(zoom)).toEqual(
        BLOOM_SCALES_PX.map((_, i) =>
          interpolateStops(
            BLOOM_WEIGHT_STOPS.map(([z, weights]) => [z, weights[i] ?? 0] as const),
            zoom,
          ),
        ),
      );
    }
    for (const [zoom, before] of BEFORE_BLEND) {
      const style = glowStyleAtZoom(zoom);
      const { sizeScale, coreShare, blend, blendSigmaPx, floorGain, floorKnee, ...drawn } = style;
      const { coreFocus, denseShare, ...rest } = drawn;
      expect([sizeScale, coreShare, blend, floorGain, floorKnee, coreFocus, denseShare]).toEqual([
        1, 1, 0, 1, 0, 1, 0,
      ]);
      expect(blendSigmaPx).toBeGreaterThan(0);
      expect(rest).toEqual(before.style);
      expect(kernelUniforms(style, 1)).toEqual(before.kernel);
      expect(kernelUniforms(style, 1, fallbackHalo(style, zoom), coreShare)).toEqual(
        before.fallback,
      );
      expect(glowReachPx(zoom)).toBe(before.reach);
    }
  });
});

describe('small screens', () => {
  /** The world's width at a zoom, CSS px. */
  const worldPx = (zoom: number): number => 512 * 2 ** zoom;
  /** A 1440 x 900 desktop's national view. */
  const DESKTOP = 4.03;
  /**
   * National views of 320 x 640 and 390 x 844 phones, an 820 x 1180 tablet,
   * and 1280 x 720 and 1366 x 768 laptops.
   */
  const NATIONAL_VIEWS = [1.81, 2.12, 3.14, 3.7, 3.81];
  /** The widest zooms of 320, 360 and 390 px phones and of a 1440 x 900 desktop. */
  const WIDEST = [1.51, 1.7, 1.82, 3.73];
  const SMALL_SCREENS = [...NATIONAL_VIEWS, ...WIDEST];
  /** Phones' national and widest views: below 720 CSS px wide, where state lines are brighter. */
  const PHONES = [1.51, 1.7, 1.81, 1.82, 2.12];
  /** A phone's state lines, --line-state in index.html, 0..255, and a wider screen's. */
  const PHONE_STATE_LINE = 0x4d;
  const STATE_LINE = 0x2a;

  /** The bloom's light that the blend took in: all of the blend but the cores' own. */
  const bloomInBlend = (style: GlowFrameStyle): number =>
    style.blend - (1 - style.coreShare) * blendCutAtScale(style.sizeScale);

  /**
   * Energy-weighted RMS spread of the bloom levels and the blend the layer
   * draws (bloomPlan), each level at its texel size and the blend at its own,
   * CSS px, for a light target of `targetPxPerCss`. The floor only raises a
   * lone school's blend where it is, never farther, so it is left out.
   */
  function drawnBloomPx(zoom: number, targetPxPerCss: number): number {
    const style = glowStyleAtZoom(zoom);
    const { weights, blur } = bloomPlan(style, targetPxPerCss, 2000);
    let energy = 0;
    let moment = 0;
    weights.forEach((weight, i) => {
      const texelPx = 2 ** (i + 1) / targetPxPerCss;
      energy += weight;
      moment += weight * texelPx * texelPx;
    });
    if (blur !== null) {
      energy += blur.weight;
      moment += blur.weight * style.blendSigmaPx ** 2;
    }
    return Math.sqrt(moment / energy);
  }

  /** One point's bloom light over the world's area: what it lays on any part of the map. */
  function bloomLight(zoom: number): number {
    const style = glowStyleAtZoom(zoom);
    const core = style.gain * 2 * Math.PI * style.coreSigmaPx ** 2;
    const drawn = bloomLevels(style, 1, 2000).reduce((a, b) => a + b, 0) + bloomInBlend(style);
    return (core * drawn) / worldPx(zoom) ** 2;
  }

  const share = (reachPx: number, zoom: number): number => reachPx / worldPx(zoom);

  /**
   * The brightest displayed value over the middle of a field of schools `km`
   * apart, or of a lone school for null, on a light target of `t` pixels per
   * CSS pixel.
   */
  function fieldPeakShown(zoom: number, km: number | null, t: number, lineGray?: number): number {
    const points: [number, number][] = [];
    const spacing = km === null ? 0 : (km / kmPerPx(zoom)) * t;
    if (km === null) points.push([128.3, 128.6]);
    for (let y = 16; km !== null && y <= 240; y += spacing) {
      for (let x = 16; x <= 240; x += spacing) points.push([x + 0.3, y + 0.6]);
    }
    const light = compositeLight(points, glowStyleAtZoom(zoom, lineGray), SIZE, t);
    const box = Math.max(Math.ceil(spacing), 6);
    let max = 0;
    for (let y = 128 - box; y < 128 + box; y++) {
      for (let x = 128 - box; x < 128 + box; x++) {
        max = Math.max(max, displayed(light[y * SIZE + x] ?? 0));
      }
    }
    return max;
  }

  it('keeps the glow reaching no farther across the country than at a desktop national view', () => {
    for (const zoom of SMALL_SCREENS) {
      // Levels an octave apart share each shrunk scale out, which widens it a little.
      for (const t of [1, 2]) {
        expect(share(drawnBloomPx(zoom, t), zoom)).toBeLessThan(
          share(drawnBloomPx(DESKTOP, t), DESKTOP) * 1.15,
        );
      }
      expect(share(glowReachPx(zoom), zoom)).toBeLessThan(
        share(glowReachPx(DESKTOP), DESKTOP) * 1.1,
      );
      // Nor laying more bloom light on any part of it.
      expect(bloomLight(zoom)).toBeLessThan(bloomLight(DESKTOP) * 1.1);
    }
  });

  it('keeps the drawn bloom’s reach across the country at every zoom below 4, and meets zoom 4 without a jump', () => {
    for (const t of [1, 2]) {
      const desktop = share(drawnBloomPx(DESKTOP, t), DESKTOP);
      // Down to where the blend stops shrinking, at 2 px (zoom 3): below, it reaches farther.
      for (let zoom = 3; zoom < FULL_SIZE_ZOOM; zoom += 1 / 16) {
        const ratio = share(drawnBloomPx(zoom, t), zoom) / desktop;
        expect(ratio).toBeGreaterThan(0.9);
        expect(ratio).toBeLessThan(1.15);
      }
    }
    // A browser zoomed out gives light targets between powers of two.
    for (const t of [0.8, 0.9, 1, 2]) {
      const below = bloomLevels(glowStyleAtZoom(FULL_SIZE_ZOOM - 1e-9), t, 2000);
      const at = bloomLevels(glowStyleAtZoom(FULL_SIZE_ZOOM), t, 2000);
      expect(below).toHaveLength(at.length);
      below.forEach((weight, i) => {
        expect(weight).toBeCloseTo(at[i] ?? 0, 6);
      });
    }
    expect(glowStyleAtZoom(FULL_SIZE_ZOOM - 1e-9).gain).toBeCloseTo(
      glowStyleAtZoom(FULL_SIZE_ZOOM).gain,
      6,
    );
  });

  it('shrinks the blend with the map, but not below 2 px, where points would read as dots', () => {
    const desktop = glowStyleAtZoom(DESKTOP);
    const desktopHalo = fallbackHalo(desktop, DESKTOP).radiusPx / desktop.blendSigmaPx;
    for (const zoom of SMALL_SCREENS) {
      const style = glowStyleAtZoom(zoom);
      const sigma = Math.max(desktop.blendSigmaPx * style.sizeScale, BLEND_MIN_SIGMA_PX);
      expect(style.blendSigmaPx).toBeCloseTo(sigma, 12);
      // As drawn, before its floor, on a light target of two pixels per CSS pixel: half a lone
      // point's blend within 1.18 sigma of it, give or take half a CSS pixel.
      const t = 2;
      const all = compositeLight([[128, 128]], { ...style, floorGain: 1 }, SIZE, t);
      const bloomOnly = compositeLight([[128, 128]], { ...style, blend: 0 }, SIZE, t);
      const blend = (r: number): number =>
        (all[128 * SIZE + 128 + r] ?? 0) - (bloomOnly[128 * SIZE + 128 + r] ?? 0);
      const half = Math.round(1.1774 * sigma * t);
      expect(blend(half - 1) / blend(0)).toBeGreaterThan(0.5);
      expect(blend(half + 1) / blend(0)).toBeLessThan(0.5);
      // The 8-bit fallback's halo, which carries the blend, shrinks with it, not with the map.
      expect(fallbackHalo(style, zoom).radiusPx / style.blendSigmaPx).toBeCloseTo(desktopHalo, 12);
    }
  }, 30_000);

  it('leaves every value from zoom 4 up as the stops give it', () => {
    for (let zoom = FULL_SIZE_ZOOM; zoom <= 16; zoom += 1 / 8) {
      const style = glowStyleAtZoom(zoom);
      expect(style.sizeScale).toBe(1);
      expect(style.coreSigmaPx).toBe(interpolateStops(CORE_SIGMA_STOPS, zoom));
      expect(style.gain).toBe(interpolateStops(GAIN_STOPS, zoom));
      expect(style.haloRadiusPx).toBe(interpolateStops(HALO_RADIUS_STOPS, zoom));
      expect(style.haloEnergy).toBe(interpolateStops(HALO_ENERGY_STOPS, zoom));
      expect(style.bloom).toEqual(bloomWeights(zoom));
      if (zoom >= FLOOR_FADE[1]) {
        expect(style.floorGain).toBe(1);
        expect(fallbackFloor(style, zoom).gain).toBe(1);
      }
      const fallback = fallbackHalo(style, zoom);
      if (style.bloom.some((w) => w > 0)) {
        expect(fallback.radiusPx).toBe(
          Math.max(style.haloRadiusPx, interpolateStops(FALLBACK_HALO_RADIUS_STOPS, zoom)),
        );
      }
    }
  });

  it('keeps a lone school well in view far out, over the state lines each screen draws', () => {
    // Its brightest pixel as displayed, 0..255, on the float path and the 8-bit fallback:
    // nationally its blend, which carries its core's light, on its floor; regionally its core too.
    const views: [zoom: number, line: number][] = [
      ...SMALL_SCREENS.map((zoom): [number, number] => [
        zoom,
        PHONES.includes(zoom) ? PHONE_STATE_LINE : STATE_LINE,
      ]),
      // A desktop's national view and a phone's, zoomed in, until the cores are in.
      ...[4, 4.03, 4.25, 4.5, 4.75, 5, 5.25, 5.5].map((zoom): [number, number] => [
        zoom,
        STATE_LINE,
      ]),
      ...[2.5, 3, 3.5, 4, 4.5, 4.75, 5, 5.25, 5.5].map((zoom): [number, number] => [
        zoom,
        PHONE_STATE_LINE,
      ]),
    ];
    for (const [zoom, line] of views) {
      const style = glowStyleAtZoom(zoom, line / 255);
      expect(style.coreSigmaPx).toBe(interpolateStops(CORE_SIGMA_STOPS, zoom));
      const k = kernelUniforms(style, 1, fallbackHalo(style, zoom), style.coreShare);
      const floor = fallbackFloor(style, zoom);
      const fallback = displayed(blendFloor(style.gain * kernelAt(k, 0), floor.gain, floor.knee));
      for (const t of [1, 1.5, 2, 3]) {
        for (const peak of [displayed(lonePoint(zoom, t, line / 255)(0)), fallback]) {
          // A fifth brighter than the state lines around it, at least: a phone's are brighter.
          expect(peak).toBeGreaterThan(1.2 * line);
        }
      }
    }
  }, 120_000);

  it('shows every field of schools on a phone at least as brightly as a lone school, and a denser one never dimmer', () => {
    // Without the floor a field of schools 60 to 130 km apart showed at a quarter to a third of
    // a lone school, under a phone's state lines: its closings faded out of view.
    const phone = PHONE_STATE_LINE / 255;
    for (const zoom of [1.51, 2.12]) {
      for (const t of [1, 2, 3]) {
        const lone = fieldPeakShown(zoom, null, t, phone);
        let sparser = lone;
        for (const km of [130, 90, 60, 40, 25]) {
          const field = fieldPeakShown(zoom, km, t, phone);
          // Within half a display step.
          expect(field).toBeGreaterThanOrEqual(lone - 0.5);
          expect(field).toBeGreaterThanOrEqual(sparser - 0.5);
          expect(field).toBeGreaterThan(1.2 * PHONE_STATE_LINE);
          sparser = field;
        }
      }
    }
  }, 120_000);

  it('lights a field of schools on a small screen as brightly as on a desktop, so a band’s dense middle keeps its color against its sparse edge', () => {
    // Without the cut a phone's field of schools 15 km apart was near the tone map's top.
    for (const t of [1, 2]) {
      const desktop = fieldPeakShown(DESKTOP, 15, t);
      for (const [zoom, line] of [
        [1.51, PHONE_STATE_LINE],
        [2.12, PHONE_STATE_LINE],
        [3.14, STATE_LINE],
      ] as const) {
        for (const screen of [t, 3]) {
          const field = fieldPeakShown(zoom, 15, screen, line / 255);
          expect(field).toBeGreaterThan(0.93 * desktop);
          expect(field).toBeLessThan(1.07 * desktop);
        }
      }
    }
    for (let zoom = FULL_SIZE_ZOOM; zoom <= 22; zoom += 0.25) {
      expect(blendCutAtScale(glowStyleAtZoom(zoom).sizeScale)).toBe(1);
    }
  }, 120_000);

  it('lights no farther past the last school of a field than its own light or a lone school’s reaches', () => {
    /** Farthest px right of x = 128, the last column of schools or a lone school, shown at 16 of 255 or more. */
    const reach = (light: Float64Array): number => {
      let far = 0;
      for (let x = 128; x < SIZE; x++)
        if (displayed(light[128 * SIZE + x] ?? 0) >= 16) far = x - 128;
      return far;
    };
    for (const [zoom, line] of [
      [1.51, PHONE_STATE_LINE],
      [2.12, PHONE_STATE_LINE],
      [3.14, STATE_LINE],
      [4.03, STATE_LINE],
    ] as const) {
      const style = glowStyleAtZoom(zoom, line / 255);
      const lone = reach(compositeLight([[128, 128.5]], style, SIZE));
      for (const km of [15, 60]) {
        const spacing = km / kmPerPx(zoom);
        const points: [number, number][] = [];
        for (let y = 28; y <= 228; y += spacing) {
          for (let x = 128; x >= 18; x -= spacing) points.push([x, y + 0.5]);
        }
        const floored = reach(compositeLight(points, style, SIZE));
        const own = reach(compositeLight(points, { ...style, floorGain: 1 }, SIZE));
        expect(floored).toBeLessThanOrEqual(Math.max(own, lone) + 1);
      }
    }
    for (let zoom = FLOOR_FADE[1]; zoom <= 22; zoom += 0.25) {
      expect(glowStyleAtZoom(zoom, PHONE_STATE_LINE / 255).floorGain).toBe(1);
    }
  }, 60_000);
});

describe('per-point kernel', () => {
  it('is brightest at the point and reaches zero at the sprite edge', () => {
    for (const zoom of [4, 8, 10]) {
      const k = kernelUniforms(glowStyleAtZoom(zoom), 0.5);
      expect(kernelAt(k, 0)).toBeCloseTo(k.coreWeight + k.haloWeight, 12);
      expect(kernelAt(k, 1)).toBe(0);
      let previous = Infinity;
      for (let d = 0; d < 1; d += 0.01) {
        const value = kernelAt(k, d);
        expect(value).toBeLessThanOrEqual(previous);
        previous = value;
      }
    }
  });

  it('fades the core to zero at the sprite edge with no step', () => {
    const k = kernelUniforms(glowStyleAtZoom(4), 1);
    expect(kernelAt(k, 0.999)).toBeLessThan(1e-6 * k.coreWeight);
    // Within the inner three quarters the core is an untouched Gaussian.
    expect(kernelAt(k, 0.5)).toBeCloseTo(k.coreWeight * Math.exp(-0.25 * k.coreFalloff), 12);
  });

  it('widens a sub-pixel core for the pixel footprint without changing its light', () => {
    const style = glowStyleAtZoom(4);
    const fine = kernelUniforms(style, 8); // 8 target px per CSS px: footprint negligible
    const coarse = kernelUniforms(style, 0.5);
    expect(coarse.coreWeight).toBeLessThan(fine.coreWeight);
    // Core light, in CSS px^2: kernel energy x (sprite radius / target px per CSS px)^2.
    const coreOnly = (k: typeof fine) => (d: number) =>
      k.coreWeight * Math.exp(-d * d * k.coreFalloff) * (1 - smoothstep(CORE_EDGE_D2, 1, d * d));
    const fineLight = energy(coreOnly(fine)) * (fine.radius / 8) ** 2;
    const coarseLight = energy(coreOnly(coarse)) * (coarse.radius / 0.5) ** 2;
    expect(coarseLight / fineLight).toBeCloseTo(1, 2);
  });

  it('gives the halo haloEnergy times the light of the core', () => {
    const style = glowStyleAtZoom(12);
    const k = kernelUniforms({ ...style, glyphOpacity: 0 }, 1);
    const core = energy(
      (d) =>
        k.coreWeight * Math.exp(-d * d * k.coreFalloff) * (1 - smoothstep(CORE_EDGE_D2, 1, d * d)),
    );
    const halo = energy((d) => kernelAt(k, d)) - core;
    // The core sprite stops at three standard deviations and loses about 1% of its light.
    expect(halo / core).toBeCloseTo(style.haloEnergy, 1);
    expect(Math.abs(halo / core / style.haloEnergy - 1)).toBeLessThan(0.02);
  });

  it('leaves a glyph center dark at glyph zoom: no core, halo cut away inside the glyph', () => {
    const style = glowStyleAtZoom(13);
    const k = kernelUniforms(style, 0.5);
    expect(k.coreWeight).toBe(0);
    expect(k.hole).toBeGreaterThan(0);
    expect(kernelAt(k, 0)).toBe(0);
    expect(kernelAt(k, k.hole * 0.7)).toBe(0);
    expect(kernelAt(k, k.hole * 1.3)).toBeGreaterThan(0);
  });
});

describe('windowed halo integral', () => {
  it('matches numerical integration', () => {
    for (const a of [0.0001, 0.5, 3.86, 20]) {
      const steps = 20000;
      let sum = 0;
      for (let i = 0; i < steps; i++) {
        const u = (i + 0.5) / steps;
        sum += (Math.exp(-a * u) * (1 - u) ** 2) / steps;
      }
      expect(windowedGaussianIntegral(a)).toBeCloseTo(sum, 7);
    }
  });
});

describe('fade-in pulse', () => {
  it('starts dark, swells once, and settles at exactly 1', () => {
    expect(pulseAt(-0.1)).toEqual({ intensity: 0, radius: 1 });
    expect(pulseAt(0).intensity).toBe(0);
    expect(pulseAt(PULSE_SECONDS)).toEqual({ intensity: 1, radius: 1 });
    expect(pulseAt(PULSE_SECONDS * 0.999).intensity).toBeCloseTo(1, 3);
    const samples = Array.from(
      { length: 400 },
      (_, i) => pulseAt((i / 400) * PULSE_SECONDS).intensity,
    );
    const peak = Math.max(...samples);
    expect(peak).toBeGreaterThan(1.2);
    // One swell: rising to the peak, then falling back, with no second hump.
    const top = samples.indexOf(peak);
    for (let i = 1; i <= top; i++) expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1] ?? 0);
    for (let i = top + 1; i < samples.length; i++) {
      expect(samples[i]).toBeLessThanOrEqual((samples[i - 1] ?? 0) + 1e-12);
    }
  });
});

describe('bloom source knee', () => {
  it('passes light up to the knee untouched', () => {
    for (const total of [0, 1e-6, 0.5, 4, BLOOM_KNEE]) expect(bloomSourceScale(total)).toBe(1);
  });

  it('eases light past the knee smoothly, always rising, and never past the limit', () => {
    let previous = 0;
    for (let total = 0.01; total < 1e6; total *= 1.05) {
      const fed = total * bloomSourceScale(total);
      expect(fed).toBeGreaterThanOrEqual(previous);
      expect(fed).toBeLessThan(BLOOM_LIMIT);
      previous = fed;
    }
    expect(1024 * bloomSourceScale(1024)).toBeGreaterThan(BLOOM_LIMIT * 0.97);
    // Slope 1 on both sides of the knee: no crease in the bloom.
    const h = 1e-6;
    const fed = (t: number): number => t * bloomSourceScale(t);
    expect((fed(BLOOM_KNEE + h) - fed(BLOOM_KNEE)) / h).toBeCloseTo(1, 4);
  });

  it('shares its constants with the GLSL source', () => {
    expect(BLOOM_SOURCE_GLSL).toContain(`GLOW_BLOOM_KNEE = ${BLOOM_KNEE.toFixed(1)}`);
    expect(BLOOM_SOURCE_GLSL).toContain(`GLOW_BLOOM_LIMIT = ${BLOOM_LIMIT.toFixed(1)}`);
  });
});

describe('8-bit fallback encoding', () => {
  const alphas = [3, 7, 9, 11, 14].map((z) => interpolateStops(FALLBACK_ALPHA_STOPS, z));

  it('screen blending adds light: 1 - (1 - a)(1 - b) encodes the sum', () => {
    const alpha = alphas[0] ?? 1;
    const enc = (light: number): number => 1 - Math.exp(-light * alpha);
    for (const [a, b] of [
      [0.01, 0.02],
      [0.5, 1.5],
      [3, 4],
    ] as const) {
      expect(1 - (1 - enc(a)) * (1 - enc(b))).toBeCloseTo(enc(a + b), 12);
    }
  });

  it('shows light from a faint halo to a dense core within a display step, or 1.5% if brighter', () => {
    // What the viewer sees: status light, tone mapped and sRGB encoded, in 8-bit steps.
    const tokens = STATUS_HEX.slice(0, 4).map(hexToLinear);
    const display = (light: number, status: number): number[] => {
      const perStatus: [number, number, number, number] = [0, 0, 0, 0];
      perStatus[status] = light;
      return toneMap(statusLight(perStatus, tokens)).map((c) => linearToSrgb(c) * 255);
    };
    let checked = 0;
    for (const alpha of alphas) {
      // Up to 3 / alpha: 4.6 at national zoom, past 99% of lit pixels in the 30,000-point bench.
      // Past it the coarse target's steps widen until its top step, at 6.2 / alpha.
      for (let light = 0.0002; light < 3 / alpha; light *= 1.01) {
        const [coarse, fine] = fallbackEncode(light, alpha);
        const decoded = fallbackDecode(coarse, fine, alpha);
        for (const status of [0, 1, 2, 3]) {
          const want = display(light, status);
          const got = display(decoded, status);
          got.forEach((channel, i) => {
            const target = want[i] ?? 0;
            expect(Math.abs(channel - target)).toBeLessThan(Math.max(1, 0.015 * target));
          });
          checked++;
        }
      }
    }
    expect(checked).toBeGreaterThan(5000);
  });

  it('decodes a saturated channel to the most light it can hold, not to infinity', () => {
    const alpha = alphas[0] ?? 1;
    const top = fallbackDecode(255, 255, alpha);
    expect(top).toBeCloseTo(-Math.log(FALLBACK_MIN_TRANSMITTANCE) / alpha, 9);
    expect(fallbackDecode(0, 0, alpha)).toBeCloseTo(0, 12);
    expect(FALLBACK_GLSL).toContain(`GLOW_FALLBACK_FINE_GAIN = ${FALLBACK_FINE_GAIN.toFixed(1)}`);
  });

  it('gives each point a halo carrying the bloom that mostly falls inside it, and the blend', () => {
    const national = glowStyleAtZoom(4);
    const halo = fallbackHalo(national, 4);
    const folded = national.bloom.reduce((sum, w, i) => sum + w * (FALLBACK_BLOOM_FOLD[i] ?? 0), 0);
    expect(halo.energy).toBeCloseTo(national.haloEnergy + folded + national.blend, 12);
    expect(halo.energy).toBeGreaterThan(0.5 * national.bloom.reduce((a, b) => a + b, 0));
    // From zoom 11 there is no bloom to fold: the fallback halo is the float path's own.
    const street = glowStyleAtZoom(13);
    expect(fallbackHalo(street, 13)).toEqual({
      energy: street.haloEnergy,
      sigmaShare: HALO_SIGMA_SHARE,
      radiusPx: street.haloRadiusPx,
    });
    // Never narrower than the float path's own halo.
    for (let zoom = 3; zoom <= 16; zoom += 0.5) {
      const style = glowStyleAtZoom(zoom);
      expect(fallbackHalo(style, zoom).radiusPx).toBeGreaterThanOrEqual(style.haloRadiusPx);
    }
    const k = kernelUniforms(national, 1, halo);
    expect(k.haloWeight).toBeGreaterThan(0);
  });
});
