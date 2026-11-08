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

/** In its worker, as the page builds the index, or on the page in slices, where no worker starts. */
export type SamePlacesHow = 'worker' | 'slices';

/**
 * A task the page ran for a light's covered schools: the step it began with
 * (map/same-places.ts StepKind; 'answer' for a worker's answer that began none, 'slice' for a
 * slice of the build on the page, 'other' for none), its wall time, and its number among the
 * page's tasks, by which a trace finds it (`same-place-task <seq>`, on a traced pass).
 */
export interface CoverTask {
  readonly kind: string;
  readonly ms: number;
  readonly seq: number;
}

/** The page's tasks for the schools a light covers, from the light to all of them marked. */
export interface CoverTasks {
  /** The light's own call (map/same-places.ts SamePlaceCovers light), on the page, in a task of its own. */
  readonly askMs: number;
  /** The call's number among the page's tasks, as a task's. */
  readonly askSeq: number;
  /** Every task after the call, in order. */
  readonly list: readonly CoverTask[];
  /** The tasks run on the page for it after the call, and their lengths. */
  readonly tasks: number;
  /** All of them together: the page's share of the light's same-place work. */
  readonly busyMs: number;
  readonly longestTaskMs: number;
  readonly medianTaskMs: number;
  /** The tasks longer than 2 ms: which, from 0, and how long. */
  readonly longTasks: readonly string[];
  /** From the light's call to its schools all covered. */
  readonly coveredAfterMs: number;
}

/**
 * What the schools at a lit one's place cost (map/same-places.ts,
 * map/glow-mount.ts), over a SYNTHETIC directory, on the page's own path: the
 * page's first light (its directory's index built, in its worker or in
 * slices on the page, and the light's schools covered), then lights after it
 * (found with the index and covered), every task the page runs for them
 * timed.
 */
export interface SamePlacesCost {
  readonly schools: number;
  readonly lit: number;
  readonly covered: number;
  /** The schools with another at their place, by the index. */
  readonly shared: number;
  /**
   * Whether the schools covered at the last light with schools lit are those the index says
   * (worked out after), and none is covered once none is lit.
   */
  readonly matches: boolean;
  /** Where the index was built: in its worker, as the page builds it, or in slices on the page. */
  readonly how: SamePlacesHow;
  readonly firstLight: CoverTasks;
  /** Each light after it, the schools lit changed each time, and last one with none lit. */
  readonly laterLights: readonly CoverTasks[];
  /**
   * The longest of 64 plain waits as long as a cover task, one a frame, before the first light:
   * what the machine adds to one.
   */
  readonly longestSpinMs: number;
  /**
   * On a traced pass: the frames MapLibre drew, each named `same-place-frame <n>` for the trace,
   * those of a quiet stretch before the first light (nothing covered, the map drawn each frame)
   * the first `quietFrames`; and each light's stretch from its call to its schools all covered,
   * on the page's clock, with each frame's time on it.
   */
  readonly frames?: {
    readonly at: readonly number[];
    readonly quietFrames: number;
    /**
     * The frames, from and up to, drawn as the first light's schools were lit and then unlit,
     * with no covers asked for: a light's frames without this feature, before the first light.
     */
    readonly litOnly: readonly [number, number];
    readonly windows: readonly (readonly [number, number])[];
  };
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
  /**
   * Times the schools a light covers over `count` SYNTHETIC schools at places in millionths of
   * a degree, one in sixteen at the place of the one before it and one in 1,024 a metre from
   * it, one in `every` lit: a page's first light, then `runs` lights after it, the lit ones
   * moved each time. `how` builds the index in its worker, as the page does, or in slices on
   * the page, as where no worker starts. `named` names every task, and each frame drawn, with
   * a user timing measure, for a trace to find (only on a traced pass).
   */
  samePlaces(
    count: number,
    every: number,
    runs: number,
    how: SamePlacesHow,
    named?: boolean,
  ): Promise<SamePlacesCost>;
  /** Median synchronous frame cost with and without the layer at `zoom`, over `frames` frames. */
  syncFrameCost(center: LngLatTuple, zoom: number, frames: number): Promise<SyncFrameCost>;
}

declare global {
  interface Window {
    glowBench?: GlowBenchApi;
    glowBenchError?: string;
  }
}
