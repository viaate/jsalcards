/**
 * The installable app: manifest, icons, service worker, offline and caching.
 *
 * The spec builds the site into a temporary folder twice, at the root of a
 * domain ("/") and on a GitHub Pages project subpath, and serves each build
 * with the headers GitHub Pages sends (ETag, Last-Modified, max-age=600).
 * Two things are added to those copies only, never to the build:
 *
 * - a harness script inlined into index.html that does what the app will do
 *   once the integration wires it in: call the real registerServiceWorker()
 *   from src/pwa after load, fetch live/closings.json the way a live poller
 *   should (cache: 'no-cache'), and compute the update line from the file's
 *   generated_at with src/state's updateLine();
 * - synthetic data files, built below and named SYNTHETIC_*. They hold no
 *   schools, only the envelope and a fixed generated_at, or (for the school
 *   tile file) a byte pattern, and exist only in the test server's memory
 *   while the tests run.
 *
 * The server honours HTTP Range as GitHub Pages does, and logs whether each
 * request asked for a range, so the tests can check that the school tile file
 * is only ever read in ranges, before and after the worker takes over.
 *
 * Nothing here names a build chunk: what the shell is comes from the build
 * itself (the precache list in sw.js and the files the build wrote).
 *
 * Runs once, under the desktop project. WebGL is SwiftShader here; nothing
 * below depends on frame rates.
 */
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium, expect, test } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';
import { build } from 'vite';

import { copy, format } from '../src/copy';
import { CACHE_NAMES, MANIFEST_FILE, SW_FILE } from '../src/pwa/config';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const ZONE = 'America/Chicago';
/** A domain of its own. */
const ROOT_BASE = '/';
/** Where GitHub Pages serves a project site: /<repo>/. */
const PROJECT_BASE = '/jsalcards/';
const CLOSINGS = 'data/live/closings.json';
const DIRECTORY = 'data/schools/meta.json';
/** The school vector tiles, which PMTiles reads in byte ranges (pipeline registry). */
const TILES = 'data/schools/schools.pmtiles';
/** The first read PMTiles makes of an archive's header: 127 bytes, bytes=0-126. */
const HEADER_BYTES = 127;

// Synthetic data: envelopes with no schools, for these tests only. ---------------------

const SYNTHETIC_GENERATED_AT = '2026-01-12T12:42:00Z';
const SYNTHETIC_GENERATED_AT_LATER = '2026-01-12T12:57:00Z';
const SYNTHETIC_DIRECTORY_STAMP = { generated_on: '2026-01-01', schools: 0, districts: 0 };

function syntheticClosings(generatedAt: string): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: generatedAt,
    directory: SYNTHETIC_DIRECTORY_STAMP,
    schools: [],
  });
}

/** A stand-in for the school tile file: a byte pattern the size of a small archive. */
const SYNTHETIC_TILES = Buffer.from(
  Array.from({ length: 3_000_000 }, (_, index) => (index * 31 + 7) & 0xff),
);

function syntheticDirectory(generatedOn: string): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: generatedOn,
    count: 0,
    ids: [],
    names: [],
    districts: { ids: [], names: [] },
    school_years: { public: '2025-2026', private: '2023-2024' },
  });
}

// The harness: what the app does once src/pwa and src/state are wired in. ------------

/** The app passes nothing and gets Vite's base; the harness is built on its own, so it is told. */
function harness(base: string): string {
  return `
import { FetchSource } from '${WEB}node_modules/pmtiles/dist/esm/index.js';
import { onDataUpdate, registerServiceWorker } from '${WEB}src/pwa/index.ts';
import { updateLine } from '${WEB}src/state/freshness.ts';

const e2e = { updates: [], line: null, generatedAt: null, handle: null };
window.__e2e = e2e;
onDataUpdate((url) => e2e.updates.push(url));

// The school tiles, read the way the map reads them: PMTiles' own FetchSource.
const tilesUrl = new URL(${JSON.stringify(`${base}${TILES}`)}, location.href).href;
const tiles = new FetchSource(tilesUrl);
e2e.readTiles = async (offset, length) => {
  try {
    const { data } = await tiles.getBytes(offset, length);
    return { length: data.byteLength, head: [...new Uint8Array(data, 0, 8)] };
  } catch (error) {
    return { error: String(error) };
  }
};
e2e.rangeFetch = async (url, range, cache) => {
  try {
    const response = await fetch(url, { headers: { range }, cache });
    const body = await response.arrayBuffer();
    return {
      status: response.status,
      length: body.byteLength,
      contentRange: response.headers.get('content-range'),
      head: [...new Uint8Array(body, 0, Math.min(8, body.byteLength))],
    };
  } catch (error) {
    return { error: String(error) };
  }
};
// The first read, before any worker exists; it is in the page's resource timing from then on.
e2e.firstTiles = e2e.readTiles(0, ${String(HEADER_BYTES)}).then((result) => ({
  ...result,
  controlled: navigator.serviceWorker.controller !== null,
}));

async function loadClosings() {
  const response = await fetch(${JSON.stringify(`${base}${CLOSINGS}`)}, { cache: 'no-cache' });
  const file = await response.json();
  e2e.generatedAt = file.generated_at;
  e2e.line = updateLine({
    generatedAt: file.generated_at,
    online: navigator.onLine,
    liveWithinMs: 20 * 60 * 1000,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    now: new Date(),
  });
}
e2e.loadClosings = loadClosings;
void loadClosings();
void registerServiceWorker({ enabled: true, base: ${JSON.stringify(base)} }).then((handle) => {
  e2e.handle = handle;
});
`;
}

/** A read of the tile file through PMTiles, or why it failed. */
interface TileRead {
  length?: number;
  head?: number[];
  error?: string;
  controlled?: boolean;
}

/** A fetch with a Range header, as the page saw its answer. */
interface RangeRead {
  status?: number;
  length?: number;
  contentRange?: string | null;
  head?: number[];
  error?: string;
}

interface Harness {
  updates: string[];
  line: string | null;
  generatedAt: string | null;
  handle: { warmed: Promise<number> } | null;
  firstTiles: Promise<TileRead>;
  loadClosings(): Promise<void>;
  readTiles(offset: number, length: number): Promise<TileRead>;
  rangeFetch(url: string, range: string, cache?: RequestCache): Promise<RangeRead>;
}

declare global {
  interface Window {
    __e2e?: Harness;
  }
}

// A static host that behaves like GitHub Pages. --------------------------------------

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
};

/** One request the server answered: its path and the Range header it carried, if any. */
interface SiteRequest {
  path: string;
  range: string | null;
  status: number;
}

/**
 * The byte span a Range header asks of a file `size` bytes long: one range,
 * as PMTiles sends. Null means serve the whole file (no header, or one this
 * server does not split, such as several ranges); 'unsatisfiable' is a 416.
 */
function byteRange(
  header: string | undefined,
  size: number,
): { start: number; end: number } | 'unsatisfiable' | null {
  const match = header === undefined ? null : /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (match === null) return null;
  const [, first = '', last = ''] = match;
  if (first === '' && last === '') return null;
  let start: number;
  let end: number;
  if (first === '') {
    // The last N bytes.
    start = Math.max(0, size - Number(last));
    end = size - 1;
  } else {
    start = Number(first);
    end = last === '' ? size - 1 : Math.min(Number(last), size - 1);
  }
  if (start >= size || start > end) return 'unsatisfiable';
  return { start, end };
}

class Site {
  readonly log: SiteRequest[] = [];
  private readonly overlay = new Map<string, { body: Buffer; modified: Date }>();
  private server: Server | undefined;
  origin = '';

  /** Serves the build in `root` under `base`; everything outside `base` is a 404. */
  constructor(
    private readonly root: string,
    readonly base: string,
  ) {}

  /** The site's URL for a path under its base. */
  url(file = ''): string {
    return `${this.origin}${this.base}${file}`;
  }

  /** Every path the server was asked for, in order. */
  get requests(): string[] {
    return this.log.map((request) => request.path);
  }

  /** Serves `body` at `file` (a path under the base) from now on, as a deploy would. */
  put(file: string, body: string | Buffer, modified = new Date()): void {
    this.overlay.set(`${this.base}${file}`, { body: Buffer.from(body), modified });
  }

  /** The requests the server answered for `file`, a path under the base. */
  requestsFor(file: string): SiteRequest[] {
    return this.log.filter((request) => request.path === `${this.base}${file}`);
  }

  /** How many times the server was asked for `file`, a path under the base. */
  hits(file: string): number {
    return this.requests.filter((request) => request === `${this.base}${file}`).length;
  }

  async start(): Promise<void> {
    const server = createServer((request, response) => {
      this.handle(request, response);
    });
    this.server = server;
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    this.origin = `http://127.0.0.1:${String((server.address() as AddressInfo).port)}`;
  }

  /** Takes the site off the network: every connection is refused from now on. */
  async stop(): Promise<void> {
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

  private handle(request: IncomingMessage, response: ServerResponse): void {
    const urlPath = decodeURIComponent(new URL(request.url ?? '/', 'http://x').pathname);
    const logged: SiteRequest = { path: urlPath, range: request.headers.range ?? null, status: 0 };
    this.log.push(logged);
    response.on('finish', () => {
      logged.status = response.statusCode;
    });
    let file = this.overlay.get(urlPath);
    if (file === undefined) {
      // GitHub Pages serves a folder's index.html for the folder.
      const inBase = urlPath.slice(this.base.length);
      const onDisk = path.join(
        this.root,
        inBase === '' || inBase.endsWith('/') ? `${inBase}index.html` : inBase,
      );
      if (!urlPath.startsWith(this.base) || !onDisk.startsWith(this.root)) {
        response.writeHead(404, { 'Content-Type': 'text/html' }).end('404');
        return;
      }
      try {
        const stat = statSync(onDisk);
        if (!stat.isFile()) throw new Error('not a file');
        file = { body: readFileSync(onDisk), modified: stat.mtime };
      } catch {
        response.writeHead(404, { 'Content-Type': 'text/html' }).end('404');
        return;
      }
    }
    const etag = `"${createHash('sha1').update(file.body).digest('hex').slice(0, 16)}"`;
    const headers = {
      'Content-Type': TYPES[path.extname(urlPath) || '.html'] ?? 'application/octet-stream',
      'Cache-Control': 'max-age=600',
      'Accept-Ranges': 'bytes',
      ETag: etag,
      'Last-Modified': file.modified.toUTCString(),
    };
    if (request.headers['if-none-match'] === etag) {
      response.writeHead(304, headers).end();
      return;
    }
    const size = file.body.length;
    const range = byteRange(request.headers.range, size);
    if (range === 'unsatisfiable') {
      response.writeHead(416, { ...headers, 'Content-Range': `bytes */${String(size)}` }).end();
      return;
    }
    if (range !== null) {
      const { start, end } = range;
      response
        .writeHead(206, {
          ...headers,
          'Content-Range': `bytes ${String(start)}-${String(end)}/${String(size)}`,
          'Content-Length': end - start + 1,
        })
        .end(file.body.subarray(start, end + 1));
      return;
    }
    response.writeHead(200, { ...headers, 'Content-Length': size }).end(file.body);
  }
}

// What the build says the shell is. ---------------------------------------------------

/** Every file the build wrote, as paths relative to its folder. */
function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
    )
    .sort();
}

/**
 * The precache list the build wrote into sw.js: Workbox's manifest entries,
 * `{url: "...", revision: ...}`, as paths relative to the base. Read from the
 * worker itself, so it is what browsers will install, whatever the chunks are
 * called.
 */
function precacheList(siteRoot: string): string[] {
  const worker = readFileSync(path.join(siteRoot, SW_FILE), 'utf8');
  const entry = /\{\s*"?url"?\s*:\s*"([^"]+)"\s*,\s*"?revision"?\s*:\s*(?:"[\da-f]+"|null)\s*\}/g;
  return [...worker.matchAll(entry)].map((match) => match[1] ?? '').sort();
}

/**
 * Whether a file the build wrote belongs to the app shell, judged by what it
 * is: the page, its icon and manifest, every script and style (the MapLibre
 * chunks and its worker among them), the Latin font subsets and the bundled
 * US lines. Source maps, app icons, other font subsets and data are not.
 */
function isShellFile(file: string): boolean {
  if (file === 'index.html' || file === 'favicon.svg' || file === MANIFEST_FILE) return true;
  if (/^assets\/[^/]+\.(?:js|css)$/.test(file)) return true;
  if (/^assets\/[^/]+\.woff2$/.test(file)) return /-latin(?:-ext)?-/.test(file);
  return /^geo\/[^/]+\.json$/.test(file);
}

/** Paths under `base` that index.html points at: scripts, styles, fonts, icons, the manifest. */
function pageReferences(siteRoot: string, base: string): string[] {
  const html = readFileSync(path.join(siteRoot, 'index.html'), 'utf8');
  const urls = [...html.matchAll(/\b(?:src|href)="([^"]+)"|\burl\(([^)]+)\)/g)].map(
    (match) => match[1] ?? match[2] ?? '',
  );
  return [
    ...new Set(urls.filter((url) => url.startsWith(base)).map((url) => url.slice(base.length))),
  ].sort();
}

// Setup ------------------------------------------------------------------------------

let root = '';
/** The build for each base, harness included. */
const builds = new Map<string, string>();

function siteRootFor(base: string): string {
  const siteRoot = builds.get(base);
  if (siteRoot === undefined) throw new Error(`no build for ${base}`);
  return siteRoot;
}

async function buildSite(base: string): Promise<void> {
  const folder = path.join(root, base === ROOT_BASE ? 'root' : base.replaceAll('/', ''));
  const siteRoot = path.join(folder, 'site');
  await build({
    root: WEB,
    base,
    logLevel: 'warn',
    build: { outDir: siteRoot, emptyOutDir: true },
  });
  const harnessEntry = path.join(folder, 'harness.js');
  writeFileSync(harnessEntry, harness(base));
  const harnessOut = path.join(folder, 'harness');
  await build({
    configFile: false,
    root: folder,
    logLevel: 'warn',
    build: {
      outDir: harnessOut,
      emptyOutDir: true,
      minify: false,
      lib: { entry: harnessEntry, formats: ['iife'], name: 'SnowlightE2E', fileName: () => 'h.js' },
    },
  });
  const index = path.join(siteRoot, 'index.html');
  const script = readFileSync(path.join(harnessOut, 'h.js'), 'utf8').replaceAll(
    '</script',
    '<\\/script',
  );
  writeFileSync(
    index,
    readFileSync(index, 'utf8').replace('</body>', `<script>${script}</script></body>`),
  );
  builds.set(base, siteRoot);
}

test.describe.configure({ mode: 'default' });

test.beforeAll(async () => {
  test.setTimeout(240_000);
  if (test.info().project.name !== 'desktop') return;
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-pwa-e2e-'));
  // One after the other: both builds write through the same Vite cache.
  await buildSite(ROOT_BASE);
  await buildSite(PROJECT_BASE);
});

test.afterAll(() => {
  if (root !== '') rmSync(root, { recursive: true, force: true });
});

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets up its own site; runs once.');
});

async function openSite(
  context: BrowserContext,
  base = ROOT_BASE,
): Promise<{ site: Site; page: Page }> {
  const site = new Site(siteRootFor(base), base);
  site.put(CLOSINGS, syntheticClosings(SYNTHETIC_GENERATED_AT), new Date('2026-01-12T12:42:05Z'));
  site.put(DIRECTORY, syntheticDirectory('2026-01-01'), new Date('2026-01-01T00:00:00Z'));
  site.put(TILES, SYNTHETIC_TILES, new Date('2026-01-01T00:00:00Z'));
  await site.start();
  const page = await context.newPage();
  await page.goto(site.url());
  return { site, page };
}

/** Waits until the worker controls the page and live/closings.json is in its cache. */
async function waitForOfflineReady(page: Page, site: Site): Promise<void> {
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, undefined, {
    timeout: 30_000,
  });
  await page.waitForFunction(
    async ([cacheName, url]) => (await (await caches.open(cacheName)).match(url)) !== undefined,
    [CACHE_NAMES.data, site.url(CLOSINGS)] as const,
    { timeout: 30_000 },
  );
}

async function fetchJson(page: Page, url: string): Promise<Record<string, unknown>> {
  return page.evaluate(
    async (target) =>
      (await (await fetch(target, { cache: 'no-cache' })).json()) as Record<string, unknown>,
    url,
  );
}

/** The paths, relative to the base, of everything in the worker's precache. */
async function precached(page: Page, base: string): Promise<string[]> {
  const paths = await page.evaluate(async () => {
    const names = (await caches.keys()).filter((name) => name.includes('precache'));
    const urls: string[] = [];
    for (const name of names) {
      for (const request of await (await caches.open(name)).keys()) {
        urls.push(new URL(request.url).pathname);
      }
    }
    return urls;
  });
  return paths.map((url) => (url.startsWith(base) ? url.slice(base.length) : url)).sort();
}

/** Reloads with the site gone and the browser offline, and checks the shell and the update line. */
async function expectOfflineShell(page: Page, site: Site, context: BrowserContext): Promise<void> {
  await site.stop();
  await context.setOffline(true);
  await page.reload();
  await expect(page).toHaveTitle(copy.appName);
  await expect(page.locator('main.stage')).toBeVisible();
  await expect(page.locator('h1.wordmark')).toHaveText(copy.appName);
  await expect(page.locator('input.search-input')).toBeVisible();
  await expect(page.locator('svg.still, canvas.maplibregl-canvas').first()).toBeAttached();

  await page.waitForFunction(() => (window.__e2e?.line ?? null) !== null);
  const shown = await page.evaluate(() => ({
    line: window.__e2e?.line ?? null,
    generatedAt: window.__e2e?.generatedAt ?? null,
  }));
  const now = new Date();
  expect(shown.generatedAt).toBe(SYNTHETIC_GENERATED_AT);
  expect(shown.line).toBe(format.offline(new Date(SYNTHETIC_GENERATED_AT), ZONE, now));
  const generatedTime = format.time(new Date(SYNTHETIC_GENERATED_AT), ZONE);
  if (format.time(now, ZONE) !== generatedTime) {
    expect(shown.line).not.toContain(format.time(now, ZONE));
  }
}

// Tests ------------------------------------------------------------------------------

/**
 * Only full Chromium evaluates installability (the headless shell always
 * answers "no errors"), and only outside incognito, which every
 * browser.newContext() is. So these tests launch their own persistent profile.
 */
async function installableContext(): Promise<{
  context: BrowserContext;
  close: () => Promise<void>;
}> {
  const profile = mkdtempSync(path.join(tmpdir(), 'snowlight-pwa-profile-'));
  const context = await chromium.launchPersistentContext(profile, {
    channel: 'chromium',
    timezoneId: ZONE,
  });
  return {
    context,
    close: async () => {
      await context.close();
      rmSync(profile, { recursive: true, force: true });
    },
  };
}

interface AppManifestResult {
  url: string;
  errors: { message: string; critical: number }[];
  data?: string;
  manifest?: { id?: string; startUrl?: string; scope?: string };
}

/** Checks everything Chrome looks at before it offers to install the app at `site`. */
async function expectInstallable(context: BrowserContext, page: Page, site: Site): Promise<void> {
  await expect(
    page.locator(`link[rel="manifest"][href="${site.base}${MANIFEST_FILE}"]`),
  ).toHaveCount(1);
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveCount(1);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
  expect(
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return {
        script: navigator.serviceWorker.controller?.scriptURL ?? null,
        scope: registration?.scope ?? null,
      };
    }),
  ).toEqual({ script: site.url(SW_FILE), scope: site.url() });

  const cdp = await context.newCDPSession(page);
  const result = (await cdp.send('Page.getAppManifest')) as AppManifestResult;
  expect(result.url).toBe(site.url(MANIFEST_FILE));
  expect(result.errors).toEqual([]);
  const parsed = JSON.parse(result.data ?? '{}') as Record<string, unknown>;
  expect(parsed).toMatchObject({
    name: copy.manifest.name,
    short_name: copy.manifest.shortName,
    display: 'standalone',
    theme_color: '#000000',
    background_color: '#000000',
  });
  // The app opens at the site base and keeps to it, and its id is that URL.
  expect(result.manifest).toMatchObject({ startUrl: site.url(), scope: site.url() });
  const { appId } = (await cdp.send('Page.getAppId')) as { appId?: string };
  expect(appId).toBe(site.url());

  const { installabilityErrors } = (await cdp.send('Page.getInstallabilityErrors')) as {
    installabilityErrors: { errorId: string }[];
  };
  expect(installabilityErrors).toEqual([]);

  for (const icon of parsed.icons as { src: string; type: string }[]) {
    const response = await page.request.get(new URL(icon.src, result.url).href);
    expect([icon.src, response.status(), response.headers()['content-type']]).toEqual([
      icon.src,
      200,
      icon.type,
    ]);
  }
}

test("meets Chrome's install criteria: manifest, icons, a worker in control", async () => {
  const { context, close } = await installableContext();
  const { site, page } = await openSite(context);
  try {
    await expectInstallable(context, page, site);
  } finally {
    await close();
    await site.stop();
  }
});

test('on a project subpath it installs, keeps to the subpath and works offline', async () => {
  const { context, close } = await installableContext();
  const { site, page } = await openSite(context, PROJECT_BASE);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  try {
    await expectInstallable(context, page, site);
    // Nothing is requested outside the subpath: the host's root may be another site.
    expect(site.requests.filter((request) => !request.startsWith(PROJECT_BASE))).toEqual([]);

    await waitForOfflineReady(page, site);
    await expectOfflineShell(page, site, context);
    await page.goto(site.url('?school=010000500870&at=33.52,-86.81,9'));
    await expect(page.locator('input.search-input')).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    await close();
    await site.stop();
  }
});

test('offline, a second visit gets the shell and the last data with its own time', async ({
  browser,
}) => {
  const context = await browser.newContext({ timezoneId: ZONE });
  const { site, page } = await openSite(context);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  try {
    // The first visit fetched the data before the worker existed; it was cached when the worker took over.
    await waitForOfflineReady(page, site);
    await expectOfflineShell(page, site, context);

    // The map code came from the precache too: MapLibre starts with no network.
    await expect(page.locator('canvas.maplibregl-canvas')).toBeAttached({ timeout: 30_000 });

    // A share link opens offline as well.
    await page.goto(site.url('?school=010000500870&at=33.52,-86.81,9'));
    await expect(page).toHaveTitle(copy.appName);
    await expect(page.locator('input.search-input')).toBeVisible();
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});

test('live data: the last copy at once, the new one in the background, and word of it', async ({
  browser,
}) => {
  const context = await browser.newContext();
  const { site, page } = await openSite(context);
  try {
    await waitForOfflineReady(page, site);
    site.put(CLOSINGS, syntheticClosings(SYNTHETIC_GENERATED_AT_LATER));

    // Stale first: the cached copy answers while the worker revalidates.
    expect((await fetchJson(page, site.url(CLOSINGS))).generated_at).toBe(SYNTHETIC_GENERATED_AT);
    await page.waitForFunction(
      (url) => window.__e2e?.updates.includes(url) === true,
      site.url(CLOSINGS),
    );
    expect((await fetchJson(page, site.url(CLOSINGS))).generated_at).toBe(
      SYNTHETIC_GENERATED_AT_LATER,
    );
  } finally {
    await context.close();
    await site.stop();
  }
});

test('the school directory is cache-first until it is evicted', async ({ browser }) => {
  const context = await browser.newContext();
  const { site, page } = await openSite(context);
  try {
    await waitForOfflineReady(page, site);
    expect((await fetchJson(page, site.url(DIRECTORY))).generated_on).toBe('2026-01-01');
    const before = site.hits(DIRECTORY);
    site.put(DIRECTORY, syntheticDirectory('2026-09-01'));
    expect((await fetchJson(page, site.url(DIRECTORY))).generated_on).toBe('2026-01-01');
    expect(site.hits(DIRECTORY)).toBe(before);

    // What evictStaticData() does when a live file names a newer directory.
    await page.evaluate(async (name) => {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) await cache.delete(request);
    }, CACHE_NAMES.staticData);
    expect((await fetchJson(page, site.url(DIRECTORY))).generated_on).toBe('2026-09-01');
  } finally {
    await context.close();
    await site.stop();
  }
});

for (const base of [ROOT_BASE, PROJECT_BASE]) {
  test(`the precache is the shell the build listed, and nothing else (base ${base})`, async ({
    browser,
  }) => {
    const siteRoot = siteRootFor(base);
    const listed = precacheList(siteRoot);
    const written = filesIn(siteRoot);

    // The build listed exactly the shell it wrote: every script and style
    // (so every MapLibre chunk and its worker, whatever they are called), the
    // Latin fonts and the US lines; no maps, data, icons or other subsets.
    expect(listed.length).toBeGreaterThan(0);
    expect(listed).toEqual(written.filter(isShellFile));
    expect(listed).toEqual(expect.arrayContaining(['index.html', 'favicon.svg', MANIFEST_FILE]));
    expect(listed.some((file) => file.startsWith('geo/'))).toBe(true);
    for (const file of listed) {
      expect(file).not.toMatch(/\.map$|^data\/|^icons\/|cyrillic|vietnamese|symbols/);
    }
    // Everything the page's HTML points at is in it, but for the home-screen
    // icon, which iOS fetches only while adding the app.
    const referenced = pageReferences(siteRoot, base).filter((file) => !file.startsWith('icons/'));
    expect(referenced.length).toBeGreaterThan(0);
    expect(referenced.filter((file) => !listed.includes(file))).toEqual([]);

    const context = await browser.newContext();
    const { site, page } = await openSite(context, base);
    try {
      await waitForOfflineReady(page, site);
      // The worker installed exactly what the build listed.
      expect(await precached(page, base)).toEqual(listed);

      // Every script, style, font and line file the page loaded once the map
      // was up is in the precache, so the same page can start offline.
      await expect(page.locator('canvas.maplibregl-canvas')).toBeAttached({ timeout: 30_000 });
      const loaded = await page.evaluate((prefix) => {
        const files = performance
          .getEntriesByType('resource')
          .map((entry) => new URL(entry.name))
          .filter((url) => url.origin === location.origin && url.pathname.startsWith(prefix))
          .map((url) => url.pathname.slice(prefix.length))
          .filter((file) => /^(?:assets|geo)\//.test(file));
        return [...new Set(files)].sort();
      }, base);
      expect(loaded.some((file) => file.endsWith('.js'))).toBe(true);
      expect(loaded.filter((file) => !listed.includes(file))).toEqual([]);

      // Hashed files the page already loaded come from the HTTP cache, not a second download.
      const twice = listed
        .filter((file) => file.startsWith('assets/'))
        .filter((file) => site.hits(file) > 1);
      expect(twice).toEqual([]);
    } finally {
      await context.close();
      await site.stop();
    }
  });
}

/** Every URL in every cache the worker keeps, precache included. */
async function cachedUrls(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const urls: string[] = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) urls.push(request.url);
    }
    return urls;
  });
}

for (const base of [ROOT_BASE, PROJECT_BASE]) {
  test(`the school tiles are read in ranges, before and after the worker takes over (base ${base})`, async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const { site, page } = await openSite(context, base);
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    const head = [...SYNTHETIC_TILES.subarray(0, 8)];
    const tilesUrl = site.url(TILES);
    try {
      // The first read, before any worker: the 127 header bytes, as a 206.
      expect(await page.evaluate(() => window.__e2e?.firstTiles)).toEqual({
        length: HEADER_BYTES,
        head,
        controlled: false,
      });
      expect(site.requestsFor(TILES)).toEqual([
        { path: `${base}${TILES}`, range: `bytes=0-${String(HEADER_BYTES - 1)}`, status: 206 },
      ]);

      // The worker takes over and caches what the page loaded before it.
      await waitForOfflineReady(page, site);
      await page.waitForFunction(() => (window.__e2e?.handle ?? null) !== null);
      const warmed = await page.evaluate(() => window.__e2e?.handle?.warmed);
      expect(warmed).toBeGreaterThan(0);

      // The same read, now with the worker in control, as PMTiles makes it.
      expect(await page.evaluate((n) => window.__e2e?.readTiles(0, n), HEADER_BYTES)).toEqual({
        length: HEADER_BYTES,
        head,
      });
      // The same bytes again, past the HTTP cache, so the server answers it through the worker.
      expect(
        await page.evaluate(
          ([url, n]) => window.__e2e?.rangeFetch(url, `bytes=0-${String(n - 1)}`, 'no-store'),
          [tilesUrl, HEADER_BYTES] as const,
        ),
      ).toEqual({
        status: 206,
        length: HEADER_BYTES,
        contentRange: `bytes 0-${String(HEADER_BYTES - 1)}/${String(SYNTHETIC_TILES.length)}`,
        head,
      });
      // A range read for the first time, deep in the file, as a tile lookup is.
      const offset = 1_234_567;
      expect(
        await page.evaluate(([o]) => window.__e2e?.readTiles(o, 16_384), [offset] as const),
      ).toEqual({
        length: 16_384,
        head: [...SYNTHETIC_TILES.subarray(offset, offset + 8)],
      });

      // The server never sent the whole file: every request for it asked for a range.
      const tileRequests = site.requestsFor(TILES);
      expect(tileRequests.length).toBeGreaterThanOrEqual(3);
      expect(tileRequests.filter((request) => request.range === null)).toEqual([]);
      expect(tileRequests.filter((request) => request.status !== 206)).toEqual([]);
      // And no cache holds it.
      expect((await cachedUrls(page)).filter((url) => url.includes('.pmtiles'))).toEqual([]);

      // A range of a file the worker holds whole is a range too, never the whole cached file.
      expect((await fetchJson(page, site.url(DIRECTORY))).generated_on).toBe('2026-01-01');
      await page.waitForFunction(
        async ([cacheName, url]) => (await (await caches.open(cacheName)).match(url)) !== undefined,
        [CACHE_NAMES.staticData, site.url(DIRECTORY)] as const,
      );
      const directory = Buffer.from(syntheticDirectory('2026-01-01'));
      expect(
        await page.evaluate(([url]) => window.__e2e?.rangeFetch(url, 'bytes=0-9'), [
          site.url(DIRECTORY),
        ] as const),
      ).toEqual({
        status: 206,
        length: 10,
        contentRange: `bytes 0-9/${String(directory.length)}`,
        head: [...directory.subarray(0, 8)],
      });
      expect(pageErrors).toEqual([]);
    } finally {
      await context.close();
      await site.stop();
    }
  });
}
