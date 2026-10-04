/**
 * How the glow looks at each zoom. All sizes are CSS pixels; the layer scales
 * them by the device pixel ratio and the light target's resolution.
 *
 * Each point is a small bright core. Around it, light spreads at several
 * scales at once, like city lights seen through air:
 *
 * - Zoom 4 to 4.5, a desktop's national view: no lone core is shown. Its
 *   light, and the bloom's finest, is carried by the blend instead, one smooth
 *   Gaussian some 15 km wide, so the points read as one field, a dim wash
 *   where schools are few and bright where they are many, like a night photo
 *   from orbit. Inside the field, where cores pile up in a town, a share of
 *   them shows sharp as fine grain (DENSE_SHARE_STOPS). Wide bloom out to
 *   about 64 px merges a metro into one glow.
 * - Below zoom 4, where screens smaller than a desktop's open on the whole
 *   country, the glow shrinks with the map (glowSizeScale), so the country
 *   looks as on a desktop: the bloom reaches 32 px at zoom 3, 16 px at 2.
 *   Only the blend stops shrinking, at 2 px, so the points still read as one
 *   field on a phone, where it stands on a floor (blendFloor) that keeps every
 *   school in view above the state lines.
 * - From zoom 4.5 the cores come back as crisp small lights over the blend's
 *   wash (CORE_FOCUS_STOPS), each school standing on its own by zoom 8, and
 *   the wide scales fade out as the glow tightens.
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

/** Width a core is drawn at, as a share of its sigma, keeping its light: crisp regional lights, not soft dots. */
export const CORE_FOCUS_STOPS: ZoomStops = [
  [4.5, 1],
  [5.5, 0.55],
  [8, 0.55],
  [9, 1],
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

/** Share of the cores (and bloom no wider than the blend) shown where they are: none nationally, where they read as specks. */
export const CORE_SHARE_STOPS: ZoomStops = [
  [4.5, 0],
  [5.5, 0.4],
  [6, 0.45],
  [8, 1],
];

/** Share of the cores shown sharp where they pile up inside a field: national grain, never a lone speck. */
export const DENSE_SHARE_STOPS: ZoomStops = [
  [4.5, 1],
  [5.5, 0],
];

/** Core light at a pixel, in lone-core peaks, over which the dense share comes in: two or three cores overlapping. */
export const DENSE_GATE: readonly [from: number, full: number] = [1.5, 3];

/** Light around a pixel, in lone-blend peaks as shown, over which the dense share comes in: inside a field only. */
export const DENSE_FIELD: readonly [from: number, full: number] = [2, 5];

/** Most light the dense share adds at a pixel, in the bloom's light there: grain, never a speck. */
export const DENSE_CAP = 1;

/** Light at the middle of a lone school's blend: its core's gain * 2 pi sigma^2 spread over the blend. */
export function loneBlendPeak(style: GlowFrameStyle): number {
  return (style.gain * style.blend * style.coreSigmaPx ** 2) / style.blendSigmaPx ** 2;
}

/** Sigma of the blend, CSS px: about 15 km at zoom 4, wide enough to merge rural neighbors, inside the bloom's reach. */
export const BLEND_SIGMA_STOPS: ZoomStops = [
  [4.5, 4],
  [5, 7],
  [6, 11],
];

/** Least sigma of the blend, CSS px, which shrinks with the map below zoom 4: narrower reads as a dot. */
export const BLEND_MIN_SIGMA_PX = 2;

/** Cut on the blend's core light below zoom 4, so a band lights each pixel as on a desktop, not washed out. */
export function blendCutAtScale(sizeScale: number): number {
  return sizeScale < 1 ? sizeScale ** 1.5 : 1;
}

/** A lone school's blend peak on a phone, which its own light spread over 2 px would leave under the state lines. */
export const BLEND_FLOOR_LIGHT = 0.15;

/** Sizes (glowSizeScale) at which {@link BLEND_FLOOR_LIGHT} is all and none of a lone school's peak. */
export const BLEND_LIFT_SCALES: readonly [full: number, none: number] = [0.3, 0.58];

/** Blend light shown for `total`, raised by `gain` up to a lone school's peak (`knee`) and never less above it. */
export function blendFloor(total: number, gain: number, knee: number): number {
  if (!(gain > 1) || !(total > 0)) return total;
  const x2 = (total / (FLOOR_ROOM * knee)) ** 2;
  const x8 = (x2 * x2) ** 2;
  return Math.max(total, (gain * total) / Math.sqrt(Math.sqrt(Math.sqrt(1 + x8))));
}

/** How far past a lone school's raised peak the floor rises before the light takes over. */
const FLOOR_ROOM = 1.25;

/** GLSL for {@link blendFloor}, on the four statuses' light at a pixel. */
export const BLEND_FLOOR_GLSL = /* glsl */ `
vec4 glow_blend_floor(vec4 light, float gain, float knee) {
  float total = light.r + light.g + light.b + light.a;
  if (gain <= 1.0 || total <= 0.0) return light;
  float x = total / (${FLOOR_ROOM.toFixed(2)} * knee);
  float x2 = x * x;
  float x8 = x2 * x2 * x2 * x2;
  return light * max(1.0, gain / sqrt(sqrt(sqrt(1.0 + x8))));
}
// Eight directions, for samples of the light around a pixel.
const vec2 GLOW_RING[8] = vec2[8](
  vec2(1.0, 0.0), vec2(0.70710678, 0.70710678), vec2(0.0, 1.0), vec2(-0.70710678, 0.70710678),
  vec2(-1.0, 0.0), vec2(-0.70710678, -0.70710678), vec2(0.0, -1.0), vec2(0.70710678, -0.70710678)
);
`;

/** {@link blendFloor}'s gain that shows a knee's light as `peak`, less 2% of the knee, and none at no lift. */
export function floorGain(knee: number, peak: number): number {
  return peak > knee ? 1 + (peak / knee - 1) * (1 + FLOOR_ROOM ** -8) ** 0.125 : 1;
}

/** How far around a pixel the dense share looks for its field, CSS px. */
export function fieldReachPx(style: GlowFrameStyle): number {
  return 5 * style.blendSigmaPx;
}

/** Widest texel, CSS px, of the level the blend is blurred from: a coarser one would show its texels. */
export const BLEND_LEVEL_PX = 4;

/** Bloom weights for each entry of {@link BLOOM_SCALES_PX} at `zoom`, before the blend. */
function ownBloomWeights(zoom: number): number[] {
  return BLOOM_SCALES_PX.map((_, i) =>
    interpolateStops(
      BLOOM_WEIGHT_STOPS.map(([z, weights]) => [z, weights[i] ?? 0] as const),
      zoom,
    ),
  );
}

/** Share of a bloom scale the blend takes: all of one no wider, none of one √2 times wider, smoothly between. */
export function blendShareOfScale(scalePx: number, sigmaPx: number): number {
  return Math.min(Math.max(1 - 2 * Math.log2(scalePx / sigmaPx), 0), 1);
}

/** The bloom and the blend at `zoom` with the glow shrunk by `sizeScale`; see {@link GlowFrameStyle}. */
function bloomAndBlend(
  zoom: number,
  sizeScale: number,
): { bloom: number[]; blend: number; blendSigmaPx: number } {
  // Relative to the cores, whose light already falls with the square root (glowSizeScale).
  const bloom = ownBloomWeights(zoom).map((weight) => weight * sizeScale * Math.sqrt(sizeScale));
  const blendSigmaPx = Math.max(
    interpolateStops(BLEND_SIGMA_STOPS, zoom) * sizeScale,
    BLEND_MIN_SIGMA_PX,
  );
  const moved = 1 - interpolateStops(CORE_SHARE_STOPS, zoom);
  if (!(moved > 0)) return { bloom, blend: 0, blendSigmaPx };
  // The cores' light that is not shown, and the same share of the fine scales'.
  let blend = moved * blendCutAtScale(sizeScale);
  bloom.forEach((weight, i) => {
    const scalePx = (BLOOM_SCALES_PX[i] ?? 0) * sizeScale;
    const share = moved * blendShareOfScale(scalePx, blendSigmaPx);
    blend += weight * share;
    bloom[i] = weight * (1 - share);
  });
  return { bloom, blend, blendSigmaPx };
}

/** Bloom weights for each entry of {@link BLOOM_SCALES_PX} at `zoom`, less the light the blend carries. */
export function bloomWeights(zoom: number): number[] {
  return bloomAndBlend(zoom, glowSizeScale(zoom)).bloom;
}

/** How the layer makes the blend on a light target of `targetPxPerCssPx`. */
export interface BlendPlan {
  /** The bloom level it is made from and added back into, 1 the first below the light target. */
  readonly level: number;
  /** Standard deviation of its blur in that level's texels, 0 for none. */
  readonly sigmaTexels: number;
  /** Blur taps on each side of the center. */
  readonly radius: number;
}

export function blendPlan(style: GlowFrameStyle, targetPxPerCssPx: number): BlendPlan {
  // Shrunk below zoom 4, a level at least half blurred, so a lone school's peak holds as it moves.
  const widest =
    (style.blendSigmaPx < BLEND_LEVEL_PX ? style.blendSigmaPx / Math.SQRT2 : BLEND_LEVEL_PX) *
    targetPxPerCssPx;
  // On a light target between powers of two the next coarser level would be wider than the blend.
  const level = Math.max(1, Math.floor(Math.log2(widest) + 1e-9));
  const scalePx = 2 ** level / targetPxPerCssPx;
  // The level already spreads a point over about its own scale; the blur adds the rest.
  const sigmaTexels = Math.sqrt(Math.max(style.blendSigmaPx ** 2 - scalePx ** 2, 0)) / scalePx;
  return { level, sigmaTexels, radius: Math.ceil(3 * sigmaTexels) };
}

/** Coarsest bloom level, CSS px per texel. */
export const MAX_BLOOM_SCALE_PX = 64;

/** Bloom levels with less weight than this are not drawn. */
export const MIN_BLOOM_WEIGHT = 1e-3;

/**
 * The bloom levels the layer draws, finest first, as their weights: level i
 * has texels of 2^(i + 1) / targetPxPerCss CSS px, out to the first level at
 * least MAX_BLOOM_SCALE_PX wide or as far as a light target whose smaller side
 * is `sizePx` target px has room for. Trailing levels that add nothing are left out.
 *
 * A scale that lands on a level, as every full-size one does on a light
 * target of one or two pixels per CSS pixel, goes to that level. One that
 * falls between two levels, shrunk (glowSizeScale) or on a light target
 * between powers of two (a browser zoomed out), is shared out between them so
 * that together they spread it as far as the scale would. A scale finer than
 * the first level or coarser than the last goes to that level. So the bloom
 * keeps all of its light and its reach at any zoom and resolution, and the
 * look does not depend on the light target's resolution.
 */
export function bloomLevels(
  style: GlowFrameStyle,
  targetPxPerCss: number,
  sizePx: number,
): number[] {
  const scales: number[] = [];
  let size = sizePx;
  for (let level = 1; ; level++) {
    const scale = 2 ** level / targetPxPerCss;
    size = Math.ceil(size / 2);
    if ((scale / 2 >= MAX_BLOOM_SCALE_PX * 0.99 && level > 1) || size < 2) break;
    scales.push(scale);
  }
  const first = scales[0];
  if (first === undefined) return [];
  const weights = scales.map(() => 0);
  const last = scales.length - 1;
  style.bloom.forEach((weight, i) => {
    const at = Math.log2(((BLOOM_SCALES_PX[i] ?? 0) * style.sizeScale) / first);
    const lo = Math.min(Math.max(Math.floor(at), 0), last);
    // The coarser level's share, twice as wide, that keeps the scale's mean square spread.
    const t = Math.min(Math.max((4 ** (at - lo) - 1) / 3, 0), 1);
    const hi = Math.min(lo + 1, last);
    weights[lo] = (weights[lo] ?? 0) + weight * (1 - t);
    weights[hi] = (weights[hi] ?? 0) + weight * t;
  });
  while (weights.length > 0 && (weights[weights.length - 1] ?? 0) < MIN_BLOOM_WEIGHT) {
    weights.pop();
  }
  return weights;
}

/** The blend's blur in one frame, and the light it adds back into its level. */
export interface BlendBlur extends BlendPlan {
  readonly weight: number;
}

/** What the layer draws for the bloom and the blend in one frame. */
export interface BloomPlan {
  /** Weight of each bloom level drawn, level 1 (texels of 2 / targetPxPerCssPx CSS px) first. */
  readonly weights: readonly number[];
  /** The blend's blur, or null when there is no blend or it needs none. */
  readonly blur: BlendBlur | null;
}

/** The bloom's levels and the blend on a light target whose smaller side is `sizePx` target px. */
export function bloomPlan(
  style: GlowFrameStyle,
  targetPxPerCssPx: number,
  sizePx: number,
): BloomPlan {
  const weights = bloomLevels(style, targetPxPerCssPx, sizePx);
  if (!(style.blend > 0)) return { weights, blur: null };
  const plan = blendPlan(style, targetPxPerCssPx);
  if ((plan.radius > 0 || style.floorGain > 1) && plan.level < weights.length) {
    // Blurred or floored, then added into its level on the way up, which needs a coarser level above.
    return { weights, blur: { ...plan, weight: style.blend } };
  }
  // A blend that needs no blur, or has no room for one, is its level as it is, if there is room.
  let size = sizePx;
  for (let level = 1; level <= plan.level; level++) size = Math.ceil(size / 2);
  if (size >= 2) {
    while (weights.length < plan.level) weights.push(0);
    weights[plan.level - 1] = (weights[plan.level - 1] ?? 0) + style.blend;
  }
  return { weights, blur: null };
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
 * zoom 5 to 10, where the blend and the bloom still reach past it and fewer
 * points are on screen; the same from zoom 11, where there is no bloom to
 * stand in for. Nationally, where every point is on screen, it stays at
 * 20 px to hold the per-frame fill down.
 */
export const FALLBACK_HALO_RADIUS_STOPS: ZoomStops = [
  [3, 20],
  [4.5, 20],
  [6, 36],
  [7.5, 30],
  [9.5, 26],
  [11, 12],
];

/** The fallback's per-point halo at a zoom: its own halo, the folded bloom and the blend, shrinking as the blend does. */
export function fallbackHalo(style: GlowFrameStyle, zoom: number): HaloShape {
  const folded = style.bloom.reduce((sum, w, i) => sum + w * (FALLBACK_BLOOM_FOLD[i] ?? 0), 0);
  const spread = folded + style.blend;
  const energy = style.haloEnergy + spread;
  if (!(spread > 0)) {
    return { energy, sigmaShare: HALO_SIGMA_SHARE, radiusPx: style.haloRadiusPx };
  }
  const shrink = style.blendSigmaPx / interpolateStops(BLEND_SIGMA_STOPS, zoom);
  const radiusPx = Math.max(
    style.haloRadiusPx,
    interpolateStops(FALLBACK_HALO_RADIUS_STOPS, zoom) * shrink,
  );
  return {
    energy,
    sigmaShare:
      (style.haloEnergy * HALO_SIGMA_SHARE +
        folded * FALLBACK_BLOOM_SIGMA_SHARE +
        style.blend * (style.blendSigmaPx / radiusPx)) /
      energy,
    radiusPx,
  };
}

/** The 8-bit fallback's {@link blendFloor}, raising a lone school's halo peak to the float path's. */
export function fallbackFloor(style: GlowFrameStyle, zoom: number): { gain: number; knee: number } {
  if (!(style.floorGain > 1)) return { gain: 1, knee: 1 };
  const k = kernelUniforms(style, 1, fallbackHalo(style, zoom), style.coreShare);
  const knee = style.gain * kernelAt(k, 0);
  return { gain: floorGain(knee, fieldPeak(style)), knee };
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
 * energy-weighted RMS spread of core, own halo, bloom and blend. The curve
 * the zoom-behavior tests pin down: wide nationally, tightening from zoom 6,
 * a small halo from zoom 11.
 */
export function glowReachPx(zoom: number): number {
  const style = glowStyleAtZoom(zoom);
  const core = style.coreSigmaPx;
  const haloSigma = HALO_SIGMA_SHARE * style.haloRadiusPx;
  let energy = style.coreShare;
  let moment = style.coreShare * core * core;
  energy += style.haloEnergy;
  moment += style.haloEnergy * haloSigma * haloSigma;
  style.bloom.forEach((weight, i) => {
    const scale = (BLOOM_SCALES_PX[i] ?? 0) * style.sizeScale;
    energy += weight;
    moment += weight * scale * scale;
  });
  // A lone point's blend stands on its floor.
  const blend = style.blend > 0 ? (style.blend * fieldPeak(style)) / style.floorKnee : 0;
  energy += blend;
  moment += blend * style.blendSigmaPx * style.blendSigmaPx;
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

// --- small screens -----------------------------------------------------------------

/**
 * About the zoom of a desktop's national view. From it up the glow is the
 * stops' own; below it the glow shrinks with the map (glowSizeScale).
 */
export const FULL_SIZE_ZOOM = 4;

/**
 * Factor on the glow's reach and light below FULL_SIZE_ZOOM, where screens
 * smaller than a desktop's open on the whole country: a small laptop at about
 * zoom 3.7, a tablet at 3.1, a phone at 2.1.
 *
 * With every size in CSS pixels, the bloom on a phone's national view would
 * reach four times as far across the country as on a desktop's, and each
 * school's light would pile into a sixteenth of the area: a storm's band would
 * lay a pale haze over half the country. So below FULL_SIZE_ZOOM the factor
 * shrinks with the map itself, as a desktop's national view would shrink to
 * fit. The halo and bloom scales shrink by it (bloomLevels), and the bloom's
 * light per point falls with its square, the map's area: on every screen the
 * bloom reaches as far across the country, and lays as much light on it. The
 * core keeps its size, about the smallest the CSS-pixel light target draws
 * without showing its pixels, and its light falls only with the factor's
 * square root, so a lone school stays well above the grey of the state lines
 * even at a small phone's widest zoom. The price is a band of schools, its
 * light packed closer, brighter than on a desktop: on a phone's national view
 * about twice as much of it reaches the tone map's pale top. Nationally the
 * blend carries the cores' light; it shrinks with the map too, but not below
 * {@link BLEND_MIN_SIGMA_PX}, where it would read as dots. The factor meets
 * 1 at FULL_SIZE_ZOOM without easing in: a smooth join would reach farther
 * than a desktop just below it, where small laptops open.
 */
export function glowSizeScale(zoom: number): number {
  return zoom < FULL_SIZE_ZOOM ? 2 ** (zoom - FULL_SIZE_ZOOM) : 1;
}

// --- one frame ---------------------------------------------------------------------

/** Everything the layer needs for one frame at a given zoom. */
export interface GlowFrameStyle {
  /**
   * {@link glowSizeScale}, 1 from zoom 4 up. The halo radius here is scaled
   * by it already, the gain and the blend by its square root and the bloom
   * weights by its 1.5th power; the bloom scales take it where the layer
   * reads them (bloomLevels).
   */
  readonly sizeScale: number;
  readonly coreSigmaPx: number;
  /** Width the core is drawn at, as a share of coreSigmaPx; see {@link CORE_FOCUS_STOPS}. */
  readonly coreFocus: number;
  /** Share of the fine light shown where it is; see {@link CORE_SHARE_STOPS}. */
  readonly coreShare: number;
  /** Share of the cores shown sharp where they pile up; see {@link DENSE_SHARE_STOPS}. */
  readonly denseShare: number;
  readonly gain: number;
  readonly haloRadiusPx: number;
  readonly haloEnergy: number;
  /** Weights for {@link BLOOM_SCALES_PX}, less the light the blend carries. */
  readonly bloom: readonly number[];
  /** Light in the blend relative to the cores, and its standard deviation, CSS px. */
  readonly blend: number;
  readonly blendSigmaPx: number;
  /** {@link blendFloor}'s gain on the blend, 1 from zoom 4 up, and its knee, a lone school's blend peak. */
  readonly floorGain: number;
  readonly floorKnee: number;
  readonly glyphOpacity: number;
  readonly glyphRadiusPx: number;
  readonly openRadiusPx: number;
}

export function glowStyleAtZoom(zoom: number): GlowFrameStyle {
  const sizeScale = glowSizeScale(zoom);
  const coreShare = interpolateStops(CORE_SHARE_STOPS, zoom);
  const style = {
    sizeScale,
    coreSigmaPx: interpolateStops(CORE_SIGMA_STOPS, zoom),
    // On a small screen's national view a pile of cores is a town, as on a desktop's.
    coreFocus: interpolateStops(CORE_FOCUS_STOPS, zoom) * sizeScale,
    coreShare,
    denseShare: interpolateStops(DENSE_SHARE_STOPS, zoom),
    gain: interpolateStops(GAIN_STOPS, zoom) * Math.sqrt(sizeScale),
    haloRadiusPx: interpolateStops(HALO_RADIUS_STOPS, zoom) * sizeScale,
    haloEnergy: interpolateStops(HALO_ENERGY_STOPS, zoom),
    ...bloomAndBlend(zoom, sizeScale),
    floorGain: 1,
    floorKnee: 0,
    glyphOpacity: smoothstep(GLYPH_FADE_START, GLYPH_FADE_END, zoom),
    glyphRadiusPx: interpolateStops(GLYPH_RADIUS_STOPS, zoom),
    openRadiusPx: interpolateStops(OPEN_RADIUS_STOPS, zoom),
  };
  const knee = loneBlendPeak(style);
  // A lone school keeps the light the cut takes, and on a phone shows at the floor's light.
  const uncut =
    knee *
    ((style.blend + (1 - coreShare) * (1 - blendCutAtScale(sizeScale))) /
      Math.max(style.blend, 1e-12));
  const [full, none] = BLEND_LIFT_SCALES;
  const peak = uncut + Math.max(BLEND_FLOOR_LIGHT - uncut, 0) * smoothstep(none, full, sizeScale);
  return { ...style, floorGain: floorGain(knee, peak), floorKnee: knee };
}

/** A lone school's blend peak as shown, after {@link blendFloor}. */
export function fieldPeak(style: GlowFrameStyle): number {
  return blendFloor(style.floorKnee, style.floorGain, style.floorKnee);
}

/**
 * The per-point kernel in the units the shader wants, for a light target
 * whose pixels are `targetPxPerCssPx` of a CSS pixel. With d the distance
 * over the sprite radius, the kernel is
 *
 *   coreWeight * exp(-d^2 * coreFalloff)
 *     + haloWeight * exp(-d^2 * haloFalloff) * (1 - d^2)^2 * hole(d)
 *
 * The core is a Gaussian, drawn at {@link coreDrawnPx} with its light kept.
 * To keep a sub-pixel core from shimmering while the map pans, its variance is
 * widened by the footprint of one target pixel and its peak lowered to match,
 * so the light it adds stays the same. The halo is a wider Gaussian windowed
 * to reach zero at the sprite edge; `hole` cuts it away under a glyph.
 */
export interface KernelUniforms {
  /** Sprite radius in target pixels. */
  readonly radius: number;
  readonly coreFalloff: number;
  /** Core peak relative to an unfiltered core at its own width: above 1 drawn narrower. */
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

/** `coreShare` is the share of the core drawn: all on the float path, whose bloom needs it; the shown share on the fallback. */
export function kernelUniforms(
  style: GlowFrameStyle,
  targetPxPerCssPx: number,
  halo: HaloShape = {
    energy: style.haloEnergy,
    sigmaShare: HALO_SIGMA_SHARE,
    radiusPx: style.haloRadiusPx,
  },
  coreShare = 1,
): KernelUniforms {
  const haloEnergy = halo.energy;
  const sigma = style.coreSigmaPx * targetPxPerCssPx;
  const drawn = coreDrawnPx(style, targetPxPerCssPx);
  const sigmaEff2 = drawn * drawn + FOOTPRINT_VARIANCE;
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
    coreWeight: ((sigma * sigma) / sigmaEff2) * (1 - style.glyphOpacity) * coreShare,
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

/** Least width a core is drawn at, target px: narrower, a moving core aliases into the bloom. */
export const MIN_CORE_DRAWN_PX = 0.7;

/** Sigma a core is drawn at, light-target px: its focused width, no narrower than {@link MIN_CORE_DRAWN_PX}. */
export function coreDrawnPx(style: GlowFrameStyle, targetPxPerCssPx: number): number {
  const sigma = style.coreSigmaPx * targetPxPerCssPx;
  return Math.max(sigma * style.coreFocus, Math.min(sigma, MIN_CORE_DRAWN_PX));
}

/** The dense share, less where cores are drawn wider than focused: overlapping, a field would read as piled. */
export function denseShareAt(style: GlowFrameStyle, targetPxPerCssPx: number): number {
  const focused = style.coreSigmaPx * targetPxPerCssPx * style.coreFocus;
  return style.denseShare * Math.min(1, (focused / coreDrawnPx(style, targetPxPerCssPx)) ** 2);
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
