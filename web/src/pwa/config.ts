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
 * - The school directory, the search index and finished storm replays change
 *   rarely; they are cache-first and expire after a week.
 * - OpenFreeMap tiles (zoom 7 and up) keep a small cache of recent tiles.
 * - Files read in byte ranges (the school vector tiles, *.pmtiles) are never
 *   cached, and any request for part of a file goes to the network as it is:
 *   a cache holds whole files, and a whole file is the wrong answer to a
 *   range request.
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

/** Runtime cache names. The precache is Workbox's own. */
export const CACHE_NAMES = Object.freeze({
  data: 'snowlight-data-v1',
  staticData: 'snowlight-static-data-v1',
  assets: 'snowlight-assets-v1',
  tileJson: 'snowlight-tilejson-v1',
  tiles: 'snowlight-tiles-v1',
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

/** How long the TileJSON may take before its cached copy is used instead. */
export const TILEJSON_TIMEOUT_SECONDS = 4;

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
 * kilobytes at a time with HTTP Range requests. No route caches them and the
 * first-visit warm-up skips them, so the browser always asks the server for
 * just the bytes it needs. A file read this way must be listed here.
 */
export const RANGE_SERVED_EXTENSIONS: readonly string[] = Object.freeze(['pmtiles']);

/** Matches a URL's path (and what follows it) when it names a range-served file. */
const RANGE_SERVED_PATH = String.raw`[^?#]*\.(?:${RANGE_SERVED_EXTENSIONS.join('|')})(?:[?#]|$)`;

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
 * requests nothing under data/ or assets/ from any other host.
 */
export function routePatterns(base: string): RoutePatterns {
  const root = escapeRegExp(normalizeBase(base));
  const site = String.raw`^https?://[^/?#]+${root}`;
  // Under data/, but never a range-served file: those go to the network untouched.
  const data = `${site}${escapeRegExp(DATA_DIR)}(?!${RANGE_SERVED_PATH})`;
  const tiles = escapeRegExp(TILE_ORIGIN);
  return {
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

/** The routes the worker tries, in order, for a request that is not a navigation. */
export type RouteName = 'range' | Exclude<keyof RoutePatterns, 'navigation'>;

/**
 * Which route serves a GET for `url` on a site at `base`, in the order the
 * worker tries them; `range` when the request carries a Range header. Null
 * means no route: the browser fetches it as if there were no worker.
 */
export function routeFor(
  url: string,
  base: string,
  init: { range?: boolean } = {},
): RouteName | null {
  if (init.range === true) return 'range';
  const patterns = routePatterns(base);
  const order = ['staticData', 'data', 'assets', 'tileJson', 'tiles'] as const;
  return order.find((name) => patterns[name].test(url)) ?? null;
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

/** The generated worker's options for a site at `base`. */
export function workboxOptions(base: string): WorkboxOptions {
  const patterns = routePatterns(base);
  return {
    globPatterns: [...PRECACHE_GLOBS],
    // No sw.js.map: vite-plugin-pwa would otherwise follow build.sourcemap and ship one.
    sourcemap: false,
    inlineWorkboxRuntime: true,
    disableDevLogs: true,
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
        },
      },
    ],
  };
}

/**
 * Adds to index.html, under the site base: the manifest link, the home-screen
 * icon iOS reads (it ignores manifest icons), and a black iOS status bar for
 * the installed app.
 */
export function pwaHead(): Plugin {
  let base = '/';
  return {
    name: 'snowlight:pwa-head',
    configResolved(config) {
      base = normalizeBase(config.base);
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
      // The routes depend on the base, which is only known once Vite has resolved its config.
      configureOptions(viteConfig, options) {
        options.workbox = workboxOptions(viteConfig.base);
      },
    },
  };
}
