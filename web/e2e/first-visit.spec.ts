/**
 * A first visit downloads each data file once, whenever the service worker
 * takes the page over: before the page reads the search index or the school
 * directory, while it downloads one, or after it has it. What the page read
 * before the worker took over is in the worker's cache once the read is done,
 * so a second visit with no network searches and shows the dust as the first.
 *
 * A deploy that publishes a new directory and a new index under new names
 * leaves no copy of the old ones kept, whether a worker took the page over
 * or none could be registered, and the new ones are downloaded once.
 *
 * The site is a build with data staged in its public/data/ folder, made here in
 * a temporary folder: a search index built by scripts/build-search-index.mjs
 * from real records (two cities, a ZIP code and two schools, as app.spec.ts
 * has them), a school directory of those two schools and three more near
 * Kansas City as the pipeline's directory has them, and a live closings file
 * that lights nothing. The closings file is SYNTHETIC: an envelope with no
 * days, for this test only. The index and the directory are published under
 * names with a hash of their content in them, as staging names them
 * (scripts/stage-data.mjs). A second build is the next deploy: the directory
 * without one of the five schools, and the index without the ZIP code, so
 * each of the three files has a new name.
 *
 * The server is this spec's own. It counts the requests that reach it for each
 * file. It answers with no-cache and an ETag, as `vite preview` does, so the
 * browser's HTTP cache answers nothing on its own: every time the page or the
 * worker asks for a file, the server hears of it, a revalidation too. It can
 * hold a file's answer, before its headers or halfway through its body, until
 * the test lets it go: holding sw.js holds the worker's take-over, so each test
 * puts it before, during or after the page's reads. And it can send data as a
 * slow network does, a piece at a time.
 *
 * Runs once, under the desktop project. WebGL here is SwiftShader.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext, Page } from '@playwright/test';
import { build } from 'vite';

import { format } from '../src/copy-format';
import { hashedPath } from '../src/data/paths';
import { CACHE_NAMES, SKIP_WAITING_MESSAGE, SW_FILE, routeFor } from '../src/pwa/config';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

const CLOSINGS = 'data/live/closings.json';

/** The worker's cache for a data file (data/...), by its route for it (src/pwa/config.ts). */
function cacheOf(file: string): string {
  return routeFor(`https://snow.test/${file}`, '/') === 'staticData'
    ? CACHE_NAMES.staticData
    : CACHE_NAMES.data;
}

/** Search records as the pipeline writes them, the same as app.spec.ts stages. */
const SEARCH_RECORDS = [
  '{"geoid":"2036000","kind":"city","lat":39.122539,"lon":-94.741781,"name":"Kansas City","population":157805,"state":"KS"}',
  '{"geoid":"2938000","kind":"city","lat":39.125155,"lon":-94.550313,"name":"Kansas City","population":521220,"state":"MO"}',
  '{"districts":[{"leaid":"2916400","name":"Kansas City 33 School District","share":1.0}],"lat":39.01414,"lon":-94.595493,"states":["MO"],"zcta":"64113"}',
  '{"kind":"school","id":"291640000557","name":"BORDER STAR MONTESSORI","sub":"","state":"MO","lat":39.013304,"lon":-94.592692,"weight":0}',
  '{"kind":"school","id":"A1902690","name":"THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS","sub":"","state":"MO","lat":39.03606,"lon":-94.593001,"weight":0}',
];

/** Five schools near Kansas City as the pipeline's directory has them, in its order (by id). */
const SCHOOLS = [
  { id: '201014000137', name: 'Olathe North Sr High', lon: -94.8093, lat: 38.888, district: 0 },
  {
    id: '201164001574',
    name: 'Shawnee Mission East High',
    lon: -94.631999,
    lat: 38.991687,
    district: 1,
  },
  { id: '201200000112', name: 'Blue Valley High', lon: -94.656, lat: 38.839, district: 2 },
  {
    id: '291640000557',
    name: 'BORDER STAR MONTESSORI',
    lon: -94.592692,
    lat: 39.013304,
    district: 3,
  },
  {
    id: 'A1902690',
    name: 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
    lon: -94.593001,
    lat: 39.03606,
    district: 0xffffffff,
  },
] as const;
const DISTRICTS = [
  ['2010140', 'Olathe'],
  ['2011640', 'Shawnee Mission Pub Sch'],
  ['2012000', 'Blue Valley'],
  ['2916400', 'KANSAS CITY 33'],
] as const;
type School = (typeof SCHOOLS)[number];
const GENERATED_AT = '2026-01-12T12:42:00Z';
const ZONE = 'America/Chicago';
/** Kansas City at zoom 6: past 5, where every school shows as dust. */
const DUST_VIEW = { center: [-94.6, 39.0] as [number, number], zoom: 6 };

function directoryMeta(schools: readonly School[], generatedOn: string): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: generatedOn,
    count: schools.length,
    ids: schools.map((school) => school.id),
    names: schools.map((school) => school.name),
    districts: { ids: DISTRICTS.map(([id]) => id), names: DISTRICTS.map(([, name]) => name) },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

function directoryPoints(schools: readonly School[]): Buffer {
  const bytes = Buffer.alloc(16 + 13 * schools.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(schools.length, 8);
  bytes.writeUInt32LE(DISTRICTS.length, 12);
  schools.forEach((school, i) => {
    const at = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), at);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), at + 4);
    bytes.writeUInt32LE(school.district, at + 8);
    bytes.writeUInt8(0, at + 12);
  });
  return bytes;
}

/** SYNTHETIC: a closings file that lights nothing, for this test only. */
function syntheticClosings(schools: readonly School[], generatedOn: string): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: GENERATED_AT,
    directory: { generated_on: generatedOn, schools: schools.length, districts: DISTRICTS.length },
    days: [],
  });
}

/** What one deploy publishes. */
interface DeployData {
  readonly records: readonly string[];
  readonly schools: readonly School[];
  readonly directoryOn: string;
}

const FIRST_DATA: DeployData = {
  records: SEARCH_RECORDS,
  schools: SCHOOLS,
  directoryOn: '2026-09-25',
};
/** The next deploy: a directory without Blue Valley High, an index without the ZIP code. */
const NEXT_DATA: DeployData = {
  records: SEARCH_RECORDS.filter((record) => !record.includes('"zcta"')),
  schools: SCHOOLS.filter((school) => school.name !== 'Blue Valley High'),
  directoryOn: '2026-10-02',
};

/** A build of the site, and the names it publishes its hashed data files under. */
interface Deploy {
  readonly root: string;
  readonly index: string;
  readonly meta: string;
  readonly points: string;
  /** Schools in its directory. */
  readonly schools: number;
}

/** The files under data/ whose names carry a content hash. */
function hashedFiles(deploy: Deploy): string[] {
  return [deploy.index, deploy.meta, deploy.points];
}

/** Every data file a deploy publishes. */
function dataFiles(deploy: Deploy): string[] {
  return [CLOSINGS, ...hashedFiles(deploy)];
}

// A static host that counts, holds and throttles. -------------------------------------

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
};

/**
 * A held answer: `reached` once the request has come and been held. `release` lets it go on;
 * `cut` ends it there, as a dropped connection does.
 */
interface Gate {
  readonly reached: Promise<void>;
  release(): void;
  cut(): void;
}

interface Hold {
  readonly path: string;
  readonly at: 'headers' | 'body';
  readonly reach: () => void;
  /** True once released, false once cut. */
  readonly opened: Promise<boolean>;
  readonly release: () => void;
}

/** How a slow network sends a data file: in `pieces` parts, `everyMs` apart. */
interface Slow {
  readonly pieces: number;
  readonly everyMs: number;
}

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

class Site {
  /** Every request the server heard, by path, in order, with the status it answered. */
  readonly log: { path: string; status: number }[] = [];
  private readonly holds: Hold[] = [];
  private server: Server | undefined;
  private lastData = 0;
  /** Paths answered with a 404, as though not deployed. */
  private readonly refused = new Set<string>();
  origin = '';

  constructor(
    private root: string,
    private readonly cacheControl = 'no-cache',
    private readonly slow: Slow | null = null,
  ) {}

  /** Serves another build from now on, as a deploy does. */
  deploy(root: string): void {
    this.root = root;
  }

  /** Answers `file` with a 404 from now on. */
  refuse(file: string): void {
    this.refused.add(`/${file}`);
  }

  url(file = ''): string {
    return `${this.origin}/${file}`;
  }

  /**
   * Holds the next answer for `file`: before its headers, or once its headers and half its
   * body are out, until the gate is released.
   */
  hold(file: string, at: Hold['at'] = 'headers'): Gate {
    let reach!: () => void;
    const reached = new Promise<void>((resolve) => {
      reach = resolve;
    });
    let open!: (go: boolean) => void;
    const opened = new Promise<boolean>((resolve) => {
      open = resolve;
    });
    const release = (): void => {
      open(true);
    };
    this.holds.push({ path: `/${file}`, at, reach, opened, release });
    return {
      reached,
      release,
      cut: () => {
        open(false);
      },
    };
  }

  /** How many requests for each file under data/ reached the server. */
  dataHits(): Record<string, number> {
    const hits: Record<string, number> = {};
    for (const { path: file } of this.log) {
      if (file.startsWith('/data/')) hits[file.slice(1)] = (hits[file.slice(1)] ?? 0) + 1;
    }
    return hits;
  }

  /** Resolves once no request for a data file has come or ended for `ms`. */
  async quiet(ms = 1000): Promise<void> {
    while (Date.now() - this.lastData < ms) await wait(100);
  }

  async start(): Promise<void> {
    const server = createServer((request, response) => {
      void this.handle(request, response);
    });
    this.server = server;
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    this.origin = `http://127.0.0.1:${String((server.address() as AddressInfo).port)}`;
  }

  /** Takes the site off the network: every connection is refused from now on. */
  async stop(): Promise<void> {
    for (const held of this.holds.splice(0)) held.release();
    const server = this.server;
    if (server === undefined) return;
    this.server = undefined;
    server.closeAllConnections();
    await new Promise<void>((resolve) => {
      server.close(() => {
        resolve();
      });
    });
  }

  private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const urlPath = decodeURIComponent(new URL(request.url ?? '/', 'http://x').pathname);
    const logged = { path: urlPath, status: 0 };
    this.log.push(logged);
    const isData = urlPath.startsWith('/data/');
    if (isData) this.lastData = Date.now();
    response.on('close', () => {
      logged.status = response.statusCode;
      if (isData) this.lastData = Date.now();
    });
    const file = path.join(this.root, urlPath.endsWith('/') ? `${urlPath}index.html` : urlPath);
    let body: Buffer;
    let modified: Date;
    try {
      if (this.refused.has(urlPath)) throw new Error('refused');
      if (!file.startsWith(this.root) || !statSync(file).isFile()) throw new Error('not a file');
      body = readFileSync(file);
      modified = statSync(file).mtime;
    } catch {
      response.writeHead(404, { 'Content-Type': 'text/html' }).end('404');
      return;
    }
    const at = this.holds.findIndex((held) => held.path === urlPath);
    const held = at < 0 ? null : (this.holds.splice(at, 1)[0] ?? null);
    if (held?.at === 'headers') {
      held.reach();
      if (!(await held.opened)) {
        response.destroy();
        return;
      }
    }
    const etag = `"${createHash('sha1').update(body).digest('hex').slice(0, 16)}"`;
    const headers = {
      'Content-Type': TYPES[path.extname(urlPath) || '.html'] ?? 'application/octet-stream',
      'Cache-Control': this.cacheControl,
      ETag: etag,
      'Last-Modified': modified.toUTCString(),
    };
    if (request.headers['if-none-match'] === etag) {
      response.writeHead(304, headers).end();
      return;
    }
    response.writeHead(200, { ...headers, 'Content-Length': body.length });
    const half = Math.ceil(body.length / 2);
    if (held?.at === 'body') {
      response.write(body.subarray(0, half));
      held.reach();
      if (await held.opened) response.end(body.subarray(half));
      else response.destroy();
      return;
    }
    if (isData && this.slow !== null) {
      const size = Math.ceil(body.length / this.slow.pieces);
      for (let start = 0; start < body.length; start += size) {
        await wait(this.slow.everyMs);
        if (response.destroyed) return;
        response.write(body.subarray(start, start + size));
      }
      response.end();
      return;
    }
    response.end(body);
  }
}

// The page. ---------------------------------------------------------------------------

interface Visit {
  readonly context: BrowserContext;
  readonly page: Page;
  /** Page errors, and console errors with the URL they are about, but SwiftShader's own lines. */
  readonly problems: string[];
}

async function firstVisit(browser: Browser, site: Site, address = ''): Promise<Visit> {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    timezoneId: ZONE,
  });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !GPU_DRIVER_NOISE.test(message.text())) {
      problems.push(`console.error: ${message.text()} (${message.location().url})`);
    }
  });
  await page.goto(site.url(address));
  return { context, page, problems };
}

/** Resolves once the map is on screen and at rest. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && !map.isMoving();
    },
    null,
    { timeout: 60_000, polling: 100 },
  );
}

/** Resolves once a service worker controls the page. */
async function takenOver(page: Page): Promise<void> {
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 60_000,
  });
}

/** Whether a service worker controls the page now. */
async function controlled(page: Page): Promise<boolean> {
  return page.evaluate(() => navigator.serviceWorker.controller !== null);
}

/** Puts the search field in focus, which starts the index download. */
async function focusSearch(page: Page): Promise<void> {
  await page.locator('input.search-input').click();
}

/** Types “pembroke” and waits for Pembroke Hill among the results. */
async function findPembroke(page: Page): Promise<void> {
  const input = page.locator('input.search-input');
  await input.click();
  await input.fill('');
  await input.pressSequentially('pembroke', { delay: 20 });
  await expect(page.locator('[role="option"]', { hasText: /Pembroke Hill/i })).toHaveCount(1, {
    timeout: 30_000,
  });
}

/** Takes the map past zoom 5, where the dust shows every school, read from the directory. */
async function zoomPast5(page: Page): Promise<void> {
  await page.evaluate((view) => {
    window.snowlightMap?.jumpTo(view);
  }, DUST_VIEW);
}

/** How many schools the glow's dust holds: none until the directory is read. */
async function dust(page: Page): Promise<number> {
  return page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as
      { implementation: { stats: { dust: number } } } | undefined;
    return layer?.implementation.stats.dust ?? 0;
  }, GLOW_LAYER);
}

async function expectDust(page: Page, deploy: Deploy): Promise<void> {
  await expect.poll(() => dust(page), { timeout: 30_000 }).toBe(deploy.schools);
}

/** Which of `files` are not in the cache the worker keeps each in. */
async function notCached(page: Page, site: Site, files: readonly string[]): Promise<string[]> {
  const wanted = files.map((file) => [file, cacheOf(file), site.url(file)] as const);
  return page.evaluate(async (entries) => {
    const missing: string[] = [];
    for (const [file, name, url] of entries) {
      const held = (await caches.has(name))
        ? await (await caches.open(name)).match(url)
        : undefined;
      if (held === undefined) missing.push(file);
    }
    return missing;
  }, wanted);
}

/**
 * Waits until each of `files` is in the cache the worker keeps it in. (page.waitForFunction
 * takes the promise an async function returns as a true answer, so this polls instead.)
 */
async function waitForCached(page: Page, site: Site, files: readonly string[]): Promise<void> {
  await expect.poll(() => notCached(page, site, files), { timeout: 30_000 }).toEqual([]);
}

/** Every file under data/ the worker's data caches hold, sorted. */
async function heldData(page: Page, site: Site): Promise<string[]> {
  const held = await page.evaluate(
    async (names) => {
      const urls: string[] = [];
      for (const name of names) {
        if (!(await caches.has(name))) continue;
        for (const request of await (await caches.open(name)).keys()) urls.push(request.url);
      }
      return urls;
    },
    [CACHE_NAMES.staticData, CACHE_NAMES.data],
  );
  return held
    .filter((url) => url.startsWith(site.url('data/')))
    .map((url) => url.slice(site.url().length))
    .sort();
}

/**
 * The files under data/ the worker's limits cover in its cache-first cache: those it has
 * cached or served itself, which Workbox lists in its own database (workbox-expiration).
 */
async function tracked(page: Page, site: Site): Promise<string[]> {
  const urls = await page.evaluate(async (cacheName) => {
    // Only opened once the worker has made it: opening it first would make it without its store.
    if (!(await indexedDB.databases()).some((db) => db.name === 'workbox-expiration')) return [];
    return new Promise<string[]>((resolve, reject) => {
      const opened = indexedDB.open('workbox-expiration');
      opened.onerror = () => {
        reject(new Error(String(opened.error)));
      };
      opened.onsuccess = () => {
        const db = opened.result;
        const all = db.transaction('cache-entries').objectStore('cache-entries').getAll();
        all.onerror = () => {
          db.close();
          reject(new Error(String(all.error)));
        };
        all.onsuccess = () => {
          db.close();
          const entries = all.result as { cacheName: string; url: string }[];
          resolve(entries.filter((entry) => entry.cacheName === cacheName).map((e) => e.url));
        };
      };
    });
  }, CACHE_NAMES.staticData);
  return urls
    .filter((url) => url.startsWith(site.url('data/')))
    .map((url) => url.slice(site.url().length))
    .sort();
}

/** The worker the server now serves installs, as the page's hourly check finds it, and waits. */
async function installUpdate(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await (await navigator.serviceWorker.getRegistration())?.update();
  });
  await expect
    .poll(
      () =>
        page.evaluate(
          async () => ((await navigator.serviceWorker.getRegistration())?.waiting ?? null) !== null,
        ),
      { timeout: 60_000 },
    )
    .toBe(true);
}

/** The waiting worker takes over, as it does once the page is hidden (src/pwa/register.ts). */
async function switchToUpdate(page: Page): Promise<void> {
  await page.evaluate(async (message) => {
    (await navigator.serviceWorker.getRegistration())?.waiting?.postMessage(message);
  }, SKIP_WAITING_MESSAGE);
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const registration = await navigator.serviceWorker.getRegistration();
          return registration?.waiting === null && registration.active?.state === 'activated';
        }),
      { timeout: 60_000 },
    )
    .toBe(true);
}

/**
 * Once the worker has the page and has what the page read in its caches, and the network has
 * gone quiet: each data file read was asked of the server once, and nothing else was.
 */
async function expectEachOnce(page: Page, site: Site, files: readonly string[]): Promise<void> {
  await takenOver(page);
  await waitForCached(page, site, files);
  await site.quiet();
  expect(site.dataHits()).toEqual(Object.fromEntries(files.map((file) => [file, 1])));
}

/**
 * A second visit with no network: the site is gone and the browser offline. The shell comes
 * from the worker, and what the first visit read works from what it kept: search when it read
 * the index, the dust when it read the directory.
 */
async function expectOfflineVisit(
  visit: Visit,
  site: Site,
  deploy: Deploy,
  files: readonly string[],
): Promise<void> {
  const { context, page, problems } = visit;
  await site.stop();
  await context.setOffline(true);
  await page.goto(site.url());
  await settle(page);
  expect(await controlled(page)).toBe(true);
  // The live file the first visit read, with its own time, said to be from offline.
  await expect(page.locator('.updated')).toHaveText(
    format.offline(new Date(GENERATED_AT), ZONE, new Date()),
    { timeout: 30_000 },
  );
  if (files.includes(deploy.index)) await findPembroke(page);
  if (files.includes(deploy.meta)) {
    await zoomPast5(page);
    await expectDust(page, deploy);
  }
  // Nothing failed but the street tiles the results ask for ahead, which come from elsewhere.
  expect(problems.filter((problem) => !problem.includes('tiles.openfreemap.org'))).toEqual([]);
}

/** The first visit's reads, each once, then the second visit's with no network. */
async function expectReadOnceAndKept(
  visit: Visit,
  site: Site,
  files: readonly string[],
): Promise<void> {
  await expectEachOnce(visit.page, site, files);
  await expectOfflineVisit(visit, site, deployed, files);
}

// Setup ------------------------------------------------------------------------------

let root = '';
const UNBUILT: Deploy = { root: '', index: '', meta: '', points: '', schools: 0 };
/** The site as a first visit finds it. */
let deployed = UNBUILT;
/** The site after the next deploy. */
let redeployed = UNBUILT;

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
}

/** Writes `bytes` under `data`, at `file` with a hash of them in its name; the name as served. */
function publish(data: string, file: string, bytes: Buffer): string {
  const published = hashedPath(file, createHash('sha256').update(bytes).digest('hex'));
  mkdirSync(path.dirname(path.join(data, published)), { recursive: true });
  writeFileSync(path.join(data, published), bytes);
  return `data/${published}`;
}

/** Stages `content` in a public folder of its own and builds the site from it, in `name`. */
async function buildDeploy(name: string, content: DeployData): Promise<Deploy> {
  const folder = path.join(root, name);
  const publicDir = path.join(folder, 'public');
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  const data = path.join(publicDir, 'data');
  mkdirSync(path.join(data, 'live'), { recursive: true });
  const records = path.join(folder, 'records.jsonl');
  const built = path.join(folder, 'search-index.bin');
  writeFileSync(records, `${content.records.join('\n')}\n`);
  execFileSync(process.execPath, ['scripts/build-search-index.mjs', '--out', built, records], {
    cwd: WEB,
    stdio: 'pipe',
  });
  const deploy: Deploy = {
    root: path.join(folder, 'site'),
    index: publish(data, 'search-index.bin', readFileSync(built)),
    meta: publish(
      data,
      'schools/meta.json',
      Buffer.from(directoryMeta(content.schools, content.directoryOn)),
    ),
    points: publish(data, 'schools/points.bin', directoryPoints(content.schools)),
    schools: content.schools.length,
  };
  writeFileSync(
    path.join(data, 'live/closings.json'),
    syntheticClosings(content.schools, content.directoryOn),
  );
  await build({
    root: WEB,
    publicDir,
    // A cache of its own, so this build never races another spec's.
    cacheDir: path.join(root, 'vite-cache'),
    logLevel: 'warn',
    build: { outDir: deploy.root, emptyOutDir: true },
  });
  return deploy;
}

test.describe.configure({ mode: 'default', timeout: 120_000 });

test.beforeAll(async () => {
  if (test.info().project.name !== 'desktop') return;
  test.setTimeout(360_000);
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-first-visit-e2e-'));
  // One after the other: both builds write through the same Vite cache.
  deployed = await buildDeploy('first', FIRST_DATA);
  redeployed = await buildDeploy('next', NEXT_DATA);
});

test.afterAll(() => {
  if (root !== '') rmSync(root, { recursive: true, force: true });
});

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets up its own site; runs once.');
});

/** A fresh server for one test, started; stopped when the test ends. */
async function serve(cacheControl?: string, slow?: Slow): Promise<Site> {
  const site = new Site(deployed.root, cacheControl, slow ?? null);
  await site.start();
  return site;
}

// Tests ------------------------------------------------------------------------------

test('each build ships the data this spec counts, the hashed files under names of their own', () => {
  for (const deploy of [deployed, redeployed]) {
    expect(filesIn(path.join(deploy.root, 'data')).sort()).toEqual(
      dataFiles(deploy)
        .map((file) => file.slice('data/'.length))
        .sort(),
    );
  }
  const renamed = hashedFiles(redeployed).filter((file) => !hashedFiles(deployed).includes(file));
  expect(renamed).toEqual(hashedFiles(redeployed));
});

test('the worker takes over before the search: the index is downloaded once, by the worker', async ({
  browser,
}) => {
  const site = await serve();
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await takenOver(visit.page);
    await findPembroke(visit.page);
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.index]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('the worker takes over while the index downloads: it is downloaded once, and kept', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const index = site.hold(deployed.index, 'body');
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await focusSearch(visit.page);
    // Half the index is in when the worker takes over.
    await index.reached;
    expect(await controlled(visit.page)).toBe(false);
    worker.release();
    await takenOver(visit.page);
    index.release();
    await findPembroke(visit.page);
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.index]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('the worker takes over after the search: the index is not downloaded again', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await findPembroke(visit.page);
    expect(await controlled(visit.page)).toBe(false);
    worker.release();
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.index]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('the map passes zoom 5 before the worker takes over: the directory is not downloaded again', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await zoomPast5(visit.page);
    await expectDust(visit.page, deployed);
    expect(await controlled(visit.page)).toBe(false);
    worker.release();
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.meta, deployed.points]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('the worker takes over while the directory downloads: it is downloaded once, and kept', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const meta = site.hold(deployed.meta, 'body');
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await zoomPast5(visit.page);
    await meta.reached;
    expect(await controlled(visit.page)).toBe(false);
    worker.release();
    await takenOver(visit.page);
    meta.release();
    await expectDust(visit.page, deployed);
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.meta, deployed.points]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('the map passes zoom 5 after the worker takes over: the directory is downloaded once, by the worker', async ({
  browser,
}) => {
  const site = await serve();
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await takenOver(visit.page);
    await zoomPast5(visit.page);
    await expectDust(visit.page, deployed);
    await expectReadOnceAndKept(visit, site, [CLOSINGS, deployed.meta, deployed.points]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('on a slow network, searching and zooming in at once, each file is downloaded once', async ({
  browser,
}) => {
  // GitHub Pages' own caching, and every data file arriving in ten pieces over two seconds.
  const site = await serve('max-age=600', { pieces: 10, everyMs: 200 });
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await focusSearch(visit.page);
    await zoomPast5(visit.page);
    await findPembroke(visit.page);
    await expectDust(visit.page, deployed);
    await expectReadOnceAndKept(visit, site, [
      CLOSINGS,
      deployed.index,
      deployed.meta,
      deployed.points,
    ]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('a download cut off before the worker takes over keeps nothing, and the next visit downloads it once and keeps it', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const meta = site.hold(deployed.meta, 'body');
  const visit = await firstVisit(browser, site);
  try {
    await settle(visit.page);
    await zoomPast5(visit.page);
    // Half the directory's names are in when the connection drops.
    await meta.reached;
    meta.cut();
    worker.release();
    await takenOver(visit.page);
    // Where each school is came whole, and is kept; of the names, nothing is, not half a file.
    await waitForCached(visit.page, site, [CLOSINGS, deployed.points]);
    await site.quiet();
    expect(await notCached(visit.page, site, [deployed.meta])).toEqual([deployed.meta]);
    expect(site.dataHits()).toEqual({ [CLOSINGS]: 1, [deployed.meta]: 1, [deployed.points]: 1 });
    // No error but the cut-off read's own.
    expect(visit.problems.splice(0).filter((problem) => !problem.includes(deployed.meta))).toEqual(
      [],
    );

    // The next visit, with the worker in control from the start, asks for the names again,
    // once, and keeps them; where each school is comes from the cache, and the live file is
    // asked for again as live files are on every visit.
    await visit.page.goto(site.url());
    await settle(visit.page);
    await zoomPast5(visit.page);
    await expectDust(visit.page, deployed);
    await waitForCached(visit.page, site, [deployed.meta]);
    await site.quiet();
    expect(site.dataHits()).toEqual({ [CLOSINGS]: 2, [deployed.meta]: 2, [deployed.points]: 1 });
    await expectOfflineVisit(visit, site, deployed, [CLOSINGS, deployed.meta, deployed.points]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('after a deploy that renames the index and the directory, each new file is downloaded once and no old copy is kept', async ({
  browser,
}) => {
  const site = await serve();
  const worker = site.hold(SW_FILE);
  const visit = await firstVisit(browser, site);
  const { page } = visit;
  try {
    // Everything is read before the worker takes over: kept by the page, never seen by the worker.
    await settle(page);
    await findPembroke(page);
    await zoomPast5(page);
    await expectDust(page, deployed);
    worker.release();
    await expectEachOnce(page, site, dataFiles(deployed));

    // The deploy. The new worker installs and takes over, and the page loads the new build.
    site.deploy(redeployed.root);
    await installUpdate(page);
    await switchToUpdate(page);
    await page.goto(site.url());
    await settle(page);
    await findPembroke(page);
    await zoomPast5(page);
    await expectDust(page, redeployed);

    // The new files come from the network once each, through the worker, whose limits cover them;
    // the copies of the old ones are gone, and nothing else under data/ is kept.
    await waitForCached(page, site, hashedFiles(redeployed));
    await expect
      .poll(() => heldData(page, site), { timeout: 30_000 })
      .toEqual(dataFiles(redeployed).sort());
    await expect
      .poll(() => tracked(page, site), { timeout: 30_000 })
      .toEqual(hashedFiles(redeployed).sort());
    await site.quiet();
    // The live file is asked for on each visit, and again when the worker finds it changed.
    const { [CLOSINGS]: closings, ...hashed } = site.dataHits();
    expect(closings).toBeGreaterThanOrEqual(2);
    expect(hashed).toEqual(
      Object.fromEntries(
        [...hashedFiles(deployed), ...hashedFiles(redeployed)].map((file) => [file, 1]),
      ),
    );
    await expectOfflineVisit(visit, site, redeployed, dataFiles(redeployed));
  } finally {
    await visit.context.close();
    await site.stop();
  }
});

test('while no worker can be registered, the page keeps what it reads, and a deploy leaves no old copy kept', async ({
  browser,
}) => {
  const site = await serve();
  site.refuse(SW_FILE);
  const visit = await firstVisit(browser, site);
  const { page } = visit;
  try {
    await settle(page);
    await findPembroke(page);
    await zoomPast5(page);
    await expectDust(page, deployed);
    await waitForCached(page, site, dataFiles(deployed));

    site.deploy(redeployed.root);
    await page.goto(site.url());
    await settle(page);
    await findPembroke(page);
    await zoomPast5(page);
    await expectDust(page, redeployed);
    expect(await controlled(page)).toBe(false);
    await waitForCached(page, site, hashedFiles(redeployed));
    await expect
      .poll(() => heldData(page, site), { timeout: 30_000 })
      .toEqual(dataFiles(redeployed).sort());
    await site.quiet();
    expect(site.dataHits()).toEqual(
      Object.fromEntries([
        [CLOSINGS, 2],
        ...[...hashedFiles(deployed), ...hashedFiles(redeployed)].map((file) => [file, 1]),
      ]),
    );
    // No error but the browser's own about the worker's script, refused with a 404.
    const refusal = '(404) was received when fetching the script';
    expect(
      visit.problems.filter((problem) => !problem.includes(SW_FILE) && !problem.includes(refusal)),
    ).toEqual([]);
  } finally {
    await visit.context.close();
    await site.stop();
  }
});
