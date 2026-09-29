/**
 * How the glow looks at each zoom. All sizes are CSS pixels; the layer scales
 * them by the device pixel ratio and the light target's resolution.
 *
 * Each point is a small bright core. Around it, light spreads at several
 * scales at once, like city lights seen through air:
 *
 * - Zoom 4 to 6, a desktop's national view: no core is shown. Its light, and
 *   the bloom's finest, is carried by the blend instead, one smooth Gaussian
 *   some 10 to 15 km wide, so the points read as one field, a dim wash where
 *   schools are few and bright where they are many, like a night photo from
 *   orbit at low resolution. Wide bloom out to about 64 px merges a metro
 *   into one glow.
 * - Below zoom 4, where screens smaller than a desktop's open on the whole
 *   country, the glow shrinks with the map (glowSizeScale), so the country
 *   looks as on a desktop: the bloom reaches 32 px at zoom 3, 16 px at 2.
 *   Only the blend stops shrinking, at 3 px, so the points still read as one
 *   field on a phone, where the blend of a lone school is lifted so it shows
 *   above the state lines (BLEND_LIFT).
 * - From zoom 6 the cores come back, each school resolving by zoom 8, and the
 *   wide scales fade out as the glow tightens.
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

/**
 * Share of the fine light shown where it is: each point's core, and the
 * bloom's scales no wider than the blend. None nationally, where cores a few
 * pixels apart read as a scatter of specks rather than as light; all of it
 * from zoom 8, where each school stands on its own.
 */
export const CORE_SHARE_STOPS: ZoomStops = [
  [6, 0],
  [8, 1],
];

/**
 * Standard deviation of the blend, CSS px: the fine light that is not shown
 * where it is, spread as one smooth Gaussian. About 15 km at zoom 4 and 10 km
 * at zoom 6, wide enough to merge neighboring rural schools into one field
 * and well inside the bloom's own reach, so the light stays over the schools
 * that make it. Below zoom 4 it shrinks with the map, to no less than
 * {@link BLEND_MIN_SIGMA_PX}.
 */
export const BLEND_SIGMA_STOPS: ZoomStops = [
  [4.5, 4],
  [5, 7],
  [6, 11],
];

/**
 * Least standard deviation of the blend, CSS px. Below zoom 4 the blend
 * shrinks with the map as the bloom does, so a small laptop's national view
 * is a desktop's made smaller. Much under this a point's blend reads as a dot
 * again, so a tablet's and a phone's national views hold it here: some 40 km
 * across the country on a phone, where a desktop's 4 px are 15 km, still
 * well inside the bloom's reach, which shrinks all the way.
 */
export const BLEND_MIN_SIGMA_PX = 3;

/**
 * Most that the blend of a lone school is lifted on a phone, over its own
 * light. Held at {@link BLEND_MIN_SIGMA_PX} while the map shrinks, a lone
 * school's blend keeps only the share of its light that falls with the square
 * root of the map's width, spread over a phone's 3 px: at a phone's widest
 * zoom 33 of 255 where a desktop's is 49, under half the state lines a phone
 * draws brighter (77). So below a tablet's zoom the blend is lifted where
 * there is no other light {@link BLEND_LIFT_REACH} blend widths around it. A
 * lone school, or a few far from others, shows above the lines; a field of
 * schools, and the light at the edge of a band of them, have light that close
 * and keep theirs.
 */
export const BLEND_LIFT = 8;

/**
 * How far around the blend the lift looks for other light, in standard
 * deviations of the blend: past a lone school's own blend, and as far as the
 * 8-bit fallback's halo reaches (15 px on a phone).
 */
export const BLEND_LIFT_REACH = 5;

/**
 * Light that far around, per light-target pixel of all statuses, at which
 * the lift has fallen to 1/e of its most: a tenth of a sparse field's, with
 * schools 60 km apart on a phone.
 */
export const BLEND_LIFT_KNEE = 0.005;

/**
 * {@link BLEND_LIFT}'s share by {@link glowSizeScale}: all of it on a phone's
 * national and widest views (a factor up to 0.3), none from a factor of 0.6
 * (zoom 3.26), so a tablet's view is nearly a desktop's and a laptop's is not
 * touched.
 */
export const BLEND_LIFT_SCALES: readonly [full: number, none: number] = [0.3, 0.6];

/** How far around the blend its lift looks for other light, CSS px; see {@link BLEND_LIFT_REACH}. */
export function liftReachPx(style: GlowFrameStyle): number {
  return BLEND_LIFT_REACH * style.blendSigmaPx;
}

/** The lift on a lone school's blend for a glow shrunk by `sizeScale`; see {@link BLEND_LIFT}. */
export function blendLiftAtScale(sizeScale: number): number {
  const [full, none] = BLEND_LIFT_SCALES;
  return BLEND_LIFT * smoothstep(none, full, sizeScale);
}

/**
 * Factor on the blend where the light {@link BLEND_LIFT_REACH} blend widths
 * around it averages `context` (all statuses summed), with lift `lift`. JS
 * mirror of the shader.
 */
export function blendLiftFactor(context: number, lift: number): number {
  return 1 + lift * Math.exp(-context / BLEND_LIFT_KNEE);
}

/**
 * GLSL for {@link blendLiftFactor}: `light` lifted by `lift` where `around`,
 * the sum of eight samples of light that far around it, is dark.
 */
export const BLEND_LIFT_GLSL = /* glsl */ `
const float GLOW_BLEND_LIFT_KNEE = ${String(BLEND_LIFT_KNEE)};
vec4 glow_blend_lift(vec4 light, vec4 around, float lift) {
  float context = (around.r + around.g + around.b + around.a) / 8.0;
  return light * (1.0 + lift * exp(-context / GLOW_BLEND_LIFT_KNEE));
}
// Eight directions, for the samples around.
const vec2 GLOW_LIFT_RING[8] = vec2[8](
  vec2(1.0, 0.0), vec2(0.70710678, 0.70710678), vec2(0.0, 1.0), vec2(-0.70710678, 0.70710678),
  vec2(-1.0, 0.0), vec2(-0.70710678, -0.70710678), vec2(0.0, -1.0), vec2(0.70710678, -0.70710678)
);
`;

/**
 * The bloom level the blend is made from, CSS px a texel. A blend no wider
 * than this is that level as it is; a wider one is that level blurred, once
 * across and once down, so it stays round and smooth where a coarser level
 * would show its texels. A narrower one, below zoom 4, is the next finer
 * level blurred.
 */
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

/**
 * Share of a bloom scale that joins a blend of standard deviation `sigmaPx`:
 * all of a scale no wider than the blend, none of one √2 times wider, and in
 * between by log2 of the ratio, so nothing jumps as the blend widens.
 */
export function blendShareOfScale(scalePx: number, sigmaPx: number): number {
  return Math.min(Math.max(1 - 2 * Math.log2(scalePx / sigmaPx), 0), 1);
}

/**
 * The bloom and the blend at `zoom`, with the glow shrunk by `sizeScale`
 * ({@link glowSizeScale}); see {@link GlowFrameStyle}. The bloom's weights
 * are cut by it and its scales shrink by it, so more of them fall inside the
 * blend on a small screen. The cores' light in the blend is cut only by the
 * gain, as the cores' own light is.
 */
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
  let blend = moved;
  bloom.forEach((weight, i) => {
    const scalePx = (BLOOM_SCALES_PX[i] ?? 0) * sizeScale;
    const share = moved * blendShareOfScale(scalePx, blendSigmaPx);
    blend += weight * share;
    bloom[i] = weight * (1 - share);
  });
  return { bloom, blend, blendSigmaPx };
}

/**
 * Bloom weights for each entry of {@link BLOOM_SCALES_PX} at `zoom`, less the
 * light the blend carries, and cut by {@link glowSizeScale} below zoom 4.
 */
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
  let level = Math.max(1, Math.round(Math.log2(BLEND_LEVEL_PX * targetPxPerCssPx)));
  if (style.blendSigmaPx < BLEND_LEVEL_PX) {
    // Shrunk below zoom 4: the finest level that is no wider than the blend.
    while (level > 1 && 2 ** level / targetPxPerCssPx > style.blendSigmaPx) level--;
  }
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
 * has texels of 2^(i + 1) / targetPxPerCss CSS px, out to MAX_BLOOM_SCALE_PX
 * or as far as a light target whose smaller side is `sizePx` target px has
 * room for. Trailing levels that add nothing are left out.
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
    if (scale > MAX_BLOOM_SCALE_PX * 1.01 || size < 2) break;
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
  /**
   * Weight of each bloom level drawn, level 1 first, whose texels are
   * 2 / targetPxPerCssPx CSS px and each level's twice the last. A blend
   * that needs no blur is in its level's weight.
   */
  readonly weights: readonly number[];
  /** The blend's blur, or null when there is no blend or it needs none. */
  readonly blur: BlendBlur | null;
}

/**
 * What the layer draws for the bloom and the blend on a light target of
 * `targetPxPerCssPx` whose smaller side is `sizePx` target px: the bloom's
 * levels ({@link bloomLevels}) and the blend, added into its level where it
 * needs no blur, or blurred there.
 */
export function bloomPlan(
  style: GlowFrameStyle,
  targetPxPerCssPx: number,
  sizePx: number,
): BloomPlan {
  const weights = bloomLevels(style, targetPxPerCssPx, sizePx);
  if (!(style.blend > 0)) return { weights, blur: null };
  const plan = blendPlan(style, targetPxPerCssPx);
  if (plan.radius > 0 && plan.level < weights.length) {
    // Blurred, then added into its level on the way up, which needs a coarser level above it.
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

/**
 * The fallback's per-point halo at a zoom: its own halo, the folded bloom
 * and the blend. The blend is the point's own fine light, so all of it goes
 * in, at its own spread as far as the halo's radius allows. Below zoom 4 the
 * halo shrinks as the blend does, with the map until the blend stops at
 * {@link BLEND_MIN_SIGMA_PX}, so it holds the blend as on a desktop.
 */
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
  energy += style.blend;
  moment += style.blend * style.blendSigmaPx * style.blendSigmaPx;
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
  /** Share of the fine light shown where it is; see {@link CORE_SHARE_STOPS}. */
  readonly coreShare: number;
  readonly gain: number;
  readonly haloRadiusPx: number;
  readonly haloEnergy: number;
  /** Weights for {@link BLOOM_SCALES_PX}, less the light the blend carries. */
  readonly bloom: readonly number[];
  /** Light in the blend relative to the cores, and its standard deviation, CSS px. */
  readonly blend: number;
  readonly blendSigmaPx: number;
  /** Lift on the blend's faint light on a phone, 0 from a tablet's zoom up; see {@link BLEND_LIFT}. */
  readonly blendLift: number;
  readonly glyphOpacity: number;
  readonly glyphRadiusPx: number;
  readonly openRadiusPx: number;
}

export function glowStyleAtZoom(zoom: number): GlowFrameStyle {
  const sizeScale = glowSizeScale(zoom);
  return {
    sizeScale,
    coreSigmaPx: interpolateStops(CORE_SIGMA_STOPS, zoom),
    coreShare: interpolateStops(CORE_SHARE_STOPS, zoom),
    gain: interpolateStops(GAIN_STOPS, zoom) * Math.sqrt(sizeScale),
    haloRadiusPx: interpolateStops(HALO_RADIUS_STOPS, zoom) * sizeScale,
    haloEnergy: interpolateStops(HALO_ENERGY_STOPS, zoom),
    ...bloomAndBlend(zoom, sizeScale),
    blendLift: blendLiftAtScale(sizeScale),
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

/**
 * `coreShare` is the share of the core drawn. The float path draws all of it,
 * since its bloom is made from the light target, and its composite shows
 * only `style.coreShare`; the fallback, with no bloom, draws that share itself.
 */
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
