import { describe, expect, it } from 'vitest';

import {
  GlowStatus,
  LUMA,
  STATUS_HEX,
  type Rgb,
  hexToLinear,
  hexToSrgb,
  linearToSrgb,
  luminance,
  srgbToLinear,
  statusLinearUniform,
  statusSrgbUniform,
} from '../color';
import {
  PEAK_LUMINANCE,
  STATUS_DOMINANCE,
  TONEMAP_GLSL,
  reinhardLuminance,
  statusLight,
  toneMap,
} from '../tonemap';

const scale = ([r, g, b]: Rgb, k: number): Rgb => [r * k, g * k, b * k];
const add = (a: Rgb, b: Rgb): Rgb => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const max3 = ([r, g, b]: Rgb): number => Math.max(r, g, b);
const min3 = ([r, g, b]: Rgb): number => Math.min(r, g, b);

const CLOSED = hexToLinear(STATUS_HEX[GlowStatus.Closed]);
const DELAYED = hexToLinear(STATUS_HEX[GlowStatus.Delayed]);
const REMOTE = hexToLinear(STATUS_HEX[GlowStatus.Remote]);
const EARLY = hexToLinear(STATUS_HEX[GlowStatus.EarlyDismissal]);
const GLOWING = [CLOSED, DELAYED, REMOTE, EARLY];

describe('status tokens', () => {
  it('are exactly the design spec colors', () => {
    expect(STATUS_HEX).toEqual(['#7FD4FF', '#FFC46B', '#B79CFF', '#6BFFB0', '#6B6B6B']);
    expect(hexToSrgb('#7FD4FF')).toEqual([127 / 255, 212 / 255, 1]);
  });

  it('decode with the exact sRGB curve and encode back to the same 8-bit value', () => {
    expect(srgbToLinear(0.5)).toBeCloseTo(0.214041, 6);
    expect(srgbToLinear(0.04045)).toBeCloseTo(0.04045 / 12.92, 12);
    for (let v = 0; v <= 255; v++) {
      expect(Math.round(linearToSrgb(srgbToLinear(v / 255)) * 255)).toBe(v);
    }
  });

  it('fill the shader uniforms in status order, linear for light and sRGB for glyphs', () => {
    const linear = statusLinearUniform();
    const srgb = statusSrgbUniform();
    STATUS_HEX.forEach((hex, i) => {
      const [lr, lg, lb] = hexToLinear(hex);
      expect(Array.from(linear.subarray(i * 3, i * 3 + 3))).toEqual([lr, lg, lb].map(Math.fround));
      expect(Array.from(srgb.subarray(i * 3, i * 3 + 3))).toEqual(hexToSrgb(hex).map(Math.fround));
    });
  });
});

describe('per-status light to color (JS mirror of the composite shader)', () => {
  const tokens = GLOWING;

  it('gives a lone status its own token hue at the gathered brightness', () => {
    tokens.forEach((token, i) => {
      const light: [number, number, number, number] = [0, 0, 0, 0];
      light[i] = 2.5;
      const rgb = statusLight(light, tokens);
      rgb.forEach((channel, c) => {
        expect(channel).toBeCloseTo((token[c] ?? 0) * 2.5, 12);
      });
    });
    expect(statusLight([0, 0, 0, 0], tokens)).toEqual([0, 0, 0]);
  });

  it('keeps the total light and lets the leading status set the hue', () => {
    const rgb = statusLight([3, 1, 0, 0], tokens);
    // Weights go as light squared: 9/10 closed, 1/10 delayed.
    const expected = add(scale(CLOSED, 0.9 * 4), scale(DELAYED, 0.1 * 4));
    rgb.forEach((channel, c) => {
      expect(channel).toBeCloseTo(expected[c] ?? 0, 12);
    });
    expect(STATUS_DOMINANCE).toBe(2);
  });

  it('mixes equal parts evenly', () => {
    const rgb = statusLight([1, 1, 1, 1], tokens);
    const mean = tokens.reduce<Rgb>((acc, t) => add(acc, scale(t, 1)), [0, 0, 0]);
    rgb.forEach((channel, c) => {
      expect(channel).toBeCloseTo(mean[c] ?? 0, 12);
    });
  });
});

describe('tone map (JS mirror of the composite shader)', () => {
  /** Light levels from a lone speck's faint halo to a pile of thousands of points. */
  const LEVELS = [1e-4, 0.003, 0.05, 0.3, 1, 2, 5, 20, 300, 1e6];
  /** Tokens, their mixes and near-neutral light: everything the composite can hand the curve. */
  const COLORS: Rgb[] = [
    ...GLOWING,
    add(CLOSED, DELAYED),
    add(REMOTE, EARLY),
    add(add(CLOSED, DELAYED), add(REMOTE, EARLY)),
    [1, 1, 1],
    [0, 0, 1],
  ];

  it('maps no light to black', () => {
    expect(toneMap([0, 0, 0])).toEqual([0, 0, 0]);
  });

  it('is Reinhard on luminance: output luminance is L / (1 + L / peak) for every color', () => {
    expect(reinhardLuminance(0)).toBe(0);
    expect(reinhardLuminance(PEAK_LUMINANCE)).toBeCloseTo(PEAK_LUMINANCE / 2, 12);
    for (const color of COLORS) {
      for (const k of LEVELS) {
        const light = scale(color, k);
        const expected = luminance(light) / (1 + luminance(light) / PEAK_LUMINANCE);
        expect(luminance(toneMap(light)) / expected).toBeCloseTo(1, 9);
      }
    }
  });

  it('scales all channels alike while the color stays in gamut, so hue and saturation hold', () => {
    for (const color of GLOWING) {
      for (const k of [1e-4, 0.05, 0.3, 0.8]) {
        const light = scale(color, k);
        const out = toneMap(light);
        const factor = reinhardLuminance(luminance(light)) / luminance(light);
        if (max3(scale(light, factor)) > 1) continue;
        out.forEach((channel, i) => {
          expect(channel).toBeCloseTo((light[i] ?? 0) * factor, 12);
        });
      }
    }
  });

  it('desaturates out-of-gamut light toward gray of the same luminance, keeping the hue', () => {
    let desaturated = 0;
    for (const color of COLORS) {
      for (const k of LEVELS) {
        const light = scale(color, k);
        const out = toneMap(light);
        const lumIn = luminance(light);
        const lumOut = luminance(out);
        // Chroma, the offset from gray, points the same way before and after.
        const chromaIn = light.map((c) => c / lumIn - 1);
        const chromaOut = out.map((c) => c / lumOut - 1);
        const ratio = Math.hypot(...chromaOut) / Math.hypot(...chromaIn);
        if (Math.hypot(...chromaIn) < 1e-9) continue;
        chromaOut.forEach((c, i) => {
          expect(c).toBeCloseTo((chromaIn[i] ?? 0) * ratio, 9);
        });
        expect(ratio).toBeLessThanOrEqual(1 + 1e-12);
        if (ratio < 0.999) {
          desaturated++;
          expect(max3(out)).toBeCloseTo(1, 12);
        }
      }
    }
    expect(desaturated).toBeGreaterThan(10);
  });

  it('gets brighter as light stacks up, stays in gamut, and is never flat white', () => {
    for (const color of COLORS) {
      let previous = -1;
      for (let k = 1e-3; k < 1e7; k *= 1.5) {
        const out = toneMap(scale(color, k));
        expect(max3(out)).toBeLessThanOrEqual(1 + 1e-12);
        expect(min3(out)).toBeGreaterThanOrEqual(0);
        // The palest channel never reaches the peak luminance, which is below white.
        expect(min3(out)).toBeLessThan(PEAK_LUMINANCE);
        const lum = luminance(out);
        expect(lum).toBeGreaterThan(previous);
        previous = lum;
      }
    }
    expect(PEAK_LUMINANCE).toBeLessThan(1);
  });

  it('keeps a dense core tinted with its status hue', () => {
    for (const color of GLOWING) {
      const core = toneMap(scale(color, 1e6));
      // The token's strongest channel stays the strongest, and clearly so.
      expect(core.indexOf(max3(core))).toBe(color.indexOf(max3(color)));
      expect(max3(core) - min3(core)).toBeGreaterThan(0.08);
    }
  });

  it('blends mixed statuses to a hue between them', () => {
    const mix = add(scale(CLOSED, 0.4), scale(DELAYED, 0.4));
    const out = toneMap(mix);
    const ratio = (c: Rgb): number => c[2] / c[0];
    expect(ratio(out)).toBeCloseTo(ratio(mix), 10);
    expect(ratio(out)).toBeLessThan(ratio(CLOSED));
    expect(ratio(out)).toBeGreaterThan(ratio(DELAYED));
  });

  it('applies exposure before the curve', () => {
    expect(toneMap(REMOTE, 2)).toEqual(toneMap(scale(REMOTE, 2)));
  });

  it('shares its constants with the GLSL source', () => {
    expect(TONEMAP_GLSL).toContain(`GLOW_PEAK_LUMINANCE = ${String(PEAK_LUMINANCE)}`);
    expect(TONEMAP_GLSL).toContain(`GLOW_STATUS_DOMINANCE = ${String(STATUS_DOMINANCE)}.0`);
    expect(TONEMAP_GLSL).toContain(`vec3(${LUMA.join(', ')})`);
    expect(TONEMAP_GLSL).toContain('lum / (1.0 + lum / GLOW_PEAK_LUMINANCE)');
  });
});
