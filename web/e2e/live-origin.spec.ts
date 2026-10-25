/**
 * The live closings file read from a live root of its own: a host published
 * apart from the site (VITE_SNOWLIGHT_LIVE_ROOT), as the live ingest will
 * publish it.
 *
 * One build with data staged in a temporary folder, as app.spec.ts makes its
 * own, its variable set to a second server on this machine: a live origin that
 * answers for live/closings.json with CORS for the site's origin, an ETag and
 * the short cache time the live host sends. Its directory holds four schools
 * and its files are SYNTHETIC: made up for this test, the schools as much as
 * the storm, living only in the temporary folder and in this server while it
 * runs. The build also ships a closings file of its own, lighting another
 * school: the page must never ask for it.
 *
 * The checks follow what a parent sees (the S8 spec, section 2), on the map,
 * the update line, the school panel and the area panel: lights and their counts from a fresh
 * file, a new school within one poll, a failed read or an older file changing
 * nothing, a blank file going dark, an ingest that stops while the page is
 * open turning Live into Updated, a file from last night, the hours when the
 * country spans two days, offline, a file for another directory lighting
 * nothing, and the worker reading the live file network-first and keeping
 * only a newer copy, which an offline reload is then given. The live root also
 * serves predictions/latest.json, as the chance passes publish it (S7): a file
 * with no districts unless a check gives it a SYNTHETIC forecast, which the
 * school panel and the area panel then show.
 *
 * Runs under the desktop project, each check twice: in a laptop's context and
 * in a phone's (Pixel 7). The page's clock is Playwright's, installed at the
 * made-up morning, so a minute's poll can be stepped over at once
 * (clock.fastForward) instead of waited out under software WebGL.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { Server } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { devices, expect, test } from '@playwright/test';
import type { Browser, BrowserContextOptions, Page, Request } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { copy } from '../src/copy';
import { chanceCopy, chanceFormat } from '../src/copy-chance';
import { format } from '../src/copy-format';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;
const BLOCKED_WORKER = 'Service Worker registration blocked by Playwright';
/** The page reads the live file again once a minute (src/data/live.ts LIVE_POLL_MS). */
const POLL_MS = 60_000;
/** How long a read, its parse and the glow's redraw may take under software WebGL. */
const SETTLE = { timeout: 30_000 };
const ZONE = 'America/Chicago';
const DATA_CACHE = 'snowlight-data-v1';

test.beforeEach(() => {
  test.skip(
    test.info().project.name !== 'desktop',
    'Runs each check in a laptop context and a phone context of its own; runs once.',
  );
});

test.describe.configure({ timeout: 240_000, mode: 'default' });

const DESKTOP: BrowserContextOptions = { viewport: { width: 1440, height: 900 } };
const PHONE: BrowserContextOptions = devices['Pixel 7'];

/**
 * SYNTHETIC: Monday Jan 12, 2026, 6:53 AM in Kansas City, the morning of a made-up storm: after
 * every file below was made, as a file stamped ahead of the clock is never called live.
 */
const NOW = new Date('2026-01-12T12:53:00Z');
const TODAY = '2026-01-12';

/** SYNTHETIC: four made-up schools near Kansas City, in one made-up district. */
const SCHOOLS = [
  { id: '290000000001', name: 'Alpha Elementary', lon: -94.6, lat: 39.05 },
  { id: '290000000002', name: 'Beta Middle', lon: -94.55, lat: 39.08 },
  { id: '290000000003', name: 'Gamma High', lon: -94.65, lat: 39.0 },
  { id: '290000000004', name: 'Delta Elementary', lon: -94.58, lat: 39.1 },
] as const;
/** SYNTHETIC: a made-up private school near them, outside any district, outside the ZIP code. */
const PRIVATE = { id: 'A9999999', name: 'Epsilon Academy', lon: -94.7, lat: 38.95 } as const;
/** Every school in the made-up directory: the four public ones, then the private one. */
const ALL = [...SCHOOLS, PRIVATE] as const;
const STAMP = { generated_on: '2026-09-25', schools: ALL.length, districts: 1 };

function meta(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: STAMP.generated_on,
    count: ALL.length,
    ids: ALL.map((school) => school.id),
    names: ALL.map((school) => school.name),
    districts: { ids: ['2900000'], names: ['Made-up District'] },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

/** The directory's points file (src/data/directory.ts): a header, then 13 bytes a school. */
function points(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * ALL.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(ALL.length, 8);
  bytes.writeUInt32LE(STAMP.districts, 12);
  ALL.forEach((school, i) => {
    const offset = 16 + 13 * i;
    const own = school === PRIVATE;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), offset);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), offset + 4);
    // The private school: no district (0xFFFFFFFF), the private flag (0x01).
    bytes.writeUInt32LE(own ? 0xffffffff : 0, offset + 8);
    bytes.writeUInt8(own ? 0x01 : 0, offset + 12);
  });
  return bytes;
}

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
  const rows = ALL.map((school) => [
    school.id,
    school.name,
    school === PRIVATE ? 0x01 : 0,
    school === PRIVATE ? null : 0,
    school === PRIVATE ? null : '2900000',
    school === PRIVATE ? null : 'Made-up District',
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

/** The made-up schools' ZIP code (their records' address), whose area panel lists all four. */
const ZIP = '64113';

/** The area files (src/data/areas-format.ts): one shard, one ZIP code, the four schools its own. */
function areaFiles(): { index: string; shard: string } {
  const own = SCHOOLS.map((school, i) => [i, school.id, 200 * (i + 1), school.lon, school.lat]);
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_zips: [ZIP],
      files: ['0.json'],
    }),
    shard: JSON.stringify({
      schema_version: 1,
      directory: STAMP,
      first: ZIP,
      areas: [[ZIP, -94.6, 39.05, ['MO'], own, []]],
    }),
  };
}

/** SYNTHETIC: a closings file made at `generatedAt`, today's rows as [school, status] pairs. */
function closings(
  generatedAt: string,
  rows: readonly (readonly [school: number, status: number])[],
  directory: typeof STAMP = STAMP,
  day: string = TODAY,
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
    directory,
    days:
      rows.length === 0
        ? []
        : [
            {
              day,
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
const FIRST = closings('2026-01-12T12:42:00Z', [
  [0, 0],
  [1, 1],
]);
/** 6:47 AM: Gamma goes remote too. */
const SECOND = closings('2026-01-12T12:47:00Z', [
  [0, 0],
  [1, 1],
  [2, 2],
]);
/** 6:52 AM: blank, as the ingest publishes it to darken the map. */
const BLANK = closings('2026-01-12T12:52:00Z', []);
/**
 * SYNTHETIC: the admin's manual statuses at 6:50 AM, as `snowlight live overrides` publishes
 * them (accounts spec C): plain rows with no weather reason, posted when the admin set them
 * (6:40 AM), Alpha closed and Beta on a 2-hour delayed start. The pipeline writes this file
 * from those overrides through its resolver, merge and publisher, and checks it there
 * (pipeline/tests/live/test_overrides.py), so the two cannot drift apart.
 */
/** The pipeline's golden manual file, stamped with this directory (its fifth school added). */
const MANUAL = JSON.stringify({
  ...(JSON.parse(
    readFileSync(
      path.join(WEB, '../pipeline/tests/live/golden/synthetic_manual_closings.json'),
      'utf8',
    ),
  ) as Record<string, unknown>),
  directory: STAMP,
});
const MANUAL_SET_AT = new Date('2026-01-12T12:40:00Z');
/** The site's own file, which the page must never read: Delta closed, newer than all. */
const SITE_OWN = closings('2026-01-12T13:30:00Z', [[3, 0]]);

/**
 * SYNTHETIC: a predictions file made at 6:50 AM, with `districts` (none: no chance for any
 * school, so the panels show none).
 */
function predictions(
  districts: readonly unknown[] = [],
  at = '2026-01-12T12:50:00Z',
  privateSchools: {
    schools: readonly unknown[];
    outlooks: readonly unknown[];
    zones: readonly string[];
  } | null = null,
): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: at,
    directory: STAMP,
    days: [TODAY, '2026-01-13'],
    districts,
    ...privateSchools,
  });
}

/**
 * SYNTHETIC: the private school's own day under the made-up warning (contract C3): its base
 * alone, counted over the private schools near it. Written compact, as the pipeline writes it:
 * false flags left out, and its reasons list kept (always written, even when empty).
 */
const PRIVATE_FORECAST = {
  state: 'forecast',
  p_no_school: 0.42,
  p_delay: 0.05,
  reasons: [0],
  why: {
    base: {
      kind: 'pooled',
      points: 42,
      scope: 'nearby',
      alert: 'winter_storm_warning',
      of: 'private_schools',
    },
  },
};

/** SYNTHETIC: a winter storm warning day for the made-up district, from its own record. */
const STORM_FORECAST = {
  state: 'forecast',
  p_no_school: 0.37,
  p_delay: 0.12,
  reasons: [0],
  previous: null,
  announces_at: null,
  buses_at: null,
  hours: null,
  why: {
    base: {
      kind: 'alert',
      points: 37,
      alert: 'winter_storm_warning',
      borrowed: false,
      live: false,
    },
    reasons: [],
  },
  record: {
    proves: 'base',
    inches: null,
    days: [
      { day: '2025-01-06', inches: null, status: 0 },
      { day: '2025-02-18', inches: null, status: null },
    ],
  },
  events: [],
};

/**
 * SYNTHETIC: an advisory day whose base is the nation's record, as a district whose region holds
 * too few recorded days of the weather gets it (spec addendum 2026-10-24 e, E3b): few local
 * records. Compact, as the pipeline writes it.
 */
const NATION_BASE = { kind: 'pooled', points: 74, scope: 'nation', weather: 'advisory' };
const THIN_FORECAST = {
  state: 'forecast',
  p_no_school: 0.74,
  p_delay: 0.01,
  reasons: [0],
  why: { base: { ...NATION_BASE, thin: true } },
};

/** What the live origin answers, and every request it was sent. */
interface LiveOrigin {
  readonly root: string;
  body: string;
  status: number;
  /** The predictions file it serves, and how many times it was read (not in `requests`). */
  predictions: string;
  predictionReads: number;
  readonly requests: {
    url: string;
    origin: string | undefined;
    answer: number;
    /** Whether it asked with If-None-Match, as a revalidation does. */
    conditional: boolean;
  }[];
  close(): Promise<void>;
}

/**
 * A second server on this machine, as the live host is to be: live/closings.json under /v1/,
 * with CORS for the site's origin alone, an ETag (a 304 to a matching If-None-Match, which,
 * as GitHub Pages sends it, carries no CORS header) and a 15-second cache time, as the host
 * sends them (S8 spec, section 9.1). Nothing else is there.
 */
async function liveOrigin(port: number, siteOrigin: string): Promise<LiveOrigin> {
  const origin: LiveOrigin = {
    root: `http://127.0.0.1:${String(port)}/v1/`,
    body: FIRST,
    status: 200,
    predictions: predictions(),
    predictionReads: 0,
    requests: [],
    close: () => Promise.resolve(),
  };
  const server: Server = createServer((request, response) => {
    const url = new URL(request.url ?? '/', origin.root);
    const cors = {
      'Access-Control-Allow-Origin': siteOrigin,
      Vary: 'Origin',
    };
    const record = (answer: number): void => {
      origin.requests.push({
        url: url.pathname,
        origin: request.headers.origin,
        answer,
        conditional: request.headers['if-none-match'] !== undefined,
      });
    };
    if (url.pathname === '/v1/predictions/latest.json' && request.method === 'GET') {
      origin.predictionReads += 1;
      response
        .writeHead(200, {
          ...cors,
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'public, max-age=15, stale-while-revalidate=15',
        })
        .end(origin.predictions);
      return;
    }
    if (
      url.pathname !== '/v1/live/closings.json' ||
      !['GET', 'HEAD'].includes(request.method ?? '')
    ) {
      record(404);
      response.writeHead(404, cors).end();
      return;
    }
    if (origin.status !== 200) {
      record(origin.status);
      response.writeHead(origin.status, cors).end();
      return;
    }
    const tag = `"${createHash('sha256').update(origin.body).digest('hex').slice(0, 16)}"`;
    const headers = {
      ...cors,
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=15, stale-while-revalidate=15',
      ETag: tag,
    };
    if (request.headers['if-none-match'] === tag) {
      record(304);
      // As GitHub Pages answers a revalidation: the ETag and cache time, and no CORS header.
      // The browser takes the cached 200's own headers, so the page still reads its copy.
      response.writeHead(304, { ETag: tag, 'Cache-Control': headers['Cache-Control'] }).end();
      return;
    }
    record(200);
    response.writeHead(200, headers).end(request.method === 'HEAD' ? undefined : origin.body);
  });
  await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));
  origin.close = () =>
    new Promise((resolve) => {
      server.closeAllConnections();
      server.close(() => {
        resolve();
      });
    });
  return origin;
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

interface Watch {
  readonly problems: string[];
  readonly requests: string[];
}

/** Console errors and warnings, page errors, failed and non-2xx requests, and every URL asked for. */
function watch(page: Page): Watch {
  const problems: string[] = [];
  const requests: string[] = [];
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
  page.on('response', (response) => {
    if (response.status() >= 400)
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
  });
  page.on('request', (request) => requests.push(request.url()));
  return { problems, requests };
}

/** A live file's read failing while the context is offline, as the browser reports it. */
function offlineRead(line: string): boolean {
  return (
    line === `requestfailed: ${theSite().live.root}live/closings.json` ||
    line === `requestfailed: ${theSite().live.root}predictions/latest.json` ||
    line === 'console.error: Failed to load resource: net::ERR_INTERNET_DISCONNECTED'
  );
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

/** The legend's lines, each status with its count where it has any. */
async function legend(page: Page): Promise<string[]> {
  const lines = await page.locator('ul.legend li').allTextContents();
  return lines.map((line) => line.replace(/\s+/g, ' ').trim());
}

/** The legend's lines for `counts` of closed, delayed, remote and early dismissal. */
function legendFor(counts: readonly [number, number, number, number]): string[] {
  const names = [
    copy.status.closed,
    copy.status.delayed,
    copy.status.remote,
    copy.status.earlyDismissal,
  ];
  return names.map((name, i) => {
    const count = counts[i] ?? 0;
    return count === 0 ? name : `${name} ${format.number(count)}`;
  });
}

interface Site {
  readonly root: string;
  readonly server: PreviewServer;
  readonly url: string;
  readonly live: LiveOrigin;
}

let site: Site | undefined;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  if (test.info().project.name !== 'desktop') return;
  const root = mkdtempSync(path.join(tmpdir(), 'snowlight-live-origin-e2e-'));
  const publicDir = path.join(root, 'public');
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  const data = path.join(publicDir, 'data');
  mkdirSync(path.join(data, 'schools'), { recursive: true });
  mkdirSync(path.join(data, 'live'), { recursive: true });
  writeFileSync(path.join(data, 'schools/meta.json'), meta());
  writeFileSync(path.join(data, 'schools/points.bin'), points());
  writeFileSync(path.join(data, 'live/closings.json'), SITE_OWN);
  // The school records the panel reads (src/data/details.ts), as made up as the schools.
  mkdirSync(path.join(data, 'schools/details'), { recursive: true });
  writeFileSync(path.join(data, 'schools/details/index.json'), detailsIndex());
  writeFileSync(path.join(data, 'schools/details/0.json'), detailsShard());
  // The schools around their ZIP code, for the area panel (src/data/areas.ts).
  mkdirSync(path.join(data, 'schools/areas'), { recursive: true });
  const area = areaFiles();
  writeFileSync(path.join(data, 'schools/areas/index.json'), area.index);
  writeFileSync(path.join(data, 'schools/areas/0.json'), area.shard);

  const sitePort = await freePort();
  const siteUrl = `http://127.0.0.1:${String(sitePort)}/`;
  const live = await liveOrigin(await freePort(), new URL(siteUrl).origin);
  const outDir = path.join(root, 'site');
  // Read by Vite as it resolves its config: the page's live root and the worker's route.
  // Plain http on this machine is a live root only in a build that allows it, as this one does.
  const before = process.env.VITE_SNOWLIGHT_LIVE_ROOT;
  const beforeLoopback = process.env.VITE_SNOWLIGHT_LIVE_LOOPBACK;
  process.env.VITE_SNOWLIGHT_LIVE_ROOT = live.root;
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
    if (before === undefined) delete process.env.VITE_SNOWLIGHT_LIVE_ROOT;
    else process.env.VITE_SNOWLIGHT_LIVE_ROOT = before;
    if (beforeLoopback === undefined) delete process.env.VITE_SNOWLIGHT_LIVE_LOOPBACK;
    else process.env.VITE_SNOWLIGHT_LIVE_LOOPBACK = beforeLoopback;
  }
  const server = await preview({
    root: WEB,
    logLevel: 'warn',
    build: { outDir },
    preview: { host: '127.0.0.1', port: sitePort, strictPort: true },
  });
  site = { root, server, url: siteUrl, live };
});

test.afterAll(async () => {
  await site?.server.close();
  await site?.live.close();
  if (site !== undefined) rmSync(site.root, { recursive: true, force: true });
});

test.beforeEach(() => {
  if (site === undefined) return;
  site.live.body = FIRST;
  site.live.status = 200;
  site.live.predictions = predictions();
  site.live.predictionReads = 0;
  site.live.requests.length = 0;
});

function theSite(): Site {
  if (site === undefined) throw new Error('no site');
  return site;
}

interface VisitOptions {
  /** Let the service worker run. */
  readonly worker?: boolean;
  /** The page's query, such as "?school=…". */
  readonly query?: string;
  /** The page's clock as it opens: the made-up morning, unless another moment is asked for. */
  readonly at?: Date;
}

/** A page on the site, its clock at the made-up morning, its problems and requests watched. */
async function visit(
  browser: Browser,
  options: BrowserContextOptions,
  { worker = false, query = '', at = NOW }: VisitOptions = {},
) {
  const { url } = theSite();
  const context = await browser.newContext({
    ...options,
    timezoneId: ZONE,
    serviceWorkers: worker ? 'allow' : 'block',
  });
  const page = await context.newPage();
  const seen = watch(page);
  await page.clock.install({ time: at });
  await page.goto(`${url}${query}`);
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  return { context, page, ...seen };
}

/**
 * Steps the page's clock over one poll, and makes sure the step stands.
 *
 * Playwright's installed clock runs on with real time by stepping its timers in a loop of its
 * own, and a jump made while one such step is on its way is undone when that step ends: the
 * loop sets the clock back to the time it began at, after the jump's timers already fired, so
 * the next jump would fall short of the next poll and the page would read nothing. So once any
 * such step has ended, the clock is looked at again, and stepped on by what it lost.
 */
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

/** The page asked for nothing under the site's own data/live/, and only the live root for it. */
function expectOnlyLiveRoot(requests: readonly string[]): void {
  const { url, live } = theSite();
  expect(requests.filter((request) => request.startsWith(`${url}data/live/`))).toEqual([]);
  expect(requests.filter((request) => request.includes('closings.json'))).not.toEqual([]);
  for (const request of requests.filter((item) => item.includes('closings.json'))) {
    expect(request.startsWith(`${live.root}live/closings.json`)).toBe(true);
  }
}

const DEVICES = [
  ['laptop', DESKTOP],
  ['phone', PHONE],
] as const;

const AT_42 = new Date('2026-01-12T12:42:00Z');
const AT_47 = new Date('2026-01-12T12:47:00Z');
const AT_52 = new Date('2026-01-12T12:52:00Z');
/** The first made-up school, closed in every file but the blank one. */
const ALPHA = SCHOOLS[0].id;
const CLOSED_TODAY = format.statusOn('closed', TODAY, NOW, ZONE);

/** The open school panel's status lines. */
function statusLines(page: Page) {
  return page.locator('aside.detail .status .headline');
}

/** The page's clock now. */
async function pageNow(page: Page): Promise<Date> {
  return new Date(await page.evaluate(() => Date.now()));
}

for (const [device, options] of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test('a fresh file lights its schools and says Live, and a new school lights within one poll', async ({
      browser,
    }) => {
      const { live } = theSite();
      const { context, page, problems, requests } = await visit(browser, options);
      const updated = page.locator('.updated');
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect.poll(() => legend(page), SETTLE).toEqual(legendFor([1, 1, 0, 0]));
      await expect(updated).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
      // Read with the site's origin, across origins.
      expect(live.requests.length).toBeGreaterThanOrEqual(1);
      expect(new Set(live.requests.map((request) => request.origin))).toEqual(
        new Set([new URL(theSite().url).origin]),
      );

      // The ingest publishes a newer file: one poll later, Gamma glows too.
      live.body = SECOND;
      const reads = live.requests.length;
      await poll(page);
      await expect.poll(() => lit(page), SETTLE).toBe(3);
      await expect.poll(() => legend(page), SETTLE).toEqual(legendFor([1, 1, 1, 0]));
      await expect(updated).toHaveText(format.liveAt(AT_47, ZONE));
      expect(live.requests.length).toBe(reads + 1);

      // Offline, the lights the page holds stay and the line says so, with the file's own time.
      await context.setOffline(true);
      await poll(page);
      await expect(updated).toHaveText(format.offline(AT_47, ZONE, NOW), SETTLE);
      expect(await lit(page)).toBe(3);
      await context.setOffline(false);

      expectOnlyLiveRoot(requests);
      // Going offline fails the one read made then; nothing else went wrong.
      expect(problems.filter((line) => !offlineRead(line))).toEqual([]);
      await context.close();
    });

    test('a failed read and an older file change nothing, and a blank file darkens the map', async ({
      browser,
    }) => {
      const { live } = theSite();
      live.body = SECOND;
      const { context, page, problems, requests } = await visit(browser, options);
      const updated = page.locator('.updated');
      const at47 = format.liveAt(AT_47, ZONE);
      await expect.poll(() => lit(page), SETTLE).toBe(3);
      await expect(updated).toHaveText(at47, SETTLE);

      // The host fails: what is shown stays, as it was true at its time.
      live.status = 500;
      await poll(page);
      await expect.poll(() => live.requests.at(-1)?.answer, SETTLE).toBe(500);
      await page.waitForTimeout(1000);
      expect(await lit(page)).toBe(3);
      await expect(updated).toHaveText(at47);

      // An edge that has not caught up serves the older file: it is not taken.
      live.status = 200;
      live.body = FIRST;
      await poll(page);
      await expect.poll(() => live.requests.at(-1)?.answer, SETTLE).toBe(200);
      await page.waitForTimeout(1000);
      expect(await lit(page)).toBe(3);
      await expect.poll(() => legend(page)).toEqual(legendFor([1, 1, 1, 0]));
      await expect(updated).toHaveText(at47);

      // A blank file, newer: the map goes dark within one poll, and the file is still live.
      live.body = BLANK;
      await poll(page);
      await expect.poll(() => lit(page), SETTLE).toBe(0);
      await expect.poll(() => legend(page), SETTLE).toEqual(legendFor([0, 0, 0, 0]));
      await expect(updated).toHaveText(format.liveAt(AT_52, ZONE));

      expectOnlyLiveRoot(requests);
      // The browser reports the failed read; the page itself says nothing went wrong.
      expect(problems).toEqual([
        `HTTP 500: ${live.root}live/closings.json`,
        'console.error: Failed to load resource: the server responded with a status of 500 (Internal Server Error)',
      ]);
      await context.close();
    });

    test('an open school panel says what the live file says, drops it within one poll of a blank file, and ignores an older one', async ({
      browser,
    }) => {
      const { live } = theSite();
      const { context, page, problems, requests } = await visit(browser, options, {
        query: `?school=${ALPHA}`,
      });
      const panel = page.locator('aside.detail');
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect(statusLines(page).first()).toContainText(CLOSED_TODAY, SETTLE);
      await expect(panel).toContainText(SCHOOLS[0].name);

      // A blank file: the map and the panel both drop it within one poll.
      live.body = BLANK;
      const reads = live.requests.length;
      await poll(page);
      await expect.poll(() => lit(page), SETTLE).toBe(0);
      await expect(panel.locator('.status')).toHaveCount(0, SETTLE);
      // The map and the open panel read the file once between them.
      expect(live.requests.length).toBe(reads + 1);

      // SECOND is older than the blank file: neither the map nor the panel takes it.
      live.body = SECOND;
      await poll(page);
      await expect.poll(() => live.requests.length, SETTLE).toBe(reads + 2);
      await page.waitForTimeout(3000);
      expect(await lit(page)).toBe(0);
      await expect(panel.locator('.status')).toHaveCount(0);

      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test("a manual status the admin set lights its school's dot and shows in its panel, confirmed by the team and posted when it was set", async ({
      browser,
    }) => {
      const { live } = theSite();
      live.body = MANUAL;
      const { context, page, problems, requests } = await visit(browser, options, {
        query: `?school=${SCHOOLS[1].id}`,
      });
      const panel = page.locator('aside.detail');
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect.poll(() => legend(page), SETTLE).toEqual(legendFor([1, 1, 0, 0]));
      await expect(page.locator('.updated')).toHaveText(
        format.liveAt(new Date('2026-01-12T12:50:00Z'), ZONE),
        SETTLE,
      );
      await expect(statusLines(page).first()).toContainText(
        format.statusOn('delayed', TODAY, NOW, ZONE),
        SETTLE,
      );
      await expect(panel).toContainText(SCHOOLS[1].name);
      await expect(panel.locator('.line-detail').first()).toHaveText(format.delay(120, null) ?? '');
      // A status the site's own team set says so, before when it was posted.
      await expect(panel.locator('.line-note').first()).toHaveText(
        `${copy.detail.confirmed} · ${format.posted(MANUAL_SET_AT, ZONE, NOW)}`,
      );

      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('the school panel and the area panel show the chance from the live root, and how it adds up', async ({
      browser,
    }) => {
      const { live } = theSite();
      // No school has a status today: a closed school's panel shows tomorrow's chance instead,
      // and a closed school counts as 100% in the area's chance.
      live.body = closings('2026-01-12T12:42:00Z', []);
      live.predictions = predictions([
        {
          district: 0,
          time_zone: ZONE,
          neighbors: [],
          days: [STORM_FORECAST, { ...STORM_FORECAST, record: null, reasons: [] }],
        },
      ]);
      const school = await visit(browser, options, { query: `?school=${ALPHA}` });
      const section = school.page.locator('aside.detail .chance');
      await expect(section.locator('.number')).toHaveText('37%', SETTLE);
      await expect(section.locator('.meaning')).toContainText(chanceFormat.chanceOn(TODAY));
      await expect(section.locator('.why-title')).toHaveText(chanceFormat.howWeGot(0.37));
      await expect(section.locator('.sum > li').first()).toContainText(
        'recorded days with a winter storm warning',
      );
      expect(live.predictionReads).toBeGreaterThanOrEqual(1);
      expect(school.problems).toEqual([]);
      await school.context.close();

      const area = await visit(browser, options, { query: `?zip=${ZIP}` });
      const panel = area.page.locator('aside.detail');
      await expect(panel).toHaveAttribute('aria-busy', 'false', SETTLE);
      await expect(panel.locator('.number')).toHaveText('37%', SETTLE);
      expect(area.problems).toEqual([]);
      await area.context.close();
    });

    test('a chance with few local records shows lighter with its line under the meaning, and none without the flag', async ({
      browser,
    }) => {
      const { live } = theSite();
      live.body = closings('2026-01-12T12:42:00Z', []);
      const serve = (today: unknown): void => {
        live.predictions = predictions([
          { district: 0, time_zone: ZONE, neighbors: [], days: [today, today] },
        ]);
      };
      serve(THIN_FORECAST);
      const school = await visit(browser, options, { query: `?school=${ALPHA}` });
      const section = school.page.locator('aside.detail .chance');
      const number = section.locator('.number');
      await expect(number).toHaveText('74%', SETTLE);
      await expect(section.locator('.meaning')).toContainText(chanceFormat.chanceOn(TODAY));
      await expect(section.locator('.few')).toHaveText(chanceCopy.fewRecords);
      await expect(section.locator('.meaning + .few')).toHaveCount(1);
      await expect(number).toHaveClass(/\bis-thin\b/u);
      await expect(section.locator('.sum > li').first()).toContainText('winter advisory days');
      const lighter = await number.evaluate((node) => getComputedStyle(node).color);
      expect(lighter).toBe('rgb(163, 163, 163)');
      expect(school.problems).toEqual([]);
      await school.context.close();

      // The same day from a file with the flag off, and from one written before it.
      for (const why of [{ base: { ...NATION_BASE, thin: false } }, { base: NATION_BASE }]) {
        serve({ ...THIN_FORECAST, why });
        const plain = await visit(browser, options, { query: `?school=${ALPHA}` });
        const shown = plain.page.locator('aside.detail .chance');
        await expect(shown.locator('.number')).toHaveText('74%', SETTLE);
        await expect(shown.locator('.meaning')).toContainText(chanceFormat.chanceOn(TODAY));
        await expect(shown.locator('.few')).toHaveCount(0);
        await expect(shown.locator('.number')).not.toHaveClass(/\bis-thin\b/u);
        await expect(shown).not.toContainText(chanceCopy.fewRecords);
        const color = await shown
          .locator('.number')
          .evaluate((node) => getComputedStyle(node).color);
        expect(color).toBe('rgb(245, 245, 245)');
        expect(plain.problems).toEqual([]);
        await plain.context.close();
      }
    });

    test('a private school panel shows its own chance from the live root, counted over private schools', async ({
      browser,
    }) => {
      const { live } = theSite();
      live.body = closings('2026-01-12T12:42:00Z', []);
      // The district's own chance is 37%; the private school's own is 42%, from the shared
      // outlooks by its place in the directory.
      live.predictions = predictions(
        [{ district: 0, time_zone: ZONE, days: [STORM_FORECAST, STORM_FORECAST] }],
        '2026-01-12T12:50:00Z',
        {
          schools: [{ school: ALL.indexOf(PRIVATE), zone: 0, days: [0, 0] }],
          outlooks: [PRIVATE_FORECAST],
          zones: [ZONE],
        },
      );
      const school = await visit(browser, options, { query: `?school=${PRIVATE.id}` });
      const panel = school.page.locator('aside.detail');
      await expect(panel.locator('h2')).toHaveText(PRIVATE.name, SETTLE);
      await expect(panel.locator('.kind')).toContainText(copy.detail.privateSchool);
      const section = panel.locator('.chance');
      await expect(section.locator('.number')).toHaveText('42%', SETTLE);
      await expect(section.locator('.meaning')).toContainText(chanceFormat.chanceOn(TODAY));
      await expect(section.locator('.why-title')).toHaveText(chanceFormat.howWeGot(0.42));
      // Its base counts private schools only, around its own name.
      await expect(section.locator('.sum > li').first()).toContainText(
        `Private schools near ${PRIVATE.name}`,
      );
      await expect(section.locator('.sum > li').first()).toContainText(
        'recorded days with a winter storm warning',
      );
      expect(school.problems).toEqual([]);
      await school.context.close();
    });

    test('a chance file over 90 minutes old shows no chance, a fresh one shows it, and a blank one takes it away', async ({
      browser,
    }) => {
      const { live } = theSite();
      live.body = closings('2026-01-12T12:42:00Z', []);
      const storm = [
        {
          district: 0,
          time_zone: ZONE,
          neighbors: [],
          days: [STORM_FORECAST, { ...STORM_FORECAST, record: null, reasons: [] }],
        },
      ];
      // 91 minutes before the page's clock: too old to show as the chance now.
      live.predictions = predictions(storm, '2026-01-12T11:22:00Z');
      const school = await visit(browser, options, { query: `?school=${ALPHA}` });
      const panel = school.page.locator('aside.detail');
      await expect(panel).toBeVisible(SETTLE);
      await expect.poll(() => live.predictionReads, SETTLE).toBeGreaterThanOrEqual(1);
      await expect(panel.locator('.chance .number')).toHaveCount(0);
      // A fresh file, read at the next side poll (five minutes): the chance shows.
      live.predictions = predictions(storm, '2026-01-12T12:50:00Z');
      for (let step = 0; step < 5; step += 1) await poll(school.page);
      await expect(panel.locator('.chance .number')).toHaveText('37%', SETTLE);
      // A blank file (predict blank), newer: the chance goes, on a laptop and a phone alike.
      live.predictions = predictions([], '2026-01-12T12:56:00Z');
      for (let step = 0; step < 5; step += 1) await poll(school.page);
      await expect(panel.locator('.chance .number')).toHaveCount(0, SETTLE);
      expect(school.problems).toEqual([]);
      await school.context.close();
    });

    test('an open area panel counts what the live file says, takes a newer one within one poll, drops it for a blank one, and ignores an older one', async ({
      browser,
    }) => {
      const { live } = theSite();
      const { context, page, problems, requests } = await visit(browser, options, {
        query: `?zip=${ZIP}`,
      });
      const panel = page.locator('aside.detail');
      const glyphs = (kind: string) => panel.locator(`button.school .glyph.is-${kind}`);
      /** How many rows show each status: closed, delayed, remote, early dismissal. */
      const tones = async (): Promise<number[]> =>
        Promise.all(
          ['closed', 'delayed', 'remote', 'early-dismissal'].map((kind) => glyphs(kind).count()),
        );
      await expect(panel).toHaveAttribute('aria-busy', 'false', SETTLE);
      await expect(panel.locator('button.school')).toHaveCount(SCHOOLS.length, SETTLE);
      await expect.poll(tones, SETTLE).toEqual([1, 1, 0, 0]);
      await expect(
        panel.getByRole('button', { name: new RegExp(SCHOOLS[0].name, 'u') }),
      ).toHaveAccessibleName(new RegExp(`${SCHOOLS[0].name}.* ${copy.status.closed}\\b`, 'u'));
      await expect.poll(() => lit(page), SETTLE).toBe(2);

      // A newer file: Gamma goes remote in the panel within one poll, the map's read and the
      // panel's one between them.
      live.body = SECOND;
      const reads = live.requests.length;
      await poll(page);
      await expect.poll(tones, SETTLE).toEqual([1, 1, 1, 0]);
      expect(live.requests.length).toBe(reads + 1);

      // A blank file: no status on any row, and no count, within one poll.
      live.body = BLANK;
      await poll(page);
      await expect.poll(tones, SETTLE).toEqual([0, 0, 0, 0]);
      await expect(panel.locator('.counts')).toHaveCount(0);
      await expect.poll(() => lit(page), SETTLE).toBe(0);

      // SECOND again, older than the blank file: not taken.
      live.body = SECOND;
      await poll(page);
      await expect.poll(() => live.requests.length, SETTLE).toBe(reads + 3);
      await page.waitForTimeout(3000);
      expect(await tones()).toEqual([0, 0, 0, 0]);
      expect(await lit(page)).toBe(0);

      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('an ingest that stops while the page is open turns Live into Updated after 20 minutes, and keeps the lights and the panel', async ({
      browser,
    }) => {
      const { live } = theSite();
      const { context, page, problems, requests } = await visit(browser, options, {
        query: `?school=${ALPHA}`,
      });
      const updated = page.locator('.updated');
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect(updated).toHaveText(format.liveAt(AT_42, ZONE), SETTLE);
      await expect(statusLines(page).first()).toContainText(CLOSED_TODAY, SETTLE);
      // The host keeps answering the same 6:42 file, minute after minute, past 7:02.
      // The page's reads of the file on their way, and any given up, from here on.
      const pending = new Set<Request>();
      let failed = 0;
      const closings = (request: Request): boolean => request.url().includes('live/closings.json');
      page.on('request', (request) => {
        if (closings(request)) pending.add(request);
      });
      page.on('requestfinished', (request) => pending.delete(request));
      page.on('requestfailed', (request) => {
        if (closings(request)) failed += 1;
        pending.delete(request);
      });
      const reads = live.requests.length;
      const start = await pageNow(page);
      // One read a minute, for the map and the open panel together: each answered 304. The page's
      // clock also runs on between steps, so a poll can fall due while a step waits; the reads
      // are counted against the minutes the page's clock moved.
      for (let minute = 1; minute <= 10; minute += 1) {
        await poll(page);
        await expect
          .poll(() => live.requests.length, SETTLE)
          .toBeGreaterThanOrEqual(reads + minute - 1);
        // Each read finished in the page before the clock jumps again: a minute's jump while one
        // is on its way would give it up (it began longer ago than a read may take), which no
        // real minute does, and the next read would then miss the HTTP cache.
        await expect.poll(() => pending.size, SETTLE).toBe(0);
      }
      await page.waitForTimeout(1000);
      const now = await pageNow(page);
      const minutes = (now.getTime() - start.getTime()) / 60_000;
      const made = live.requests.length - reads;
      expect(made).toBeGreaterThanOrEqual(Math.floor(minutes) - 1);
      expect(made).toBeLessThanOrEqual(Math.ceil(minutes));
      expect(failed).toBe(0);
      expect(live.requests.slice(reads).map((request) => request.answer)).toEqual(
        Array.from({ length: made }, () => 304),
      );
      expect(now.getTime()).toBeGreaterThan(AT_42.getTime() + 20 * 60_000);
      await expect(updated).toHaveText(format.updatedAt(AT_42, ZONE, now), SETTLE);
      await expect(page.locator('.updated .dot')).toHaveCount(0);
      // The lights were true at their time, and each expires by its own day: they stay.
      expect(await lit(page)).toBe(2);
      await expect(statusLines(page).first()).toContainText(CLOSED_TODAY);

      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('a file 25 minutes old keeps its lights and says when it was updated, not live', async ({
      browser,
    }) => {
      const { live } = theSite();
      const made = new Date(NOW.getTime() - 25 * 60_000);
      live.body = closings(made.toISOString().replace('.000Z', 'Z'), [
        [0, 0],
        [1, 1],
      ]);
      const { context, page, problems, requests } = await visit(browser, options);
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect(page.locator('.updated')).toHaveText(format.updatedAt(made, ZONE, NOW), SETTLE);
      await expect(page.locator('.updated .dot')).toHaveCount(0);
      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('a file from last night lights what it holds for today, and says Updated with its date', async ({
      browser,
    }) => {
      const { live } = theSite();
      // 9:40 PM the evening before: the ingest stopped after the evening's announcements.
      const made = new Date('2026-01-12T03:40:00Z');
      live.body = closings('2026-01-12T03:40:00Z', [
        [0, 0],
        [1, 1],
      ]);
      const { context, page, problems, requests } = await visit(browser, options);
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await expect(page.locator('.updated')).toHaveText(format.updatedAt(made, ZONE, NOW), SETTLE);
      await expect(page.locator('.updated')).toContainText('Jan 11');
      await expect(page.locator('.updated .dot')).toHaveCount(0);
      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('in the hours when the country spans two days the map is dark, and the file still live', async ({
      browser,
    }) => {
      const { live } = theSite();
      // 12:30 AM Tuesday in Kansas City, 10:30 PM Monday in the West.
      const at = new Date('2026-01-13T06:30:00Z');
      const made = new Date('2026-01-13T06:28:00Z');
      live.body = closings(
        '2026-01-13T06:28:00Z',
        [
          [0, 0],
          [1, 1],
        ],
        STAMP,
        '2026-01-13',
      );
      const { context, page, problems, requests } = await visit(browser, options, {
        at,
        query: `?school=${ALPHA}`,
      });
      await expect(page.locator('.updated')).toHaveText(format.liveAt(made, ZONE), SETTLE);
      await page.waitForTimeout(2000);
      expect(await lit(page)).toBe(0);
      expect(await legend(page)).toEqual(legendFor([0, 0, 0, 0]));
      await expect(page.locator('aside.detail')).toContainText(SCHOOLS[0].name, SETTLE);
      // Without its district's time zone (the predictions file gives it, and this build ships
      // none), the panel names no day for the school rather than guess one; never "Open".
      await page.waitForTimeout(1000);
      expect(await statusLines(page).allTextContents()).toEqual([]);
      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('a file for another directory lights nothing', async ({ browser }) => {
      const { live } = theSite();
      live.body = closings(
        '2026-01-12T12:44:00Z',
        [
          [0, 0],
          [1, 1],
        ],
        { ...STAMP, generated_on: '2026-10-01' },
      );
      const { context, page, problems, requests } = await visit(browser, options);
      await expect.poll(() => live.requests.length, SETTLE).toBeGreaterThanOrEqual(1);
      await page.waitForTimeout(3000);
      expect(await lit(page)).toBe(0);
      expect(await legend(page)).toEqual(legendFor([0, 0, 0, 0]));
      // Nothing from the file is shown, so no time is given for it.
      await expect(page.locator('.updated')).toHaveCount(0);
      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);
      await context.close();
    });

    test('the worker reads the live file network-first, keeps only a newer copy, and an offline reload is given it', async ({
      browser,
    }) => {
      const { live } = theSite();
      const { context, page, problems, requests } = await visit(browser, options, {
        worker: true,
      });
      const updated = page.locator('.updated');
      await expect.poll(() => lit(page), SETTLE).toBe(2);
      await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
        timeout: 60_000,
      });
      const fileUrl = `${live.root}live/closings.json`;
      const kept = (): Promise<string | null> =>
        page.evaluate(
          async ([name, url]) => {
            const response = await (await caches.open(name)).match(url);
            return response === undefined ? null : await response.text();
          },
          [DATA_CACHE, fileUrl] as const,
        );
      // Kept as the page read it before the worker took over, or as the worker read it since.
      await expect.poll(kept, SETTLE).toBe(FIRST);

      // Through the worker, a poll gets the network's newer file, not the kept one.
      live.body = SECOND;
      await poll(page);
      await expect.poll(() => lit(page), SETTLE).toBe(3);
      await expect.poll(kept, SETTLE).toBe(SECOND);

      // An edge behind serves the older file: the page ignores it, and the worker keeps the newer.
      live.body = FIRST;
      const reads = live.requests.length;
      await poll(page);
      await expect.poll(() => live.requests.length, SETTLE).toBeGreaterThan(reads);
      expect(live.requests.at(-1)?.answer).toBe(200);
      await page.waitForTimeout(2000);
      expect(await kept()).toBe(SECOND);
      expect(await lit(page)).toBe(3);
      await expect(updated).toHaveText(format.liveAt(AT_47, ZONE));
      expectOnlyLiveRoot(requests);
      expect(problems).toEqual([]);

      // Offline, a reload starts from nothing in the page, and the browser's own cache holds the
      // older copy it fetched last: the worker gives the newer kept copy, with its own time.
      await context.setOffline(true);
      await page.reload();
      await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
        timeout: 60_000,
      });
      await expect.poll(() => lit(page), SETTLE).toBe(3);
      await expect(updated).toHaveText(format.offline(AT_47, ZONE, await pageNow(page)), SETTLE);
      expect(await kept()).toBe(SECOND);
      await context.close();
    });
  });
}
