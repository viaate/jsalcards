/**
 * Search engine bench: builds an index from 200,000 SYNTHETIC records (see
 * synthetic-records.ts), serves it with the real client and worker from a
 * production build of bench.html, and measures what the bar asks for:
 *
 *   - index size, gzip-compressed (at most 3 MB)
 *   - worker ready within 400 ms of the start of the index fetch
 *   - p95 query time at most 8 ms, in the worker and round trip
 *   - no main-thread task over 16 ms, from a Chrome trace of the whole run
 *   - with the worker chunk deleted, `ready` and every search reject within
 *     1 s instead of hanging
 *
 * SEARCH_BENCH_RECORDS=a.jsonl,b.jsonl runs the same bench on other search
 * records (the generic shape in src/search/types.ts) instead.
 * Results go to $SEARCH_BENCH_OUT/search-bench.json.
 */
import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { expect, test } from '@playwright/test';
import type { CDPSession, Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';
import { gzipSync } from 'node:zlib';

import { encodeIndex, validateRecord } from '../../src/search/encode';
import type { SearchRecord } from '../../src/search/types';
import { benchQueries } from './queries';
import { syntheticSearchRecords } from './synthetic-records';
import { benchOutDir } from './vite.config';

const here = import.meta.dirname;
const port = Number(process.env.SEARCH_BENCH_PORT ?? '5107');
const INDEX_FILE = 'synthetic-search-index.bin';
const MAX_GZIP_BYTES = 3_000_000;
const MAX_READY_MS = 400;
const MAX_P95_MS = 8;
const MAX_MAIN_TASK_MS = 16;
/** A copy of the bench page, served beside it, whose worker chunk is deleted. */
const NO_WORKER_DIR = 'no-worker';
const MAX_FAILURE_MS = 1000;

interface TraceEvent {
  readonly name: string;
  readonly ph: string;
  readonly pid: number;
  readonly tid: number;
  readonly ts: number;
  readonly dur?: number;
  readonly args?: { readonly name?: string };
}

function loadRecords(): { records: SearchRecord[]; source: string } {
  const files = process.env.SEARCH_BENCH_RECORDS;
  if (!files) return { records: syntheticSearchRecords(), source: 'synthetic' };
  const records: SearchRecord[] = [];
  for (const file of files.split(',')) {
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        if (line.trim()) records.push(validateRecord(JSON.parse(line), `${file}:${String(i + 1)}`));
      });
  }
  return { records, source: files };
}

function percentile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return 0;
  const at = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, at)] ?? 0;
}

function summary(values: readonly number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  const round = (x: number): number => Math.round(x * 1000) / 1000;
  return {
    count: sorted.length,
    p50: round(percentile(sorted, 50)),
    p95: round(percentile(sorted, 95)),
    p99: round(percentile(sorted, 99)),
    max: round(sorted[sorted.length - 1] ?? 0),
    mean: round(sorted.reduce((a, b) => a + b, 0) / Math.max(1, sorted.length)),
  };
}

async function startTrace(cdp: CDPSession): Promise<() => Promise<TraceEvent[]>> {
  const events: TraceEvent[] = [];
  cdp.on('Tracing.dataCollected', (e) => {
    // The protocol types values as string maps; trace events carry numbers too.
    events.push(...(e.value as unknown as TraceEvent[]));
  });
  await cdp.send('Tracing.start', {
    categories:
      'toplevel,blink.user_timing,devtools.timeline,disabled-by-default-devtools.timeline',
    transferMode: 'ReportEvents',
  });
  return async () => {
    const complete = new Promise<void>((done) => {
      cdp.once('Tracing.tracingComplete', () => {
        done();
      });
    });
    await cdp.send('Tracing.end');
    await complete;
    return events;
  };
}

/** Longest tasks on the thread that recorded `mark`, between two marks, and on worker threads. */
function taskStats(events: readonly TraceEvent[], from: string, to: string) {
  const start = events.find((e) => e.name === from);
  const end = events.find((e) => e.name === to);
  if (!start || !end) throw new Error('trace is missing the bench marks');
  const threadNames = new Map<string, string>();
  for (const e of events) {
    if (e.ph === 'M' && e.name === 'thread_name') {
      threadNames.set(`${String(e.pid)}:${String(e.tid)}`, e.args?.name ?? '');
    }
  }
  const tasks = events.filter(
    (e) =>
      e.ph === 'X' &&
      (e.name === 'RunTask' || e.name === 'ThreadControllerImpl::RunTask') &&
      e.ts >= start.ts &&
      e.ts <= end.ts,
  );
  const main = tasks.filter((e) => e.pid === start.pid && e.tid === start.tid);
  const mainDurations = main.map((e) => (e.dur ?? 0) / 1000);
  const worker = tasks.filter((e) =>
    (threadNames.get(`${String(e.pid)}:${String(e.tid)}`) ?? '').startsWith('DedicatedWorker'),
  );
  const top = (list: readonly number[]) =>
    [...list]
      .sort((a, b) => b - a)
      .slice(0, 5)
      .map((ms) => Math.round(ms * 100) / 100);
  return {
    mainThread: threadNames.get(`${String(start.pid)}:${String(start.tid)}`) ?? 'unknown',
    mainTasks: main.length,
    mainLongest: top(mainDurations),
    mainOver16ms: mainDurations.filter((ms) => ms > MAX_MAIN_TASK_MS).length,
    workerLongest: top(worker.map((e) => (e.dur ?? 0) / 1000)),
  };
}

let server: PreviewServer | undefined;
let gzipBytes = 0;
let rawBytes = 0;
let recordCount = 0;
let source = '';
let queries: string[] = [];
let deletedWorker = '';

/** Copies the built page into site/no-worker/, leaving out the worker chunk. */
function writeNoWorkerCopy(site: string): string {
  const dir = join(site, NO_WORKER_DIR);
  mkdirSync(join(dir, 'assets'), { recursive: true });
  copyFileSync(join(site, 'bench.html'), join(dir, 'bench.html'));
  const assets = readdirSync(join(site, 'assets'));
  const workers = assets.filter((f) => /^worker-.*\.js$/.test(f));
  if (workers.length !== 1)
    throw new Error(`expected one worker chunk, found ${workers.join(', ')}`);
  for (const f of assets) {
    if (!f.startsWith('worker-')) copyFileSync(join(site, 'assets', f), join(dir, 'assets', f));
  }
  return `${NO_WORKER_DIR}/assets/${workers[0] ?? ''}`;
}

test.beforeAll(async () => {
  const loaded = loadRecords();
  source = loaded.source;
  recordCount = loaded.records.length;
  const { bytes } = encodeIndex(loaded.records);
  const gz = gzipSync(bytes, { level: 9 });
  gzipBytes = gz.length;
  rawBytes = bytes.length;
  queries = benchQueries(loaded.records);

  const configFile = resolve(here, 'vite.config.ts');
  await build({ configFile, logLevel: 'warn' });
  writeFileSync(join(benchOutDir, 'site', INDEX_FILE), gz);
  deletedWorker = writeNoWorkerCopy(join(benchOutDir, 'site'));
  server = await preview({
    configFile,
    logLevel: 'warn',
    preview: { host: '127.0.0.1', port, strictPort: true },
  });
});

test.afterAll(async () => {
  await server?.close();
});

async function openBench(page: Page, dir = ''): Promise<void> {
  await page.goto(`http://127.0.0.1:${String(port)}/${dir}bench.html`);
  await page.waitForFunction(() => 'searchBench' in window);
  expect(await page.evaluate(() => window.crossOriginIsolated)).toBe(true);
}

test('search engine meets the bar', async ({ page }) => {
  await openBench(page);
  await page.evaluate((qs) => {
    window.searchBench.setQueries(qs);
  }, queries);
  const cdp = await page.context().newCDPSession(page);
  const stopTrace = await startTrace(cdp);

  await page.evaluate((file) => window.searchBench.start(file), INDEX_FILE);
  await page.evaluate(() => window.searchBench.run());
  await page.evaluate(() => window.searchBench.burst(200));
  await page.evaluate(() => performance.mark('search-done'));
  const trace = taskStats(await stopTrace(), 'search-start', 'search-done');

  const results = await page.evaluate(() => window.searchBench.results());
  const start = results.start;
  const burst = results.burst;
  const timings = results.timings;
  if (!start || !burst) throw new Error('the bench page did not finish');

  const worker = summary(timings.map((t) => t.worker));
  const roundTrip = summary(timings.map((t) => t.roundTrip));
  const report = {
    note: 'Chromium headless on this machine; the search worker needs no GPU.',
    source,
    records: recordCount,
    index: { gzipBytes, rawBytes, tokens: start.info.tokens },
    ready: {
      workerMsFromFetch: Math.round(start.info.loadMs * 10) / 10,
      mainThreadMsFromCreate: Math.round(start.readyMs * 10) / 10,
      phases: Object.fromEntries(
        Object.entries(start.info.phases).map(([k, v]) => [k, Math.round(v * 10) / 10]),
      ),
    },
    queries: {
      count: timings.length,
      firstQueryMs: timings[0]?.worker ?? 0,
      workerMs: worker,
      roundTripMs: roundTrip,
      slowest: [...timings]
        .sort((a, b) => b.worker - a.worker)
        .slice(0, 8)
        .map((t) => ({ q: t.q.slice(0, 40), ms: Math.round(t.worker * 100) / 100 })),
      withHits: timings.filter((t) => t.hits > 0).length,
    },
    burst,
    trace,
  };
  writeFileSync(join(benchOutDir, 'search-bench.json'), `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  expect.soft(gzipBytes, 'index gzip bytes').toBeLessThanOrEqual(MAX_GZIP_BYTES);
  expect.soft(start.info.loadMs, 'ready ms from fetch').toBeLessThanOrEqual(MAX_READY_MS);
  expect.soft(worker.p95, 'p95 query ms in the worker').toBeLessThanOrEqual(MAX_P95_MS);
  expect.soft(roundTrip.p95, 'p95 query ms round trip').toBeLessThanOrEqual(MAX_P95_MS);
  expect.soft(trace.mainOver16ms, 'main-thread tasks over 16 ms').toBe(0);
  expect.soft(burst.resolved, 'only the newest of a burst resolves').toBe(1);
  expect.soft(burst.superseded, 'every older search in a burst is superseded').toBe(burst.sent - 1);
});

test('a deleted worker chunk rejects ready and every search within 1 s', async ({ page }) => {
  // The chunk is really gone: the server answers 404 for it.
  const chunk = await fetch(`http://127.0.0.1:${String(port)}/${deletedWorker}`);
  expect(chunk.status, `GET ${deletedWorker}`).toBe(404);

  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await openBench(page, `${NO_WORKER_DIR}/`);
  const probe = await page.evaluate(([file, wait]) => window.searchBench.probe(file, wait), [
    `../${INDEX_FILE}`,
    5000,
  ] as const);
  const report = { deletedWorker, probe };
  writeFileSync(
    join(benchOutDir, 'search-bench-no-worker.json'),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  expect(probe.ready.outcome, 'ready').toBe('rejected');
  expect(probe.ready.ms, 'ms until ready rejects').toBeLessThan(MAX_FAILURE_MS);
  expect(probe.ready.errorName).toBe('SearchUnavailableError');
  expect(probe.ready.error).toContain('search worker failed to start');
  expect(probe.waiting.outcome, 'search made before the failure').toBe('rejected');
  expect(probe.waiting.abort).toBe(false);
  expect(probe.waiting.ms).toBeLessThan(MAX_FAILURE_MS);
  expect(probe.later.outcome, 'search made after the failure').toBe('rejected');
  expect(probe.later.errorName).toBe('SearchUnavailableError');
  expect(errors, 'uncaught page errors').toEqual([]);
});

test('the intact page still loads after the failure case', async ({ page }) => {
  await openBench(page);
  const probe = await page.evaluate(([file, wait]) => window.searchBench.probe(file, wait), [
    INDEX_FILE,
    5000,
  ] as const);
  expect(probe.ready.outcome).toBe('resolved');
  expect(probe.later.outcome).toBe('resolved');
});
