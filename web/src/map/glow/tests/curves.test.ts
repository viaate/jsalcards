import { describe, expect, it } from 'vitest';

import { STATUS_HEX, hexToLinear, linearToSrgb } from '../color';

import {
  BLEND_LEVEL_PX,
  BLEND_LIFT,
  BLEND_MIN_SIGMA_PX,
  BLOOM_KNEE,
  BLOOM_LIMIT,
  BLOOM_SCALES_PX,
  BLOOM_SOURCE_GLSL,
  BLOOM_WEIGHT_STOPS,
  CORE_EDGE_D2,
  CORE_SIGMA_STOPS,
  FALLBACK_ALPHA_STOPS,
  FALLBACK_BLOOM_FOLD,
  FALLBACK_FINE_GAIN,
  FALLBACK_GLSL,
  FALLBACK_HALO_RADIUS_STOPS,
  FALLBACK_MIN_TRANSMITTANCE,
  FULL_SIZE_ZOOM,
  GAIN_STOPS,
  type GlowFrameStyle,
  HALO_ENERGY_STOPS,
  HALO_RADIUS_STOPS,
  HALO_SIGMA_SHARE,
  GLYPH_FADE_END,
  GLYPH_FADE_START,
  MIN_BLOOM_WEIGHT,
  POINT_SHARE_STOPS,
  PULSE_SECONDS,
  blendLiftFactor,
  blendPlan,
  blendShareOfScale,
  bloomLevels,
  bloomPlan,
  bloomSourceScale,
  bloomWeights,
  fallbackDecode,
  fallbackEncode,
  fallbackHalo,
  glowReachPx,
  glowStyleAtZoom,
  interpolateStops,
  kernelAt,
  kernelUniforms,
  liftReachPx,
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
    for (const reach of national) expect(reach).toBeGreaterThan(40);
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

/** Light the composite shows `r` px right of a lone point in the middle of a light target. */
function lonePoint(zoom: number): (r: number) => number {
  const light = compositeLight([[128.5, 128.5]], glowStyleAtZoom(zoom), SIZE);
  return (r) => light[128 * SIZE + 128 + r] ?? 0;
}

/** Farthest distance at which `light` shows above `level` of 255, CSS px. */
function reachAbove(light: (r: number) => number, level: number): number {
  let reach = 0;
  for (let r = 0; r < SIZE / 2; r++) if (displayed(light(r)) > level) reach = r;
  return reach;
}

/** Brightest and dimmest displayed value over the middle of a square grid of points. */
function gridRange(zoom: number, spacing: number): [min: number, max: number] {
  const points: [number, number][] = [];
  for (let y = 128 - 72; y <= 128 + 72; y += spacing) {
    for (let x = 128 - 72; x <= 128 + 72; x += spacing) points.push([x + 0.3, y + 0.6]);
  }
  const light = compositeLight(points, glowStyleAtZoom(zoom), SIZE);
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
  it('shows no core up to zoom 6 and every core from zoom 8, more of them at each step between', () => {
    for (let zoom = 2; zoom <= 6; zoom += 0.25) {
      const style = glowStyleAtZoom(zoom);
      expect(style.coreShare).toBe(0);
      expect(style.blend).toBeGreaterThan(1);
    }
    let previous = 0;
    for (let zoom = 6.25; zoom < 8; zoom += 0.25) {
      const share = glowStyleAtZoom(zoom).coreShare;
      expect(share).toBeGreaterThan(previous);
      expect(share - previous).toBeLessThan(0.15);
      previous = share;
    }
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
      // Below zoom 4 the bloom's light is cut by more than the cores' (glowSizeScale).
      expect(shown).toBeCloseTo(1 + style.sizeScale ** 1.5 * own, 12);
    }
  });

  it('turns a lone point at national zoom into soft light that never vanishes', () => {
    for (const zoom of [2.12, 3, 3.14, 4, 5, 5.6, 6]) {
      const light = lonePoint(zoom);
      // No speck: 4 px out the light is still above half its peak, where a core's is 2% of it.
      // Below zoom 4 the blend shrinks with the map down to 3 px, and the probe with it.
      const out = Math.min(4, Math.round(glowStyleAtZoom(zoom).blendSigmaPx));
      expect(light(0) / light(out)).toBeLessThan(1.7);
      expect(displayed(light(0))).toBeGreaterThan(20);
    }
    // From zoom 8 a school is a point of its own again.
    const street = lonePoint(9);
    expect(street(0) / street(4)).toBeGreaterThan(10);
  }, 30_000);

  it('merges schools about 15 km apart into one even field', () => {
    for (const zoom of [2.12, 3, 4, 5, 5.6, 6]) {
      const spacing = Math.max(4, Math.round(15 / kmPerPx(zoom)));
      const [min, max] = gridRange(zoom, spacing);
      // Regionally each school keeps a quiet soft point on the field (POINT_SHARE_STOPS): at
      // zoom 6, a step before the cores come back, schools 16 px apart ripple it by 15%.
      const ripple = 0.05 + 0.6 * interpolateStops(POINT_SHARE_STOPS, zoom);
      expect((max - min) / max).toBeLessThan(ripple);
    }
    // Where the cores show, the same schools are points in a darker field.
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

  it('adds no pass nationally and blurs a finely sampled level beyond', () => {
    for (let zoom = FULL_SIZE_ZOOM; zoom <= 4.5; zoom += 0.125) {
      expect(blendPlan(glowStyleAtZoom(zoom), 1).radius).toBe(0);
    }
    // Below zoom 4, where the blend shrinks under the 4 px level's own spread: a short blur of
    // the 2 px level, a quarter of the light target, whatever the point count.
    for (let zoom = 1.5; zoom < FULL_SIZE_ZOOM; zoom += 0.125) {
      const small = blendPlan(glowStyleAtZoom(zoom), 1);
      expect(small.level).toBe(1);
      expect(small.radius).toBeGreaterThan(0);
      expect(small.radius).toBeLessThanOrEqual(6);
    }
    const plan = blendPlan(glowStyleAtZoom(6), 1);
    expect(2 ** plan.level).toBe(BLEND_LEVEL_PX);
    expect(plan.sigmaTexels).toBeGreaterThan(2);
    expect(plan.radius).toBe(Math.ceil(3 * plan.sigmaTexels));
    // The same level in CSS px on a light target of two pixels per CSS px.
    expect(2 ** blendPlan(glowStyleAtZoom(6), 2).level / 2).toBe(BLEND_LEVEL_PX);
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
      expect(fallback(0) / fallback(4)).toBeLessThan(1.7);
      expect(displayed(fallback(0))).toBeGreaterThan(0.9 * displayed(float(0)));
      expect(displayed(fallback(0))).toBeLessThan(1.5 * displayed(float(0)));
    }
  });

  it('leaves zoom 8 and up as it was', () => {
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
      const { sizeScale, coreShare, blend, blendSigmaPx, blendLift, ...rest } = style;
      expect([sizeScale, coreShare, blend, blendLift]).toEqual([1, 1, 0, 0]);
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
  const bloomInBlend = (style: GlowFrameStyle): number => style.blend - (1 - style.coreShare);

  /**
   * Energy-weighted RMS spread of the bloom levels and the blend the layer
   * draws (bloomPlan), each level at its texel size and the blend at its own,
   * CSS px, for a light target of `targetPxPerCss`.
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
      // Down to where the blend stops shrinking, at 3 px (zoom 3.58): below, it reaches farther.
      for (let zoom = 3.6; zoom < FULL_SIZE_ZOOM; zoom += 1 / 16) {
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

  it('shrinks the blend with the map, but not below 3 px, where points would read as dots', () => {
    const desktop = glowStyleAtZoom(DESKTOP);
    const desktopHalo = fallbackHalo(desktop, DESKTOP).radiusPx / desktop.blendSigmaPx;
    for (const zoom of SMALL_SCREENS) {
      const style = glowStyleAtZoom(zoom);
      const sigma = Math.max(desktop.blendSigmaPx * style.sizeScale, BLEND_MIN_SIGMA_PX);
      expect(style.blendSigmaPx).toBeCloseTo(sigma, 12);
      // As drawn, before a phone's lift: half a lone point's blend within 1.18 sigma of it,
      // give or take a pixel.
      const all = compositeLight([[128.5, 128.5]], { ...style, blendLift: 0 }, SIZE);
      const bloomOnly = compositeLight([[128.5, 128.5]], { ...style, blend: 0 }, SIZE);
      const blend = (r: number): number =>
        (all[128 * SIZE + 128 + r] ?? 0) - (bloomOnly[128 * SIZE + 128 + r] ?? 0);
      const half = Math.round(1.1774 * sigma);
      expect(blend(half - 1) / blend(0)).toBeGreaterThan(0.5);
      expect(blend(half + 1) / blend(0)).toBeLessThan(0.5);
      // The 8-bit fallback's halo, which carries the blend, shrinks with it, not with the map:
      // on a phone 15 px, where the bloom alone would have it at 5.
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
      expect(style.blendLift).toBe(0);
      const fallback = fallbackHalo(style, zoom);
      if (style.bloom.some((w) => w > 0)) {
        expect(fallback.radiusPx).toBe(
          Math.max(style.haloRadiusPx, interpolateStops(FALLBACK_HALO_RADIUS_STOPS, zoom)),
        );
      }
    }
  });

  it('keeps a lone school well in view on small screens, even at their widest zoom', () => {
    // Its brightest pixel as displayed, 0..255, on a light target of one pixel per CSS pixel,
    // on the float path and the 8-bit fallback: nationally its blend, which carries its core's
    // light, lifted on a phone where no other light is near.
    const desktop = displayed(lonePoint(DESKTOP)(0));
    for (const zoom of SMALL_SCREENS) {
      const style = glowStyleAtZoom(zoom);
      expect(style.coreSigmaPx).toBe(interpolateStops(CORE_SIGMA_STOPS, zoom));
      const k = kernelUniforms(style, 1, fallbackHalo(style, zoom), style.coreShare);
      const light = style.gain * kernelAt(k, 0);
      const around = style.gain * kernelAt(k, liftReachPx(style) / k.radius);
      const fallback = displayed(light * blendLiftFactor(around, style.blendLift));
      for (const peak of [displayed(lonePoint(zoom)(0)), fallback]) {
        expect(peak).toBeGreaterThan(0.5 * desktop);
        // A fifth brighter than the state lines around it, at least: a phone's are brighter.
        // One between light pixels peaks a little lower on screen.
        const line = PHONES.includes(zoom) ? PHONE_STATE_LINE : STATE_LINE;
        expect(peak).toBeGreaterThan(1.2 * line);
      }
    }
  }, 30_000);

  it('lifts only schools far from others: a field or a band keeps its light and its reach', () => {
    for (const zoom of [1.51, 2.12]) {
      const style = glowStyleAtZoom(zoom);
      // Schools 15 km and 60 km apart filling the left half of the light target.
      for (const km of [15, 60]) {
        const spacing = km / kmPerPx(zoom);
        const points: [number, number][] = [];
        for (let y = 28; y <= 228; y += spacing) {
          for (let x = 18; x <= 128; x += spacing) points.push([x + 0.3, y + 0.6]);
        }
        const lifted = compositeLight(points, style, SIZE);
        const plain = compositeLight(points, { ...style, blendLift: 0 }, SIZE);
        for (let x = 50; x < 90; x += 5) {
          const at = 128 * SIZE + x;
          expect(displayed(lifted[at] ?? 0) - displayed(plain[at] ?? 0)).toBeLessThan(1);
        }
        // Nor does the light past its last schools reach farther.
        const edge = (light: Float64Array): number => {
          let reach = 0;
          for (let x = 128; x < SIZE; x++)
            if (displayed(light[128 * SIZE + x] ?? 0) >= 16) reach = x;
          return reach;
        };
        expect(edge(lifted)).toBeLessThanOrEqual(edge(plain) + 1);
      }
    }
    // No lift from a tablet's national view up.
    for (let zoom = 3.3; zoom <= 22; zoom += 0.25) expect(glowStyleAtZoom(zoom).blendLift).toBe(0);
    expect(glowStyleAtZoom(3.14).blendLift).toBeLessThan(0.1 * BLEND_LIFT);
  }, 30_000);
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
