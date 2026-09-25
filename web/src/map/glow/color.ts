/**
 * Status codes and color handling for the glow layer.
 *
 * Status tokens are sRGB hex values from the design spec. The glow pass adds
 * light in linear space, so tokens are decoded with the exact sRGB transfer
 * function before they reach the GPU and encoded again after tone mapping.
 * Glyphs are drawn straight in display space so their fill is the token itself.
 */

/** Status codes as stored in the point set's `status` Uint8Array. */
export const GlowStatus = {
  Closed: 0,
  Delayed: 1,
  Remote: 2,
  EarlyDismissal: 3,
  Open: 4,
} as const;

export type GlowStatus = (typeof GlowStatus)[keyof typeof GlowStatus];

/** Number of valid status codes. Codes at or above this are rejected. */
export const STATUS_COUNT = 5;

/** Design tokens, indexed by status code. Open is drawn as a faint gray dot and never glows. */
export const STATUS_HEX: readonly [string, string, string, string, string] = [
  '#7FD4FF', // closed: filled dot
  '#FFC46B', // delayed: ring
  '#B79CFF', // remote: diamond
  '#6BFFB0', // early dismissal: half-filled dot
  '#6B6B6B', // open: faint gray dot (text-3 token)
];

export type Rgb = readonly [number, number, number];

/** Parses `#RRGGBB` into 0..1 display (sRGB-encoded) components. */
export function hexToSrgb(hex: string): Rgb {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (match === null) throw new Error(`glow: "${hex}" is not a #RRGGBB color`);
  const channel = (pair: string | undefined): number => Number.parseInt(pair ?? '0', 16) / 255;
  return [channel(match[1]), channel(match[2]), channel(match[3])];
}

/** sRGB electro-optical transfer function (IEC 61966-2-1), display value to linear light. */
export function srgbToLinear(value: number): number {
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** Inverse of {@link srgbToLinear}, linear light to display value. */
export function linearToSrgb(value: number): number {
  const v = Math.min(Math.max(value, 0), 1);
  return v <= 0.0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - 0.055;
}

export function hexToLinear(hex: string): Rgb {
  const [r, g, b] = hexToSrgb(hex);
  return [srgbToLinear(r), srgbToLinear(g), srgbToLinear(b)];
}

/** Rec. 709 luminance weights, for linear-light RGB. */
export const LUMA: Rgb = [0.2126, 0.7152, 0.0722];

export function luminance([r, g, b]: Rgb): number {
  return LUMA[0] * r + LUMA[1] * g + LUMA[2] * b;
}

/** Linear-light status colors, flattened for `uniform3fv`. */
export function statusLinearUniform(): Float32Array {
  const out = new Float32Array(STATUS_COUNT * 3);
  STATUS_HEX.forEach((hex, i) => {
    out.set(hexToLinear(hex), i * 3);
  });
  return out;
}

/** Display-space status colors, flattened for `uniform3fv`. */
export function statusSrgbUniform(): Float32Array {
  const out = new Float32Array(STATUS_COUNT * 3);
  STATUS_HEX.forEach((hex, i) => {
    out.set(hexToSrgb(hex), i * 3);
  });
  return out;
}
