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
  FrameSample,
  GlObjectCounts,
  GlowBenchApi,
  GlowBenchInfo,
  LngLatTuple,
  Recording,
} from '../bench/api';
import { BLOOM_SCALES_PX, PULSE_SECONDS } from '../src/map/glow/curves';

const OUT = resolve(import.meta.dirname, '../bench/out');
const REPORT = resolve(OUT, 'glow.json');
const RUN_ID = process.env.GLOW_BENCH_RUN ?? '';

const SYNTHETIC_POINTS = 30_000;
const STRESS_POINTS = 150_000;
const LAYER_CPU_BUDGET_MS = 1.0;
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

test('on a 2x screen the CSS-pixel light target reads the same as device resolution', async ({
  browser,
  baseURL,
}) => {
  // Default: one light pixel per CSS pixel, a quarter of the device pixels at 2x.
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  const problems = watchProblems(page, baseURL);
  await installApiHelper(page);
  const shots: Buffer[] = [];
  for (const res of [1, 2]) {
    const info = await openBench(page, `?count=${String(SYNTHETIC_POINTS)}&res=${String(res)}`);
    expect(info.devicePixelRatio).toBe(2);
    await view(page, CONUS_CENTER, CONUS_ZOOM);
    shots.push(await page.screenshot({ path: resolve(OUT, `conus-2x-res${String(res)}.png`) }));
  }
  await context.close();
  const [reduced, device] = shots;
  if (reduced === undefined || device === undefined) throw new Error('missing screenshots');
  const diff = await compareImages(reduced, device);
  report('lightResolution', {
    compared: 'device pixel ratio 2: 1 light px per CSS px (default) vs 2 (device resolution)',
    ...diff,
  });
  expect(diff.psnrDb).toBeGreaterThan(40);
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
  // Guard band of 48 CSS px a side at one light pixel per CSS pixel.
  expect([resized.targetWidth, resized.targetHeight]).toEqual([1096, 796]);
  expect(dense.layerPixelRatio).toBe(2);
  expect([dense.targetWidth, dense.targetHeight]).toEqual([1096, 796]);
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
