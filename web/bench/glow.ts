/**
 * Glow bench page: a black MapLibre map with the bundled US outline and
 * SYNTHETIC points (see synthetic.ts), driven by e2e/bench-glow.spec.ts.
 *
 * URL parameters:
 *   count=30000   number of synthetic points
 *   fallback=1    force the 8-bit fallback path
 *   res=1         light target resolution, target px per CSS px
 *   timing=1      time the layer's GPU work with timer queries
 */
import 'maplibre-gl/dist/maplibre-gl.css';

import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

import { GlowLayer } from '../src/map/glow';
import { BASEMAP_IDS } from '../src/map/basemap/ids';
import { coverMarks, markLitDots } from '../src/map/glow-mount';
import {
  COVER_MS,
  SamePlaceCovers,
  coveredBy,
  samePlacesNow,
  taskLoop,
} from '../src/map/same-places';
import type { Tasks } from '../src/map/same-places';
import type {
  ContextLossReport,
  CoverTask,
  CoverTasks,
  SyncFrameCost,
  FrameSample,
  GlObjectCounts,
  GlowBenchApi,
  Recording,
  SamePlacesCost,
} from './api';
import { benchStyle, conusGeometry } from './basemap';
import { LandMask, generateSyntheticPoints, type SyntheticPoints } from './synthetic';

// --- WebGL object accounting, installed before any context exists ---------

const GL_KINDS = {
  buffer: ['createBuffer', 'deleteBuffer'],
  texture: ['createTexture', 'deleteTexture'],
  framebuffer: ['createFramebuffer', 'deleteFramebuffer'],
  renderbuffer: ['createRenderbuffer', 'deleteRenderbuffer'],
  vertexArray: ['createVertexArray', 'deleteVertexArray'],
  program: ['createProgram', 'deleteProgram'],
  shader: ['createShader', 'deleteShader'],
  query: ['createQuery', 'deleteQuery'],
} as const;

type GlMethod = (this: WebGL2RenderingContext, ...args: unknown[]) => unknown;

const liveObjects = new Map<string, Set<unknown>>();
for (const [kind, [create, remove]] of Object.entries(GL_KINDS)) {
  const live = new Set<unknown>();
  liveObjects.set(kind, live);
  const proto = WebGL2RenderingContext.prototype as unknown as Record<string, GlMethod>;
  const originalCreate = proto[create];
  const originalRemove = proto[remove];
  if (originalCreate === undefined || originalRemove === undefined) continue;
  proto[create] = function (this: WebGL2RenderingContext, ...args: unknown[]): unknown {
    const object = originalCreate.apply(this, args);
    if (object !== null) live.add(object);
    return object;
  };
  proto[remove] = function (this: WebGL2RenderingContext, ...args: unknown[]): unknown {
    live.delete(args[0]);
    return originalRemove.apply(this, args);
  };
}

function liveGlObjects(): GlObjectCounts {
  const counts: Record<string, number> = {};
  for (const [kind, live] of liveObjects) counts[kind] = live.size;
  return counts;
}

// --- page setup ----------------------------------------------------------

const params = new URLSearchParams(location.search);
const initialCount = Number(params.get('count') ?? '30000');
const resParam = params.get('res');

// MapLibre finds its worker next to its own module, which a bundle moves.
maplibregl.setWorkerUrl(workerUrl);

const geometry = conusGeometry();
const mask = new LandMask(geometry.land);
const synthesize = (count: number): SyntheticPoints =>
  generateSyntheticPoints(mask, geometry.counties, count);
let points: SyntheticPoints = synthesize(initialCount);

const layer = new GlowLayer({
  // GPU timer queries are off unless asked for: on SwiftShader they do not
  // measure the rasterizer's work well, and they add main-thread calls.
  gpuTiming: params.get('timing') === '1',
  ...(params.get('fallback') === '1' ? { forceFallback: true } : {}),
  ...(resParam !== null ? { lightResolution: Number(resParam) } : {}),
});

const map = new maplibregl.Map({
  container: 'map',
  style: benchStyle(geometry),
  center: [-96.4, 38.4],
  zoom: 3.9,
  attributionControl: false,
  fadeDuration: 0,
  renderWorldCopies: false,
  dragRotate: false,
  pitchWithRotate: false,
  maxPitch: 0,
});

const nextFrame = (): Promise<number> => new Promise((resolve) => requestAnimationFrame(resolve));
/** Resolves in a task of its own, a message to a port, as soon as the page is free. */
const nextTask = (): Promise<void> =>
  new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => {
      channel.port1.close();
      resolve();
    };
    channel.port2.postMessage(null);
  });

async function settle(): Promise<void> {
  await new Promise<void>((resolve) => {
    map.once('idle', () => {
      resolve();
    });
    map.triggerRepaint();
  });
  await nextFrame();
  await nextFrame();
}

/** Records every frame MapLibre draws until `done` resolves. */
async function record(start: () => void, done: Promise<unknown>): Promise<Recording> {
  const samples: FrameSample[] = [];
  const rafIntervals: number[] = [];
  let lastRender = -1;
  let lastLayerFrames = layer.stats.frames;
  const onRender = (): void => {
    const t = performance.now();
    const stats = layer.stats;
    const drew = stats.frames !== lastLayerFrames;
    lastLayerFrames = stats.frames;
    if (lastRender >= 0) {
      samples.push({
        interval: t - lastRender,
        layerCpuMs: drew ? stats.lastCpuMs : 0,
        layerGpuMs: drew ? stats.lastGpuMs : null,
        zoom: map.getZoom(),
        layerDrew: drew,
      });
    }
    lastRender = t;
  };
  let recording = true;
  let lastRaf = -1;
  const onRaf = (t: number): void => {
    if (!recording) return;
    if (lastRaf >= 0) rafIntervals.push(t - lastRaf);
    lastRaf = t;
    requestAnimationFrame(onRaf);
  };
  map.on('render', onRender);
  requestAnimationFrame(onRaf);
  const t0 = performance.now();
  start();
  await done;
  const durationMs = performance.now() - t0;
  recording = false;
  map.off('render', onRender);
  return { durationMs, samples, rafIntervals };
}

const linear = (t: number): number => t;

/** How far ahead of the layer clock a skewed server clock runs, ms. */
const CLOCK_SKEW_MS = 5000;

const api: GlowBenchApi = {
  info() {
    const gl = map.getCanvas().getContext('webgl2');
    const debug = gl?.getExtension('WEBGL_debug_renderer_info');
    const renderer =
      gl === null ? 'none' : String(gl.getParameter(debug?.UNMASKED_RENDERER_WEBGL ?? gl.RENDERER));
    const stats = layer.stats;
    return {
      synthetic: true,
      renderer,
      mode: stats.mode,
      crossOriginIsolated: self.crossOriginIsolated,
      devicePixelRatio: devicePixelRatio,
      pointCount: stats.count,
      layerFrames: stats.frames,
      targetWidth: stats.targetWidth,
      targetHeight: stats.targetHeight,
      layerPixelRatio: stats.pixelRatio,
      bloomLevels: stats.bloomLevels,
      bornClamped: stats.bornClamped,
      gpuTimer: (gl?.getExtension('EXT_disjoint_timer_query_webgl2') ?? null) !== null,
      mapVersion: maplibregl.getVersion(),
    };
  },

  setPointCount(count) {
    const t0 = performance.now();
    points = synthesize(count);
    const t1 = performance.now();
    layer.setData({ lngLat: points.lngLat, status: points.status });
    return { generateMs: t1 - t0, setDataMs: performance.now() - t1 };
  },

  async samePlaces(count, every, runs, how, named = false): Promise<SamePlacesCost> {
    if (!map.isStyleLoaded()) await new Promise((resolve) => map.once('load', resolve));
    const synthetic = synthesize(count).lngLat;
    // In millionths of a degree, as points.bin keeps them and the page reads them.
    const places = new Int32Array(count * 2);
    for (let i = 0; i < count * 2; i++) places[i] = Math.round((synthetic[i] ?? 0) * 1e6);
    // One school in sixteen at the place of the one before it: one in eight at a place it
    // shares, as 12.6% of the directory's are; and one in 1,024 nine millionths of a degree
    // (a metre) north of it, as about a hundred are.
    for (let i = 1; i < count; i += 16) {
      places[i * 2] = places[i * 2 - 2] ?? 0;
      places[i * 2 + 1] = (places[i * 2 - 1] ?? 0) + (i % 1024 === 1 ? 9 : 0);
    }
    // As data/closings.ts lights them: each lit row at its school's place in the directory,
    // one in `every`, from `offset` on.
    const litFrom = (offset: number): Set<number> => {
      const schools = new Set<number>();
      for (let i = offset; i < count; i += every) schools.add(i);
      return schools;
    };
    // The dots of a school tiles source that holds no tile here, so a feature state costs what
    // the call does (the tiles' own share is MapLibre's, the same for every lit school).
    if (map.getSource(BASEMAP_IDS.schoolsSource) === undefined) {
      map.addSource(BASEMAP_IDS.schoolsSource, {
        type: 'vector',
        tiles: ['https://bench.invalid/{z}/{x}/{y}.pbf'],
        minzoom: 22,
        maxzoom: 22,
        bounds: [0, 0, 0.0001, 0.0001],
      });
    }
    const dots = markLitDots(map);
    layer.setDust(Float64Array.from(places, (e6) => e6 * 1e-6));
    await nextFrame();
    // The page's own path (map/glow-mount.ts): each light's schools marked lit and its covers
    // asked for (the worker made at the first, in the task after it), every task the page runs
    // for them timed, the events of the worker's answers among them, until they are all marked;
    // each labelled with the step it began with (Builders.steps).
    let log: CoverTask[] = [];
    let seq = 0;
    // The step the task now running began with, if it began one.
    const began: { kind: string | null } = { kind: null };
    let done: (() => void) | null = null;
    let settledAt = 0;
    const loop = taskLoop();
    // Every one named on a traced pass, for the spec's trace to find the thread time its task
    // took beside its wall time: kept, and measured once the page's lights are done, so the
    // measures' own cost (a few tenths of a millisecond each, more while traced) is in no task
    // of theirs and in no frame (a measure's trace events carry the times it is given).
    const names: [string, number, number][] = [];
    const name = (at: number, start: number, end: number): void => {
      if (named) names.push([`same-place-task ${String(at)}`, start, end]);
    };
    const time = (task: () => void, otherwise: string): void => {
      const start = performance.now();
      task();
      const end = performance.now();
      const at = seq++;
      log.push({ kind: began.kind ?? otherwise, ms: end - start, seq: at });
      began.kind = null;
      name(at, start, end);
    };
    const timed: Tasks = {
      post(task) {
        loop.post(() => {
          time(task, how === 'slices' ? 'slice' : 'other');
        });
      },
      run(task) {
        time(task, 'answer');
      },
      close() {
        loop.close();
      },
    };
    const covers = new SamePlaceCovers(coverMarks(dots, layer), {
      tasks: timed,
      ...(how === 'slices' ? { worker: () => null } : {}),
      steps(kind) {
        began.kind ??= kind;
      },
      covered: () => {
        settledAt = performance.now();
        // Told in a task after this one, so the bench's own work after a light (the next light,
        // the check at the end) is in no task of theirs.
        void nextTask().then(() => done?.());
      },
    });
    // The frames MapLibre draws, named on a traced pass, for each one's thread time.
    const frameAt: number[] = [];
    const drawn = (): void => {
      if (!named) return;
      const at = performance.now();
      names.push([`same-place-frame ${String(frameAt.length)}`, at, at]);
      frameAt.push(at);
    };
    map.on('render', drawn);
    // The machine's own share: a plain wait as long as a cover task, each in a frame's task, so
    // a task's time beyond it is told from the machine's.
    const spins: number[] = [];
    for (let n = 0; n < 64; n++) {
      await nextFrame();
      const start = performance.now();
      while (performance.now() < start + COVER_MS) {
        // Waiting.
      }
      spins.push(performance.now() - start);
    }
    // A quiet stretch, the map drawn each frame and nothing covered: the frames' own thread time.
    for (let n = 0; n < 24; n++) {
      map.triggerRepaint();
      await nextFrame();
    }
    const quietFrames = frameAt.length;
    // And a control: the first light's schools lit and then unlit, its dots and dust, with no
    // covers asked for, the frames it draws (what a light costs a frame without this feature).
    for (const lit of [litFrom(0), new Set<number>()]) {
      await nextFrame();
      await nextTask();
      dots.mark(lit);
      layer.hideDust(lit);
      for (let n = 0; n < 6; n++) await nextFrame();
    }
    const litOnly: [number, number] = [quietFrames, frameAt.length];
    const windows: [number, number][] = [];
    const show = async (schools: Set<number>): Promise<CoverTasks> => {
      // Lit after a frame, in a task of its own as the page lights its schools (the live file's,
      // not a frame's); the call in a task of its own after that, so a trace tells its thread
      // time from the lighting's and from the frames'.
      await nextFrame();
      await nextTask();
      dots.mark(schools);
      layer.hideDust(schools);
      await nextTask();
      log = [];
      const finished = new Promise<void>((resolve) => {
        done = resolve;
      });
      const start = performance.now();
      covers.light(places, schools);
      const end = performance.now();
      const askSeq = seq++;
      name(askSeq, start, end);
      const askMs = end - start;
      await finished;
      const coveredAfterMs = settledAt - start;
      windows.push([start, start + coveredAfterMs]);
      done = null;
      const sorted = log.map(({ ms }) => ms).sort((a, b) => a - b);
      return {
        askMs,
        askSeq,
        list: log,
        tasks: log.length,
        busyMs: sorted.reduce((sum, ms) => sum + ms, 0),
        longestTaskMs: sorted.at(-1) ?? 0,
        medianTaskMs: sorted[Math.floor(sorted.length / 2)] ?? Number.NaN,
        longTasks: log.flatMap(({ kind, ms }, at) =>
          ms > 2 ? [`${String(at)} ${kind}: ${ms.toFixed(2)}`] : [],
        ),
        coveredAfterMs,
      };
    };
    const firstLit = litFrom(0);
    const firstLight = await show(firstLit);
    const laterLights: CoverTasks[] = [];
    let last = firstLit;
    for (let run = 1; run <= runs; run++) {
      // The lit ones moved by a few each time: as many lit, others covered.
      last = litFrom((run * 16) % every);
      laterLights.push(await show(last));
    }
    // Worked out after, untimed: the schools covered are the index's for the last light.
    const index = samePlacesNow(places);
    const want = [...coveredBy(index, Int32Array.from(last))].sort((a, b) => a - b);
    const have = [...covers.covered].sort((a, b) => a - b);
    const matches = want.length === have.length && want.every((school, i) => school === have[i]);
    // And last a light with none lit: every one uncovered.
    laterLights.push(await show(new Set()));
    const uncovered = covers.covered.length === 0;
    covers.close();
    map.off('render', drawn);
    for (const [label, start, end] of names) performance.measure(label, { start, end });
    dots.mark(new Set());
    layer.hideDust(new Set());
    layer.setDust(null);
    return {
      schools: count,
      lit: firstLit.size,
      covered: have.length,
      shared: index.shared,
      matches: matches && uncovered,
      how,
      firstLight,
      laterLights,
      longestSpinMs: Math.max(...spins),
      ...(named ? { frames: { at: frameAt, quietFrames, litOnly, windows } } : {}),
    };
  },

  pulse(share, clock = 'layer') {
    const now =
      clock === 'epoch' ? Date.now() : layer.now() + (clock === 'skewed' ? CLOCK_SKEW_MS : 0);
    const bornAt = new Float64Array(points.status.length).fill(Number.NaN);
    const step = Math.max(1, Math.round(1 / share));
    // Staggered a little into the past, so on the layer clock no time is in the future.
    for (let i = 0; i < bornAt.length; i += step) bornAt[i] = now - (i % 7) * 40;
    layer.setData({ lngLat: points.lngLat, status: points.status, bornAt });
  },

  setPoints(lngLat, status) {
    layer.setData({ lngLat: new Float64Array(lngLat), status: new Uint8Array(status) });
  },

  async view(center, zoom) {
    map.jumpTo({ center: [center[0], center[1]], zoom });
    await settle();
  },

  async pan(from, to, zoom, durationMs) {
    await api.view(from, zoom);
    return record(
      () => {
        map.easeTo({ center: [to[0], to[1]], zoom, duration: durationMs, easing: linear });
      },
      new Promise((resolve) => map.once('moveend', resolve)),
    );
  },

  async zoomSweep(center, fromZoom, toZoom, durationMs) {
    await api.view(center, fromZoom);
    return record(
      () => {
        map.easeTo({
          center: [center[0], center[1]],
          zoom: toZoom,
          duration: durationMs,
          easing: linear,
        });
      },
      new Promise((resolve) => map.once('moveend', resolve)),
    );
  },

  async setLayerVisible(visible) {
    const present = map.getLayer(layer.id) !== undefined;
    if (visible && !present) map.addLayer(layer);
    if (!visible && present) map.removeLayer(layer.id);
    await settle();
  },

  async setPixelRatio(ratio) {
    map.setPixelRatio(ratio);
    await settle();
  },

  densest() {
    return points.densest;
  },

  liveGlObjects,

  async churn(counts, cycles) {
    const sets = counts.map(synthesize);
    for (let cycle = 0; cycle < cycles; cycle++) {
      for (const set of sets) {
        layer.setData({ lngLat: set.lngLat, status: set.status });
        map.triggerRepaint();
        await nextFrame();
      }
    }
    const last = sets[sets.length - 1];
    if (last !== undefined) points = last;
    await settle();
  },

  async syncFrameCost(center, zoom, frames): Promise<SyncFrameCost> {
    const gl = map.getCanvas().getContext('webgl2');
    if (gl === null) throw new Error('bench: no WebGL2 context');
    const pixel = new Uint8Array(4);
    const measure = async (): Promise<number> => {
      await api.view(center, zoom);
      const times: number[] = [];
      for (let i = 0; i < frames; i++) {
        // Nudge the camera so every frame redraws for real.
        map.jumpTo({ center: [center[0] + (i % 2) * 1e-4, center[1]], zoom });
        const t0 = performance.now();
        map.redraw();
        gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
        times.push(performance.now() - t0);
      }
      times.sort((a, b) => a - b);
      return times[Math.floor(times.length / 2)] ?? Number.NaN;
    };
    const withLayerMs = await measure();
    await api.setLayerVisible(false);
    const withoutLayerMs = await measure();
    await api.setLayerVisible(true);
    return { zoom, withLayerMs, withoutLayerMs, layerMs: withLayerMs - withoutLayerMs };
  },

  async loseAndRestoreContext(): Promise<ContextLossReport> {
    const gl = map.getCanvas().getContext('webgl2');
    const lose = gl?.getExtension('WEBGL_lose_context');
    if (lose === undefined || lose === null) throw new Error('bench: WEBGL_lose_context missing');
    let lostFired = false;
    let restoredFired = false;
    const lost = new Promise<void>((resolve) =>
      map.once('webglcontextlost', () => {
        lostFired = true;
        resolve();
      }),
    );
    lose.loseContext();
    await lost;
    await nextFrame();
    const restored = new Promise<void>((resolve) =>
      map.once('webglcontextrestored', () => {
        restoredFired = true;
        resolve();
      }),
    );
    lose.restoreContext();
    await restored;
    const framesBefore = layer.stats.frames;
    for (let i = 0; i < 300 && layer.stats.frames <= framesBefore + 2; i++) {
      map.triggerRepaint();
      await nextFrame();
    }
    await settle();
    return {
      lostFired,
      restoredFired,
      layerBack: map.getLayer(layer.id) !== undefined,
      modeAfter: layer.stats.mode,
      framesAfter: layer.stats.frames - framesBefore,
    };
  },
};

// Exposed for ad-hoc profiling from the console.
Object.assign(window, { __benchMap: map, __benchLayer: layer });

map.on('load', () => {
  layer.setData({ lngLat: points.lngLat, status: points.status });
  map.addLayer(layer);
  void settle().then(() => {
    window.glowBench = api;
  });
});
map.on('error', (event: maplibregl.ErrorEvent) => {
  window.glowBenchError = event.error.message;
  console.error(event.error);
});
