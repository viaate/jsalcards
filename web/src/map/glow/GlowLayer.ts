/**
 * GlowLayer: every affected school as light on a near-black map.
 *
 * A MapLibre custom layer in raw WebGL2. Each frame:
 *
 * 1. prerender, light: every glowing point adds a soft radial kernel into a
 *    half-float (RGBA16F) target, one channel per status, with additive
 *    blending, so a dense area simply gathers more light. The target has a
 *    guard band around the map so light from just off screen still blooms
 *    into view.
 *    Bloom: the target is halved a few times and added back up with a
 *    per-scale weight, which spreads each point's light over 4 to 64 px at a
 *    cost that does not depend on the number of points. Light past a knee
 *    feeds the bloom at a falling rate, so its size has a bound.
 *    The light target has one pixel per CSS pixel by default: full resolution
 *    on a 1x screen, reduced on high-density screens where it reads the same.
 * 2. render, composite: a full-screen pass turns the per-status light into
 *    linear RGB (overlapping statuses blend, the leading one keeps its hue),
 *    tone maps it (Reinhard on luminance, hue preserving) and screens it onto
 *    the map. From zoom 11 a glyph pass draws a crisp per-status shape on
 *    every school, open ones included.
 *
 * Without float render targets the light is gathered in two 8-bit targets
 * at once, a coarse one for dense cores and a fine one for faint halos:
 * points are added in optical depth with screen blending and a zoom-scaled
 * alpha, each carrying most of the bloom in its own halo since there is no
 * bloom pass, and the same composite decodes and tone maps them. The
 * fallback's glow is a little tighter than the float path's; see
 * FALLBACK_ALPHA_STOPS in curves.ts.
 *
 * Points pulse in once from their bornAt. The layer clock is re-based on
 * every setData and a bornAt later than now is moved back to now, so the
 * layer asks for frames for at most one pulse after each setData.
 */
import type {
  CustomLayerInterface,
  CustomRenderMethodInput,
  Map as MapLibreMap,
} from 'maplibre-gl';

import { statusLinearUniform, statusSrgbUniform } from './color';
import {
  FALLBACK_ALPHA_STOPS,
  type GlowFrameStyle,
  type HaloShape,
  PULSE_SECONDS,
  bloomWeightAtScale,
  fallbackHalo,
  glowStyleAtZoom,
  interpolateStops,
  kernelUniforms,
} from './curves';
import {
  type LightFormat,
  type LightTarget,
  type Program,
  createLightTarget,
  createProgram,
  deleteLightTarget,
  supportsHalfFloatTarget,
  uniform,
} from './gl';
import { mercatorXFromLng, mercatorYFromLat } from './mercator';
import {
  type GlowPoints,
  OFFSET_BORN,
  OFFSET_HI,
  OFFSET_LO,
  OFFSET_STATUS,
  PackScratch,
  type PackedPoints,
  STRIDE_BYTES,
  packPoints,
} from './pack';
import {
  ATTRIB,
  COMPOSITE_FRAG,
  DIAMOND_SCALE,
  DOWNSAMPLE_FRAG,
  FULLSCREEN_VERT,
  GLYPH_AA_PX,
  GLYPH_FRAG,
  GLYPH_VERT,
  LIGHT_FRAG,
  LIGHT_VERT,
  UPSAMPLE_FRAG,
} from './shaders';

export interface GlowLayerOptions {
  /** Layer id in the map style. */
  readonly id?: string;
  /**
   * Light target resolution in target pixels per CSS pixel, capped at the
   * device's own. Default 1: soft light at CSS-pixel resolution reads the same
   * as device resolution on a high-density screen. Glyphs always draw at
   * device resolution.
   */
  readonly lightResolution?: number;
  /** Force the 8-bit fallback, as on a device without float render targets. */
  readonly forceFallback?: boolean;
  /** Override `prefers-reduced-motion`. When true, new points appear without a pulse. */
  readonly reducedMotion?: boolean;
  /** Time the layer's GPU work with EXT_disjoint_timer_query_webgl2 when available. */
  readonly gpuTiming?: boolean;
}

export type GlowRenderMode = 'float' | 'fallback' | 'none';

export interface GlowLayerStats {
  /** Frames the layer has drawn. */
  readonly frames: number;
  /** Main-thread time spent in prerender and render for the last frame, ms. */
  readonly lastCpuMs: number;
  /** GPU time of the most recent frame whose timer queries have resolved, ms, or null. */
  readonly lastGpuMs: number | null;
  readonly mode: GlowRenderMode;
  /** Light target size in pixels, guard band included. */
  readonly targetWidth: number;
  readonly targetHeight: number;
  /** Bloom levels drawn in the last frame. */
  readonly bloomLevels: number;
  /** Device pixels per CSS pixel the last frame was drawn at. */
  readonly pixelRatio: number;
  /** Points on the GPU, and how many of them glow. */
  readonly count: number;
  readonly glowCount: number;
  /** Input rows rejected by the last setData. */
  readonly dropped: number;
  /** Rows of the last setData whose bornAt was later than now; they pulsed in at once. */
  readonly bornClamped: number;
}

/** Accumulated light multiplier ahead of the tone map. */
const EXPOSURE = 1;

/**
 * One light-target pixel per CSS pixel. On a 1x screen that is full
 * resolution; on 2x and 3x screens the target is a quarter or a ninth of the
 * device's pixels, which the bench shows reads the same as device resolution.
 */
const DEFAULT_LIGHT_RESOLUTION = 1;

/** Guard band around the map in the light target, CSS px: about the widest bloom's reach. */
const GUARD_CSS_PX = 48;

/** Coarsest bloom level, CSS px per texel. */
const MAX_BLOOM_SCALE_PX = 64;

/** Bloom levels with less weight than this are not drawn. */
const MIN_BLOOM_WEIGHT = 1e-3;

interface GpuResources {
  readonly light: Program;
  readonly down: Program;
  readonly up: Program;
  readonly composite: Program;
  readonly glyph: Program;
  readonly buffer: WebGLBuffer;
  /** Attributes starting at record 0: glowing points, then open ones. */
  readonly vaoAll: WebGLVertexArrayObject;
  /** Attributes starting at the first open record. */
  readonly vaoOpen: WebGLVertexArrayObject;
  /** No attributes, for full-screen passes. */
  readonly vaoEmpty: WebGLVertexArrayObject;
  /** Half-float light targets and bloom; false for the 8-bit fallback. */
  readonly float: boolean;
  readonly format: LightFormat;
  readonly maxPointSize: number;
  readonly maxViewport: readonly [number, number];
  /** levels[0] is the light target; the rest are bloom levels, each half the last. */
  levels: LightTarget[];
  timer: GpuTimer | null;
}

interface FrameState {
  readonly style: GlowFrameStyle;
  readonly zoom: number;
  /** Device pixels per CSS pixel. */
  readonly deviceRatio: number;
  readonly now: number;
  readonly width: number;
  readonly height: number;
  /** Light target pixels per CSS pixel. */
  readonly targetPxPerCss: number;
  /** Light target size, guard band included. */
  readonly targetSize: readonly [number, number];
  /** The map's share of the light target, per axis. */
  readonly mapShare: readonly [number, number];
  /** Bloom levels drawn this frame, and each one's weight. */
  readonly bloomWeights: readonly number[];
  /** The 8-bit fallback's per-point alpha; 0 on the float path. */
  readonly fallbackAlpha: number;
}

interface TimerExt {
  readonly TIME_ELAPSED_EXT: GLenum;
  readonly GPU_DISJOINT_EXT: GLenum;
}

/** Frames whose timer queries may be in flight at once; at most two queries each. */
const MAX_PENDING_TIMED_FRAMES = 4;

/** TIME_ELAPSED queries around the layer's GPU work, read back a few frames late. */
class GpuTimer {
  private readonly free: WebGLQuery[] = [];
  private readonly pending: WebGLQuery[][] = [];
  private current: WebGLQuery[] = [];
  private skipping = false;
  lastMs: number | null = null;

  constructor(
    private readonly gl: WebGL2RenderingContext,
    private readonly ext: TimerExt,
  ) {}

  begin(): void {
    // A GPU that falls behind would otherwise keep adding queries; skip timing until it catches up.
    this.skipping = this.pending.length >= MAX_PENDING_TIMED_FRAMES;
    if (this.skipping) return;
    const query = this.free.pop() ?? this.gl.createQuery();
    this.gl.beginQuery(this.ext.TIME_ELAPSED_EXT, query);
    this.current.push(query);
  }

  end(): void {
    if (!this.skipping) this.gl.endQuery(this.ext.TIME_ELAPSED_EXT);
  }

  /** Closes the frame's queries and reads back any frame whose queries have all resolved. */
  endFrame(): void {
    // Both passes of a frame make the same skip decision, so a frame is timed whole or not at all.
    if (this.current.length > 0) this.pending.push(this.current);
    this.current = [];
    const gl = this.gl;
    const disjoint = gl.getParameter(this.ext.GPU_DISJOINT_EXT) === true;
    for (;;) {
      const oldest = this.pending[0];
      const last = oldest?.[oldest.length - 1];
      if (oldest === undefined || last === undefined) break;
      if (gl.getQueryParameter(last, gl.QUERY_RESULT_AVAILABLE) !== true) break;
      this.pending.shift();
      let ns = 0;
      for (const query of oldest) {
        ns += gl.getQueryParameter(query, gl.QUERY_RESULT) as number;
        this.free.push(query);
      }
      if (!disjoint) this.lastMs = ns / 1e6;
    }
  }

  dispose(): void {
    for (const query of [...this.free, ...this.current, ...this.pending.flat()]) {
      this.gl.deleteQuery(query);
    }
    this.free.length = 0;
    this.pending.length = 0;
    this.current = [];
  }
}

/** Id of the layer drawn right after `id`, to re-insert it in the same place. */
function layerAfter(map: MapLibreMap, id: string): string | undefined {
  const order = map.getLayersOrder();
  const index = order.indexOf(id);
  return index >= 0 ? order[index + 1] : undefined;
}

export class GlowLayer implements CustomLayerInterface {
  readonly id: string;
  readonly type = 'custom' as const;
  readonly renderingMode = '2d' as const;

  private readonly options: GlowLayerOptions;
  /**
   * `performance.now()` the layer clock counts from, in ms. Reset on every
   * setData, so born times and the frame clock stay small float32 values
   * however long the page stays open.
   */
  private clockOrigin = performance.now();
  private readonly scratch = new PackScratch();
  /** Linear-light tokens for the four glowing statuses. */
  private readonly linearTokens = statusLinearUniform().subarray(0, 12);
  private readonly srgbColors = statusSrgbUniform();
  private readonly matrix = new Float32Array(16);

  private map: MapLibreMap | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private res: GpuResources | null = null;
  private packed: PackedPoints | null = null;
  private frame: FrameState | null = null;
  private failed = false;

  private cssWidth = 0;
  private cssWidthFor = -1;
  private motionQuery: MediaQueryList | null = null;
  private prefersReducedMotion = false;

  private contextLost = false;
  private restoreBeforeId: string | undefined;
  private restoreMap: MapLibreMap | null = null;

  private frames = 0;
  private cpuMs = 0;
  private lastCpuMs = 0;
  private lastBloomLevels = 0;
  private lastPixelRatio = 1;

  constructor(options: GlowLayerOptions = {}) {
    this.options = options;
    this.id = options.id ?? 'snowlight-glow';
  }

  /**
   * Replaces every point. Safe to call before or after the layer is on a map.
   * A bornAt later than now pulses in now, so the layer asks for frames for
   * at most one pulse after this call.
   */
  setData(points: GlowPoints): void {
    const nowMs = performance.now();
    this.clockOrigin = nowMs;
    this.packed = packPoints(points, { originMs: nowMs, nowMs }, this.scratch);
    if (this.res !== null && this.gl !== null) this.upload(this.gl, this.res);
    this.map?.triggerRepaint();
  }

  /** The clock `bornAt` uses: `performance.now()` milliseconds. */
  now(): number {
    return performance.now();
  }

  get stats(): GlowLayerStats {
    const res = this.res;
    const target = res?.levels[0];
    return {
      frames: this.frames,
      lastCpuMs: this.lastCpuMs,
      lastGpuMs: res?.timer?.lastMs ?? null,
      mode: res === null ? 'none' : res.float ? 'float' : 'fallback',
      targetWidth: target?.width ?? 0,
      targetHeight: target?.height ?? 0,
      bloomLevels: this.lastBloomLevels,
      pixelRatio: this.lastPixelRatio,
      count: this.packed?.count ?? 0,
      glowCount: this.packed?.glowCount ?? 0,
      dropped: this.packed?.dropped ?? 0,
      bornClamped: this.packed?.bornClamped ?? 0,
    };
  }

  onAdd(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    this.map = map;
    this.gl = gl;
    this.contextLost = false;
    this.restoreMap = null;
    this.failed = false;
    this.cssWidthFor = -1;
    try {
      this.res = this.createResources(gl);
      this.upload(gl, this.res);
    } catch (error) {
      this.failed = true;
      this.res = null;
      console.error(error);
    }
    map.getCanvasContainer().addEventListener('webglcontextlost', this.handleContextLost, true);
    map.off('webglcontextrestored', this.handleContextRestored);
    map.on('webglcontextrestored', this.handleContextRestored);
    this.watchMotion();
  }

  onRemove(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    if (this.res !== null) this.deleteResources(gl, this.res);
    this.res = null;
    this.gl = null;
    this.frame = null;
    map.getCanvasContainer().removeEventListener('webglcontextlost', this.handleContextLost, true);
    // A removal caused by context loss keeps listening so the layer can come back.
    if (!this.contextLost) map.off('webglcontextrestored', this.handleContextRestored);
    this.motionQuery?.removeEventListener('change', this.handleMotionChange);
    this.motionQuery = null;
    this.map = null;
  }

  prerender(gl: WebGL2RenderingContext, args: CustomRenderMethodInput): void {
    const started = performance.now();
    this.frame = null;
    this.cpuMs = 0;
    const res = this.res;
    if (res === null || this.failed || args.shaderData.variantName !== 'mercator') return;
    const frame = this.beginFrame(gl, res);
    const packed = this.packed;
    if (packed !== null && packed.glowCount > 0) {
      res.timer?.begin();
      if (this.ensureLevels(gl, res, frame)) {
        this.drawLight(gl, res, packed, frame, args);
        if (res.float) this.drawBloom(gl, res, frame);
      }
      res.timer?.end();
      gl.bindVertexArray(null);
      gl.bindTexture(gl.TEXTURE_2D, null);
    }
    this.cpuMs += performance.now() - started;
  }

  render(gl: WebGL2RenderingContext, args: CustomRenderMethodInput): void {
    const started = performance.now();
    const res = this.res;
    const packed = this.packed;
    const frame = this.frame;
    if (res === null || frame === null || packed === null || packed.count === 0) {
      this.finishFrame(started, res);
      return;
    }
    res.timer?.begin();
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.SCISSOR_TEST);
    gl.colorMask(true, true, true, true);
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.FUNC_ADD);

    if (packed.glowCount > 0) this.drawComposite(gl, res, frame);
    if (frame.style.glyphOpacity > 0) this.drawGlyphs(gl, res, packed, frame, args);
    gl.bindVertexArray(null);
    gl.bindTexture(gl.TEXTURE_2D, null);
    res.timer?.end();

    // lastBornSeconds is never later than its setData, so this stops one pulse after it at most.
    if (!this.reducedMotion() && packed.lastBornSeconds + PULSE_SECONDS > frame.now) {
      this.map?.triggerRepaint();
    }
    this.finishFrame(started, res);
  }

  // --- frame -------------------------------------------------------------

  private finishFrame(started: number, res: GpuResources | null): void {
    this.cpuMs += performance.now() - started;
    this.lastCpuMs = this.cpuMs;
    this.frames++;
    res?.timer?.endFrame();
  }

  private beginFrame(gl: WebGL2RenderingContext, res: GpuResources): FrameState {
    const map = this.map;
    const width = gl.drawingBufferWidth;
    const height = gl.drawingBufferHeight;
    if (this.cssWidthFor !== width && map !== null) {
      this.cssWidth = map.getCanvas().clientWidth;
      this.cssWidthFor = width;
    }
    const deviceRatio = this.cssWidth > 0 ? width / this.cssWidth : 1;
    const zoom = map?.getZoom() ?? 0;
    const style = glowStyleAtZoom(zoom);
    const targetPxPerCss = Math.min(
      this.options.lightResolution ?? DEFAULT_LIGHT_RESOLUTION,
      deviceRatio,
    );
    const cssW = width / deviceRatio;
    const cssH = height / deviceRatio;
    const w0 = Math.max(1, Math.ceil((cssW + 2 * GUARD_CSS_PX) * targetPxPerCss));
    const h0 = Math.max(1, Math.ceil((cssH + 2 * GUARD_CSS_PX) * targetPxPerCss));

    const bloomWeights: number[] = [];
    if (res.float) {
      let size = Math.min(w0, h0);
      for (let level = 1; ; level++) {
        const scale = 2 ** level / targetPxPerCss;
        size = Math.ceil(size / 2);
        if (scale > MAX_BLOOM_SCALE_PX * 1.01 || size < 2) break;
        bloomWeights.push(bloomWeightAtScale(style.bloom, scale));
      }
      // Drop trailing levels that add nothing.
      while (
        bloomWeights.length > 0 &&
        (bloomWeights[bloomWeights.length - 1] ?? 0) < MIN_BLOOM_WEIGHT
      ) {
        bloomWeights.pop();
      }
    }
    const frame: FrameState = {
      style,
      zoom,
      deviceRatio,
      now: (performance.now() - this.clockOrigin) / 1000,
      width,
      height,
      targetPxPerCss,
      targetSize: [w0, h0],
      mapShare: [(cssW * targetPxPerCss) / w0, (cssH * targetPxPerCss) / h0],
      bloomWeights,
      fallbackAlpha: res.float ? 0 : interpolateStops(FALLBACK_ALPHA_STOPS, zoom),
    };
    this.frame = frame;
    this.lastBloomLevels = bloomWeights.length;
    this.lastPixelRatio = deviceRatio;
    return frame;
  }

  private reducedMotion(): boolean {
    return this.options.reducedMotion ?? this.prefersReducedMotion;
  }

  /**
   * Loads the mercator-to-clip matrix, re-based on a float32 origin near the
   * camera. The product is formed in float64, so after the cast to float32 the
   * translation is small and the per-point math stays precise at any zoom.
   */
  private setPointUniforms(
    gl: WebGL2RenderingContext,
    program: Program,
    args: CustomRenderMethodInput,
    frame: FrameState,
    ndcScale: readonly [number, number],
    maxPointSize: number,
  ): void {
    const m = args.defaultProjectionData.mainMatrix;
    const center = this.map?.getCenter();
    const ox = Math.fround(center === undefined ? 0.5 : mercatorXFromLng(center.lng));
    const oy = Math.fround(center === undefined ? 0.5 : mercatorYFromLat(center.lat));
    const out = this.matrix;
    for (let i = 0; i < 12; i++) out[i] = m[i] ?? 0;
    for (let row = 0; row < 4; row++) {
      out[12 + row] = (m[row] ?? 0) * ox + (m[4 + row] ?? 0) * oy + (m[12 + row] ?? 0);
    }
    gl.uniformMatrix4fv(uniform(program, 'u_matrix'), false, out);
    gl.uniform2f(uniform(program, 'u_origin'), ox, oy);
    gl.uniform2f(uniform(program, 'u_ndcScale'), ndcScale[0], ndcScale[1]);
    gl.uniform1f(uniform(program, 'u_maxPointSize'), maxPointSize);
    gl.uniform1f(uniform(program, 'u_now'), frame.now);
    gl.uniform1f(uniform(program, 'u_motion'), this.reducedMotion() ? 0 : 1);
  }

  private setKernelUniforms(
    gl: WebGL2RenderingContext,
    program: Program,
    frame: FrameState,
    targetPxPerCss: number,
    halo: HaloShape | undefined,
  ): number {
    const kernel = kernelUniforms(frame.style, targetPxPerCss, halo);
    gl.uniform1f(uniform(program, 'u_radius'), kernel.radius);
    gl.uniform1f(uniform(program, 'u_coreFalloff'), kernel.coreFalloff);
    gl.uniform1f(uniform(program, 'u_coreWeight'), kernel.coreWeight);
    gl.uniform1f(uniform(program, 'u_haloFalloff'), kernel.haloFalloff);
    gl.uniform1f(uniform(program, 'u_haloWeight'), kernel.haloWeight);
    gl.uniform1f(uniform(program, 'u_hole'), kernel.hole);
    return kernel.radius;
  }

  /**
   * Sets a viewport larger than the drawing buffer by `margin` on every side,
   * so sprites centered just off screen are not clipped away, and returns the
   * NDC scale that keeps the map aligned inside it.
   */
  private setMarginViewport(
    gl: WebGL2RenderingContext,
    res: GpuResources,
    frame: FrameState,
    marginPx: number,
  ): [number, number] {
    const mx = Math.max(
      0,
      Math.min(Math.ceil(marginPx), Math.floor((res.maxViewport[0] - frame.width) / 2)),
    );
    const my = Math.max(
      0,
      Math.min(Math.ceil(marginPx), Math.floor((res.maxViewport[1] - frame.height) / 2)),
    );
    gl.viewport(-mx, -my, frame.width + 2 * mx, frame.height + 2 * my);
    return [frame.width / (frame.width + 2 * mx), frame.height / (frame.height + 2 * my)];
  }

  /** (Re)allocates the light target and bloom levels for this frame's size. */
  private ensureLevels(gl: WebGL2RenderingContext, res: GpuResources, frame: FrameState): boolean {
    const [w0, h0] = frame.targetSize;
    const first = res.levels[0];
    if (first !== undefined && (first.width !== w0 || first.height !== h0)) {
      for (const level of res.levels) deleteLightTarget(gl, level);
      res.levels = [];
    }
    while (res.levels.length < 1 + frame.bloomWeights.length) {
      const previous = res.levels[res.levels.length - 1];
      const target =
        previous === undefined
          ? createLightTarget(gl, w0, h0, res.format)
          : createLightTarget(
              gl,
              Math.ceil(previous.width / 2),
              Math.ceil(previous.height / 2),
              res.format,
            );
      if (target === null) return false;
      res.levels.push(target);
    }
    return true;
  }

  private drawLight(
    gl: WebGL2RenderingContext,
    res: GpuResources,
    packed: PackedPoints,
    frame: FrameState,
    args: CustomRenderMethodInput,
  ): void {
    const target = res.levels[0];
    if (target === undefined) return;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
    gl.viewport(0, 0, target.width, target.height);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.SCISSOR_TEST);
    gl.colorMask(true, true, true, true);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.FUNC_ADD);
    if (res.float) {
      gl.blendFunc(gl.ONE, gl.ONE);
    } else {
      // Screen: 1 - (1 - a)(1 - b), which adds light in the optical-depth encoding.
      gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_COLOR, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    }

    const program = res.light;
    gl.useProgram(program.program);
    this.setPointUniforms(gl, program, args, frame, frame.mapShare, res.maxPointSize);
    // The fallback has no bloom, so each point carries most of the bloom's light in its own halo.
    const halo = res.float ? undefined : fallbackHalo(frame.style, frame.zoom);
    this.setKernelUniforms(gl, program, frame, frame.targetPxPerCss, halo);
    gl.uniform1f(uniform(program, 'u_gain'), frame.style.gain);
    gl.uniform1f(uniform(program, 'u_encode'), frame.fallbackAlpha);
    gl.bindVertexArray(res.vaoAll);
    gl.drawArrays(gl.POINTS, 0, packed.glowCount);
  }

  /**
   * Halves the light target once per bloom level, then walks back up to level
   * 1: each step tent-upsamples the coarser level onto the finer one, which
   * the blend first scales by its own weight. Level 1 ends up holding every
   * weighted scale of bloom; the composite adds it to the core light.
   */
  private drawBloom(gl: WebGL2RenderingContext, res: GpuResources, frame: FrameState): void {
    const weights = frame.bloomWeights;
    if (weights.length === 0) return;
    gl.bindVertexArray(res.vaoEmpty);
    gl.activeTexture(gl.TEXTURE0);

    gl.disable(gl.BLEND);
    const down = res.down;
    gl.useProgram(down.program);
    gl.uniform1i(uniform(down, 'u_source'), 0);
    for (let i = 1; i <= weights.length; i++) {
      const source = res.levels[i - 1];
      const target = res.levels[i];
      if (source === undefined || target === undefined) return;
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
      gl.viewport(0, 0, target.width, target.height);
      gl.bindTexture(gl.TEXTURE_2D, source.texture);
      gl.uniform2f(uniform(down, 'u_texel'), 1 / source.width, 1 / source.height);
      // Only the light target's own pixels are eased past the bloom knee.
      gl.uniform1f(uniform(down, 'u_limit'), i === 1 ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    if (weights.length < 2) return;

    gl.enable(gl.BLEND);
    gl.blendEquation(gl.FUNC_ADD);
    gl.blendFunc(gl.ONE, gl.CONSTANT_COLOR);
    const up = res.up;
    gl.useProgram(up.program);
    gl.uniform1i(uniform(up, 'u_source'), 0);
    for (let i = weights.length; i >= 2; i--) {
      const source = res.levels[i];
      const target = res.levels[i - 1];
      if (source === undefined || target === undefined) return;
      const keep = weights[i - 2] ?? 0;
      gl.blendColor(keep, keep, keep, keep);
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
      gl.viewport(0, 0, target.width, target.height);
      gl.bindTexture(gl.TEXTURE_2D, source.texture);
      gl.uniform2f(uniform(up, 'u_texel'), 1 / source.width, 1 / source.height);
      gl.uniform1f(uniform(up, 'u_scale'), i === weights.length ? (weights[i - 1] ?? 0) : 1);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  }

  private drawComposite(gl: WebGL2RenderingContext, res: GpuResources, frame: FrameState): void {
    const light = res.levels[0];
    if (light === undefined) return;
    const levels = frame.bloomWeights.length;
    const bloom = levels > 0 ? res.levels[1] : undefined;
    const program = res.composite;
    gl.useProgram(program.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, light.texture);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, (bloom ?? light).texture);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, light.fine ?? light.texture);
    gl.uniform1i(uniform(program, 'u_light'), 0);
    gl.uniform1i(uniform(program, 'u_bloom'), 1);
    gl.uniform1i(uniform(program, 'u_lightFine'), 2);
    // With one level nothing upsampled onto it, so its own weight still applies.
    const bloomScale = bloom === undefined ? 0 : levels === 1 ? (frame.bloomWeights[0] ?? 0) : 1;
    gl.uniform1f(uniform(program, 'u_bloomScale'), bloomScale);
    const texel = bloom ?? light;
    gl.uniform2f(uniform(program, 'u_bloomTexel'), 1 / texel.width, 1 / texel.height);
    const [sx, sy] = frame.mapShare;
    gl.uniform2f(uniform(program, 'u_uvScale'), sx, sy);
    gl.uniform2f(uniform(program, 'u_uvOffset'), (1 - sx) / 2, (1 - sy) / 2);
    gl.uniform1f(uniform(program, 'u_exposure'), EXPOSURE);
    gl.uniform1f(uniform(program, 'u_decode'), frame.fallbackAlpha);
    gl.uniform3fv(uniform(program, 'u_tokens'), this.linearTokens);
    // Screen: light adds to the map but never pushes a channel past full.
    gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_COLOR, gl.ZERO, gl.ONE);
    gl.bindVertexArray(res.vaoEmpty);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.activeTexture(gl.TEXTURE0);
  }

  private drawGlyphs(
    gl: WebGL2RenderingContext,
    res: GpuResources,
    packed: PackedPoints,
    frame: FrameState,
    args: CustomRenderMethodInput,
  ): void {
    const program = res.glyph;
    const ratio = frame.deviceRatio;
    const glyphRadius = frame.style.glyphRadiusPx * ratio;
    gl.useProgram(program.program);
    const reach = glyphRadius * DIAMOND_SCALE * 1.4 + GLYPH_AA_PX;
    const ndcScale = this.setMarginViewport(gl, res, frame, reach);
    this.setPointUniforms(gl, program, args, frame, ndcScale, res.maxPointSize);
    gl.uniform1f(uniform(program, 'u_glyphRadius'), glyphRadius);
    gl.uniform1f(uniform(program, 'u_openRadius'), frame.style.openRadiusPx * ratio);
    gl.uniform1f(uniform(program, 'u_opacity'), frame.style.glyphOpacity);
    gl.uniform1f(uniform(program, 'u_ringWidth'), Math.max(1.5 * ratio, glyphRadius * 0.36));
    gl.uniform3fv(uniform(program, 'u_colors'), this.srgbColors);
    gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    // Open schools first so every affected school sits on top of them.
    if (packed.openCount > 0) {
      gl.bindVertexArray(res.vaoOpen);
      gl.drawArrays(gl.POINTS, 0, packed.openCount);
    }
    if (packed.glowCount > 0) {
      gl.bindVertexArray(res.vaoAll);
      gl.drawArrays(gl.POINTS, 0, packed.glowCount);
    }
  }

  // --- resources ---------------------------------------------------------

  private createResources(gl: WebGL2RenderingContext): GpuResources {
    const float = this.options.forceFallback !== true && supportsHalfFloatTarget(gl);
    const format: LightFormat = float ? 'half' : 'byte';
    const light = createProgram(gl, LIGHT_VERT, LIGHT_FRAG, 'glow light');
    const down = createProgram(gl, FULLSCREEN_VERT, DOWNSAMPLE_FRAG, 'glow downsample');
    const up = createProgram(gl, FULLSCREEN_VERT, UPSAMPLE_FRAG, 'glow upsample');
    const composite = createProgram(gl, FULLSCREEN_VERT, COMPOSITE_FRAG, 'glow composite');
    const glyph = createProgram(gl, GLYPH_VERT, GLYPH_FRAG, 'glow glyph');
    const timerExt =
      this.options.gpuTiming === true
        ? (gl.getExtension('EXT_disjoint_timer_query_webgl2') as TimerExt | null)
        : null;
    const pointRange = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE) as Float32Array | null;
    const viewportDims = gl.getParameter(gl.MAX_VIEWPORT_DIMS) as Int32Array | null;
    return {
      light,
      down,
      up,
      composite,
      glyph,
      buffer: gl.createBuffer(),
      vaoAll: gl.createVertexArray(),
      vaoOpen: gl.createVertexArray(),
      vaoEmpty: gl.createVertexArray(),
      float,
      format,
      maxPointSize: pointRange?.[1] ?? 64,
      maxViewport: [viewportDims?.[0] ?? 4096, viewportDims?.[1] ?? 4096],
      levels: [],
      timer: timerExt === null ? null : new GpuTimer(gl, timerExt),
    };
  }

  private deleteResources(gl: WebGL2RenderingContext, res: GpuResources): void {
    for (const program of [res.light, res.down, res.up, res.composite, res.glyph]) {
      gl.deleteProgram(program.program);
    }
    gl.deleteBuffer(res.buffer);
    gl.deleteVertexArray(res.vaoAll);
    gl.deleteVertexArray(res.vaoOpen);
    gl.deleteVertexArray(res.vaoEmpty);
    for (const level of res.levels) deleteLightTarget(gl, level);
    res.levels = [];
    res.timer?.dispose();
  }

  /** Uploads the packed points into the one vertex buffer, replacing its storage in place. */
  private upload(gl: WebGL2RenderingContext, res: GpuResources): void {
    const packed = this.packed;
    gl.bindVertexArray(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, res.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, packed?.bytes ?? new Uint8Array(0), gl.STATIC_DRAW);
    this.bindAttributes(gl, res.vaoAll, res.buffer, 0);
    this.bindAttributes(gl, res.vaoOpen, res.buffer, packed?.glowCount ?? 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
  }

  private bindAttributes(
    gl: WebGL2RenderingContext,
    vao: WebGLVertexArrayObject,
    buffer: WebGLBuffer,
    firstRecord: number,
  ): void {
    const base = firstRecord * STRIDE_BYTES;
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(ATTRIB.hi);
    gl.vertexAttribPointer(ATTRIB.hi, 2, gl.FLOAT, false, STRIDE_BYTES, base + OFFSET_HI);
    gl.enableVertexAttribArray(ATTRIB.lo);
    gl.vertexAttribPointer(ATTRIB.lo, 2, gl.FLOAT, false, STRIDE_BYTES, base + OFFSET_LO);
    gl.enableVertexAttribArray(ATTRIB.born);
    gl.vertexAttribPointer(ATTRIB.born, 1, gl.FLOAT, false, STRIDE_BYTES, base + OFFSET_BORN);
    gl.enableVertexAttribArray(ATTRIB.status);
    gl.vertexAttribIPointer(ATTRIB.status, 1, gl.UNSIGNED_BYTE, STRIDE_BYTES, base + OFFSET_STATUS);
    gl.bindVertexArray(null);
  }

  // --- context loss and motion preference --------------------------------

  /**
   * Runs in the capture phase on the canvas container, before MapLibre's own
   * handler tears the style down. MapLibre cannot restore custom layers, so
   * the layer steps out now and puts itself back once the context returns.
   */
  private readonly handleContextLost = (): void => {
    const map = this.map;
    if (map === null) return;
    this.contextLost = true;
    this.restoreMap = map;
    this.restoreBeforeId = layerAfter(map, this.id);
    // Everything on the GPU died with the context; nothing to delete.
    this.res = null;
    this.gl = null;
    try {
      map.removeLayer(this.id);
    } catch {
      // The style is mid-swap; the restore handler re-adds the layer either way.
    }
  };

  private readonly handleContextRestored = (): void => {
    const map = this.restoreMap;
    if (map === null) return;
    map.off('webglcontextrestored', this.handleContextRestored);
    const readd = (): void => {
      if (map.getLayer(this.id) !== undefined) return;
      const before = this.restoreBeforeId;
      map.addLayer(
        this,
        before !== undefined && map.getLayer(before) !== undefined ? before : undefined,
      );
    };
    try {
      readd();
    } catch {
      map.once('style.load', readd);
    }
  };

  private watchMotion(): void {
    if (this.motionQuery !== null || typeof matchMedia !== 'function') return;
    this.motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
    this.prefersReducedMotion = this.motionQuery.matches;
    this.motionQuery.addEventListener('change', this.handleMotionChange);
  }

  private readonly handleMotionChange = (event: MediaQueryListEvent): void => {
    this.prefersReducedMotion = event.matches;
    this.map?.triggerRepaint();
  };
}
