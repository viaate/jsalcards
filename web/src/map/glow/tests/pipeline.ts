/**
 * A CPU mirror of the float path for tests: the light pass, the bloom's
 * downsample and upsample chains, the blend's blur and the composite, on a
 * small square light target at one target pixel per CSS pixel, for points of
 * one status. It samples textures the way the shaders do (bilinear, clamped
 * at the edges), so a test sees the light a viewer would, not an idealized
 * kernel.
 */
import { STATUS_HEX, hexToLinear, linearToSrgb } from '../color';
import {
  type GlowFrameStyle,
  blendLiftFactor,
  bloomPlan,
  bloomSourceScale,
  kernelAt,
  kernelUniforms,
  liftReachPx,
} from '../curves';
import { statusLight, toneMap } from '../tonemap';

/** A single-channel texture, row-major, `size` texels a side. */
interface Level {
  readonly size: number;
  readonly data: Float64Array;
}

/** Bilinear sample at (x, y) in texel units (texel k's center at k + 0.5), clamped at the edges. */
function sample(level: Level, x: number, y: number): number {
  const { size, data } = level;
  const clamp = (i: number): number => Math.min(Math.max(i, 0), size - 1);
  const fx = x - 0.5;
  const fy = y - 0.5;
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const tx = fx - x0;
  const ty = fy - y0;
  const at = (i: number, j: number): number => data[clamp(j) * size + clamp(i)] ?? 0;
  return (
    (1 - ty) * ((1 - tx) * at(x0, y0) + tx * at(x0 + 1, y0)) +
    ty * ((1 - tx) * at(x0, y0 + 1) + tx * at(x0 + 1, y0 + 1))
  );
}

const DIAGONALS = [
  [-1, -1],
  [1, -1],
  [-1, 1],
  [1, 1],
] as const;

/** DOWNSAMPLE_FRAG: four taps one source texel off each diagonal, eased past the knee from the light target. */
function downsample(source: Level, limit: boolean): Level {
  const size = Math.ceil(source.size / 2);
  const data = new Float64Array(size * size);
  const ratio = source.size / size;
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const x = (i + 0.5) * ratio;
      const y = (j + 0.5) * ratio;
      let sum = 0;
      for (const [dx, dy] of DIAGONALS) {
        const light = sample(source, x + dx, y + dy);
        sum += limit ? light * bloomSourceScale(light) : light;
      }
      data[j * size + i] = sum * 0.25;
    }
  }
  return { size, data };
}

/** UPSAMPLE_FRAG and the composite's bloom taps: a tent over `coarse` at each texel of a `size` target. */
function upsample(coarse: Level, size: number, scale: number): Float64Array {
  const data = new Float64Array(size * size);
  const ratio = coarse.size / size;
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const x = (i + 0.5) * ratio;
      const y = (j + 0.5) * ratio;
      let sum = 0;
      for (const [dx, dy] of DIAGONALS) sum += sample(coarse, x + 0.5 * dx, y + 0.5 * dy);
      data[j * size + i] = sum * 0.25 * scale;
    }
  }
  return data;
}

/** The eight directions BLEND_LIFT_GLSL looks around in. */
const RING = Array.from({ length: 8 }, (_, i) => [
  Math.cos((i * Math.PI) / 4),
  Math.sin((i * Math.PI) / 4),
]);

/**
 * BLUR_FRAG along x (`across`) or y, scaled by `scale`, lifted by `lift`
 * where the source `reach` texels around is dark.
 */
function blur(
  source: Level,
  sigma: number,
  radius: number,
  across: boolean,
  scale: number,
  lift = 0,
  reach = 0,
): Level {
  const { size, data } = source;
  const out = new Float64Array(size * size);
  const weights = Array.from({ length: radius + 1 }, (_, i) =>
    Math.exp((-0.5 * i * i) / (sigma * sigma)),
  );
  const total = weights.reduce((sum, w, i) => sum + (i === 0 ? w : 2 * w), 0);
  const clamp = (i: number): number => Math.min(Math.max(i, 0), size - 1);
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      let sum = 0;
      for (let k = -radius; k <= radius; k++) {
        const x = across ? clamp(i + k) : i;
        const y = across ? j : clamp(j + k);
        sum += (weights[Math.abs(k)] ?? 0) * (data[y * size + x] ?? 0);
      }
      let around = 0;
      if (lift > 0) {
        for (const [dx = 0, dy = 0] of RING)
          around += sample(source, i + 0.5 + reach * dx, j + 0.5 + reach * dy);
      }
      out[j * size + i] = ((sum * scale) / total) * blendLiftFactor((around * scale) / 8, lift);
    }
  }
  return { size, data: out };
}

/**
 * The light the composite tone maps at each pixel of a `size` x `size`
 * light target, for points at (x, y) in its pixels, all of one status.
 */
export function compositeLight(
  points: readonly (readonly [number, number])[],
  style: GlowFrameStyle,
  size: number,
): Float64Array {
  // Light pass: every point's sprite, whole cores, added up.
  const k = kernelUniforms(style, 1);
  const light: Level = { size, data: new Float64Array(size * size) };
  for (const [px, py] of points) {
    const r = k.radius;
    for (let j = Math.max(0, Math.floor(py - r)); j <= Math.min(size - 1, Math.ceil(py + r)); j++) {
      for (
        let i = Math.max(0, Math.floor(px - r));
        i <= Math.min(size - 1, Math.ceil(px + r));
        i++
      ) {
        const d = Math.hypot(i + 0.5 - px, j + 0.5 - py) / r;
        if (d < 1) {
          light.data[j * size + i] = (light.data[j * size + i] ?? 0) + style.gain * kernelAt(k, d);
        }
      }
    }
  }

  // Bloom weights per level, and the blend, as GlowLayer picks them.
  const { weights, blur: blend } = bloomPlan(style, 1, size);

  // Down the chain; the blend's level blurred across; back up, the blend added into its level.
  const levels: Level[] = [light];
  for (let i = 1; i <= weights.length; i++) {
    const source = levels[i - 1];
    if (source !== undefined) levels.push(downsample(source, i === 1));
  }
  const blurredLevel = blend === null ? undefined : levels[blend.level];
  const across =
    blend !== null && blurredLevel !== undefined
      ? blur(blurredLevel, blend.sigmaTexels, blend.radius, true, 1)
      : undefined;
  for (let i = weights.length; i >= 2; i--) {
    const source = levels[i];
    const target = levels[i - 1];
    if (source === undefined || target === undefined) continue;
    const up = upsample(source, target.size, i === weights.length ? (weights[i - 1] ?? 0) : 1);
    const keep = weights[i - 2] ?? 0;
    for (let t = 0; t < up.length; t++) up[t] = (up[t] ?? 0) + keep * (target.data[t] ?? 0);
    if (across !== undefined && blend !== null && i - 1 === blend.level) {
      const { sigmaTexels, radius, weight } = blend;
      const reach = liftReachPx(style) / 2 ** blend.level;
      const down = blur(across, sigmaTexels, radius, false, weight, style.blendLift, reach);
      for (let t = 0; t < up.length; t++) up[t] = (up[t] ?? 0) + (down.data[t] ?? 0);
    }
    levels[i - 1] = { size: target.size, data: up };
  }

  // Composite: the shown share of the cores, plus the bloom.
  const out = new Float64Array(size * size);
  const bloom = weights.length > 0 ? levels[1] : undefined;
  const bloomScale = bloom === undefined ? 0 : weights.length === 1 ? (weights[0] ?? 0) : 1;
  const spread = bloom === undefined ? undefined : upsample(bloom, size, bloomScale);
  for (let t = 0; t < out.length; t++) {
    out[t] = style.coreShare * (light.data[t] ?? 0) + (spread?.[t] ?? 0);
  }
  return out;
}

const closed = [hexToLinear(STATUS_HEX[0])];

/** What a viewer sees for closed-status light: tone mapped, sRGB encoded, in 0..255. */
export function displayed(light: number): number {
  const rgb = toneMap(statusLight([light, 0, 0, 0], closed));
  return Math.max(...rgb.map(linearToSrgb)) * 255;
}
