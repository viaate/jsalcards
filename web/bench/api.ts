/**
 * The contract between the glow bench page (bench/glow.ts) and its
 * Playwright driver (e2e/bench-glow.spec.ts). Types only.
 */
import type { GlowRenderMode } from '../src/map/glow';

export type LngLatTuple = readonly [lng: number, lat: number];

/**
 * Where a pulse's bornAt values come from: the layer's own clock; a server
 * clock running 5 s ahead of it; or `Date.now()` epoch milliseconds passed by
 * mistake. The last two put every born time in the future.
 */
export type BornClock = 'layer' | 'skewed' | 'epoch';

/** One frame MapLibre drew while a scripted camera move ran. */
export interface FrameSample {
  /** Time since the previous drawn frame, ms. */
  readonly interval: number;
  /** Main-thread time inside the glow layer this frame, ms. */
  readonly layerCpuMs: number;
  /** GPU time of the most recently resolved frame, ms, when timer queries work. */
  readonly layerGpuMs: number | null;
  readonly zoom: number;
  /** False when the layer was not part of this frame (for the baseline run). */
  readonly layerDrew: boolean;
}

export interface Recording {
  readonly durationMs: number;
  readonly samples: readonly FrameSample[];
  /** requestAnimationFrame cadence over the same window, ms. */
  readonly rafIntervals: readonly number[];
}

export interface GlowBenchInfo {
  readonly synthetic: true;
  readonly renderer: string;
  readonly mode: GlowRenderMode;
  readonly crossOriginIsolated: boolean;
  readonly devicePixelRatio: number;
  readonly pointCount: number;
  /** Frames the layer has drawn since it was created. */
  readonly layerFrames: number;
  readonly targetWidth: number;
  readonly targetHeight: number;
  /** Device pixels per CSS pixel the layer last drew at. */
  readonly layerPixelRatio: number;
  readonly bloomLevels: number;
  /** Rows of the last setData whose bornAt was later than now. */
  readonly bornClamped: number;
  readonly gpuTimer: boolean;
  readonly mapVersion: string;
}

export type GlObjectCounts = Readonly<Record<string, number>>;

export interface ContextLossReport {
  readonly lostFired: boolean;
  readonly restoredFired: boolean;
  readonly layerBack: boolean;
  readonly modeAfter: GlowRenderMode;
  readonly framesAfter: number;
}

/** Full frames drawn synchronously: map.redraw() then a 1-pixel readback that waits for the GPU. */
export interface SyncFrameCost {
  readonly zoom: number;
  readonly withLayerMs: number;
  readonly withoutLayerMs: number;
  readonly layerMs: number;
}

export interface GlowBenchApi {
  info(): GlowBenchInfo;
  /** Regenerates SYNTHETIC points and hands them to the layer. */
  setPointCount(count: number): { readonly generateMs: number; readonly setDataMs: number };
  /** Gives a share of the current points a fresh bornAt so they pulse in. */
  pulse(share: number, clock?: BornClock): void;
  /**
   * Replaces the points with the given SYNTHETIC ones: interleaved longitude,
   * latitude pairs and one status code each.
   */
  setPoints(lngLat: readonly number[], status: readonly number[]): void;
  view(center: LngLatTuple, zoom: number): Promise<void>;
  pan(from: LngLatTuple, to: LngLatTuple, zoom: number, durationMs: number): Promise<Recording>;
  zoomSweep(
    center: LngLatTuple,
    fromZoom: number,
    toZoom: number,
    durationMs: number,
  ): Promise<Recording>;
  setLayerVisible(visible: boolean): Promise<void>;
  /** Overrides the map's pixel ratio, as when a window moves to a denser screen. */
  setPixelRatio(ratio: number): Promise<void>;
  densest(): LngLatTuple;
  liveGlObjects(): GlObjectCounts;
  /** Alternates setData between the given counts, drawing a frame after each. */
  churn(counts: readonly number[], cycles: number): Promise<void>;
  loseAndRestoreContext(): Promise<ContextLossReport>;
  /** Median synchronous frame cost with and without the layer at `zoom`, over `frames` frames. */
  syncFrameCost(center: LngLatTuple, zoom: number, frames: number): Promise<SyncFrameCost>;
}

declare global {
  interface Window {
    glowBench?: GlowBenchApi;
    glowBenchError?: string;
  }
}
