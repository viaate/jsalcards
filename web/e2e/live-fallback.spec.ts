/**
 * The live files on a network that blocks the live host by name: a school's
 * web filter that closes every connection to viaate.github.io and lets the
 * site's own domain through. The page then reads the same files from the
 * build's second live root (VITE_SNOWLIGHT_LIVE_FALLBACK, src/data/live-roots.ts),
 * which the site serves through status.snowlightmap.com/api/live/v1/.
 *
 * One build, with data staged in a temporary folder as live-origin.spec.ts
 * makes its own: its first live root is the real live host, which every check
 * here intercepts (the filter, or a host that answers with a file the check
 * gives), so nothing goes out to it; its second is a server on this machine.
 * The directory holds four schools and every file is SYNTHETIC: made up for
 * this test, the schools as much as the storm, living only in the temporary
 * folder and in these servers while they run.
 *
 * Runs under the desktop project, in a laptop's context. The page's clock is
 * Playwright's, installed at the made-up morning.
 */
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { Server } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext, Page, Route } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { format } from '../src/copy-format';
import { seasonFormat } from '../src/copy-season';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;
const BLOCKED_WORKER = 'Service Worker registration blocked by Playwright';
/** The page reads the live file again once a minute (src/data/live.ts LIVE_POLL_MS). */
const POLL_MS = 60_000;
const SETTLE = { timeout: 30_000 };
const ZONE = 'America/Chicago';
const DATA_CACHE = 'snowlight-data-v1';
/** The live host the site's build names (.github/workflows/preview.yml). */
const LIVE_HOST = 'https://viaate.github.io/snowlight-live/v1/';

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Runs once, in a laptop context of its own.');
});

test.describe.configure({ timeout: 240_000, mode: 'default' });

/** SYNTHETIC: Monday Jan 12, 2026, 6:53 AM in Kansas City, the morning of a made-up storm. */
const NOW = new Date('2026-01-12T12:53:00Z');
const TODAY = '2026-01-12';
const TOMORROW = '2026-01-13';

/** SYNTHETIC: four made-up schools near Kansas City, in one made-up district. */
const SCHOOLS = [
  { id: '290000000001', name: 'Alpha Elementary', lon: -94.6, lat: 39.05 },
  { id: '290000000002', name: 'Beta Middle', lon: -94.55, lat: 39.08 },
  { id: '290000000003', name: 'Gamma High', lon: -94.65, lat: 39.0 },
  { id: '290000000004', name: 'Delta Elementary', lon: -94.58, lat: 39.1 },
] as const;
const STAMP = { generated_on: '2026-09-25', schools: SCHOOLS.length, districts: 1 };

function meta(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: STAMP.generated_on,
    count: SCHOOLS.length,
    ids: SCHOOLS.map((school) => school.id),
    names: SCHOOLS.map((school) => school.name),
    districts: { ids: ['2900000'], names: ['Made-up District'] },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

/** The directory's points file (src/data/directory.ts): a header, then 13 bytes a school. */
function points(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * SCHOOLS.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(SCHOOLS.length, 8);
  bytes.writeUInt32LE(STAMP.districts, 12);
  SCHOOLS.forEach((school, i) => {
    const offset = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), offset);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), offset + 4);
    bytes.writeUInt32LE(0, offset + 8);
    bytes.writeUInt8(0, offset + 12);
  });
  return bytes;
}

/** SYNTHETIC: a closings file made at `generatedAt`, today's rows as [school, status] pairs. */
function closings(
  generatedAt: string,
  rows: readonly (readonly [school: number, status: number])[],
): string {
  let before = -1;
  const gaps = rows.map(([school]) => {
    const gap = school - before - 1;
    before = school;
    return gap;
  });
  const shifted = rows.filter(([, status]) => status === 1 || status === 3);
  return JSON.stringify({
    schema_version: 1,
    generated_at: generatedAt,
    directory: STAMP,
    days: [
      {
        day: TODAY,
        gaps,
        statuses: rows.map(([, status]) => status),
        announced: rows.map(() => null),
        reasons: rows.map(() => 0),
        shifts: shifted.map(() => null),
        clocks: shifted.map(() => null),
      },
    ],
  });
}

/** 6:42 AM: Alpha closed, Beta delayed. */
const AT_42 = new Date('2026-01-12T12:42:00Z');
const FIRST = closings(AT_42.toISOString().replace('.000', ''), [
  [0, 0],
  [1, 1],
]);
/** 6:47 AM: Gamma goes remote too. */
const AT_47 = new Date('2026-01-12T12:47:00Z');
const SECOND = closings(AT_47.toISOString().replace('.000', ''), [
  [0, 0],
  [1, 1],
  [2, 2],
]);

/** SYNTHETIC: a predictions file made at 6:50 AM with no districts: no chance for any school. */
const PREDICTIONS = JSON.stringify({
  schema_version: 1,
  generated_at: '2026-01-12T12:50:00Z',
  directory: STAMP,
  days: [TODAY, TOMORROW],
  districts: [],
});

/** SYNTHETIC: live/season.json, counting from Oct 27 through Jan 11: Alpha closed 2 days, delayed 1. */
const SEASON = JSON.stringify({
  schema_version: 1,
  season: '2025-2026',
  since: '2025-10-27',
  through: '2026-01-11',
  directory: STAMP,
  content_sha256: '5'.repeat(64),
  gaps: [0],
  closed: [2],
  delayed: [1],
  remote: [0],
  early_dismissal: [0],
});
const SEASON_LINE = seasonFormat.line(
  { closed: 2, delayed: 1, remote: 0, earlyDismissal: 0 },
  '2025-10-27',
);

/** The school records' index: one shard, from the first school. */
function detailsIndex(): string {
  return JSON.stringify({
    schema_version: 1,
    directory: STAMP,
    shards: 1,
    first_ids: [SCHOOLS[0].id],
    files: ['0.json'],
  });
}

/** SYNTHETIC: the four made-up schools' records, at one made-up address. */
function detailsShard(): string {
  const rows = SCHOOLS.map((school) => [
    school.id,
    school.name,
    0,
    0,
    '2900000',
    'Made-up District',
    '1 Main St',
    'Kansas City',
    'MO',
    '64113',
    'Jackson County',
    'KG',
    '05',
    300,
    '8165550100',
    [],
  ]);
  return JSON.stringify({ schema_version: 1, directory: STAMP, first: 0, rows });
}

/** The live files by their path under a root. */
const LIVE_FILES = (closingsFile: string): Record<string, string> => ({
  'live/closings.json': closingsFile,
  'predictions/latest.json': PREDICTIONS,
  'live/season.json': SEASON,
});

/** The second root: the same files as the live host, on a server of this machine. */
interface SecondRoot {
  readonly root: string;
  /** The closings file it serves, or a status it answers every read with. */
  closings: string;
  status: number;
  /** Whether it takes each read and never answers (a hung edge, a filter that drops it). */
  hang: boolean;
  /** Each path asked for, in order. */
  readonly asked: string[];
  close(): Promise<void>;
}

async function secondRoot(port: number, siteOrigin: string): Promise<SecondRoot> {
  const second: SecondRoot = {
    root: `http://127.0.0.1:${String(port)}/api/live/v1/`,
    closings: FIRST,
    status: 200,
    hang: false,
    asked: [],
    close: () => Promise.resolve(),
  };
  const server: Server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', second.root);
    second.asked.push(url.pathname);
    if (second.hang) return;
    const headers = {
      'Access-Control-Allow-Origin': siteOrigin,
      Vary: 'Origin',
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
    };
    if (second.status !== 200) {
      response.writeHead(second.status, { ...headers, 'Cache-Control': 'no-store' }).end();
      return;
    }
    const prefix = new URL(second.root).pathname;
    const body = url.pathname.startsWith(prefix)
      ? LIVE_FILES(second.closings)[url.pathname.slice(prefix.length)]
      : undefined;
    if (body === undefined) {
      response.writeHead(404, { ...headers, 'Cache-Control': 'no-store' }).end();
      return;
    }
    response.writeHead(200, headers).end(body);
  });
  await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));
  second.close = () =>
    new Promise((resolve) => {
      server.closeAllConnections();
      server.close(() => {
        resolve();
      });
    });
  return second;
}

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createNetServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address !== null ? address.port : 0;
      server.close(() => {
        resolve(port);
      });
    });
  });
}

interface Site {
  readonly root: string;
  readonly server: PreviewServer;
  readonly url: string;
  readonly second: SecondRoot;
}

let site: Site | undefined;

/**
 * Lets context.route() answer what the worker asks of the live host too, as Playwright does in
 * Chromium only with this flag, read as each worker starts: no read goes out to the real host.
 */
const WORKER_ROUTES = 'PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS';
const workerRoutesBefore = process.env[WORKER_ROUTES];

test.beforeAll(async () => {
  test.setTimeout(300_000);
  if (test.info().project.name !== 'desktop') return;
  process.env[WORKER_ROUTES] = '1';
  const root = mkdtempSync(path.join(tmpdir(), 'snowlight-live-fallback-e2e-'));
  const publicDir = path.join(root, 'public');
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  const data = path.join(publicDir, 'data');
  mkdirSync(path.join(data, 'schools'), { recursive: true });
  writeFileSync(path.join(data, 'schools/meta.json'), meta());
  writeFileSync(path.join(data, 'schools/points.bin'), points());
  // The school records the panel reads (src/data/details.ts), as made up as the schools.
  mkdirSync(path.join(data, 'schools/details'), { recursive: true });
  writeFileSync(path.join(data, 'schools/details/index.json'), detailsIndex());
  writeFileSync(path.join(data, 'schools/details/0.json'), detailsShard());

  const sitePort = await freePort();
  const siteUrl = `http://127.0.0.1:${String(sitePort)}/`;
  const second = await secondRoot(await freePort(), new URL(siteUrl).origin);
  const outDir = path.join(root, 'site');
  const names = [
    'VITE_SNOWLIGHT_LIVE_ROOT',
    'VITE_SNOWLIGHT_LIVE_FALLBACK',
    'VITE_SNOWLIGHT_LIVE_LOOPBACK',
  ] as const;
  const before = names.map((name) => process.env[name]);
  process.env.VITE_SNOWLIGHT_LIVE_ROOT = LIVE_HOST;
  process.env.VITE_SNOWLIGHT_LIVE_FALLBACK = second.root;
  // Plain http on this machine for the second root, as only an e2e build allows.
  process.env.VITE_SNOWLIGHT_LIVE_LOOPBACK = '1';
  try {
    await build({
      root: WEB,
      publicDir,
      cacheDir: path.join(root, 'vite-cache'),
      logLevel: 'warn',
      build: { outDir, emptyOutDir: true },
    });
  } finally {
    names.forEach((name, i) => {
      const value = before[i];
      if (value === undefined) Reflect.deleteProperty(process.env, name);
      else process.env[name] = value;
    });
  }
  const server = await preview({
    root: WEB,
    logLevel: 'warn',
    build: { outDir },
    preview: { host: '127.0.0.1', port: sitePort, strictPort: true },
  });
  site = { root, server, url: siteUrl, second };
});

test.afterAll(async () => {
  if (workerRoutesBefore === undefined) Reflect.deleteProperty(process.env, WORKER_ROUTES);
  else process.env[WORKER_ROUTES] = workerRoutesBefore;
  await site?.server.close();
  await site?.second.close();
  if (site !== undefined) rmSync(site.root, { recursive: true, force: true });
});

test.beforeEach(() => {
  if (site === undefined) return;
  site.second.closings = FIRST;
  site.second.status = 200;
  site.second.hang = false;
  site.second.asked.length = 0;
});

function theSite(): Site {
  if (site === undefined) throw new Error('no site');
  return site;
}

/**
 * What the live host does with each read: as the school's filter, as itself with its files, or
 * as itself in an outage of its own (an HTTP error for every read).
 */
type Host = 'closed' | 'silent' | { readonly closings: string } | { readonly status: number };

interface LiveHost {
  mode: Host;
  /** Each URL asked of it, by the page or its worker. */
  readonly asked: string[];
}

/**
 * Every request to the live host, by the page or its worker, is answered here: none goes out.
 * A filter closes the connection, or never answers; the host itself serves `closings`.
 */
async function interceptLiveHost(context: BrowserContext, mode: Host): Promise<LiveHost> {
  const host: LiveHost = { mode, asked: [] };
  const origin = new URL(theSite().url).origin;
  await context.route('https://viaate.github.io/**', async (route: Route) => {
    host.asked.push(route.request().url());
    const now = host.mode;
    if (now === 'closed') {
      await route.abort('connectionclosed');
      return;
    }
    if (now === 'silent') return;
    const headers = { 'Access-Control-Allow-Origin': origin };
    if ('status' in now) {
      await route.fulfill({ status: now.status, headers, body: '' });
      return;
    }
    const file = LIVE_FILES(now.closings)[route.request().url().slice(LIVE_HOST.length)];
    if (file === undefined) {
      await route.fulfill({ status: 404, headers, body: '' });
      return;
    }
    await route.fulfill({
      status: 200,
      headers: {
        'Access-Control-Allow-Origin': origin,
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'max-age=600',
      },
      body: file,
    });
  });
  return host;
}

/** Problems a blocked live host itself makes: its failed reads, and nothing else. */
function blockedRead(line: string): boolean {
  return (
    line.startsWith(`requestfailed: ${LIVE_HOST}`) ||
    line === 'console.error: Failed to load resource: net::ERR_CONNECTION_CLOSED'
  );
}

interface Visit {
  readonly context: BrowserContext;
  readonly page: Page;
  readonly host: LiveHost;
  readonly problems: string[];
}

async function visit(browser: Browser, mode: Host, worker = false, query = ''): Promise<Visit> {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    timezoneId: ZONE,
    serviceWorkers: worker ? 'allow' : 'block',
  });
  const host = await interceptLiveHost(context, mode);
  const page = await context.newPage();
  const problems: string[] = [];
  page.on('console', (message) => {
    const type = message.type();
    const text = message.text();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(text)) {
      if (text !== BLOCKED_WORKER) problems.push(`console.${type}: ${text}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
      problems.push(`requestfailed: ${request.url()}`);
    }
  });
  await page.clock.install({ time: NOW });
  await page.goto(`${theSite().url}${query}`);
  await settled(page);
  return { context, page, host, problems };
}

/** Waits for the map to take the place of its still picture. */
async function settled(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
}

/** How many schools the glow lights now. */
async function lit(page: Page): Promise<number> {
  await page.waitForFunction((id) => window.snowlightMap?.getLayer(id) !== undefined, GLOW_LAYER, {
    timeout: 60_000,
  });
  return page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as {
      implementation: { stats: { glowCount: number } };
    };
    return layer.implementation.stats.glowCount;
  }, GLOW_LAYER);
}

/** Steps the page's clock over one poll, and makes sure the step stands (live-origin.spec.ts). */
async function poll(page: Page): Promise<void> {
  const ticks = (): Promise<number> => page.evaluate(() => performance.now());
  const target = (await ticks()) + POLL_MS;
  await page.clock.fastForward(POLL_MS);
  for (let look = 0; look < 5; look += 1) {
    await page.waitForTimeout(250);
    const lost = target - (await ticks());
    if (lost <= 0) return;
    await page.clock.fastForward(Math.ceil(lost));
  }
  throw new Error('The page clock did not take the step over one poll.');
}

const closingsAsked = (asked: readonly string[]): number =>
  asked.filter((item) => item.endsWith('/live/closings.json')).length;

test("a filter that closes every connection to the live host: a fresh page shows today's file from the second root, and stays on it", async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host, problems } = await visit(browser, 'closed');
  const updated = page.locator('.updated');
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await expect(updated).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
  // The live host was asked first, and the second root only after it closed the connection.
  expect(closingsAsked(host.asked)).toBe(1);
  expect(closingsAsked(second.asked)).toBeGreaterThanOrEqual(1);

  // The ingest publishes a newer file: one poll later it shows, read from the second root alone.
  second.closings = SECOND;
  const asked = host.asked.length;
  await poll(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(updated).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  expect(host.asked.length).toBe(asked);
  expect(problems.filter((line) => !blockedRead(line))).toEqual([]);
  await context.close();
});

test('a live host that never answers: the page asks the second root once its wait is up', async ({
  browser,
}) => {
  const { second } = theSite();
  second.closings = SECOND;
  const { context, page, host, problems } = await visit(browser, 'silent');
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  expect(closingsAsked(host.asked)).toBe(1);
  expect(closingsAsked(second.asked)).toBeGreaterThanOrEqual(1);
  expect(problems).toEqual([]);
  await context.close();
});

test('an open network: the page reads the live host alone and never asks the second root', async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host, problems } = await visit(browser, { closings: FIRST });
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
  host.mode = { closings: SECOND };
  await poll(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  expect(closingsAsked(host.asked)).toBeGreaterThanOrEqual(2);
  expect(second.asked).toEqual([]);
  expect(problems).toEqual([]);
  await context.close();
});

test('with the second root failing too, the page shows what it showed with one root: nothing, and no time', async ({
  browser,
}) => {
  const { second } = theSite();
  second.status = 502;
  const { context, page, host } = await visit(browser, 'closed');
  await expect.poll(() => closingsAsked(second.asked), SETTLE).toBeGreaterThanOrEqual(1);
  await page.waitForTimeout(3000);
  expect(closingsAsked(host.asked)).toBeGreaterThanOrEqual(1);
  expect(await lit(page)).toBe(0);
  await expect(page.locator('.updated')).toHaveCount(0);
  await context.close();
});

test("a worker that kept an older copy: on the blocking network, a reload is given today's file from the second root", async ({
  browser,
}) => {
  const { second } = theSite();
  // At home first: the live host answers, and the worker keeps its file.
  const { context, page, host, problems } = await visit(browser, { closings: FIRST }, true);
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 60_000,
  });
  const kept = (url: string): Promise<string | null> =>
    page.evaluate(
      async ([name, file]) => {
        const response = await (await caches.open(name)).match(file);
        return response === undefined ? null : await response.text();
      },
      [DATA_CACHE, url] as const,
    );
  await expect.poll(() => kept(`${LIVE_HOST}live/closings.json`), SETTLE).toBe(FIRST);
  expect(second.asked).toEqual([]);

  // Then at school: the filter closes every connection to the live host. Through the worker,
  // its kept copy is not taken for an answer: the second root's newer file is shown.
  host.mode = 'closed';
  second.closings = SECOND;
  await page.reload();
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  await expect.poll(() => kept(`${second.root}live/closings.json`), SETTLE).toBe(SECOND);
  expect(problems.filter((line) => !blockedRead(line))).toEqual([]);
  await context.close();
});

test('a worker that kept a copy, with both roots failing: a reload shows the kept copy with its own time, as with one root', async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host } = await visit(browser, { closings: FIRST }, true);
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 60_000,
  });
  await page.waitForFunction(
    async ([name, file]) => (await (await caches.open(name)).match(file)) !== undefined,
    [DATA_CACHE, `${LIVE_HOST}live/closings.json`] as const,
    { timeout: 30_000 },
  );
  host.mode = 'closed';
  second.status = 502;
  await page.reload();
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
  expect(closingsAsked(second.asked)).toBeGreaterThanOrEqual(1);
  await context.close();
});

/** A visit at home first: the live host answers with `file`, and the worker keeps it. */
async function keptAtHome(browser: Browser, file = FIRST): Promise<Visit> {
  const home = await visit(browser, { closings: file }, true);
  await expect.poll(() => lit(home.page), SETTLE).toBe(file === FIRST ? 2 : 3);
  await home.page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 60_000,
  });
  await home.page.waitForFunction(
    async ([name, url, body]) => {
      const response = await (await caches.open(name)).match(url);
      return response !== undefined && (await response.text()) === body;
    },
    [DATA_CACHE, `${LIVE_HOST}live/closings.json`, file] as const,
    { timeout: 30_000 },
  );
  return home;
}

/** The seconds from `since` until the page says it is live as of `at`. */
async function secondsUntilLiveAt(page: Page, at: Date, since: number): Promise<number> {
  await expect(page.locator('.updated')).toHaveText(format.liveAt(at, ZONE), SETTLE);
  return (Date.now() - since) / 1000;
}

test('a worker that kept a copy, a live host that is blocked or silent and a second root that never answers: a reload shows the kept copy with its own time within the waits, and the second is left alone after', async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host } = await keptAtHome(browser);
  expect(second.asked).toEqual([]);
  second.hang = true;
  for (const mode of ['closed', 'silent'] as const) {
    host.mode = mode;
    // A new visit in the same tab: what the last one remembered is gone.
    await page.evaluate(() => {
      sessionStorage.clear();
    });
    second.asked.length = 0;
    const since = Date.now();
    await page.reload();
    // The worker's wait (silent), then the second root's: 8 s at most past the page's own start.
    expect(await secondsUntilLiveAt(page, AT_42, since)).toBeLessThan(15);
    expect(await lit(page)).toBe(2);
    expect(closingsAsked(second.asked)).toBe(1);
    // The second failed: the next polls read the live host alone, and still show the kept copy.
    await poll(page);
    await poll(page);
    await page.waitForTimeout(1000);
    expect(closingsAsked(second.asked)).toBe(1);
    await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_42, ZONE));
    expect(await lit(page)).toBe(2);
  }
  await context.close();
});

test('a reload within the visit reads the second root first, and the live host is tried again only after 10 minutes', async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host, problems } = await visit(browser, 'closed');
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  expect(closingsAsked(host.asked)).toBe(1);
  // Every live file the page reads goes to the second root from then on.
  const hostAsked = host.asked.length;
  const took = Number(
    await page.evaluate(() => sessionStorage.getItem('snowlight-live-root') ?? 'NaN'),
  );
  expect(Number.isFinite(took)).toBe(true);

  // A reload: the visit remembers the second root, and the live host is not asked.
  second.closings = SECOND;
  await page.reload();
  await settled(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  expect(host.asked.length).toBe(hostAsked);

  // A poll a minute: the live host is left alone until 10 minutes after the second took over.
  const minutes = (): Promise<number> => page.evaluate((at) => (Date.now() - at) / 60_000, took);
  while ((await minutes()) < 9) {
    const before = closingsAsked(second.asked);
    await poll(page);
    await expect.poll(() => closingsAsked(second.asked), SETTLE).toBeGreaterThan(before);
  }
  expect(host.asked.length).toBe(hostAsked);
  // Past 10 minutes: the live host is tried first once (by whichever file is read first), fails,
  // and the second takes over again.
  while ((await minutes()) < 11) await poll(page);
  await expect.poll(() => host.asked.length, SETTLE).toBe(hostAsked + 1);
  const again = closingsAsked(second.asked);
  await poll(page);
  await expect.poll(() => closingsAsked(second.asked), SETTLE).toBeGreaterThan(again);
  expect(host.asked.length).toBe(hostAsked + 1);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE));
  expect(problems.filter((line) => !blockedRead(line))).toEqual([]);
  await context.close();
});

test("a first visit with a worker on the blocking network: its polls and a reload stay on today's file from the second root", async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host, problems } = await visit(browser, 'closed', true);
  await expect.poll(() => lit(page), SETTLE).toBe(2);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 60_000,
  });
  second.closings = SECOND;
  await poll(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  await page.reload();
  await settled(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  expect(closingsAsked(host.asked)).toBe(1);
  expect(problems.filter((line) => !blockedRead(line))).toEqual([]);
  await context.close();
});

test("a worker that kept an older copy and a live host that never answers: a reload is given today's file from the second root", async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host } = await keptAtHome(browser);
  host.mode = 'silent';
  second.closings = SECOND;
  await page.reload();
  await settled(page);
  await expect.poll(() => lit(page), SETTLE).toBe(3);
  await expect(page.locator('.updated')).toHaveText(format.liveAt(AT_47, ZONE), SETTLE);
  expect(closingsAsked(second.asked)).toBeGreaterThanOrEqual(1);
  await context.close();
});

test('a live host that answers with an error of its own: the page never asks the second root, which could do no better', async ({
  browser,
}) => {
  const { second } = theSite();
  const { context, page, host } = await visit(browser, { status: 503 });
  await expect.poll(() => closingsAsked(host.asked), SETTLE).toBeGreaterThanOrEqual(1);
  await poll(page);
  await expect.poll(() => closingsAsked(host.asked), SETTLE).toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(5000);
  expect(second.asked).toEqual([]);
  expect(await lit(page)).toBe(0);
  await expect(page.locator('.updated')).toHaveCount(0);
  await context.close();
});

test('with the second root failing too, it is asked once and then left alone for 10 minutes', async ({
  browser,
}) => {
  const { second } = theSite();
  second.status = 502;
  const { context, page, host } = await visit(browser, 'closed');
  await expect.poll(() => closingsAsked(second.asked), SETTLE).toBe(1);
  for (let minute = 0; minute < 3; minute += 1) await poll(page);
  await expect.poll(() => closingsAsked(host.asked), SETTLE).toBeGreaterThanOrEqual(4);
  expect(closingsAsked(second.asked)).toBe(1);
  expect(await lit(page)).toBe(0);
  await context.close();
});

test('an open school panel on the blocking network reads the chances and the season counts from the second root; on an open network it asks the second root nothing', async ({
  browser,
}) => {
  const { second } = theSite();
  const query = `?school=${SCHOOLS[0].id}`;
  const blocked = await visit(browser, 'closed', false, query);
  const panel = blocked.page.locator('aside.detail');
  await expect(panel).toContainText(SCHOOLS[0].name, SETTLE);
  await expect(panel.locator('.season')).toHaveText(SEASON_LINE, SETTLE);
  const prefix = new URL(second.root).pathname;
  expect(second.asked).toContain(`${prefix}predictions/latest.json`);
  expect(second.asked).toContain(`${prefix}live/season.json`);
  expect(blocked.problems.filter((line) => !blockedRead(line))).toEqual([]);
  await blocked.context.close();

  second.asked.length = 0;
  const open = await visit(browser, { closings: FIRST }, false, query);
  const openPanel = open.page.locator('aside.detail');
  await expect(openPanel).toContainText(SCHOOLS[0].name, SETTLE);
  await expect(openPanel.locator('.season')).toHaveText(SEASON_LINE, SETTLE);
  expect(open.host.asked).toContain(`${LIVE_HOST}predictions/latest.json`);
  expect(open.host.asked).toContain(`${LIVE_HOST}live/season.json`);
  expect(second.asked).toEqual([]);
  expect(open.problems).toEqual([]);
  await open.context.close();
});
