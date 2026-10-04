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
 *    per-scale weight, which spreads each point's light over 4 to 64 px (less
 *    below zoom 4, see glowSizeScale) at a cost that does not depend on the
 *    number of points. Light past a knee feeds the bloom at a falling rate,
 *    so its size has a bound.
 *    Nationally the composite shows no lone core: the blend, one bloom level
 *    blurred to a smooth Gaussian, carries their light instead, so the points
 *    read as one field rather than a scatter of specks, and only where cores
 *    pile up inside the field does a share of them show sharp, as grain.
 *    Below zoom 4 the blend stands on a floor (blendFloor), so every school
 *    shows at least as brightly as a lone one, above the state lines.
 *    The light target has the device's own resolution, up to two pixels per
 *    CSS pixel, so the light is as sharp as the map under it.
 * 2. render, composite: a full-screen pass turns the per-status light into
 *    linear RGB (overlapping statuses blend, the leading one keeps its hue),
 *    tone maps it (Reinhard on luminance, hue preserving) and screens it onto
 *    the map. From zoom 11 a glyph pass draws a crisp per-status shape on
 *    every school, open ones included.
 *
 * Without float render targets the light is gathered in two 8-bit targets
 * at once, a coarse one for dense cores and a fine one for faint halos:
 * points are added in optical depth with screen blending and a zoom-scaled
 * alpha, each carrying most of the bloom, and the blend, in its own halo
 * since there is no bloom pass, and the same composite decodes and tone maps
 * them. The fallback's glow is a little tighter than the float path's; see
 * FALLBACK_ALPHA_STOPS in curves.ts.
 *
 * Points pulse in once from their bornAt. The layer clock is re-based on
 * every setData and a bornAt later than now is moved back to now, so the
 * layer asks for frames for at most one pulse after each setData.
 *
 * With a dust style, the layer also draws every school it is given with
 * setDust as a faint speck (dust.ts), in render before the composite, so the
 * glow's light is screened over it; a school flagged with hideDust (one the
 * glow lights) gives way to its light, and filterDust leaves out the kinds of
 * school the page hides, all but the one keepDust names (the school whose
 * panel is open). dustNear finds the specks drawn near a point, for a tap on
 * one, and none while the layer is off the map. The dust has its own small
 * program, compiled the first time it is drawn, and draws nothing outside
 * its zooms.
 */
import type {
  CustomLayerInterface,
  CustomRenderMethodInput,
  Map as MapLibreMap,
} from 'maplibre-gl';

import { statusLinearUniform, statusSrgbUniform } from './color';
import {
  type BlendBlur,
  DENSE_CAP,
  DENSE_FIELD,
  DENSE_GATE,
  FALLBACK_ALPHA_STOPS,
  type GlowFrameStyle,
  type HaloShape,
  PULSE_SECONDS,
  bloomPlan,
  denseShareAt,
  fallbackFloor,
  fallbackHalo,
  fieldPeak,
  fieldReachPx,
  glowStyleAtZoom,
  interpolateStops,
  kernelUniforms,
} from './curves';
import {
  DUST_ATTRIB,
  DUST_FRAG,
  DUST_HIDDEN_Y,
  DUST_VERT,
  type DustGrid,
  type DustStyle,
  dustAtZoom,
  dustGrid,
  dustRuns,
  dustSlotsNear,
  dustSpriteSize,
} from './dust';
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
  BLUR_FRAG,
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
   * device's own. Default: the device's own, up to LIGHT_RESOLUTION_CAP.
   * Glyphs always draw at device resolution.
   */
  readonly lightResolution?: number;
  /** Force the 8-bit fallback, as on a device without float render targets. */
  readonly forceFallback?: boolean;
  /** Override `prefers-reduced-motion`. When true, new points appear without a pulse. */
  readonly reducedMotion?: boolean;
  /** Time the layer's GPU work with EXT_disjoint_timer_query_webgl2 when available. */
  readonly gpuTiming?: boolean;
  /** How to draw the schools given to setDust; without it, none are drawn. */
  readonly dust?: DustStyle;
}

/**
 * 'none' until the layer first has points to draw (an empty layer compiles
 * no shaders and allocates nothing), or after the GPU could not run it.
 */
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
  /** Schools held as dust, and how many of them are left out: lit, or of a kind not shown. */
  readonly dust: number;
  readonly dustHidden: number;
  /**
   * Whether the last frame drew the dust, and how many specks it drew: the
   * runs of its grid in view, the ones the glow lights (drawn off the world) too.
   */
  readonly dustDrawn: boolean;
  readonly dustInView: number;
}

/** Accumulated light multiplier ahead of the tone map. */
const EXPOSURE = 1;

/** Most light-target pixels per CSS pixel: on a 3x phone two read as sharp as three, at under half the cost. */
const LIGHT_RESOLUTION_CAP = 2;

/** Guard band around the map in the light target, CSS px: about the widest bloom's reach. */
const GUARD_CSS_PX = 48;

interface GpuResources {
  readonly light: Program;
  readonly down: Program;
  readonly up: Program;
  readonly blur: Program;
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
  /** Largest light target the GPU can allocate and draw into, px. */
  readonly maxTarget: readonly [number, number];
  /** levels[0] is the light target; the rest are bloom levels, each half the last. */
  levels: LightTarget[];
  /** The blend's first blur pass, the size of the level it blurs; made when first needed. */
  blurTarget: LightTarget | null;
  timer: GpuTimer | null;
}

/** The dust's program and buffer, made the first time it is drawn. */
interface DustResources {
  readonly program: Program;
  readonly positions: WebGLBuffer;
  readonly vao: WebGLVertexArrayObject;
  readonly maxPointSize: number;
  /** Schools in the buffer; 0 until the positions are uploaded. */
  count: number;
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
  /** The blend's blur, or null when there is no blend or it needs none. */
  readonly blur: BlendBlur | null;
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

  /** Every school's position for the dust (dust.ts), in its grid's order. */
  private dust: DustGrid | null = null;
  /** Each school's kind flags, in the grid's order. */
  private dustKinds: Uint8Array | null = null;
  /** One flag per school in the grid's order: 1 for a school the glow lights. */
  private dustLit: Uint8Array | null = null;
  private dustLitSet: ReadonlySet<number> = new Set();
  /** Which kinds of school show as dust, by their kind flags. */
  private dustShows: (kind: number) => boolean = () => true;
  /** The school shown as dust whatever its kind (keepDust), and its slot in the grid. */
  private dustKeptSchool: number | null = null;
  private dustKept = -1;
  /** The positions the GPU draws: the grid's, with each speck left out moved off the world. */
  private dustDrawnAt: Float32Array | null = null;
  private dustLeftOut = 0;
  private dustRes: DustResources | null = null;
  /** Set when the GPU could not run the dust: the lights go on without it. */
  private dustFailed = false;
  /** Whether dustDrawnAt changed since it was last uploaded. */
  private dustStale = false;
  private dustDrawn = false;
  private dustInView = 0;

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

  /**
   * Every school to draw as dust, as longitude, latitude pairs in degrees,
   * with each one's kind flags for filterDust (none: every school shows), or
   * null for none. The schools hideDust names are places in this list.
   */
  setDust(lngLat: Float32Array | Float64Array | null, kinds?: Uint8Array): void {
    const grid = lngLat === null ? null : dustGrid(lngLat);
    this.dust = grid;
    this.dustKinds = null;
    this.dustLit = null;
    this.dustDrawnAt = null;
    this.dustLeftOut = 0;
    if (grid !== null) {
      const count = grid.order.length;
      this.dustKinds = new Uint8Array(count);
      this.dustLit = new Uint8Array(count);
      for (let slot = 0; slot < count; slot++) {
        this.dustKinds[slot] = kinds?.[grid.order[slot] ?? 0] ?? 0;
      }
      for (const school of this.dustLitSet) {
        const slot = grid.slotOf[school];
        if (slot !== undefined) this.dustLit[slot] = 1;
      }
      this.dustKept = this.slotOf(this.dustKeptSchool);
      this.dustDrawnAt = grid.positions.slice();
      this.placeAllDust();
    }
    this.dustStale = true;
    this.map?.triggerRepaint();
  }

  /** Leaves these schools (places in setDust's list) out of the dust, and no others. */
  hideDust(schools: ReadonlySet<number>): void {
    const before = this.dustLitSet;
    this.dustLitSet = schools;
    const grid = this.dust;
    const lit = this.dustLit;
    if (grid === null || lit === null) return;
    const mark = (school: number, flag: 0 | 1): void => {
      const slot = grid.slotOf[school];
      if (slot === undefined || lit[slot] === flag) return;
      lit[slot] = flag;
      this.placeDust(slot);
    };
    for (const school of before) if (!schools.has(school)) mark(school, 0);
    for (const school of schools) mark(school, 1);
    this.map?.triggerRepaint();
  }

  /** Shows as dust only the schools whose kind flags `shows` keeps (the page's filter). */
  filterDust(shows: (kind: number) => boolean): void {
    this.dustShows = shows;
    if (this.placeAllDust()) this.map?.triggerRepaint();
  }

  /** Shows this school as dust whatever its kind (the open school), or none with null. */
  keepDust(school: number | null): void {
    this.dustKeptSchool = school;
    const before = this.dustKept;
    this.dustKept = this.slotOf(school);
    if (before === this.dustKept) return;
    let changed = before >= 0 && this.placeDust(before);
    if (this.dustKept >= 0) changed = this.placeDust(this.dustKept) || changed;
    if (changed) this.map?.triggerRepaint();
  }

  /** A school's slot in the dust's grid, or -1 for none. */
  private slotOf(school: number | null): number {
    return school === null ? -1 : (this.dust?.slotOf[school] ?? -1);
  }

  /**
   * The schools whose specks are drawn within `reach` Web Mercator units of
   * (x, y) each way, by their places in setDust's list: lit ones and those of
   * a kind not shown left out, and every one while the layer draws no dust:
   * without a dust style, off a map, its context lost until it comes back, or
   * where the GPU could not run the dust.
   */
  dustNear(x: number, y: number, reach: number): number[] {
    const grid = this.dust;
    if (grid === null || this.options.dust === undefined || this.gl === null || this.dustFailed) {
      return [];
    }
    return dustSlotsNear(grid, x, y, reach)
      .filter((slot) => this.dustShown(slot))
      .map((slot) => grid.order[slot] ?? 0);
  }

  private dustShown(slot: number): boolean {
    if (this.dustLit?.[slot] === 1) return false;
    return slot === this.dustKept || this.dustShows(this.dustKinds?.[slot] ?? 0);
  }

  /** Draws this slot's speck where it is, or off the world if it is left out; true if that changed. */
  private placeDust(slot: number): boolean {
    const grid = this.dust;
    const drawnAt = this.dustDrawnAt;
    if (grid === null || drawnAt === null) return false;
    const y = this.dustShown(slot) ? (grid.positions[slot * 2 + 1] ?? 0) : DUST_HIDDEN_Y;
    const was = drawnAt[slot * 2 + 1];
    if (was === y) return false;
    drawnAt[slot * 2 + 1] = y;
    this.dustLeftOut += y === DUST_HIDDEN_Y ? 1 : was === DUST_HIDDEN_Y ? -1 : 0;
    this.dustStale = true;
    return true;
  }

  private placeAllDust(): boolean {
    let changed = false;
    const count = this.dust?.order.length ?? 0;
    for (let slot = 0; slot < count; slot++) changed = this.placeDust(slot) || changed;
    return changed;
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
      dust: this.dust === null ? 0 : this.dust.slotOf.length,
      dustHidden: this.dustLeftOut,
      dustDrawn: this.dustDrawn,
      dustInView: this.dustInView,
    };
  }

  onAdd(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    this.map = map;
    this.gl = gl;
    this.contextLost = false;
    this.restoreMap = null;
    this.failed = false;
    this.dustFailed = false;
    this.cssWidthFor = -1;
    this.res = null;
    // Shaders and buffers wait for the first frame with points to draw (ensureResources).
    map.getCanvasContainer().addEventListener('webglcontextlost', this.handleContextLost, true);
    map.off('webglcontextrestored', this.handleContextRestored);
    map.on('webglcontextrestored', this.handleContextRestored);
    this.watchMotion();
  }

  onRemove(map: MapLibreMap, gl: WebGL2RenderingContext): void {
    if (this.res !== null) this.deleteResources(gl, this.res);
    this.res = null;
    if (this.dustRes !== null) this.deleteDust(gl, this.dustRes);
    this.dustRes = null;
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
    const res = this.ensureResources(gl);
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
    // Under the glow's light, which the composite screens over it.
    this.dustDrawn = this.drawDust(gl, args);
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
    const cssW = width / deviceRatio;
    const cssH = height / deviceRatio;
    const [maxW, maxH] = res.maxTarget;
    const targetPxPerCss = Math.min(
      this.options.lightResolution ?? LIGHT_RESOLUTION_CAP,
      deviceRatio,
      // The 8-bit fallback runs on the weakest GPUs, where four times the fill costs the most.
      res.float ? Infinity : 1,
      // A target the GPU cannot allocate would leave the glow undrawn.
      maxW / (cssW + 2 * GUARD_CSS_PX),
      maxH / (cssH + 2 * GUARD_CSS_PX),
    );
    const w0 = Math.max(1, Math.min(maxW, Math.ceil((cssW + 2 * GUARD_CSS_PX) * targetPxPerCss)));
    const h0 = Math.max(1, Math.min(maxH, Math.ceil((cssH + 2 * GUARD_CSS_PX) * targetPxPerCss)));

    const plan = res.float ? bloomPlan(style, targetPxPerCss, Math.min(w0, h0)) : null;
    const bloomWeights = plan?.weights ?? [];
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
      blur: plan?.blur ?? null,
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
    this.loadMatrix(gl, program, args);
    gl.uniform2f(uniform(program, 'u_ndcScale'), ndcScale[0], ndcScale[1]);
    gl.uniform1f(uniform(program, 'u_maxPointSize'), maxPointSize);
    gl.uniform1f(uniform(program, 'u_now'), frame.now);
    gl.uniform1f(uniform(program, 'u_motion'), this.reducedMotion() ? 0 : 1);
  }

  /** Loads u_matrix and u_origin (see setPointUniforms). */
  private loadMatrix(
    gl: WebGL2RenderingContext,
    program: Program,
    args: CustomRenderMethodInput,
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
  }

  private setKernelUniforms(
    gl: WebGL2RenderingContext,
    program: Program,
    frame: FrameState,
    targetPxPerCss: number,
    halo: HaloShape | undefined,
    coreShare: number,
  ): number {
    const kernel = kernelUniforms(frame.style, targetPxPerCss, halo, coreShare);
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
    const blurred = frame.blur === null ? undefined : res.levels[frame.blur.level];
    const spare = res.blurTarget;
    if (
      blurred !== undefined &&
      (spare?.width !== blurred.width || spare.height !== blurred.height)
    ) {
      if (spare !== null) deleteLightTarget(gl, spare);
      res.blurTarget = createLightTarget(gl, blurred.width, blurred.height, res.format);
      if (res.blurTarget === null) return false;
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
    // The float path's bloom is made from whole cores; the fallback draws only the share shown.
    const coreShare = res.float ? 1 : frame.style.coreShare;
    this.setKernelUniforms(gl, program, frame, frame.targetPxPerCss, halo, coreShare);
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
   *
   * Where the blend needs a blur, its level is blurred across into a spare
   * target once the chain is down, then vertically back onto the level with
   * the blend's weight once the coarser levels are in.
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

    const blur = frame.blur;
    const blurred = blur === null ? undefined : res.levels[blur.level];
    const across = res.blurTarget;
    if (blur !== null && blurred !== undefined && across !== null) {
      this.drawBlur(gl, res, blur, blurred, across, [1 / blurred.width, 0], 1);
    }

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
      if (blur !== null && across !== null && i - 1 === blur.level) {
        gl.blendFunc(gl.ONE, gl.ONE);
        this.drawBlur(
          gl,
          res,
          blur,
          across,
          target,
          [0, 1 / across.height],
          blur.weight,
          frame.style,
        );
        gl.useProgram(up.program);
        gl.blendFunc(gl.ONE, gl.CONSTANT_COLOR);
      }
    }
  }

  /**
   * One axis of the blend's blur from `source` into `target`, scaled by
   * `scale`; with `floored`, the second pass, put on the blend's floor.
   */
  private drawBlur(
    gl: WebGL2RenderingContext,
    res: GpuResources,
    blur: BlendBlur,
    source: LightTarget,
    target: LightTarget,
    step: readonly [number, number],
    scale: number,
    floored: GlowFrameStyle | null = null,
  ): void {
    const program = res.blur;
    gl.useProgram(program.program);
    gl.uniform1i(uniform(program, 'u_source'), 0);
    gl.uniform2f(uniform(program, 'u_step'), step[0], step[1]);
    gl.uniform1f(uniform(program, 'u_sigma'), blur.sigmaTexels);
    gl.uniform1i(uniform(program, 'u_radius'), blur.radius);
    gl.uniform1f(uniform(program, 'u_scale'), scale);
    gl.uniform1f(uniform(program, 'u_floorGain'), floored?.floorGain ?? 1);
    gl.uniform1f(uniform(program, 'u_floorKnee'), floored?.floorKnee ?? 1);
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
    gl.viewport(0, 0, target.width, target.height);
    gl.bindTexture(gl.TEXTURE_2D, source.texture);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
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
    // The float path shows only the sharp share of the cores; the fallback drew only that share.
    gl.uniform1f(uniform(program, 'u_coreShare'), res.float ? frame.style.coreShare : 1);
    // Nationally the float path also shows cores where they pile up.
    const dense = res.float ? denseShareAt(frame.style, frame.targetPxPerCss) : 0;
    gl.uniform1f(uniform(program, 'u_denseShare'), dense);
    gl.uniform2f(uniform(program, 'u_denseGate'), DENSE_GATE[0], DENSE_GATE[1]);
    gl.uniform2f(uniform(program, 'u_denseField'), DENSE_FIELD[0], DENSE_FIELD[1]);
    const lone = kernelUniforms(frame.style, frame.targetPxPerCss).coreWeight * frame.style.gain;
    gl.uniform1f(uniform(program, 'u_corePeak'), Math.max(lone, 1e-6));
    gl.uniform1f(uniform(program, 'u_fieldPeak'), Math.max(fieldPeak(frame.style), 1e-6));
    const reach = fieldReachPx(frame.style) * frame.targetPxPerCss;
    gl.uniform2f(uniform(program, 'u_fieldReach'), reach / light.width, reach / light.height);
    gl.uniform1f(uniform(program, 'u_denseCap'), DENSE_CAP);
    const texel = bloom ?? light;
    gl.uniform2f(uniform(program, 'u_bloomTexel'), 1 / texel.width, 1 / texel.height);
    const [sx, sy] = frame.mapShare;
    gl.uniform2f(uniform(program, 'u_uvScale'), sx, sy);
    gl.uniform2f(uniform(program, 'u_uvOffset'), (1 - sx) / 2, (1 - sy) / 2);
    gl.uniform1f(uniform(program, 'u_exposure'), EXPOSURE);
    gl.uniform1f(uniform(program, 'u_decode'), frame.fallbackAlpha);
    // The float path floors the blend in its own blur; the fallback floors its halos here.
    const floor = res.float ? { gain: 1, knee: 1 } : fallbackFloor(frame.style, frame.zoom);
    gl.uniform1f(uniform(program, 'u_floorGain'), floor.gain);
    gl.uniform1f(uniform(program, 'u_floorKnee'), floor.knee);
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

  /**
   * Every school's speck, where the zoom has dust: straight onto the map,
   * keeping the brighter of speck and map at each pixel. Returns whether it
   * drew.
   */
  private drawDust(gl: WebGL2RenderingContext, args: CustomRenderMethodInput): boolean {
    this.dustInView = 0;
    const style = this.options.dust;
    const map = this.map;
    const grid = this.dust;
    if (style === undefined || map === null || grid === null || this.dustFailed) return false;
    if (args.shaderData.variantName !== 'mercator') return false;
    const dust = dustAtZoom(style, map.getZoom());
    if (dust === null) return false;
    // Only the rows of cells in view (the map is never turned or tilted, so its bounds are its view).
    const bounds = map.getBounds();
    const runs = dustRuns(
      grid.cellStart,
      mercatorXFromLng(bounds.getWest()),
      mercatorYFromLat(bounds.getNorth()),
      mercatorXFromLng(bounds.getEast()),
      mercatorYFromLat(bounds.getSouth()),
    );
    if (runs.length === 0) return false;
    const res = this.ensureDust(gl);
    if (res === null || res.count === 0) return false;

    const width = gl.drawingBufferWidth;
    const clientWidth = map.getCanvas().clientWidth;
    const ratio = clientWidth > 0 ? width / clientWidth : 1;
    const radius = dust.radius * ratio;
    const size = Math.min(dustSpriteSize(radius, dust.softness), res.maxPointSize);
    const program = res.program;
    gl.viewport(0, 0, width, gl.drawingBufferHeight);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.SCISSOR_TEST);
    gl.colorMask(true, true, true, true);
    gl.enable(gl.BLEND);
    // The brighter of speck and map: specks never add up, and a dot drawn twice is the same dot.
    gl.blendEquation(gl.MAX);
    gl.useProgram(program.program);
    this.loadMatrix(gl, program, args);
    gl.uniform1f(uniform(program, 'u_size'), size);
    gl.uniform1f(uniform(program, 'u_radius'), radius);
    gl.uniform1f(uniform(program, 'u_softness'), dust.softness);
    const [r, g, b] = style.color;
    const a = dust.opacity;
    gl.uniform4f(uniform(program, 'u_color'), r * a, g * a, b * a, a);
    gl.bindVertexArray(res.vao);
    for (const [first, count] of runs) {
      gl.drawArrays(gl.POINTS, first, count);
      this.dustInView += count;
    }
    gl.bindVertexArray(null);
    gl.blendEquation(gl.FUNC_ADD);
    return true;
  }

  /** The dust's program and buffer, made once, and filled again when the positions change. */
  private ensureDust(gl: WebGL2RenderingContext): DustResources | null {
    if (this.dustRes === null) {
      try {
        const pointRange = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE) as Float32Array | null;
        const res: DustResources = {
          program: createProgram(gl, DUST_VERT, DUST_FRAG, 'glow dust'),
          positions: gl.createBuffer(),
          vao: gl.createVertexArray(),
          maxPointSize: pointRange?.[1] ?? 64,
          count: 0,
        };
        gl.bindVertexArray(res.vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, res.positions);
        gl.enableVertexAttribArray(DUST_ATTRIB.position);
        gl.vertexAttribPointer(DUST_ATTRIB.position, 2, gl.FLOAT, false, 0, 0);
        gl.bindVertexArray(null);
        gl.bindBuffer(gl.ARRAY_BUFFER, null);
        this.dustRes = res;
      } catch (error) {
        this.dustFailed = true;
        console.error(error);
        return null;
      }
      this.dustStale = true;
    }
    const res = this.dustRes;
    if (this.dustStale) {
      const positions = this.dustDrawnAt ?? new Float32Array(0);
      gl.bindVertexArray(null);
      gl.bindBuffer(gl.ARRAY_BUFFER, res.positions);
      gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, null);
      res.count = positions.length / 2;
      this.dustStale = false;
    }
    return res;
  }

  private deleteDust(gl: WebGL2RenderingContext, res: DustResources): void {
    gl.deleteProgram(res.program.program);
    gl.deleteBuffer(res.positions);
    gl.deleteVertexArray(res.vao);
  }

  // --- resources ---------------------------------------------------------

  /**
   * The GPU resources, created on the first frame that has points to draw.
   * Until then the layer compiles no shaders and allocates nothing, so a map
   * with nothing lit pays nothing for it: no shader compiles holding up the
   * page while it loads. Null while there is nothing to draw or the GPU
   * cannot run the layer.
   */
  private ensureResources(gl: WebGL2RenderingContext): GpuResources | null {
    if (this.res !== null || this.failed) return this.res;
    if ((this.packed?.count ?? 0) === 0) return null;
    try {
      this.res = this.createResources(gl);
      this.upload(gl, this.res);
    } catch (error) {
      this.failed = true;
      this.res = null;
      console.error(error);
    }
    return this.res;
  }

  private createResources(gl: WebGL2RenderingContext): GpuResources {
    const float = this.options.forceFallback !== true && supportsHalfFloatTarget(gl);
    const format: LightFormat = float ? 'half' : 'byte';
    const light = createProgram(gl, LIGHT_VERT, LIGHT_FRAG, 'glow light');
    const down = createProgram(gl, FULLSCREEN_VERT, DOWNSAMPLE_FRAG, 'glow downsample');
    const up = createProgram(gl, FULLSCREEN_VERT, UPSAMPLE_FRAG, 'glow upsample');
    const blur = createProgram(gl, FULLSCREEN_VERT, BLUR_FRAG, 'glow blur');
    const composite = createProgram(gl, FULLSCREEN_VERT, COMPOSITE_FRAG, 'glow composite');
    const glyph = createProgram(gl, GLYPH_VERT, GLYPH_FRAG, 'glow glyph');
    const timerExt =
      this.options.gpuTiming === true
        ? (gl.getExtension('EXT_disjoint_timer_query_webgl2') as TimerExt | null)
        : null;
    const pointRange = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE) as Float32Array | null;
    const viewportDims = gl.getParameter(gl.MAX_VIEWPORT_DIMS) as Int32Array | null;
    const maxViewport: [number, number] = [viewportDims?.[0] ?? 4096, viewportDims?.[1] ?? 4096];
    const maxTexture = (gl.getParameter(gl.MAX_TEXTURE_SIZE) as number | null) ?? 4096;
    return {
      light,
      down,
      up,
      blur,
      composite,
      glyph,
      buffer: gl.createBuffer(),
      vaoAll: gl.createVertexArray(),
      vaoOpen: gl.createVertexArray(),
      vaoEmpty: gl.createVertexArray(),
      float,
      format,
      maxPointSize: pointRange?.[1] ?? 64,
      maxViewport,
      maxTarget: [Math.min(maxTexture, maxViewport[0]), Math.min(maxTexture, maxViewport[1])],
      levels: [],
      blurTarget: null,
      timer: timerExt === null ? null : new GpuTimer(gl, timerExt),
    };
  }

  private deleteResources(gl: WebGL2RenderingContext, res: GpuResources): void {
    for (const program of [res.light, res.down, res.up, res.blur, res.composite, res.glyph]) {
      gl.deleteProgram(program.program);
    }
    gl.deleteBuffer(res.buffer);
    gl.deleteVertexArray(res.vaoAll);
    gl.deleteVertexArray(res.vaoOpen);
    gl.deleteVertexArray(res.vaoEmpty);
    for (const level of res.levels) deleteLightTarget(gl, level);
    res.levels = [];
    if (res.blurTarget !== null) deleteLightTarget(gl, res.blurTarget);
    res.blurTarget = null;
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
    this.dustRes = null;
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
