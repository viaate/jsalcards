import { describe, expect, it } from 'vitest';

import { STATUS_HEX, hexToLinear, linearToSrgb } from '../color';

import {
  BLOOM_KNEE,
  BLOOM_LIMIT,
  BLOOM_SCALES_PX,
  BLOOM_SOURCE_GLSL,
  CORE_EDGE_D2,
  FALLBACK_ALPHA_STOPS,
  FALLBACK_BLOOM_FOLD,
  FALLBACK_FINE_GAIN,
  FALLBACK_GLSL,
  FALLBACK_MIN_TRANSMITTANCE,
  HALO_SIGMA_SHARE,
  GLYPH_FADE_END,
  GLYPH_FADE_START,
  PULSE_SECONDS,
  bloomSourceScale,
  bloomWeightAtScale,
  bloomWeights,
  fallbackDecode,
  fallbackEncode,
  fallbackHalo,
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
    const national = [3, 4, 5, 6].map(glowReachPx);
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
    expect(bloomWeights(4).reduce((a, b) => a + b)).toBeGreaterThan(1.5);
    expect(bloomWeights(11).every((w) => w === 0)).toBe(true);
    expect(bloomWeights(15).every((w) => w === 0)).toBe(true);
    // The widest scales fade first as the map zooms in.
    const last = BLOOM_SCALES_PX.length - 1;
    expect(bloomWeights(9)[last]).toBeLessThan(bloomWeights(6)[last] ?? 0);
  });

  it('reads bloom weights by CSS-pixel scale, independent of target resolution', () => {
    const weights = bloomWeights(5);
    BLOOM_SCALES_PX.forEach((scale, i) => {
      expect(bloomWeightAtScale(weights, scale)).toBeCloseTo(weights[i] ?? 0, 12);
    });
    expect(bloomWeightAtScale(weights, 2)).toBe(0);
    expect(bloomWeightAtScale(weights, 128)).toBe(0);
    const between = bloomWeightAtScale(weights, Math.SQRT2 * 8);
    expect(between).toBeCloseTo(((weights[1] ?? 0) + (weights[2] ?? 0)) / 2, 12);
  });

  it('fades glyphs in between zoom 10.5 and 11', () => {
    expect(glowStyleAtZoom(GLYPH_FADE_START - 0.01).glyphOpacity).toBe(0);
    expect(glowStyleAtZoom(GLYPH_FADE_END).glyphOpacity).toBe(1);
    const mid = glowStyleAtZoom((GLYPH_FADE_START + GLYPH_FADE_END) / 2).glyphOpacity;
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1);
  });
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

  it('gives each point a halo carrying the bloom that mostly falls inside it', () => {
    const national = glowStyleAtZoom(4);
    const halo = fallbackHalo(national, 4);
    const folded = national.bloom.reduce((sum, w, i) => sum + w * (FALLBACK_BLOOM_FOLD[i] ?? 0), 0);
    expect(halo.energy).toBeCloseTo(national.haloEnergy + folded, 12);
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
