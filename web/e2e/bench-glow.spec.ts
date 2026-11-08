/**
 * Glow renderer benchmark. Runs only through `npm run bench:glow`
 * (bench/playwright.config.ts); the app's own e2e run skips it.
 *
 * Every point is SYNTHETIC (bench/synthetic.ts). Chromium here has no GPU and
 * draws WebGL2 with SwiftShader on the CPU, so frame rates describe the
 * software rasterizer. The layer's main-thread time per frame is the number
 * that carries over to real hardware, and it has a hard budget.
 *
 * Writes bench/out/glow.json and screenshots next to it.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { cpus, loadavg } from 'node:os';
import { resolve } from 'node:path';

import { expect, test, type Page } from '@playwright/test';
import sharp from 'sharp';

import type {
  BornClock,
  CoverTasks,
  FrameSample,
  GlObjectCounts,
  GlowBenchApi,
  GlowBenchInfo,
  LngLatTuple,
  Recording,
  SamePlacesCost,
  SamePlacesHow,
} from '../bench/api';
import { BLOOM_SCALES_PX, PULSE_SECONDS } from '../src/map/glow/curves';
import { COVER_MS, SLICE_MS } from '../src/map/same-places';

const OUT = resolve(import.meta.dirname, '../bench/out');
const REPORT = resolve(OUT, 'glow.json');
const RUN_ID = process.env.GLOW_BENCH_RUN ?? '';

const SYNTHETIC_POINTS = 30_000;
const STRESS_POINTS = 150_000;
const LAYER_CPU_BUDGET_MS = 1.0;
/** The directory's schools (2026-10 edition). */
const DIRECTORY_SCHOOLS = 118_211;
/**
 * The page's share of the schools at lit places, by the lead's ruling R4-B1-MEASURE (the test
 * below says how): the most main-thread thread time any task of theirs may take (the light's
 * own call, and each task the page runs for them after it: making the worker and sending it the
 * places, taking its answers, finding a light's covered schools and marking them, the first on
 * a page included), and the median cover task's; the wall time over which an untraced task must
 * show it was held off the CPU, by thread time at most OFF_CPU_THREAD_MS in the matching traced
 * page; and the thread time a frame drawn while schools are covered may add over a quiet frame
 * before it is a should-fix (reported, not asserted).
 */
const SAME_PLACES_THREAD_MS = 5;
const SAME_PLACES_MEDIAN_COVER_THREAD_MS = 2;
const SAME_PLACES_WALL_MS = 5;
const OFF_CPU_THREAD_MS = 2.5;
const FRAME_ADDED_THREAD_MS = 5;
/** Pages of each day, untraced and traced in turn. */
const PAGES_EACH = 3;
/**
 * The longest from a light to the schools at its lit places all covered, a page's first
 * included: the worker's start and build, thirty or so milliseconds, and the frames drawn
 * between the page's tasks; and with the CPU four times slower, as Lighthouse's phone runs are.
 */
const COVERED_AFTER_MS = 200;
const SLOW_CPU = 4;
const SLOW_COVERED_AFTER_MS = 500;
const CONUS_CENTER: LngLatTuple = [-96.4, 38.4];
const CONUS_ZOOM = 3.9;
const PAN_FROM: LngLatTuple = [-103, 38.4];
const PAN_TO: LngLatTuple = [-89, 38.4];
const PAN_ZOOM = 4.2;
const PAN_MS = 5000;
/** Three SYNTHETIC lone points (closed, delayed, remote) a degree apart, and where they sit. */
const LONE_CENTER: LngLatTuple = [-94, 39.1];
const LONE_LNGLAT = [-95, 39.1, -94, 39.1, -93, 39.1];
const LONE_STATUS = [0, 1, 2];
/** A SYNTHETIC pile of closed points on one spot. */
const PILE_CENTER: LngLatTuple = [-87.6, 41.9];

// The bench config sets GLOW_BENCH_RUN; the app's e2e run leaves it unset and skips this file.
test.skip(process.env.GLOW_BENCH_RUN === undefined, 'Run with npm run bench:glow');

// --- helpers ---------------------------------------------------------------

function watchProblems(page: Page, baseURL: string | undefined): string[] {
  const list: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      list.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => list.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => list.push(`requestfailed: ${request.url()}`));
  page.on('request', (request) => {
    if (baseURL !== undefined && new URL(request.url()).origin !== new URL(baseURL).origin) {
      list.push(`foreign request: ${request.url()}`);
    }
  });
  return list;
}

async function openBench(page: Page, query = ''): Promise<GlowBenchInfo> {
  await page.goto(`/glow.html${query}`);
  await page.waitForFunction(
    () => window.glowBench !== undefined || window.glowBenchError !== undefined,
    null,
    { timeout: 120_000 },
  );
  expect(await page.evaluate(() => window.glowBenchError)).toBeUndefined();
  return page.evaluate(() => api().info());
}

/** Resolves the bench API inside the page. Serialized into page.evaluate callbacks. */
declare function api(): GlowBenchApi;

async function installApiHelper(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (globalThis as unknown as { api: () => GlowBenchApi }).api = () => {
      const bench = window.glowBench;
      if (bench === undefined) throw new Error('glow bench not ready');
      return bench;
    };
  });
}

async function view(page: Page, center: LngLatTuple, zoom: number): Promise<void> {
  await page.evaluate(([c, z]) => api().view(c, z), [center, zoom] as const);
}

async function pan(page: Page): Promise<Recording> {
  return page.evaluate(([from, to, zoom, ms]) => api().pan(from, to, zoom, ms), [
    PAN_FROM,
    PAN_TO,
    PAN_ZOOM,
    PAN_MS,
  ] as const);
}

function quantile(values: readonly number[], q: number): number {
  if (values.length === 0) return Number.NaN;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * q;
  const a = sorted[Math.floor(position)] ?? Number.NaN;
  const b = sorted[Math.ceil(position)] ?? Number.NaN;
  return a + (b - a) * (position - Math.floor(position));
}

const round = (value: number, digits = 3): number => Number(value.toFixed(digits));

interface Summary {
  readonly frames: number;
  readonly durationMs: number;
  readonly frameIntervalMs: { readonly median: number; readonly p95: number };
  readonly fps: { readonly fromMedianInterval: number; readonly mean: number };
  readonly rafIntervalMs: { readonly median: number; readonly p95: number };
  readonly layerCpuMs: {
    readonly median: number;
    readonly p95: number;
    readonly max: number;
  } | null;
  readonly layerGpuMs: {
    readonly median: number;
    readonly p95: number;
    readonly samples: number;
  } | null;
}

function summarize(
  recording: Recording,
  samples: readonly FrameSample[] = recording.samples,
): Summary {
  const intervals = samples.map((s) => s.interval);
  const drawn = samples.filter((s) => s.layerDrew);
  const cpu = drawn.map((s) => s.layerCpuMs);
  const gpu = drawn.map((s) => s.layerGpuMs).filter((v): v is number => v !== null);
  const median = quantile(intervals, 0.5);
  return {
    frames: samples.length,
    durationMs: round(recording.durationMs, 1),
    frameIntervalMs: { median: round(median, 2), p95: round(quantile(intervals, 0.95), 2) },
    fps: {
      fromMedianInterval: round(1000 / median, 1),
      mean: round((samples.length * 1000) / recording.durationMs, 1),
    },
    rafIntervalMs: {
      median: round(quantile(recording.rafIntervals, 0.5), 2),
      p95: round(quantile(recording.rafIntervals, 0.95), 2),
    },
    layerCpuMs:
      cpu.length === 0
        ? null
        : {
            median: round(quantile(cpu, 0.5), 4),
            p95: round(quantile(cpu, 0.95), 4),
            max: round(Math.max(...cpu), 4),
          },
    layerGpuMs:
      gpu.length === 0
        ? null
        : {
            median: round(quantile(gpu, 0.5), 3),
            p95: round(quantile(gpu, 0.95), 3),
            samples: gpu.length,
          },
  };
}

/** Per-channel difference between two same-size screenshots. */
async function compareImages(a: Buffer, b: Buffer): Promise<Record<string, number>> {
  const [ra, rb] = await Promise.all([
    sharp(a).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
    sharp(b).removeAlpha().raw().toBuffer({ resolveWithObject: true }),
  ]);
  expect([ra.info.width, ra.info.height]).toEqual([rb.info.width, rb.info.height]);
  let sum = 0;
  let sumSq = 0;
  let max = 0;
  let over8 = 0;
  const n = ra.data.length;
  for (let i = 0; i < n; i++) {
    const d = Math.abs((ra.data[i] ?? 0) - (rb.data[i] ?? 0));
    sum += d;
    sumSq += d * d;
    if (d > max) max = d;
    if (d > 8) over8++;
  }
  const mse = sumSq / n;
  return {
    meanAbsDiff: round(sum / n, 4),
    maxAbsDiff: max,
    channelsOver8Pct: round((over8 / n) * 100, 4),
    psnrDb: mse === 0 ? 99 : round(10 * Math.log10((255 * 255) / mse), 2),
  };
}

interface PixelFacts {
  readonly tokenPixels: Record<string, number>;
  readonly hottest: readonly [number, number, number];
  /** Brightest channel anywhere, 0..255. */
  readonly peak: number;
  /** Pixels with every channel at 250 or more. */
  readonly whitePixels: number;
  /** Bright pixels (a channel at 128 or more) whose whole 3x3 neighbourhood is the same color: flat plateaus. */
  readonly flatBright: number;
  /** Pixels with a channel above 8. */
  readonly litPixels: number;
  readonly litShare: number;
}

/** Pixel facts about a screenshot: exact token hits, the hottest pixel, and how much is lit. */
async function pixelFacts(png: Buffer): Promise<PixelFacts> {
  const { data, info } = await sharp(png).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const tokens: Record<string, readonly [number, number, number]> = {
    closed: [0x7f, 0xd4, 0xff],
    delayed: [0xff, 0xc4, 0x6b],
    remote: [0xb7, 0x9c, 0xff],
    earlyDismissal: [0x6b, 0xff, 0xb0],
  };
  const tokenPixels: Record<string, number> = Object.fromEntries(
    Object.keys(tokens).map((name) => [name, 0]),
  );
  let hottest: [number, number, number] = [0, 0, 0];
  let peak = 0;
  let lit = 0;
  let white = 0;
  let flatBright = 0;
  const { width, height } = info;
  const same = (a: number, b: number): boolean =>
    data[a] === data[b] && data[a + 1] === data[b + 1] && data[a + 2] === data[b + 2];
  for (let i = 0; i < data.length; i += 3) {
    const r = data[i] ?? 0;
    const g = data[i + 1] ?? 0;
    const b = data[i + 2] ?? 0;
    const max = Math.max(r, g, b);
    if (r + g + b > hottest[0] + hottest[1] + hottest[2]) hottest = [r, g, b];
    if (max > peak) peak = max;
    if (max > 8) lit++;
    if (Math.min(r, g, b) >= 250) white++;
    for (const [name, [tr, tg, tb]] of Object.entries(tokens)) {
      if (r === tr && g === tg && b === tb) tokenPixels[name] = (tokenPixels[name] ?? 0) + 1;
    }
    const x = (i / 3) % width;
    const y = Math.floor(i / 3 / width);
    if (max >= 128 && x > 0 && y > 0 && x < width - 1 && y < height - 1) {
      let flat = true;
      for (let dy = -1; dy <= 1 && flat; dy++) {
        for (let dx = -1; dx <= 1 && flat; dx++) flat = same(i, i + (dy * width + dx) * 3);
      }
      if (flat) flatBright++;
    }
  }
  return {
    tokenPixels,
    hottest,
    peak,
    whitePixels: white,
    flatBright,
    litPixels: lit,
    litShare: round(lit / (data.length / 3), 4),
  };
}

/** Merges one section into glow.json, starting the file fresh for each bench run. */
function report(section: string, data: unknown, info?: GlowBenchInfo): void {
  mkdirSync(OUT, { recursive: true });
  let current: Record<string, unknown> = {};
  if (existsSync(REPORT)) {
    const parsed = JSON.parse(readFileSync(REPORT, 'utf8')) as Record<string, unknown>;
    if (parsed.runId === RUN_ID) current = parsed;
  }
  if (current.runId === undefined) {
    current = {
      runId: RUN_ID,
      generatedAt: new Date().toISOString(),
      synthetic: true,
      note: 'Every point is synthetic (bench/synthetic.ts). There is no GPU: Chromium renders WebGL2 with SwiftShader on the CPU, so fps and GPU times describe the software rasterizer, not real hardware. layerCpuMs is main-thread time inside the layer per frame.',
      budget: { layerCpuMedianMs: LAYER_CPU_BUDGET_MS },
    };
  }
  if (info !== undefined && current.environment === undefined) {
    current.environment = {
      renderer: info.renderer,
      gpu: 'none (SwiftShader software rasterizer)',
      cpus: cpus().length,
      viewport: { width: 1440, height: 900 },
      devicePixelRatio: info.devicePixelRatio,
      crossOriginIsolated: info.crossOriginIsolated,
      lightTarget: { width: info.targetWidth, height: info.targetHeight },
      mapLibre: info.mapVersion,
    };
  }
  // Other work on the machine shares the CPU with SwiftShader; record how busy it was.
  current[section] =
    typeof data === 'object' && data !== null && !Array.isArray(data)
      ? { ...data, loadAverage1m: round(loadavg()[0] ?? 0, 2) }
      : data;
  writeFileSync(REPORT, `${JSON.stringify(current, null, 2)}\n`);
}

// --- the benchmark ---------------------------------------------------------

test.describe.configure({ mode: 'serial' });

test('30,000 points: screenshots, 5 s pan and zoom sweep within the layer CPU budget', async ({
  page,
  baseURL,
}) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const info = await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  expect(info.synthetic).toBe(true);
  expect(info.mode).toBe('float');
  expect(info.pointCount).toBe(SYNTHETIC_POINTS);

  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const conus = await pixelFacts(await page.screenshot({ path: resolve(OUT, 'conus.png') }));
  const densest = await page.evaluate(() => api().densest());
  const shots: Record<string, PixelFacts> = { conus };
  for (const [name, zoom] of [
    ['region', 6.5],
    ['city', 9],
    ['metro', 12],
    ['street', 14.5],
  ] as const) {
    await view(page, densest, zoom);
    shots[name] = await pixelFacts(await page.screenshot({ path: resolve(OUT, `${name}.png`) }));
  }
  report('screenshots', shots);
  // The densest core is bright but never flat white, even where all four statuses mix.
  expect(conus.whitePixels).toBe(0);
  expect(Math.min(...conus.hottest)).toBeLessThan(245);
  // Glyph fills are the design tokens to the exact 8-bit value.
  for (const count of Object.values(shots.metro?.tokenPixels ?? {}))
    expect(count).toBeGreaterThan(0);

  // A 5 s continuous pan across the country at national zoom: every point in play.
  const panRun = summarize(await pan(page));
  // The same pan without the layer, to separate the map's own cost.
  await page.evaluate(() => api().setLayerVisible(false));
  const baselineRun = summarize(await pan(page));
  await page.evaluate(() => api().setLayerVisible(true));

  // Zoom sweep into the densest synthetic town and back out.
  const zoomIn = await page.evaluate(([c]) => api().zoomSweep(c, 3.5, 14, 5000), [
    densest,
  ] as const);
  const zoomOut = await page.evaluate(([c]) => api().zoomSweep(c, 14, 3.5, 5000), [
    densest,
  ] as const);
  const sweep: Recording = {
    durationMs: zoomIn.durationMs + zoomOut.durationMs,
    samples: [...zoomIn.samples, ...zoomOut.samples],
    rafIntervals: [...zoomIn.rafIntervals, ...zoomOut.rafIntervals],
  };
  const byZoom = Object.fromEntries(
    (
      [
        [3, 7],
        [7, 11],
        [11, 15],
      ] as const
    ).map(([lo, hi]) => [
      `z${String(lo)}-${String(hi)}`,
      summarize(
        sweep,
        sweep.samples.filter((s) => s.zoom >= lo && s.zoom < hi),
      ),
    ]),
  );
  const sweepRun = summarize(sweep);

  report(
    'runs30k',
    {
      points: SYNTHETIC_POINTS,
      pan: panRun,
      panWithoutLayer: baselineRun,
      zoomSweep: { ...sweepRun, byZoom },
    },
    info,
  );
  report('pass', {
    layerCpuBudget: (panRun.layerCpuMs?.median ?? Infinity) <= LAYER_CPU_BUDGET_MS,
  });

  expect(panRun.frames).toBeGreaterThan(10);
  expect(panRun.layerCpuMs?.median ?? Infinity).toBeLessThanOrEqual(LAYER_CPU_BUDGET_MS);
  expect(sweepRun.layerCpuMs?.median ?? Infinity).toBeLessThanOrEqual(LAYER_CPU_BUDGET_MS);
  expect(problems).toEqual([]);
});

test('150,000 points render, and replacing data leaks no GL objects', async ({ page, baseURL }) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);

  const before = await page.evaluate(() => api().liveGlObjects());
  await page.evaluate(([stress, base]) => api().churn([stress, base], 10), [
    STRESS_POINTS,
    SYNTHETIC_POINTS,
  ] as const);
  const after = await page.evaluate(() => api().liveGlObjects());

  const load = await page.evaluate((count) => api().setPointCount(count), STRESS_POINTS);
  const info = await page.evaluate(() => api().info());
  const run = summarize(await pan(page));
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  await page.screenshot({ path: resolve(OUT, 'conus-150k.png') });

  report('runs150k', {
    points: info.pointCount,
    generateMs: round(load.generateMs, 1),
    setDataMs: round(load.setDataMs, 2),
    pan: run,
  });
  report('glObjects', { before, afterTwentySetDataCalls: after });

  expect(info.pointCount).toBe(STRESS_POINTS);
  expect(run.frames).toBeGreaterThan(3);
  // Timer queries are pooled and capped, so only their bound is checked.
  const withoutQueries = (counts: GlObjectCounts): GlObjectCounts =>
    Object.fromEntries(Object.entries(counts).filter(([kind]) => kind !== 'query'));
  expect(withoutQueries(after)).toEqual(withoutQueries(before));
  expect(after.query ?? 0).toBeLessThanOrEqual(12);
  expect(problems).toEqual([]);
});

test('context loss: the layer comes back and draws the same picture', async ({ page, baseURL }) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const before = await page.screenshot();

  const loss = await page.evaluate(() => api().loseAndRestoreContext());
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const after = await page.screenshot();
  const diff = await compareImages(before, after);
  report('contextLoss', { ...loss, beforeVsAfter: diff });

  expect(loss).toMatchObject({
    lostFired: true,
    restoredFired: true,
    layerBack: true,
    modeAfter: 'float',
  });
  expect(loss.framesAfter).toBeGreaterThan(0);
  expect(diff.psnrDb).toBeGreaterThan(45);
  expect(problems).toEqual([]);
});

test('new points pulse in once and settle; reduced motion shows them at once', async ({
  page,
  baseURL,
}) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const settled = await page.screenshot();

  // The layer keeps asking for frames while points pulse, then stops.
  const framesBefore = await page.evaluate(() => api().info().layerFrames);
  await page.evaluate(() => {
    api().pulse(0.1);
  });
  // Born times on the layer's own clock, all in the past: nothing moved.
  const bornClamped = await page.evaluate(() => api().info().bornClamped);
  await page.waitForTimeout(400);
  const midPulse = await page.screenshot({ path: resolve(OUT, 'pulse.png') });
  await page.waitForTimeout(2000);
  const framesDuring = (await page.evaluate(() => api().info().layerFrames)) - framesBefore;
  await page.waitForTimeout(1000);
  const framesAfter =
    (await page.evaluate(() => api().info().layerFrames)) - framesBefore - framesDuring;
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const afterPulse = await page.screenshot();

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => {
    api().pulse(0.1);
  });
  await page.waitForTimeout(100);
  const reduced = await page.screenshot();

  const pulse = {
    bornClamped,
    layerFramesDuringPulse: framesDuring,
    layerFramesInTheSecondAfter: framesAfter,
    midPulseVsSettled: await compareImages(settled, midPulse),
    afterPulseVsSettled: await compareImages(settled, afterPulse),
    reducedMotionVsSettled: await compareImages(settled, reduced),
  };
  report('pulse', pulse);

  // Mid-pulse differs visibly; afterwards and under reduced motion it matches the settled map.
  expect(bornClamped).toBe(0);
  expect(framesDuring).toBeGreaterThan(10);
  expect(framesAfter).toBe(0);
  expect(pulse.midPulseVsSettled.psnrDb).toBeLessThan(45);
  expect(pulse.afterPulseVsSettled.psnrDb).toBeGreaterThan(50);
  expect(pulse.reducedMotionVsSettled.psnrDb).toBeGreaterThan(50);
  expect(problems).toEqual([]);
});

test('a bornAt later than now pulses in at once and stops asking for frames', async ({
  page,
  baseURL,
}) => {
  // A server clock a few seconds ahead, or Date.now() epoch ms passed where
  // performance.now() belongs, must not hide schools or repaint forever.
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const settledPng = await page.screenshot();
  const settled = await pixelFacts(settledPng);

  const clocks: readonly BornClock[] = ['skewed', 'epoch'];
  const results: Record<
    string,
    {
      bornClamped: number;
      layerFramesDuringPulse: number;
      layerFramesInTheSecondAfterPulsePlus1s: number;
      litShare: { midPulse: number; settled: number };
      midPulseVsSettled: Record<string, number>;
      afterVsSettled: Record<string, number>;
    }
  > = {};
  for (const clock of clocks) {
    await view(page, CONUS_CENTER, CONUS_ZOOM);
    const framesBefore = await page.evaluate(() => api().info().layerFrames);
    const setAt = Date.now();
    // Every point gets a born time in the future.
    await page.evaluate((c) => {
      api().pulse(1, c);
    }, clock);
    const bornClamped = await page.evaluate(() => api().info().bornClamped);
    await page.waitForTimeout(400);
    const midPng = await page.screenshot({ path: resolve(OUT, `pulse-${clock}.png`) });
    const mid = await pixelFacts(midPng);
    // Wait out one pulse and a second more, then count frames over the next second.
    await page.waitForTimeout(Math.max(0, setAt + (PULSE_SECONDS + 1) * 1000 - Date.now()));
    const framesAtQuiet = await page.evaluate(() => api().info().layerFrames);
    await page.waitForTimeout(1000);
    const framesInQuietSecond =
      (await page.evaluate(() => api().info().layerFrames)) - framesAtQuiet;
    const afterPng = await page.screenshot();
    const midVsSettled = await compareImages(settledPng, midPng);
    const afterVsSettled = await compareImages(settledPng, afterPng);
    results[clock] = {
      bornClamped,
      layerFramesDuringPulse: framesAtQuiet - framesBefore,
      layerFramesInTheSecondAfterPulsePlus1s: framesInQuietSecond,
      litShare: { midPulse: mid.litShare, settled: settled.litShare },
      midPulseVsSettled: midVsSettled,
      afterVsSettled,
    };
  }
  report('futureBornAt', results);
  for (const r of Object.values(results)) {
    // Every school is lit mid-pulse (before the fix none of them were) and visibly pulsing.
    expect(r.bornClamped).toBe(SYNTHETIC_POINTS);
    expect(r.litShare.midPulse).toBeGreaterThan(r.litShare.settled * 0.6);
    expect(r.midPulseVsSettled.psnrDb).toBeLessThan(45);
    // One pulse, then the layer stops asking for frames and matches the settled map.
    expect(r.layerFramesDuringPulse).toBeGreaterThan(5);
    expect(r.layerFramesInTheSecondAfterPulsePlus1s).toBe(0);
    expect(r.afterVsSettled.psnrDb).toBeGreaterThan(50);
  }
  expect(problems).toEqual([]);
});

test('a pile of points on one spot blooms no wider than a smaller pile', async ({
  page,
  baseURL,
}) => {
  // Thousands of SYNTHETIC points on one spot: the bloom has a bound in both render paths.
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const results: Record<string, { litRadiusPx: Record<string, number>; whitePixels: number }> = {};
  for (const mode of ['float', 'fallback'] as const) {
    const info = await openBench(page, `?count=100${mode === 'fallback' ? '&fallback=1' : ''}`);
    expect(info.mode).toBe(mode);
    const radius: Record<string, number> = {};
    let whitePixels = 0;
    for (const count of [2_000, SYNTHETIC_POINTS]) {
      await page.evaluate(
        ([n, c]) => {
          api().setPoints(
            Array.from({ length: n * 2 }, (_, i) => c[i % 2] ?? 0),
            new Array<number>(n).fill(0),
          );
        },
        [count, PILE_CENTER] as const,
      );
      await view(page, PILE_CENTER, 4);
      const facts = await pixelFacts(
        await page.screenshot({ path: resolve(OUT, `pile-${String(count)}-${mode}.png`) }),
      );
      // Equivalent radius of the lit area (a channel above 8), px.
      radius[String(count)] = round(Math.sqrt(facts.litPixels / Math.PI), 1);
      whitePixels += facts.whitePixels;
    }
    results[mode] = { litRadiusPx: radius, whitePixels };
  }
  report('pile', results);
  // The bloom's widest scale is 64 px; its tent filters carry light about twice that far.
  const reach = 2 * Math.max(...BLOOM_SCALES_PX);
  for (const { litRadiusPx, whitePixels } of Object.values(results)) {
    const small = litRadiusPx['2000'] ?? 0;
    const large = litRadiusPx[String(SYNTHETIC_POINTS)] ?? Infinity;
    expect(large).toBeLessThan(small * 1.15);
    expect(large).toBeLessThan(reach);
    expect(whitePixels).toBe(0);
  }
  expect(problems).toEqual([]);
});

test('on a 2x screen the light target has the device’s resolution by default', async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const shots: Buffer[] = [];
  for (const res of ['', '&res=2', '&res=1']) {
    const info = await openBench(page, `?count=${String(SYNTHETIC_POINTS)}${res}`);
    expect(info.devicePixelRatio).toBe(2);
    await view(page, CONUS_CENTER, CONUS_ZOOM);
    shots.push(
      await page.screenshot({ path: resolve(OUT, `conus-2x${res.replace('&', '-')}.png`) }),
    );
  }
  await context.close();
  const [byDefault, device, reduced] = shots;
  if (byDefault === undefined || device === undefined || reduced === undefined) {
    throw new Error('missing screenshots');
  }
  const same = await compareImages(byDefault, device);
  const diff = await compareImages(reduced, device);
  report('lightResolution', {
    compared: 'device pixel ratio 2: 2 light px per CSS px (default) vs 1',
    ...diff,
  });
  expect(same.psnrDb).toBeGreaterThan(60);
  expect(problems).toEqual([]);
});

test('synchronous frame cost with and without the layer', async ({ page, baseURL }) => {
  // map.redraw() plus a 1-pixel readback waits for SwiftShader to finish the
  // frame, which the timer query extension on SwiftShader does not measure well.
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  const densest = await page.evaluate(() => api().densest());
  const costs = [];
  for (const [center, zoom] of [
    [CONUS_CENTER, PAN_ZOOM],
    [densest, 9],
    [densest, 12],
  ] as const) {
    costs.push(
      await page.evaluate(([c, z]) => api().syncFrameCost(c, z, 9), [center, zoom] as const),
    );
  }
  report('syncFrameCostMs', costs);
  // Chromium flags the deliberate readback stall once; nothing else is allowed.
  expect(problems.filter((p) => !p.includes('GPU stall due to ReadPixels'))).toEqual([]);
});

test('resizing the map and changing its pixel ratio reallocate the light target', async ({
  page,
  baseURL,
}) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const first = await openBench(page, `?count=${String(SYNTHETIC_POINTS)}`);
  await view(page, CONUS_CENTER, CONUS_ZOOM);

  await page.setViewportSize({ width: 1000, height: 700 });
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const resized = await page.evaluate(() => api().info());
  const resizedShot = await pixelFacts(await page.screenshot());

  await page.evaluate(() => api().setPixelRatio(2));
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const dense = await page.evaluate(() => api().info());
  const denseShot = await pixelFacts(await page.screenshot());

  await page.evaluate(() => api().setPixelRatio(1));
  await page.setViewportSize({ width: 1440, height: 900 });
  await view(page, CONUS_CENTER, CONUS_ZOOM);
  const back = await page.evaluate(() => api().info());

  report('resize', {
    initial: { target: [first.targetWidth, first.targetHeight], pixelRatio: first.layerPixelRatio },
    at1000x700: {
      target: [resized.targetWidth, resized.targetHeight],
      litShare: resizedShot.litShare,
    },
    atPixelRatio2: {
      target: [dense.targetWidth, dense.targetHeight],
      pixelRatio: dense.layerPixelRatio,
      litShare: denseShot.litShare,
    },
    restored: { target: [back.targetWidth, back.targetHeight], pixelRatio: back.layerPixelRatio },
  });
  // Guard band of 48 CSS px a side, at the device's resolution.
  expect([resized.targetWidth, resized.targetHeight]).toEqual([1096, 796]);
  expect(dense.layerPixelRatio).toBe(2);
  expect([dense.targetWidth, dense.targetHeight]).toEqual([2192, 1592]);
  expect([back.targetWidth, back.targetHeight]).toEqual([first.targetWidth, first.targetHeight]);
  expect(back.layerPixelRatio).toBe(1);
  expect(resizedShot.litShare).toBeGreaterThan(0.2);
  expect(denseShot.litShare).toBeGreaterThan(0.2);
  expect(problems).toEqual([]);
});

test('8-bit fallback: no flat white, soft cores, lone points as bright as the float path', async ({
  page,
  baseURL,
}) => {
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const conus: Partial<Record<'float' | 'fallback', Buffer>> = {};
  const lone: Partial<Record<'float' | 'fallback', Record<string, PixelFacts>>> = {};
  let fallbackPan: Summary | null = null;
  for (const mode of ['float', 'fallback'] as const) {
    const info = await openBench(
      page,
      `?count=${String(SYNTHETIC_POINTS)}${mode === 'fallback' ? '&fallback=1' : ''}`,
    );
    expect(info.mode).toBe(mode);
    await view(page, CONUS_CENTER, CONUS_ZOOM);
    conus[mode] = await page.screenshot(
      mode === 'fallback' ? { path: resolve(OUT, 'conus-fallback.png') } : {},
    );
    if (mode === 'fallback') fallbackPan = summarize(await pan(page));
    await page.evaluate(
      ([ll, st]) => {
        api().setPoints(ll, st);
      },
      [LONE_LNGLAT, LONE_STATUS] as const,
    );
    const facts: Record<string, PixelFacts> = {};
    for (const zoom of [4, 8]) {
      await view(page, LONE_CENTER, zoom);
      const shot = await page.screenshot({ clip: { x: 420, y: 350, width: 600, height: 200 } });
      facts[`z${String(zoom)}`] = await pixelFacts(shot);
    }
    lone[mode] = facts;
  }
  const floatConus = conus.float;
  const fallbackConus = conus.fallback;
  if (floatConus === undefined || fallbackConus === undefined) throw new Error('missing shots');
  const floatFacts = await pixelFacts(floatConus);
  const fallbackFacts = await pixelFacts(fallbackConus);
  const loneSummary = Object.fromEntries(
    ['z4', 'z8'].map((z) => [
      z,
      {
        peak: { float: lone.float?.[z]?.peak, fallback: lone.fallback?.[z]?.peak },
        litPixels: { float: lone.float?.[z]?.litPixels, fallback: lone.fallback?.[z]?.litPixels },
      },
    ]),
  );
  report('fallback', {
    mode: 'fallback',
    pan: fallbackPan,
    conus: {
      vsFloat: await compareImages(floatConus, fallbackConus),
      litShare: { float: floatFacts.litShare, fallback: fallbackFacts.litShare },
      whitePixels: { float: floatFacts.whitePixels, fallback: fallbackFacts.whitePixels },
      flatBright: { float: floatFacts.flatBright, fallback: fallbackFacts.flatBright },
      hottest: { float: floatFacts.hottest, fallback: fallbackFacts.hottest },
    },
    lone: loneSummary,
  });

  expect(fallbackPan?.layerCpuMs?.median ?? Infinity).toBeLessThanOrEqual(LAYER_CPU_BUDGET_MS);
  // Dense metros roll off: no flat white, and no more flat plateaus than the float path has.
  expect(fallbackFacts.whitePixels).toBe(0);
  expect(Math.min(...fallbackFacts.hottest)).toBeLessThan(245);
  expect(fallbackFacts.flatBright).toBeLessThanOrEqual(floatFacts.flatBright + 20);
  // Same picture at a glance: at least half as much of the map lit.
  expect(fallbackFacts.litShare).toBeGreaterThan(floatFacts.litShare * 0.5);
  // A lone school is as bright as on the float path and lights a similar area.
  for (const z of ['z4', 'z8']) {
    const f = lone.float?.[z];
    const b = lone.fallback?.[z];
    if (f === undefined || b === undefined) throw new Error(`missing lone shots at ${z}`);
    expect(b.peak).toBeGreaterThanOrEqual(f.peak * 0.9);
    expect(b.litPixels).toBeGreaterThan(f.litPixels * 0.6);
    expect(b.litPixels).toBeLessThan(f.litPixels * 1.6);
  }
  expect(problems).toEqual([]);
});

interface TraceEvent {
  readonly name: string;
  readonly ph: string;
  readonly ts: number;
  readonly dur?: number;
  readonly tdur?: number;
  readonly pid: number;
  readonly tid: number;
  readonly id?: string;
  readonly id2?: { readonly local?: string };
  readonly args?: { readonly name?: string };
}

/** A task's wall time and the thread (CPU) time its thread spent on it, in milliseconds. */
interface WallAndThread {
  readonly wallMs: number;
  readonly threadMs: number;
}

/**
 * For each task and frame the bench named (bench/glow.ts: `same-place-task <seq>`,
 * `same-place-frame <n>`), the wall and thread time of the page's main-thread task that ran it,
 * from a trace: the shortest of the main thread's tasks that holds it.
 */
function tracedTimes(events: readonly TraceEvent[]): {
  tasks: Map<number, WallAndThread>;
  frames: Map<number, WallAndThread>;
} {
  const main = events.find((e) => e.name === 'thread_name' && e.args?.name === 'CrRendererMain');
  const tasks = new Map<number, WallAndThread>();
  const frames = new Map<number, WallAndThread>();
  if (main === undefined) return { tasks, frames };
  const onMain = (e: TraceEvent): boolean => e.pid === main.pid && e.tid === main.tid;
  const runs = events
    .filter((e) => onMain(e) && e.ph === 'X' && e.name === 'ThreadControllerImpl::RunTask')
    .sort((a, b) => a.ts - b.ts);
  const begun = new Map<string, TraceEvent>();
  for (const e of [...events].sort((a, b) => a.ts - b.ts)) {
    const named = /^same-place-(task|frame) (\d+)$/.exec(e.name);
    if (named === null) continue;
    const key = `${e.name} ${e.id2?.local ?? e.id ?? ''}`;
    if (e.ph === 'b') begun.set(key, e);
    // A measure of no length (a frame's) is an instant.
    const start = e.ph === 'n' ? e : begun.get(key);
    if ((e.ph !== 'e' && e.ph !== 'n') || start === undefined) continue;
    // The last task to start at or before its middle, and those before it that may hold it
    // too: by its middle, as its ends, taken on the page's clock, can fall a few microseconds
    // outside the task that ran it on the trace's.
    const mid = (start.ts + e.ts) / 2;
    let low = 0;
    let high = runs.length;
    while (low < high) {
      const at = (low + high) >> 1;
      if ((runs[at]?.ts ?? 0) <= mid) low = at + 1;
      else high = at;
    }
    let best: TraceEvent | undefined;
    for (let k = low - 1; k >= 0 && k >= low - 64; k--) {
      const run = runs[k];
      if (run === undefined || run.ts + (run.dur ?? 0) < mid) continue;
      if (best === undefined || (run.dur ?? 0) < (best.dur ?? 0)) best = run;
    }
    if (best === undefined) continue;
    const times = { wallMs: (best.dur ?? 0) / 1000, threadMs: (best.tdur ?? 0) / 1000 };
    (named[1] === 'task' ? tasks : frames).set(Number(named[2]), times);
  }
  return { tasks, frames };
}

/** What the same-place bench reports of a page, its asserts aside. */
interface PageTimes {
  readonly cost: SamePlacesCost;
  /** By the bench's seq; empty on a page not traced. */
  readonly traced: Map<number, WallAndThread>;
  readonly frames: Map<number, WallAndThread>;
}

test('the schools at a lit one’s place, in a directory the size of the real one, are found and covered within budget', async ({
  page,
  baseURL,
}) => {
  // SYNTHETIC places, one school in eight at a place it shares; one in ten lit (a big day's
  // share) and one in two hundred (a usual day's). Each page takes the page's own path from
  // its first light (map/same-places.ts SamePlaceCovers): the worker made then, the index built
  // in it, which answers with the light's covered schools too, and those marked a few at a
  // time from the event of its answer on; then six lights after it, the lit ones moved each
  // time, found with the index and marked likewise. Each page runs the code for the first time,
  // as a page's first light does.
  //
  // How this proves its bar, by the lead's ruling R4-B1-MEASURE: "no page task of this feature
  // does work that grows with the covered count, with real margin under 5 ms" is shown by three
  // gates, each hard. Wall time alone cannot show it on this 4-CPU machine, where the bench's
  // own SwiftShader GPU process takes about 3.4 CPUs and a plain busy wait (longestSpinMs) was
  // measured at 4.4 to 9.6 ms of wall time: such tasks are off the CPU, not at work.
  // A, code cost: on traced pages (big day and usual day, x1) every task of this feature, the
  //   light's call included, takes 5 ms of main-thread thread time (CPU time of
  //   CrRendererMain, from the trace) or less, and the median cover task 2 ms or less.
  // B, structure: same-places.test.ts counts, with no clock, what each task looks at and marks:
  //   the same most per task on days ten times apart in covered and lit schools.
  // C, wall time: the untraced pages' tasks are reported beside the same run's spin control,
  //   and one over 5 ms of wall time must show 2.5 ms of thread time or less at the same place
  //   in the matching traced page (held off the CPU); otherwise it fails.
  // At x4 the time to all covered stays at 500 ms at most, and its tasks are reported. The
  // frames MapLibre draws in a light's cover stretch are reported beside frames with no covers
  // (big day, x1): not this feature's tasks; more than 5 ms of thread time over them is a
  // should-fix, not a failure.
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const cdp = await page.context().newCDPSession(page);
  const measure = (every: number, how: SamePlacesHow, named: boolean): Promise<SamePlacesCost> =>
    page.evaluate(
      ([count, share, runs, built, traced]) => api().samePlaces(count, share, runs, built, traced),
      [DIRECTORY_SCHOOLS, every, 6, how, named] as const,
    );
  const untraced = async (every: number, how: SamePlacesHow = 'worker'): Promise<PageTimes> => ({
    cost: await measure(every, how, false),
    traced: new Map(),
    frames: new Map(),
  });
  const traced = async (every: number): Promise<PageTimes> => {
    const events: TraceEvent[] = [];
    const collect = (data: { value: object[] }): void => {
      events.push(...(data.value as unknown as TraceEvent[]));
    };
    cdp.on('Tracing.dataCollected', collect);
    await cdp.send('Tracing.start', {
      categories: process.env.SAME_PLACE_TRACE_CATEGORIES ?? 'toplevel,blink.user_timing',
      transferMode: 'ReportEvents',
    });
    const cost = await measure(every, 'worker', true);
    const complete = new Promise<void>((resolve) => {
      cdp.once('Tracing.tracingComplete', () => {
        resolve();
      });
    });
    await cdp.send('Tracing.end');
    await complete;
    cdp.off('Tracing.dataCollected', collect);
    // For a look at a page's tasks by hand: each traced page's trace and the bench's own numbers.
    const dir = process.env.SAME_PLACE_TRACE_DIR;
    if (dir !== undefined) {
      mkdirSync(dir, { recursive: true });
      const file = resolve(dir, `same-place-${String(every)}-${String(Date.now())}.json`);
      writeFileSync(file, JSON.stringify({ cost, events }));
    }
    return { cost, ...renamed(tracedTimes(events)) };
  };
  const renamed = ({
    tasks,
    frames,
  }: ReturnType<typeof tracedTimes>): Pick<PageTimes, 'traced' | 'frames'> => ({
    traced: tasks,
    frames,
  });
  const slowly = async <T>(cost: () => Promise<T>): Promise<T> => {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: SLOW_CPU });
    try {
      return await cost();
    } finally {
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    }
  };
  const open = async (): Promise<void> => {
    await openBench(page, '?count=100');
  };
  const loadBefore = loadavg();
  // Untraced and traced pages in turn, each traced page the match of the untraced one before it.
  const big: PageTimes[] = [];
  const bigTraced: PageTimes[] = [];
  const small: PageTimes[] = [];
  const smallTraced: PageTimes[] = [];
  for (let n = 0; n < PAGES_EACH; n++) {
    await open();
    big.push(await untraced(10));
    await open();
    bigTraced.push(await traced(10));
  }
  for (let n = 0; n < PAGES_EACH; n++) {
    await open();
    small.push(await untraced(200));
    await open();
    smallTraced.push(await traced(200));
  }
  const slow: PageTimes[] = [];
  for (let n = 0; n < 2; n++) {
    await open();
    slow.push(await slowly(() => untraced(10)));
  }
  await open();
  const slowTraced = await slowly(() => traced(10));
  const onPage: PageTimes[] = [];
  const onPageSlow: PageTimes[] = [];
  for (let n = 0; n < 2; n++) {
    await open();
    onPage.push(await untraced(10, 'slices'));
  }
  for (let n = 0; n < 2; n++) {
    await open();
    onPageSlow.push(await slowly(() => untraced(10, 'slices')));
  }
  const loadAfter = loadavg();

  const ms = (value: number): number => round(value, 2);
  const lights = ({ cost }: PageTimes): CoverTasks[] => [cost.firstLight, ...cost.laterLights];
  const median = (values: readonly number[]): number =>
    [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? Number.NaN;
  const later = (cost: SamePlacesCost): number =>
    Math.max(...cost.laterLights.map(({ coveredAfterMs }) => coveredAfterMs));
  const COVER_KINDS = new Set(['uncovering', 'covering']);
  /** Each light's tasks, the call first: its kind and its wall and thread time (traced pages). */
  const tasksOf = (times: PageTimes, light: CoverTasks) =>
    [{ kind: 'call', ms: light.askMs, seq: light.askSeq }, ...light.list].map((task) => ({
      ...task,
      thread: times.traced.get(task.seq)?.threadMs,
    }));
  const summary = (pages: readonly PageTimes[]) => ({
    askMs: pages.map((times) => lights(times).map(({ askMs }) => ms(askMs))),
    firstLight: pages.map(({ cost: { firstLight } }) => ({
      tasks: firstLight.tasks,
      busyMs: ms(firstLight.busyMs),
      longestTaskMs: ms(firstLight.longestTaskMs),
      medianTaskMs: ms(firstLight.medianTaskMs),
      longTasks: firstLight.longTasks,
      coveredAfterMs: ms(firstLight.coveredAfterMs),
    })),
    laterLights: pages.map(({ cost }) => ({
      tasks: cost.laterLights.map(({ tasks }) => tasks),
      busyMs: cost.laterLights.map(({ busyMs }) => ms(busyMs)),
      longestTaskMs: ms(Math.max(...cost.laterLights.map(({ longestTaskMs }) => longestTaskMs))),
      longTasks: cost.laterLights.flatMap(({ longTasks }) => longTasks),
      coveredAfterMs: ms(later(cost)),
    })),
    longestSpinMs: pages.map(({ cost }) => ms(cost.longestSpinMs)),
  });
  /** A traced page's tasks, light by light: "kind wall/thread" for each, the call first. */
  const wallAndThread = (times: PageTimes) =>
    lights(times).map((light) =>
      tasksOf(times, light).map(
        ({ kind, ms: wall, thread }) =>
          `${kind} ${wall.toFixed(2)}/${thread === undefined ? '?' : thread.toFixed(2)}`,
      ),
    );
  const tracedSummary = (pages: readonly PageTimes[]) => ({
    ...summary(pages),
    longestThreadMs: pages.map((times) =>
      ms(
        Math.max(
          ...lights(times).flatMap((light) =>
            tasksOf(times, light).map(({ thread }) => thread ?? Infinity),
          ),
        ),
      ),
    ),
    medianCoverThreadMs: pages.map((times) => ms(medianCoverThread(times))),
    tasksWallAndThreadMs: pages.map(wallAndThread),
  });
  const medianCoverThread = (times: PageTimes): number =>
    median(
      lights(times).flatMap((light) =>
        tasksOf(times, light)
          .filter(({ kind }) => COVER_KINDS.has(kind))
          .map(({ thread }) => thread ?? Infinity),
      ),
    );
  // Gate C: each untraced task over 5 ms of wall time against its match in the traced page:
  // the same light, the same step, the same turn of it; else the longest of that step in that
  // light, else of the light.
  const offCpu = (pages: readonly PageTimes[], tracedPages: readonly PageTimes[]) =>
    pages.flatMap((times, at) => {
      const match = tracedPages[at];
      return lights(times).flatMap((light, n) => {
        const matched = match === undefined ? undefined : lights(match)[n];
        const theirs = match === undefined || matched === undefined ? [] : tasksOf(match, matched);
        const turns = new Map<string, number>();
        return tasksOf(times, light).flatMap((task) => {
          const turn = turns.get(task.kind) ?? 0;
          turns.set(task.kind, turn + 1);
          if (task.ms <= SAME_PLACES_WALL_MS) return [];
          const same = theirs.filter(({ kind }) => kind === task.kind);
          const pick = same[turn] ?? (same.length > 0 ? same : theirs);
          const thread = Array.isArray(pick)
            ? Math.max(...pick.map(({ thread: t }) => t ?? Infinity))
            : (pick.thread ?? Infinity);
          return [
            {
              page: at,
              light: n,
              task: `${task.kind} ${String(turn)}`,
              wallMs: ms(task.ms),
              matchedThreadMs: ms(thread),
              offCpu: thread <= OFF_CPU_THREAD_MS,
            },
          ];
        });
      });
    });
  const gateC = [...offCpu(big, bigTraced), ...offCpu(small, smallTraced)];
  // The frames drawn while a light's schools were being covered, beside those of the quiet
  // stretch before the first light, on the traced big days at x1.
  const frameReport = bigTraced.map(({ cost, frames }) => {
    const shown = cost.frames;
    if (shown === undefined) return null;
    const thread = (n: number): number | undefined => frames.get(n)?.threadMs;
    const quiet = shown.at.flatMap((_, n) => {
      const t = n < shown.quietFrames ? thread(n) : undefined;
      return t === undefined ? [] : [t];
    });
    // Each frame from a light's call to its schools all covered, and the first after (it draws
    // the dust once they are, GlowLayer showCoveredDust).
    const after = new Set(
      shown.windows.map(([, to]) => shown.at.findIndex((at) => at > to)).filter((n) => n >= 0),
    );
    const inWindow = shown.at.flatMap((at, n) => {
      const t = thread(n);
      const covering = after.has(n) || shown.windows.some(([from, to]) => at >= from && at <= to);
      return covering && t !== undefined ? [t] : [];
    });
    const [litFrom, litTo] = shown.litOnly;
    const litOnly = shown.at.flatMap((_, n) => {
      const t = n >= litFrom && n < litTo ? thread(n) : undefined;
      return t === undefined ? [] : [t];
    });
    const baseline = median(quiet);
    const most = inWindow.length > 0 ? Math.max(...inWindow) : Number.NaN;
    const litMost = litOnly.length > 0 ? Math.max(...litOnly) : Number.NaN;
    return {
      quietFrames: quiet.length,
      quietMedianThreadMs: ms(baseline),
      quietLongestThreadMs: ms(Math.max(...quiet)),
      litOnlyFrames: litOnly.length,
      litOnlyThreadMs: litOnly.map(ms),
      coverThreadMs: inWindow.map(ms),
      addedOverLitOnlyMs: ms(most - litMost),
      coverFrames: inWindow.length,
      coverMedianThreadMs: ms(median(inWindow)),
      coverLongestThreadMs: ms(most),
      addedOverQuietMs: ms(most - baseline),
      shouldFix: most - baseline > FRAME_ADDED_THREAD_MS,
    };
  });
  report('samePlaces', {
    ruling:
      'R4-B1-MEASURE: gates A (traced thread time), B (same-places.test.ts counts), C (wall time against the matching traced page)',
    schools: DIRECTORY_SCHOOLS,
    shared: big[0]?.cost.shared,
    lit: { big: big[0]?.cost.lit, small: small[0]?.cost.lit },
    covered: { big: big[0]?.cost.covered, small: small[0]?.cost.covered },
    coverMs: COVER_MS,
    cpus: cpus().length,
    loadAverage: { before: loadBefore.map((l) => ms(l)), after: loadAfter.map((l) => ms(l)) },
    gateA: {
      threadBudgetMs: SAME_PLACES_THREAD_MS,
      medianCoverThreadBudgetMs: SAME_PLACES_MEDIAN_COVER_THREAD_MS,
      big: tracedSummary(bigTraced),
      small: tracedSummary(smallTraced),
    },
    gateC: { wallMs: SAME_PLACES_WALL_MS, offCpuThreadMs: OFF_CPU_THREAD_MS, checked: gateC },
    untraced: { big: summary(big), small: summary(small) },
    slowCpu: { untraced: summary(slow), traced: tracedSummary([slowTraced]) },
    onThePage: { sliceMs: SLICE_MS, cpu: summary(onPage), slowCpu: summary(onPageSlow) },
    coveredAfterBudgetMs: { cpu: COVERED_AFTER_MS, slowCpu: SLOW_COVERED_AFTER_MS },
    frames: { addedThreadShouldFixMs: FRAME_ADDED_THREAD_MS, bigDays: frameReport },
  });
  const worker = [...big, ...bigTraced, ...small, ...smallTraced, ...slow, slowTraced];
  const slices = [...onPage, ...onPageSlow];
  for (const { cost } of [...worker, ...slices]) {
    expect(cost.schools).toBe(DIRECTORY_SCHOOLS);
    expect(cost.covered).toBeGreaterThan(0);
    expect(cost.matches).toBe(true);
    // One in eight at a place it shares, and the near ones with them.
    expect(cost.shared).toBeGreaterThan(DIRECTORY_SCHOOLS / 8);
    expect(cost.how).toBe(slices.some((times) => times.cost === cost) ? 'slices' : 'worker');
  }
  // Gate A: every task of this feature's, the call, each listing and send step, each answer
  // taken, each uncover and cover task and the first cover, at 5 ms of thread time or less, on
  // every traced page at x1, the first light of a page (run before the page has made its code
  // fast) and each after it; and the median cover task at 2 ms or less. A task the trace did not
  // find fails too.
  for (const times of [...bigTraced, ...smallTraced]) {
    for (const light of lights(times)) {
      for (const task of tasksOf(times, light)) {
        expect(task.thread, `${task.kind} ${String(task.seq)} thread ms`).toBeDefined();
        expect(
          task.thread ?? Infinity,
          `${task.kind} ${String(task.seq)} thread ms`,
        ).toBeLessThanOrEqual(SAME_PLACES_THREAD_MS);
      }
    }
    expect(medianCoverThread(times)).toBeLessThanOrEqual(SAME_PLACES_MEDIAN_COVER_THREAD_MS);
  }
  // Gate C: a task long in wall time was held off the CPU, by its thread time in the match.
  for (const check of gateC) expect(check, JSON.stringify(check)).toMatchObject({ offCpu: true });
  for (const times of [...big, ...small, ...bigTraced, ...smallTraced]) {
    // A dark dot at a lit place is covered soon after the light, not seconds on.
    for (const light of lights(times)) {
      expect(light.coveredAfterMs).toBeLessThanOrEqual(COVERED_AFTER_MS);
    }
  }
  for (const times of [...slow, slowTraced]) {
    for (const light of lights(times)) {
      expect(light.coveredAfterMs).toBeLessThanOrEqual(SLOW_COVERED_AFTER_MS);
    }
  }
  // Built on the page, where no worker starts: its slices keep to SLICE_MS, and its covers to
  // COVER_MS, one task after another, and it is in as soon. (A task there can also meet a stop
  // of V8's own, a collection or a compile of 2 to 6 ms that lands on whichever task is
  // running: the page's own path above has none of the build's on the page.)
  // (R3-S3: the median slice and the time to covered; the lights after the first take the same
  // cover tasks as the worker's pages, which gate A covers.)
  for (const times of onPage) {
    const slicesOf = times.cost.firstLight.list.filter(({ kind }) => kind === 'slice');
    expect(slicesOf.length).toBeGreaterThan(0);
    expect(median(slicesOf.map(({ ms: wall }) => wall))).toBeLessThanOrEqual(SLICE_MS + 0.5);
    expect(times.cost.firstLight.medianTaskMs).toBeLessThanOrEqual(SLICE_MS + 0.5);
    for (const light of lights(times)) {
      expect(light.coveredAfterMs).toBeLessThanOrEqual(COVERED_AFTER_MS);
    }
  }
  for (const times of onPageSlow) {
    for (const light of lights(times)) {
      expect(light.coveredAfterMs).toBeLessThanOrEqual(SLOW_COVERED_AFTER_MS);
    }
  }
  for (const { cost } of [...big, ...bigTraced, ...slow]) {
    expect(cost.lit).toBe(Math.ceil(DIRECTORY_SCHOOLS / 10));
  }
  expect(problems).toEqual([]);
});
