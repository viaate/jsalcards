/**
 * How the glow looks at each zoom. All sizes are CSS pixels; the layer scales
 * them by the device pixel ratio and the light target's resolution.
 *
 * Each point is a small bright core. Around it, light spreads at several
 * scales at once, like city lights seen through air:
 *
 * - Zoom 3 to 6, the national view: wide bloom out to about 64 px, so a metro
 *   merges into one glow and a lone town is a speck with a faint halo.
 * - From zoom 6 the wide scales fade out and the glow tightens.
 * - From zoom 11 each school is a crisp per-status glyph with a small halo
 *   drawn around it (not under it, so a ring stays a ring).
 *
 * The wide scales are not drawn per point. Blurring the sum of all points
 * equals summing each point's blurred light, so the layer blurs the whole
 * light target once per scale, at a cost that does not grow with the number
 * of points.
 */

/** A piecewise-linear curve over zoom, as [zoom, value] stops in ascending zoom order. */
export type ZoomStops = readonly (readonly [zoom: number, value: number])[];

/** Evaluates a {@link ZoomStops} curve, holding the end values beyond the first and last stop. */
export function interpolateStops(stops: ZoomStops, zoom: number): number {
  const first = stops[0];
  if (first === undefined) throw new Error('glow: a zoom curve needs at least one stop');
  if (zoom <= first[0]) return first[1];
  for (let i = 1; i < stops.length; i++) {
    const hi = stops[i];
    const lo = stops[i - 1];
    if (hi === undefined || lo === undefined) break;
    if (zoom <= hi[0]) {
      const t = (zoom - lo[0]) / (hi[0] - lo[0]);
      return lo[1] + (hi[1] - lo[1]) * t;
    }
  }
  const last = stops[stops.length - 1];
  return last === undefined ? first[1] : last[1];
}

export function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
}

// --- per-point kernel --------------------------------------------------------

/** Standard deviation of each point's bright core, CSS px. */
export const CORE_SIGMA_STOPS: ZoomStops = [
  [3, 0.85],
  [6, 1],
  [9, 1.5],
  [11, 1.9],
  [16, 2.3],
];

/**
 * Light at the center of one isolated core, before tone mapping. Low
 * nationally, where a metro stacks hundreds of points, rising as points
 * spread apart so a lone school still reads.
 */
export const GAIN_STOPS: ZoomStops = [
  [3, 0.42],
  [5, 0.48],
  [7, 0.65],
  [9, 0.95],
  [11, 0.9],
  [16, 0.9],
];

/** Radius of the halo drawn around each point from zoom 9, CSS px. */
export const HALO_RADIUS_STOPS: ZoomStops = [
  [3, 20],
  [6, 20],
  [9, 16],
  [11, 12],
  [16, 14],
];

/** Light in each point's own halo relative to its core. Zero while the bloom carries the halo. */
export const HALO_ENERGY_STOPS: ZoomStops = [
  [8.5, 0],
  [10, 0.6],
  [11, 1.2],
  [16, 1.2],
];

/** Halo standard deviation as a share of its radius. */
export const HALO_SIGMA_SHARE = 0.36;

/** A point's own halo: its light relative to the core, and its spread. */
export interface HaloShape {
  readonly energy: number;
  /** Standard deviation as a share of the halo radius. */
  readonly sigmaShare: number;
  /** Halo radius, CSS px. */
  readonly radiusPx: number;
}

// --- bloom ---------------------------------------------------------------------

/** CSS-pixel scales of the bloom, each twice the last. */
export const BLOOM_SCALES_PX: readonly number[] = [4, 8, 16, 32, 64];

/**
 * Light at each bloom scale relative to the cores, by zoom. One row per zoom
 * stop, one column per entry of {@link BLOOM_SCALES_PX}.
 */
export const BLOOM_WEIGHT_STOPS: readonly (readonly [zoom: number, weights: readonly number[]])[] =
  [
    [3, [0.3, 0.42, 0.48, 0.4, 0.2]],
    [6, [0.3, 0.42, 0.46, 0.34, 0.14]],
    [8, [0.3, 0.38, 0.32, 0.16, 0.04]],
    [10, [0.2, 0.14, 0.05, 0, 0]],
    [11, [0, 0, 0, 0, 0]],
  ];

/** Bloom weights for each entry of {@link BLOOM_SCALES_PX} at `zoom`. */
export function bloomWeights(zoom: number): number[] {
  return BLOOM_SCALES_PX.map((_, i) =>
    interpolateStops(
      BLOOM_WEIGHT_STOPS.map(([z, weights]) => [z, weights[i] ?? 0] as const),
      zoom,
    ),
  );
}

/**
 * Weight for a bloom level whose texels are `scalePx` CSS px, interpolated in
 * log2 scale between the entries of {@link BLOOM_SCALES_PX}. Levels finer
 * than the first scale or coarser than the last get nothing, so the look does
 * not depend on the light target's resolution.
 */
export function bloomWeightAtScale(weights: readonly number[], scalePx: number): number {
  const position = Math.log2(scalePx / (BLOOM_SCALES_PX[0] ?? 1));
  if (position < -1e-6 || position > weights.length - 1 + 1e-6) return 0;
  const lo = Math.floor(position + 1e-6);
  const t = Math.max(0, position - lo);
  return (weights[lo] ?? 0) * (1 - t) + (weights[lo + 1] ?? 0) * t;
}

/**
 * Bloom source limit, in light per light-target pixel (all statuses summed).
 * Light up to the knee feeds the bloom as it is; past it, at a falling rate
 * that levels off at the limit. In a national view of 30,000 points only the
 * top 0.1% of pixels pass the knee, so real data keeps its look, while a
 * pile of thousands of points on one spot (whose core the half-float target
 * already holds near 1,000) blooms no wider than a dense metro instead of
 * spreading a disc hundreds of pixels across. The core itself is not limited:
 * the tone map already keeps it in range.
 */
export const BLOOM_KNEE = 8;
export const BLOOM_LIMIT = 32;

/** Factor on a light-target pixel's light before it feeds the bloom. JS mirror of the shader. */
export function bloomSourceScale(total: number): number {
  if (!(total > BLOOM_KNEE)) return 1;
  const over = total - BLOOM_KNEE;
  return (BLOOM_KNEE + over / (1 + over / (BLOOM_LIMIT - BLOOM_KNEE))) / total;
}

/** GLSL for {@link bloomSourceScale}, applied to one light-target sample. */
export const BLOOM_SOURCE_GLSL = /* glsl */ `
const float GLOW_BLOOM_KNEE = ${BLOOM_KNEE.toFixed(1)};
const float GLOW_BLOOM_LIMIT = ${BLOOM_LIMIT.toFixed(1)};
vec4 glow_bloom_source(vec4 light) {
  float total = light.r + light.g + light.b + light.a;
  if (total <= GLOW_BLOOM_KNEE) return light;
  float over = total - GLOW_BLOOM_KNEE;
  return light * ((GLOW_BLOOM_KNEE + over / (1.0 + over / (GLOW_BLOOM_LIMIT - GLOW_BLOOM_KNEE))) / total);
}
`;

// --- 8-bit fallback ------------------------------------------------------------

/**
 * Without float render targets the light is gathered in 8-bit targets. Each
 * point writes 1 - exp(-light * alpha) with screen blending, and screening
 * two such values gives 1 - exp(-(a + b) * alpha): light still adds, in
 * optical depth, and a dense core rolls off smoothly where plain 8-bit
 * addition would clip it to a flat disc.
 *
 * One 8-bit channel cannot hold both a faint halo and a dense core, so the
 * light is written twice in one draw: a coarse target at the zoom-scaled
 * alpha, with headroom for dense cores, and a fine one at
 * {@link FALLBACK_FINE_GAIN} times that alpha, which resolves faint halos in
 * steps sixteen times smaller and saturates early. The composite decodes
 * both and weighs each by its precision at that level, then tone maps the
 * light exactly as the float path does.
 *
 * Alpha is scaled by zoom: nationally many points overlap, so a low alpha
 * leaves headroom (light up to about 6.2 / alpha before the top 8-bit step);
 * zoomed in, few overlap, and a higher alpha spends the bits on the halos.
 */
export const FALLBACK_ALPHA_STOPS: ZoomStops = [
  [3, 0.65],
  [7, 0.85],
  [9, 1.25],
  [11, 2],
];

/** The fine target's alpha relative to the coarse one's. */
export const FALLBACK_FINE_GAIN = 16;

/**
 * The fallback has no bloom, so each point's own halo carries the bloom
 * scales that mostly fall inside it: this share of each entry of
 * {@link BLOOM_SCALES_PX}. The wide scales, which would only spread thinly
 * past the halo's edge, are left out, so the fallback's glow is a little
 * tighter than the float path's.
 */
export const FALLBACK_BLOOM_FOLD: readonly number[] = [1, 1, 0.6, 0.25, 0.08];

/** Spread of the folded bloom in the fallback halo, as a share of the halo radius. */
export const FALLBACK_BLOOM_SIGMA_SHARE = 0.26;

/**
 * Fallback halo radius, CSS px. Wider than the float path's own halo from
 * zoom 7 to 10, where the bloom still reaches past it and few points are on
 * screen; the same from zoom 11, where there is no bloom to stand in for.
 * Nationally, where every point is on screen, it stays at 20 px to hold the
 * per-frame fill down.
 */
export const FALLBACK_HALO_RADIUS_STOPS: ZoomStops = [
  [3, 20],
  [6, 20],
  [7.5, 30],
  [9.5, 26],
  [11, 12],
];

/** The fallback's per-point halo at a zoom: its own halo plus the folded bloom. */
export function fallbackHalo(style: GlowFrameStyle, zoom: number): HaloShape {
  const folded = style.bloom.reduce((sum, w, i) => sum + w * (FALLBACK_BLOOM_FOLD[i] ?? 0), 0);
  const energy = style.haloEnergy + folded;
  if (!(folded > 0)) {
    return { energy, sigmaShare: HALO_SIGMA_SHARE, radiusPx: style.haloRadiusPx };
  }
  return {
    energy,
    sigmaShare:
      (style.haloEnergy * HALO_SIGMA_SHARE + folded * FALLBACK_BLOOM_SIGMA_SHARE) / energy,
    radiusPx: Math.max(style.haloRadiusPx, interpolateStops(FALLBACK_HALO_RADIUS_STOPS, zoom)),
  };
}

/** Smallest transmittance an 8-bit channel is decoded at: half its last step. */
export const FALLBACK_MIN_TRANSMITTANCE = 0.5 / 255;

/**
 * Light as the two 8-bit fallback targets store it, coarse then fine, in
 * 0..255. JS mirror of the light shader and the blender's rounding.
 */
export function fallbackEncode(light: number, alpha: number): [coarse: number, fine: number] {
  const store = (a: number): number => Math.round((1 - Math.exp(-light * a)) * 255);
  return [store(alpha), store(alpha * FALLBACK_FINE_GAIN)];
}

/**
 * Light decoded from the two stored 8-bit values: each decode weighted by
 * the inverse square of its step size there, and a saturated fine value
 * left out. JS mirror of `glow_fallback_decode`.
 */
export function fallbackDecode(coarse: number, fine: number, alpha: number): number {
  const fineAlpha = alpha * FALLBACK_FINE_GAIN;
  const tCoarse = Math.max(1 - coarse / 255, FALLBACK_MIN_TRANSMITTANCE);
  const tFine = Math.max(1 - fine / 255, FALLBACK_MIN_TRANSMITTANCE);
  const lightCoarse = -Math.log(tCoarse) / alpha;
  const lightFine = -Math.log(tFine) / fineAlpha;
  // A step of one 8-bit level is about 1 / (255 * alpha * transmittance) of light.
  const wCoarse = (alpha * tCoarse) ** 2;
  const wFine = tFine > FALLBACK_MIN_TRANSMITTANCE ? (fineAlpha * tFine) ** 2 : 0;
  return (wCoarse * lightCoarse + wFine * lightFine) / (wCoarse + wFine);
}

/** GLSL for {@link fallbackDecode}, per channel, on samples of the two 8-bit light targets. */
export const FALLBACK_GLSL = /* glsl */ `
const float GLOW_FALLBACK_FINE_GAIN = ${FALLBACK_FINE_GAIN.toFixed(1)};
const float GLOW_FALLBACK_MIN_TRANSMITTANCE = ${String(FALLBACK_MIN_TRANSMITTANCE)};
vec4 glow_fallback_decode(vec4 coarse, vec4 fine, float alpha) {
  float fineAlpha = alpha * GLOW_FALLBACK_FINE_GAIN;
  vec4 tCoarse = max(vec4(1.0) - coarse, vec4(GLOW_FALLBACK_MIN_TRANSMITTANCE));
  vec4 tFine = max(vec4(1.0) - fine, vec4(GLOW_FALLBACK_MIN_TRANSMITTANCE));
  vec4 lightCoarse = -log(tCoarse) / alpha;
  vec4 lightFine = -log(tFine) / fineAlpha;
  vec4 wCoarse = alpha * tCoarse;
  wCoarse *= wCoarse;
  vec4 wFine = fineAlpha * tFine;
  wFine *= wFine * vec4(greaterThan(tFine, vec4(GLOW_FALLBACK_MIN_TRANSMITTANCE)));
  return (wCoarse * lightCoarse + wFine * lightFine) / (wCoarse + wFine);
}
`;

/**
 * Roughly how far from a lone point its glow reaches, CSS px: the
 * energy-weighted RMS spread of core, own halo and bloom. The curve the
 * zoom-behavior tests pin down: wide nationally, tightening from zoom 6, a
 * small halo from zoom 11.
 */
export function glowReachPx(zoom: number): number {
  const style = glowStyleAtZoom(zoom);
  const core = style.coreSigmaPx;
  const haloSigma = HALO_SIGMA_SHARE * style.haloRadiusPx;
  let energy = 1;
  let moment = core * core;
  energy += style.haloEnergy;
  moment += style.haloEnergy * haloSigma * haloSigma;
  style.bloom.forEach((weight, i) => {
    const scale = BLOOM_SCALES_PX[i] ?? 0;
    energy += weight;
    moment += weight * scale * scale;
  });
  return 2 * Math.sqrt(moment / energy);
}

// --- glyphs ----------------------------------------------------------------------

/** Glyph radius, CSS px. */
export const GLYPH_RADIUS_STOPS: ZoomStops = [
  [11, 4.5],
  [14, 5.5],
  [17, 6.5],
];

/** Open-school dot radius, CSS px. */
export const OPEN_RADIUS_STOPS: ZoomStops = [
  [11, 2],
  [14, 2.5],
  [17, 3],
];

/** Glyphs fade in over this zoom range and are fully crisp from its end. */
export const GLYPH_FADE_START = 10.5;
export const GLYPH_FADE_END = 11;

// --- one frame ---------------------------------------------------------------------

/** Everything the layer needs for one frame at a given zoom. */
export interface GlowFrameStyle {
  readonly coreSigmaPx: number;
  readonly gain: number;
  readonly haloRadiusPx: number;
  readonly haloEnergy: number;
  /** Weights for {@link BLOOM_SCALES_PX}. */
  readonly bloom: readonly number[];
  readonly glyphOpacity: number;
  readonly glyphRadiusPx: number;
  readonly openRadiusPx: number;
}

export function glowStyleAtZoom(zoom: number): GlowFrameStyle {
  return {
    coreSigmaPx: interpolateStops(CORE_SIGMA_STOPS, zoom),
    gain: interpolateStops(GAIN_STOPS, zoom),
    haloRadiusPx: interpolateStops(HALO_RADIUS_STOPS, zoom),
    haloEnergy: interpolateStops(HALO_ENERGY_STOPS, zoom),
    bloom: bloomWeights(zoom),
    glyphOpacity: smoothstep(GLYPH_FADE_START, GLYPH_FADE_END, zoom),
    glyphRadiusPx: interpolateStops(GLYPH_RADIUS_STOPS, zoom),
    openRadiusPx: interpolateStops(OPEN_RADIUS_STOPS, zoom),
  };
}

/**
 * The per-point kernel in the units the shader wants, for a light target
 * whose pixels are `targetPxPerCssPx` of a CSS pixel. With d the distance
 * over the sprite radius, the kernel is
 *
 *   coreWeight * exp(-d^2 * coreFalloff)
 *     + haloWeight * exp(-d^2 * haloFalloff) * (1 - d^2)^2 * hole(d)
 *
 * The core is a Gaussian. To keep a sub-pixel core from shimmering while the
 * map pans, its variance is widened by the footprint of one target pixel and
 * its peak lowered to match, so the light it adds stays the same. The halo is
 * a wider Gaussian windowed to reach zero at the sprite edge; `hole` cuts it
 * away under a glyph.
 */
export interface KernelUniforms {
  /** Sprite radius in target pixels. */
  readonly radius: number;
  readonly coreFalloff: number;
  /** Core peak relative to an unfiltered core (at most 1). */
  readonly coreWeight: number;
  readonly haloFalloff: number;
  readonly haloWeight: number;
  /** Normalized radius inside which the halo is cut away, 0 for none. */
  readonly hole: number;
}

/**
 * Variance added to the core for the target pixel's footprint, px^2. Half a
 * pixel of standard deviation keeps a moving speck's peak within about 20%
 * whether it sits on a pixel center or between four.
 */
const FOOTPRINT_VARIANCE = 0.25;

/** Core sprites reach this many effective standard deviations. */
const CORE_REACH_SIGMAS = 3;

/**
 * Squared normalized radius where the core starts fading to zero, so it ends
 * smoothly at the sprite edge instead of stepping from 1% of its peak to 0.
 */
export const CORE_EDGE_D2 = 0.5625;

export function kernelUniforms(
  style: GlowFrameStyle,
  targetPxPerCssPx: number,
  halo: HaloShape = {
    energy: style.haloEnergy,
    sigmaShare: HALO_SIGMA_SHARE,
    radiusPx: style.haloRadiusPx,
  },
): KernelUniforms {
  const haloEnergy = halo.energy;
  const sigma = style.coreSigmaPx * targetPxPerCssPx;
  const sigmaEff2 = sigma * sigma + FOOTPRINT_VARIANCE;
  const coreReach = CORE_REACH_SIGMAS * Math.sqrt(sigmaEff2);
  const haloRadius = halo.radiusPx * targetPxPerCssPx;
  const radius = haloEnergy > 0 ? Math.max(haloRadius, coreReach) : coreReach;
  const haloSigma = halo.sigmaShare * haloRadius;
  const hole =
    style.glyphOpacity > 0 && haloEnergy > 0
      ? ((style.glyphRadiusPx * targetPxPerCssPx) / radius) * style.glyphOpacity
      : 0;
  return {
    radius,
    coreFalloff: (radius * radius) / (2 * sigmaEff2),
    // The glyph takes the core's place, so a ring's center stays dark.
    coreWeight: ((sigma * sigma) / sigmaEff2) * (1 - style.glyphOpacity),
    haloFalloff: (radius * radius) / (2 * haloSigma * haloSigma),
    // Core light is 2 pi sigma^2; the windowed halo's is haloWeight * pi * R^2 * I(falloff).
    haloWeight:
      haloEnergy > 0
        ? (haloEnergy * 2 * sigma * sigma) /
          (radius *
            radius *
            windowedGaussianIntegral((radius * radius) / (2 * haloSigma * haloSigma)))
        : 0,
    hole,
  };
}

/**
 * Integral over u in 0..1 of exp(-a u) (1 - u)^2: the light in the windowed
 * halo exp(-a d^2) (1 - d^2)^2 over the unit disc is pi times this.
 */
export function windowedGaussianIntegral(a: number): number {
  if (a < 1e-3) return 1 / 3 - a / 12;
  const a2 = a * a;
  const a3 = a2 * a;
  return 1 / a - 2 / a2 + 2 / a3 - (2 * Math.exp(-a)) / a3;
}

/**
 * Kernel value at normalized distance `d` (0 at the point, 1 at the sprite
 * edge). JS mirror of the fragment shader, for tests.
 */
export function kernelAt(k: KernelUniforms, d: number): number {
  if (d >= 1) return 0;
  const d2 = d * d;
  const window = (1 - d2) ** 2;
  const hole = k.hole > 0 ? smoothstep(k.hole * 0.75, k.hole * 1.1, d) : 1;
  return (
    k.coreWeight * Math.exp(-d2 * k.coreFalloff) * (1 - smoothstep(CORE_EDGE_D2, 1, d2)) +
    k.haloWeight * Math.exp(-d2 * k.haloFalloff) * window * hole
  );
}

// --- pulse -------------------------------------------------------------------------

/** Length of the fade-in pulse for a newly added point, seconds. */
export const PULSE_SECONDS = 1.6;

/** Extra brightness at the pulse's crest. */
const PULSE_GAIN = 1.1;
/** Extra radius at the pulse's crest. */
const PULSE_GROW = 0.35;

/**
 * Brightness and radius multipliers for a point `age` seconds after it
 * appeared: it fades in, swells once and settles at exactly 1. Mirrors the
 * vertex shader.
 */
export function pulseAt(age: number): { readonly intensity: number; readonly radius: number } {
  if (age < 0) return { intensity: 0, radius: 1 };
  const t = age / PULSE_SECONDS;
  if (t >= 1) return { intensity: 1, radius: 1 };
  const swell = Math.sin(Math.PI * t) ** 2 * (1 - t);
  return {
    intensity: smoothstep(0, 0.12, t) * (1 + PULSE_GAIN * swell),
    radius: 1 + PULSE_GROW * swell,
  };
}

/** GLSL constants for the pulse, kept next to their JS mirror. */
export const PULSE_GLSL = /* glsl */ `
const float GLOW_PULSE_SECONDS = ${String(PULSE_SECONDS)};
const float GLOW_PULSE_GAIN = ${String(PULSE_GAIN)};
const float GLOW_PULSE_GROW = ${String(PULSE_GROW)};
`;
