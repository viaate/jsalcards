/**
 * The composite pass tone map, in one place for both the shader and a JS
 * mirror that the unit tests exercise.
 *
 * Accumulated light is linear RGB with no upper bound. The curve is Reinhard
 * on luminance: with L the Rec. 709 luminance of the light,
 *
 *   L' = L / (1 + L / PEAK_LUMINANCE)
 *
 * applied as one scale factor on all three channels, so hue and saturation
 * are kept. The curve rises with slope 1 from black and approaches
 * PEAK_LUMINANCE, below 1, without reaching it: a denser cluster is always
 * brighter, and no pixel is ever flat white.
 *
 * A saturated hue can leave the gamut before its luminance reaches the peak
 * (a blue channel passes 1 while the luminance is still about 0.6). There the
 * color is desaturated toward the gray of the same luminance, just enough to
 * fit. That keeps the luminance the curve asked for and the hue, and lets the
 * hottest cores pale the way bright lights do, where clipping each channel
 * would shift the hue and scaling it back would flatten the core into a disc.
 */
import { LUMA, type Rgb, luminance } from './color';

/** Luminance the curve approaches for unlimited light. Below 1, so nothing is flat white. */
export const PEAK_LUMINANCE = 0.9;

/** Reinhard on a luminance value, with its asymptote at {@link PEAK_LUMINANCE}. */
export function reinhardLuminance(lum: number): number {
  return lum / (1 + lum / PEAK_LUMINANCE);
}

/**
 * How firmly the leading status sets the hue where statuses overlap: each
 * status weighs in as its light raised to this power. 1 would be a plain
 * additive mix, where equal parts of all four hues sum to near white; 2 lets
 * the leading status keep its color while the others tint it.
 */
export const STATUS_DOMINANCE = 2;

/** Light per glowing status: closed, delayed, remote, early dismissal. */
export type StatusLight = readonly [number, number, number, number];

/**
 * JS mirror of `glow_status_light` in {@link TONEMAP_GLSL}: turns the light
 * gathered per status into linear RGB light, keeping the total and taking the
 * hue from the statuses weighted by {@link STATUS_DOMINANCE}.
 */
export function statusLight(light: StatusLight, tokens: readonly Rgb[]): Rgb {
  const total = light.reduce((a, b) => a + Math.max(b, 0), 0);
  if (!(total > 1e-8)) return [0, 0, 0];
  const weights = light.map((v) => Math.max(v, 0) ** STATUS_DOMINANCE);
  const weightSum = weights.reduce((a, b) => a + b, 0);
  const hue: [number, number, number] = [0, 0, 0];
  weights.forEach((w, i) => {
    const token = tokens[i] ?? [0, 0, 0];
    for (let c = 0; c < 3; c++) hue[c] = (hue[c] ?? 0) + ((token[c] ?? 0) * w) / weightSum;
  });
  return [hue[0] * total, hue[1] * total, hue[2] * total];
}

/** JS mirror of `glow_tonemap` in {@link TONEMAP_GLSL}. Input and output are linear light. */
export function toneMap(rgb: Rgb, exposure = 1): Rgb {
  const r = Math.max(rgb[0] * exposure, 0);
  const g = Math.max(rgb[1] * exposure, 0);
  const b = Math.max(rgb[2] * exposure, 0);
  const lum = luminance([r, g, b]);
  if (!(lum > 1e-8)) return [0, 0, 0];
  const mapped = reinhardLuminance(lum);
  const k = mapped / lum;
  const out: [number, number, number] = [r * k, g * k, b * k];
  const peak = Math.max(...out);
  if (peak <= 1) return out;
  // Out of gamut: move toward the gray of luminance `mapped` until the peak channel is 1.
  const s = (1 - mapped) / (peak - mapped);
  return [
    mapped + (out[0] - mapped) * s,
    mapped + (out[1] - mapped) * s,
    mapped + (out[2] - mapped) * s,
  ];
}

const glslFloat = (value: number): string =>
  Number.isInteger(value) ? `${String(value)}.0` : String(value);

/** GLSL ES 3.00 source for the tone map, generated from the same constants as {@link toneMap}. */
export const TONEMAP_GLSL = /* glsl */ `
const vec3 GLOW_LUMA = vec3(${LUMA.map(glslFloat).join(', ')});
const float GLOW_PEAK_LUMINANCE = ${glslFloat(PEAK_LUMINANCE)};
const float GLOW_STATUS_DOMINANCE = ${glslFloat(STATUS_DOMINANCE)};

// Per-status light (closed, delayed, remote, early dismissal) to linear RGB.
vec3 glow_status_light(vec4 light, vec3 tokens[4]) {
  light = max(light, vec4(0.0));
  float total = light.r + light.g + light.b + light.a;
  if (total <= 1e-8) return vec3(0.0);
  vec4 w = pow(light, vec4(GLOW_STATUS_DOMINANCE));
  w /= (w.r + w.g + w.b + w.a);
  return (tokens[0] * w.r + tokens[1] * w.g + tokens[2] * w.b + tokens[3] * w.a) * total;
}

// Reinhard on luminance, one scale on all channels; out-of-gamut colors are
// desaturated toward the gray of the same luminance just enough to fit.
vec3 glow_tonemap(vec3 rgb) {
  rgb = max(rgb, vec3(0.0));
  float lum = dot(rgb, GLOW_LUMA);
  if (lum <= 1e-8) return vec3(0.0);
  float mapped = lum / (1.0 + lum / GLOW_PEAK_LUMINANCE);
  vec3 c = rgb * (mapped / lum);
  float peak = max(c.r, max(c.g, c.b));
  if (peak > 1.0) c = mix(vec3(mapped), c, (1.0 - mapped) / (peak - mapped));
  return c;
}

vec3 glow_linear_to_srgb(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  vec3 lo = c * 12.92;
  vec3 hi = 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055;
  return mix(hi, lo, vec3(lessThanEqual(c, vec3(0.0031308))));
}
`;
