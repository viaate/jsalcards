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
import type {
  ContextLossReport,
  SyncFrameCost,
  FrameSample,
  GlObjectCounts,
  GlowBenchApi,
  Recording,
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
