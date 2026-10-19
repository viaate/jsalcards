/**
 * What the service worker caches and how, in one place for both sides:
 * the build (vite.config.ts passes `pwaOptions()` to VitePWA and adds
 * `pwaHead()`) and the page (register.ts and data.ts read the same names).
 *
 * - The app shell (index.html, scripts, styles, the Latin fonts, the bundled
 *   US lines) is precached at install.
 * - Files under data/ that change during the day, live/ first among them, are
 *   served stale-while-revalidate: the last copy at once, then the network
 *   copy into the cache, and the page told when it differs.
 * - A build that reads live/closings.json from a live root of its own
 *   (liveRootOf, VITE_SNOWLIGHT_LIVE_ROOT) serves that one file network-first:
 *   the network's copy while it answers within LIVE_TIMEOUT_SECONDS, the last
 *   copy only when it does not, in the same cache as the data files.
 * - The school directory, the search index and finished storm replays change
 *   rarely; they are cache-first and expire after a week.
 * - A data file the page or its search worker reads before the first worker
 *   takes the page over goes into the cache its route uses as it is read
 *   (keep.ts), so the worker never downloads it again. The worker's limits
 *   cover only what it has cached or served itself, so the page drops the
 *   copies of hashed files its build no longer ships (data.ts dropOldData).
 * - OpenFreeMap tiles (zoom 7 and up) keep a small cache of recent tiles: only
 *   answers that are tiles (onlyTiles), and never for a request that asks to
 *   go past the cache. A cache an earlier build kept and this one does not is
 *   deleted as this build's worker takes over (RETIRED_CACHES).
 * - Files read in byte ranges (the school vector tiles, *.pmtiles) are never
 *   cached, and any request for part of a file goes to the network as it is:
 *   a cache holds whole files, and a whole file is the wrong answer to a
 *   range request.
 * - schools/edition.json, which names the deployed directory, is in no route:
 *   the page never reads it, and a reader that did must get the deployed file,
 *   never a copy a cache kept (NETWORK_ONLY_DATA).
 * - The US mask (geo/us-mask.<hash>.pmtiles) is a .pmtiles file too, but read
 *   whole, once, by the page, when someone heads for the streets
 *   (src/map/basemap/mask/feed.ts): not precached, so a visit that never
 *   leaves the national view never downloads it, and in no route, so it goes
 *   to the network (and the browser's cache) as it is.
 *
 * The manifest is a static file, public/manifest.webmanifest, written with the
 * icons by scripts/build-icons.mjs from src/copy.ts. Its URLs are relative to
 * where pwaHead() links it, <base>manifest.webmanifest, so one file serves any
 * base. Registration is the page's job (register.ts), after load, so the
 * build injects no script.
 *
 * This module imports nothing at run time, so Vite's config loader and the
 * page can both load it, and the page's bundle keeps only what it uses.
 */

import type { HtmlTagDescriptor, Plugin } from 'vite';
import type { VitePWAOptions } from 'vite-plugin-pwa';

export const SW_FILE = 'sw.js';
export const MANIFEST_FILE = 'manifest.webmanifest';
/** Where the pipeline's files are published, under the site base. */
export const DATA_DIR = 'data/';
/** The OpenFreeMap host (src/map/basemap/openfreemap.ts). */
export const TILE_ORIGIN = 'https://tiles.openfreemap.org';

/**
 * Where a live root keeps the closings file, as data/ does: PUBLISHED_PATHS.closings
 * (src/types/generated), which this module, importing nothing, cannot name (a test holds them equal).
 */
export const LIVE_CLOSINGS_PATH = 'live/closings.json';

/** Hosts a live root may name over plain http, in a build that allows it: this machine. */
const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(['localhost', '127.0.0.1', '[::1]']);

/**
 * The live root a build names (VITE_SNOWLIGHT_LIVE_ROOT), as an absolute URL
 * ending in a slash, or null when it names none or one that cannot serve the
 * page: anything but https, a path that is not a folder, or one with a query,
 * a fragment or credentials. Plain http on this machine only when `loopback`
 * (VITE_SNOWLIGHT_LIVE_LOOPBACK, which only the e2e's build sets).
 */
export function liveRootOf(value: string | null | undefined, loopback = false): string | null {
  if (value === null || value === undefined || value === '') return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const secure =
    url.protocol === 'https:' ||
    (loopback && url.protocol === 'http:' && LOOPBACK_HOSTS.has(url.hostname));
  const plain = url.search === '' && url.hash === '' && url.username === '' && url.password === '';
  return secure && plain && url.pathname.endsWith('/') ? url.href : null;
}

/** The build's variable naming the live root; unset or empty, the page reads its own data/. */
export const LIVE_ROOT_ENV = 'VITE_SNOWLIGHT_LIVE_ROOT';

/** The build's variable that, as "1", lets a live root be plain http on this machine (e2e only). */
export const LIVE_LOOPBACK_ENV = 'VITE_SNOWLIGHT_LIVE_LOOPBACK';

/**
 * The live root a build's variables name, checked (liveRootOf): null when
 * VITE_SNOWLIGHT_LIVE_ROOT is unset or empty. One set to anything liveRootOf
 * refuses throws, so a mistyped root fails the build rather than turning live
 * reads off without a word.
 */
export function checkedLiveRoot(env: Readonly<Record<string, unknown>> | undefined): string | null {
  const value = env?.[LIVE_ROOT_ENV];
  if (value === undefined || value === null || value === '') return null;
  const root =
    typeof value === 'string' ? liveRootOf(value, env?.[LIVE_LOOPBACK_ENV] === '1') : null;
  if (root === null) {
    throw new Error(
      `${LIVE_ROOT_ENV} must be an https URL of a folder, ending in "/", with no query, fragment or credentials; got ${JSON.stringify(value)}`,
    );
  }
  return root;
}

/** Runtime cache names. The precache is Workbox's own. */
export const CACHE_NAMES = Object.freeze({
  data: 'snowlight-data-v1',
  staticData: 'snowlight-static-data-v1',
  assets: 'snowlight-assets-v1',
  tileJson: 'snowlight-tilejson-v1',
  tiles: 'snowlight-tiles-v2',
});

const DAY_SECONDS = 86_400;

/**
 * Bounds on each runtime cache. The data cache keeps its last copies for as
 * long as it takes. The tile cache is for the last place looked at, offline:
 * 32 tiles is about one desktop screen at zoom 7 and up. OpenFreeMap tiles
 * over seven US cities averaged 146 KB decoded (112 tiles, zooms 7 to 14,
 * September 2026), so it holds about 5 MB; the HTTP cache serves revisits
 * online.
 */
export const CACHE_LIMITS = Object.freeze({
  data: { maxEntries: 64 },
  staticData: { maxEntries: 32, maxAgeSeconds: 7 * DAY_SECONDS },
  assets: { maxEntries: 32, maxAgeSeconds: 30 * DAY_SECONDS },
  tileJson: { maxEntries: 2, maxAgeSeconds: 7 * DAY_SECONDS },
  tiles: { maxEntries: 32, maxAgeSeconds: 7 * DAY_SECONDS },
});

/**
 * Caches earlier builds kept that this one does not use: deleted as this
 * build's worker takes over (retireCachesScript). snowlight-tiles-v1 kept any
 * 200 that was not text, so a network's block page sent as a tile could stay
 * in it for a week.
 */
export const RETIRED_CACHES: readonly string[] = Object.freeze(['snowlight-tiles-v1']);

/** The script the worker imports that deletes RETIRED_CACHES (pwaHead writes it). */
export const RETIRE_FILE = 'sw-retire.js';

/** The source of RETIRE_FILE: on the worker's activate, it deletes `names`. */
export function retireCachesScript(names: readonly string[] = RETIRED_CACHES): string {
  return `// Deletes the caches earlier builds kept that this one does not (src/pwa/config.ts).
self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all(${JSON.stringify(names)}.map((name) => caches.delete(name))));
});
`;
}

/** How long the TileJSON may take before its cached copy is used instead. */
export const TILEJSON_TIMEOUT_SECONDS = 4;

/** How long the live root's closings file may take before its cached copy is used instead. */
export const LIVE_TIMEOUT_SECONDS = 4;

/**
 * Precached files, as globs in the build output. Scripts and styles are
 * content-hashed; only the Latin font subsets are taken, the rest load on
 * demand. Source maps, icons, robots.txt and data/ stay out.
 */
export const PRECACHE_GLOBS: readonly string[] = Object.freeze([
  'index.html',
  'favicon.svg',
  MANIFEST_FILE,
  'assets/*.{js,css}',
  'assets/geist-*latin*.woff2',
  'geo/*.json',
]);

/** Paths under data/ served cache-first: the directory, the search index, finished replays. */
const STATIC_DATA = String.raw`(?:schools/|search(?:[-./]|$)|replays/(?!index\.json))`;

/**
 * Extensions of the files the page reads in byte ranges instead of whole:
 * schools/schools.pmtiles, tens of megabytes that PMTiles reads a few
 * kilobytes at a time with HTTP Range requests. No route caches them and a
 * first visit keeps none of them (keep.ts), so the browser always asks the
 * server for just the bytes it needs. A file read this way must be listed here.
 */
export const RANGE_SERVED_EXTENSIONS: readonly string[] = Object.freeze(['pmtiles']);

/** Matches a URL's path (and what follows it) when it names a range-served file. */
const RANGE_SERVED_PATH = String.raw`[^?#]*\.(?:${RANGE_SERVED_EXTENSIONS.join('|')})(?:[?#]|$)`;

/**
 * Files under data/ that no route serves, so the worker never answers for them
 * from a cache: schools/edition.json has a plain name and changes with each
 * deploy that changes the directory.
 */
const NETWORK_ONLY_DATA = String.raw`schools/edition\.json(?:[?#]|$)`;

/** Whether `url` (absolute, or a path) names a file read in byte ranges. */
export function isRangeServed(url: string): boolean {
  return new RegExp(`^${RANGE_SERVED_PATH}`).test(new URL(url, 'https://x.invalid/').pathname);
}

/** Escapes a string for use inside a RegExp. */
function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

/** A site base as Vite gives it ("/" or "/repo/"), with both slashes. */
export function normalizeBase(base: string): string {
  let path = base.trim();
  if (!path.startsWith('/')) path = `/${path}`;
  if (!path.endsWith('/')) path = `${path}/`;
  return path;
}

export interface RoutePatterns {
  /** The closings file at the build's live root, served network-first; null without a root. */
  readonly live: RegExp | null;
  /** Files under data/ served cache-first. */
  readonly staticData: RegExp;
  /** Every other file under data/ but range-served ones, served stale-while-revalidate. */
  readonly data: RegExp;
  /** Build assets not in the precache, such as other font subsets. */
  readonly assets: RegExp;
  readonly tileJson: RegExp;
  readonly tiles: RegExp;
  /** Navigations answered with the precached index.html (tested against path and query). */
  readonly navigation: RegExp;
}

/**
 * The routes for a site at `base`. Workbox tests a RegExp against the full
 * URL. The site's own routes are anchored to the path right after the host
 * and base, so "data/" deeper in a path never matches; the host itself is left
 * open because the site's domain is not known at build time, and the page
 * requests nothing under data/ or assets/ from any other host. The live route
 * names its file in full at `liveRoot`, a root liveRootOf gave (checked where
 * the build or the page reads its variable), and is tried before the others.
 */
export function routePatterns(base: string, liveRoot: string | null = null): RoutePatterns {
  const root = escapeRegExp(normalizeBase(base));
  const site = String.raw`^https?://[^/?#]+${root}`;
  // Under data/, but never a range-served or network-only file: those go to the network untouched.
  const data = `${site}${escapeRegExp(DATA_DIR)}(?!${RANGE_SERVED_PATH}|${NETWORK_ONLY_DATA})`;
  const tiles = escapeRegExp(TILE_ORIGIN);
  return {
    live:
      liveRoot === null || liveRoot === ''
        ? null
        : new RegExp(`^${escapeRegExp(`${liveRoot}${LIVE_CLOSINGS_PATH}`)}(?:[?#]|$)`),
    staticData: new RegExp(`${data}${STATIC_DATA}`),
    data: new RegExp(data),
    assets: new RegExp(`${site}assets/[^?#]+\\.(?:woff2|js|css)(?:[?#]|$)`),
    tileJson: new RegExp(`^${tiles}/planet(?:[?#]|$)`),
    tiles: new RegExp(`^${tiles}/`),
    navigation: new RegExp(`^${root}(?:index\\.html)?(?:\\?.*)?$`),
  };
}

/**
 * Whether a request asks for part of a file. The worker's first route: such a
 * request goes to the network as it is and its answer (a 206) is never stored.
 * Workbox writes this function into sw.js as source text, so it must stay
 * self-contained.
 */
export const isRangeRequest = ({ request }: { request: Request }): boolean =>
  request.headers.has('range');

/**
 * Keeps nothing but tiles in the tile cache: a 200 whose body is a vector
 * tile, empty or starting with its layers (field 3, length-delimited: 0x1a;
 * OpenFreeMap's tiles, as the browser unzips them, all do). An answer that
 * is not (a network's block page or challenge sent with a 200, whatever its
 * type) goes on to the map, which refuses it and asks again past the cache
 * (openfreemap.ts), but it is never kept, to be served for that tile from
 * then on. A request that asks to go past the cache (cache: 'reload') gets
 * the network's answer, whatever the cache holds. Workbox writes this plugin
 * into sw.js as source text, so it must stay self-contained.
 */
export const onlyTiles = {
  cacheWillUpdate: async ({ response }: { response: Response }): Promise<Response | null> => {
    if (response.status !== 200) return null;
    if (/^\s*text\//i.test(response.headers.get('content-type') ?? '')) return null;
    const bytes = new Uint8Array(await response.clone().arrayBuffer());
    return bytes.length === 0 || bytes[0] === 0x1a ? response : null;
  },
  cachedResponseWillBeUsed: ({
    request,
    cachedResponse,
  }: {
    request: Request;
    cachedResponse?: Response;
  }): Promise<Response | null> =>
    Promise.resolve(request.cache === 'reload' ? null : (cachedResponse ?? null)),
};

/** Finds the copy of a file a cache keeps; in the worker, whichever of its caches holds it. */
type Held = (request: Request) => Promise<Response | undefined>;

/**
 * The closings file at the build's live root, newer only, in the worker as in
 * the page: newer is a later generated_at, which, as a UtcInstant of fixed
 * form, compares as text, and a copy that is not a 200 with a generated_at is
 * no file at all.
 *
 * - cacheWillUpdate keeps a copy only when it is newer than the copy kept. An
 *   older copy (an edge or a worker that has not caught up) or an equal one
 *   never replaces the newer kept copy.
 * - handlerWillRespond gives the page the kept copy in place of an older
 *   answer. A page that has just opened holds no file to set an older one
 *   against: offline, the browser's own cache can answer with the last copy
 *   it fetched, which may be older than the one kept; and an edge behind
 *   answers with an older one too.
 *
 * The kept copy, and only it, can stand against nothing: when it is stamped
 * more than ten minutes past the device's clock (data/live.ts LIVE_AHEAD_MS)
 * and, as well, more than an hour past the answer's own stamp
 * (LIVE_AHEAD_OF_ANSWER_MS). Such a stamp says the publisher's clock was
 * wrong, so it never holds off what the network answers, across reloads.
 * Either test alone is not enough: on a device whose clock runs slow, every
 * sound kept copy is past the clock, and an edge behind answers with a copy
 * minutes older than the kept one; neither may replace the newer kept copy.
 * With no answer to set it by (an error), the clock alone decides. The
 * network's answer is never refused for its stamp: a device clock set back,
 * or one that runs slow, never keeps a newer file from the page.
 *
 * `held` finds the copy kept: by default, whichever cache of the worker holds
 * it; the page passes its own (keep.ts). Workbox writes this plugin into sw.js
 * as source text, so each function must stay self-contained, the stamp reader
 * in each included.
 */
export const keepNewerClosings = {
  cacheWillUpdate: async (
    { request, response }: { request: Request; response: Response },
    held: Held = (key) => (globalThis as unknown as { caches: { match: Held } }).caches.match(key),
  ): Promise<Response | null> => {
    const stampOf = async (copy: Response | undefined): Promise<string> => {
      try {
        const file =
          copy?.status === 200 ? (JSON.parse(await copy.clone().text()) as unknown) : null;
        const stamp = (file as { generated_at?: unknown }).generated_at;
        return typeof stamp === 'string' ? stamp : '';
      } catch {
        return '';
      }
    };
    // The kept copy's stamp, or '' when it stands against nothing: stamped more than ten minutes
    // past this device's clock (data/live.ts LIVE_AHEAD_MS) and, as well, more than an hour past
    // the answer's own (LIVE_AHEAD_OF_ANSWER_MS), or past the clock with no answer to set it by.
    const standing = (kept: string, answer: string): string => {
      const at = Date.parse(kept);
      return at <= Date.now() + 10 * 60_000 ||
        (answer !== '' && at <= Date.parse(answer) + 60 * 60_000)
        ? kept
        : '';
    };
    const stamp = await stampOf(response);
    if (stamp === '') return null;
    return stamp > standing(await stampOf(await held(request)), stamp) ? response : null;
  },
  handlerWillRespond: async (
    { request, response }: { request: Request; response: Response },
    held: Held = (key) => (globalThis as unknown as { caches: { match: Held } }).caches.match(key),
  ): Promise<Response> => {
    const stampOf = async (copy: Response | undefined): Promise<string> => {
      try {
        const file =
          copy?.status === 200 ? (JSON.parse(await copy.clone().text()) as unknown) : null;
        const stamp = (file as { generated_at?: unknown }).generated_at;
        return typeof stamp === 'string' ? stamp : '';
      } catch {
        return '';
      }
    };
    // The kept copy's stamp, or '' when it stands against nothing: stamped more than ten minutes
    // past this device's clock (data/live.ts LIVE_AHEAD_MS) and, as well, more than an hour past
    // the answer's own (LIVE_AHEAD_OF_ANSWER_MS), or past the clock with no answer to set it by.
    const standing = (kept: string, answer: string): string => {
      const at = Date.parse(kept);
      return at <= Date.now() + 10 * 60_000 ||
        (answer !== '' && at <= Date.parse(answer) + 60 * 60_000)
        ? kept
        : '';
    };
    const kept = await held(request);
    if (kept === undefined) return response;
    const answer = await stampOf(response);
    return standing(await stampOf(kept), answer) > answer ? kept : response;
  },
};

/** The routes the worker tries, in order, for a request that is not a navigation. */
export type RouteName = 'range' | Exclude<keyof RoutePatterns, 'navigation'>;

/**
 * Which route serves a GET for `url` on a site at `base` whose build reads
 * live/closings.json from `liveRoot` (a root liveRootOf gave; null for its
 * own data/), in the order
 * the worker tries them; `range` when the request carries a Range header.
 * Null means no route: the browser fetches it as if there were no worker.
 */
export function routeFor(
  url: string,
  base: string,
  init: { range?: boolean; liveRoot?: string | null } = {},
): RouteName | null {
  if (init.range === true) return 'range';
  const patterns = routePatterns(base, init.liveRoot ?? null);
  const order = ['live', 'staticData', 'data', 'assets', 'tileJson', 'tiles'] as const;
  return order.find((name) => patterns[name]?.test(url) === true) ?? null;
}

/** The message Workbox's broadcast-update plugin posts when a cached file changed. */
export interface CacheUpdatedMessage {
  readonly type: 'CACHE_UPDATED';
  readonly meta: 'workbox-broadcast-update';
  readonly payload: { readonly cacheName: string; readonly updatedURL: string };
}

export function isCacheUpdatedMessage(data: unknown): data is CacheUpdatedMessage {
  if (typeof data !== 'object' || data === null) return false;
  const { type, meta, payload } = data as Record<string, unknown>;
  if (type !== 'CACHE_UPDATED' || meta !== 'workbox-broadcast-update') return false;
  if (typeof payload !== 'object' || payload === null) return false;
  const { cacheName, updatedURL } = payload as Record<string, unknown>;
  return typeof cacheName === 'string' && typeof updatedURL === 'string';
}

/** What the page posts to a waiting worker to make it take over (generateSW listens for it). */
export const SKIP_WAITING_MESSAGE = Object.freeze({ type: 'SKIP_WAITING' });

/** The home-screen icon iOS reads from a <link>. */
export const APPLE_TOUCH_ICON = 'icons/apple-touch-icon.png';

type WorkboxOptions = NonNullable<VitePWAOptions['workbox']>;

/**
 * The generated worker's options for a site at `base`, whose build reads
 * live/closings.json from `liveRoot` when it names one (checkedLiveRoot).
 */
export function workboxOptions(base: string, liveRoot: string | null = null): WorkboxOptions {
  const patterns = routePatterns(base, liveRoot);
  // Network-first: the newest file whenever the network answers, never a broadcast. Only a
  // build with a live root has the route; one without builds the same worker as before.
  const live: NonNullable<WorkboxOptions['runtimeCaching']> =
    patterns.live === null
      ? []
      : [
          {
            urlPattern: patterns.live,
            handler: 'NetworkFirst',
            options: {
              cacheName: CACHE_NAMES.data,
              networkTimeoutSeconds: LIVE_TIMEOUT_SECONDS,
              expiration: { ...CACHE_LIMITS.data, purgeOnQuotaError: true },
              cacheableResponse: { statuses: [200] },
              plugins: [keepNewerClosings],
            },
          },
        ];
  return {
    globPatterns: [...PRECACHE_GLOBS],
    // No sw.js.map: vite-plugin-pwa would otherwise follow build.sourcemap and ship one.
    sourcemap: false,
    inlineWorkboxRuntime: true,
    disableDevLogs: true,
    // Deletes the caches earlier builds kept (RETIRED_CACHES), as this worker takes over.
    importScripts: [RETIRE_FILE],
    cleanupOutdatedCaches: true,
    // The first worker takes the open page at once, so this visit's data is cached for offline.
    clientsClaim: true,
    // Updates wait; the page decides when to switch (register.ts).
    skipWaiting: false,
    navigateFallback: 'index.html',
    navigateFallbackAllowlist: [patterns.navigation],
    runtimeCaching: [
      {
        // First, so no cache ever answers part of a file with the whole of it.
        urlPattern: isRangeRequest,
        handler: 'NetworkOnly',
      },
      ...live,
      {
        urlPattern: patterns.staticData,
        handler: 'CacheFirst',
        options: {
          cacheName: CACHE_NAMES.staticData,
          expiration: { ...CACHE_LIMITS.staticData, purgeOnQuotaError: true },
          cacheableResponse: { statuses: [200] },
        },
      },
      {
        urlPattern: patterns.data,
        handler: 'StaleWhileRevalidate',
        options: {
          cacheName: CACHE_NAMES.data,
          expiration: { ...CACHE_LIMITS.data, purgeOnQuotaError: true },
          cacheableResponse: { statuses: [200] },
          // Tells the page when the network copy differs from the one it was just given.
          broadcastUpdate: { options: {} },
        },
      },
      {
        urlPattern: patterns.assets,
        handler: 'CacheFirst',
        options: {
          cacheName: CACHE_NAMES.assets,
          expiration: { ...CACHE_LIMITS.assets, purgeOnQuotaError: true },
          cacheableResponse: { statuses: [200] },
        },
      },
      {
        urlPattern: patterns.tileJson,
        handler: 'NetworkFirst',
        options: {
          cacheName: CACHE_NAMES.tileJson,
          networkTimeoutSeconds: TILEJSON_TIMEOUT_SECONDS,
          expiration: { ...CACHE_LIMITS.tileJson, purgeOnQuotaError: true },
          cacheableResponse: { statuses: [200] },
        },
      },
      {
        urlPattern: patterns.tiles,
        handler: 'CacheFirst',
        options: {
          cacheName: CACHE_NAMES.tiles,
          expiration: { ...CACHE_LIMITS.tiles, purgeOnQuotaError: true },
          cacheableResponse: { statuses: [200] },
          plugins: [onlyTiles],
        },
      },
    ],
  };
}

/**
 * Adds to index.html, under the site base: the manifest link, the home-screen
 * icon iOS reads (it ignores manifest icons), and a black iOS status bar for
 * the installed app; and writes the script the worker imports to delete
 * retired caches (RETIRE_FILE).
 */
export function pwaHead(): Plugin {
  let base = '/';
  return {
    name: 'snowlight:pwa-head',
    configResolved(config) {
      base = normalizeBase(config.base);
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: RETIRE_FILE, source: retireCachesScript() });
    },
    transformIndexHtml(): HtmlTagDescriptor[] {
      return [
        {
          tag: 'link',
          attrs: { rel: 'manifest', href: `${base}${MANIFEST_FILE}` },
          injectTo: 'head',
        },
        {
          tag: 'link',
          attrs: { rel: 'apple-touch-icon', href: `${base}${APPLE_TOUCH_ICON}` },
          injectTo: 'head',
        },
        {
          tag: 'meta',
          attrs: { name: 'apple-mobile-web-app-status-bar-style', content: 'black' },
          injectTo: 'head',
        },
      ];
    },
  };
}

/** The VitePWA options: a generated worker, the static manifest, no injected registration. */
export function pwaOptions(): Partial<VitePWAOptions> {
  return {
    strategies: 'generateSW',
    filename: SW_FILE,
    injectRegister: false,
    registerType: 'prompt',
    // public/manifest.webmanifest is the manifest; pwaHead() links it.
    manifest: false,
    includeAssets: [],
    integration: {
      // The routes depend on the base and the live root, only known once Vite has resolved its
      // config.
      configureOptions(viteConfig, options) {
        const env = viteConfig.env as Readonly<Record<string, unknown>> | undefined;
        // A root set but refused fails the build here.
        options.workbox = workboxOptions(viteConfig.base, checkedLiveRoot(env));
      },
    },
  };
}
