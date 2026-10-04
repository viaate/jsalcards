/**
 * A CPU mirror of the float path for tests: the light pass, the bloom's
 * downsample and upsample chains, the blend's blur and the composite, the
 * dense share included, on a small square light target of one target pixel
 * per CSS pixel unless told otherwise, for points of one status. It samples
 * textures the way the shaders do (bilinear, clamped at the edges), so a test
 * sees the light a viewer would, not an idealized kernel. The 8-bit
 * fallback's too, its channels rounded as stored.
 */
import { STATUS_HEX, hexToLinear, linearToSrgb } from '../color';
import {
  DENSE_CAP,
  DENSE_FIELD,
  DENSE_GATE,
  FALLBACK_ALPHA_STOPS,
  FALLBACK_MIN_TRANSMITTANCE,
  type GlowFrameStyle,
  blendFloor,
  bloomPlan,
  bloomSourceScale,
  denseShareAt,
  fallbackDecode,
  fallbackEncode,
  fallbackFloor,
  fallbackHalo,
  fallbackLift,
  fallbackPeak,
  fieldPeak,
  fieldReachPx,
  interpolateStops,
  kernelAt,
  kernelUniforms,
  smoothstep,
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

/** The eight directions GLOW_RING looks around in. */
const RING = Array.from({ length: 8 }, (_, i) => [
  Math.cos((i * Math.PI) / 4),
  Math.sin((i * Math.PI) / 4),
]);

/** BLUR_FRAG along x (`across`) or y, scaled by `scale`, on a floor of `gain` over `knee`. */
function blur(
  source: Level,
  sigma: number,
  radius: number,
  across: boolean,
  scale: number,
  gain = 1,
  knee = 1,
): Level {
  const { size, data } = source;
  const out = new Float64Array(size * size);
  const weights = Array.from({ length: radius + 1 }, (_, i) =>
    radius === 0 ? 1 : Math.exp((-0.5 * i * i) / (sigma * sigma)),
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
      out[j * size + i] = blendFloor((sum * scale) / total, gain, knee);
    }
  }
  return { size, data: out };
}

/**
 * The light the composite tone maps at each pixel of a `size` x `size`
 * light target of `targetPxPerCss` pixels per CSS pixel, for points at (x, y)
 * in its pixels, all of one status.
 */
export function compositeLight(
  points: readonly (readonly [number, number])[],
  style: GlowFrameStyle,
  size: number,
  targetPxPerCss = 1,
): Float64Array {
  // Light pass: every point's sprite, whole cores, added up.
  const k = kernelUniforms(style, targetPxPerCss);
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
  const { weights, blur: blend } = bloomPlan(style, targetPxPerCss, size);

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
      const { sigmaTexels, radius, weight, floorGain, floorKnee } = blend;
      const down = blur(across, sigmaTexels, radius, false, weight, floorGain, floorKnee);
      for (let t = 0; t < up.length; t++) up[t] = (up[t] ?? 0) + (down.data[t] ?? 0);
    }
    levels[i - 1] = { size: target.size, data: up };
  }

  // Composite: the shown share of the cores, the dense share where they pile up, and the bloom.
  const out = new Float64Array(size * size);
  const bloom = weights.length > 0 ? levels[1] : undefined;
  const bloomScale = bloom === undefined ? 0 : weights.length === 1 ? (weights[0] ?? 0) : 1;
  const spread = bloom === undefined ? undefined : upsample(bloom, size, bloomScale);
  const corePeak = Math.max(k.coreWeight * style.gain, 1e-6);
  const blendPeak = Math.max(fieldPeak(style), 1e-6);
  const reach = fieldReachPx(style) * targetPxPerCss;
  const denseShare = denseShareAt(style, targetPxPerCss);
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const t = j * size + i;
      const core = light.data[t] ?? 0;
      const here = spread?.[t] ?? 0;
      let dense = 0;
      if (denseShare > 0 && bloom !== undefined) {
        // The composite samples the bloom level itself around, a level of half the light target.
        let around = 0;
        for (const [dx = 0, dy = 0] of RING) {
          around += sample(bloom, (i + 0.5 + reach * dx) / 2, (j + 0.5 + reach * dy) / 2);
        }
        const field = (around * bloomScale) / (8 * blendPeak);
        const share =
          denseShare *
          smoothstep(DENSE_GATE[0], DENSE_GATE[1], core / corePeak) *
          smoothstep(DENSE_FIELD[0], DENSE_FIELD[1], field);
        dense = Math.min(share * core, DENSE_CAP * here);
      }
      out[t] = style.coreShare * core + dense + here;
    }
  }
  return out;
}

/** What the light pass adds at (i, j) of a light target of one pixel per CSS pixel, for `kernel`. */
function splat(
  points: readonly (readonly [number, number])[],
  size: number,
  radius: number,
  at: (d: number) => number,
): Float64Array {
  const out = new Float64Array(size * size);
  for (const [px, py] of points) {
    for (
      let j = Math.max(0, Math.floor(py - radius));
      j <= Math.min(size - 1, Math.ceil(py + radius));
      j++
    ) {
      for (
        let i = Math.max(0, Math.floor(px - radius));
        i <= Math.min(size - 1, Math.ceil(px + radius));
        i++
      ) {
        const d = Math.hypot(i + 0.5 - px, j + 0.5 - py) / radius;
        if (d < 1) out[j * size + i] = (out[j * size + i] ?? 0) + at(d);
      }
    }
  }
  return out;
}

/** An 8-bit channel's value for `light` written as 1 - exp(-light * alpha), and read back. */
function byte(light: number, alpha: number): number {
  const stored = Math.round((1 - Math.exp(-light * alpha)) * 255) / 255;
  return -Math.log(Math.max(1 - stored, FALLBACK_MIN_TRANSMITTANCE)) / alpha;
}

/**
 * The 8-bit fallback's light as its composite tone maps it, for points of one
 * status at (x, y) on a `size` x `size` light target of one pixel per CSS
 * pixel: halos and the share of the cores drawn, on their floor, and the
 * whole cores, kept apart, where they pile up inside a field.
 */
export function fallbackCompositeLight(
  points: readonly (readonly [number, number])[],
  style: GlowFrameStyle,
  zoom: number,
  size: number,
): Float64Array {
  const halo = fallbackHalo(style, zoom);
  const k = kernelUniforms(style, 1, halo, style.coreShare);
  const alpha = interpolateStops(FALLBACK_ALPHA_STOPS, zoom);
  const light = splat(points, size, k.radius, (d) => style.gain * kernelAt(k, d)).map((v) =>
    fallbackDecode(...fallbackEncode(v, alpha), alpha),
  );
  // The cores alone, in a lone core's peaks: the kernel's core, whole.
  const whole = kernelUniforms(style, 1, halo);
  const unit = { ...whole, coreWeight: 1, haloWeight: 0 };
  const cores = splat(points, size, whole.radius, (d) => kernelAt(unit, d)).map((v) => byte(v, 1));
  const floor = fallbackFloor(style, zoom);
  const corePeak = Math.max(whole.coreWeight * style.gain, 1e-6);
  const field = Math.max(fallbackPeak(style, zoom), 1e-6);
  const reach = fieldReachPx(style);
  const denseShare = denseShareAt(style, 1);
  const level: Level = { size, data: light };
  const out = new Float64Array(size * size);
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const t = j * size + i;
      const here = light[t] ?? 0;
      const shown = here * fallbackLift(here, floor.gain, floor.knee);
      let dense = 0;
      const core = (cores[t] ?? 0) * corePeak;
      if (denseShare > 0) {
        let around = 0;
        for (const [dx = 0, dy = 0] of RING)
          around += sample(level, i + 0.5 + reach * dx, j + 0.5 + reach * dy);
        const share =
          denseShare *
          smoothstep(DENSE_GATE[0], DENSE_GATE[1], core / corePeak) *
          smoothstep(DENSE_FIELD[0], DENSE_FIELD[1], around / (8 * field));
        dense = Math.min(share * core, DENSE_CAP * shown);
      }
      out[t] = dense + shown;
    }
  }
  return out;
}

const closed = [hexToLinear(STATUS_HEX[0])];

/** What a viewer sees for closed-status light: tone mapped, sRGB encoded, in 0..255. */
export function displayed(light: number): number {
  const rgb = toneMap(statusLight([light, 0, 0, 0], closed));
  return Math.max(...rgb.map(linearToSrgb)) * 255;
}
