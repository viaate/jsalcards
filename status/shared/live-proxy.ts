/**
 * The live files, read through this site: GET or HEAD /api/live/v1/<path>
 * answers with the file the live host publishes at LIVE_UPSTREAM<path>,
 * fetched here, for a page on a network that blocks the live host by name (a
 * school's web filter that closes every connection to github.io) but lets
 * snowlightmap.com and its subdomains through. The map asks here only when its
 * read of the live host itself fails the way a filter makes it fail
 * (web/src/data/live-roots.ts), so a visitor on an open network costs this
 * nothing.
 *
 * It is read-only and serves only the files the map reads from the live root
 * (LIVE_PATHS); any other path is a 404 that never reaches the live host. A
 * browser on any origin but the site's is refused (403) before the live host
 * is asked. It passes on the live host's status, type, ETag and Last-Modified,
 * and sends a conditional request on as it came, so an unchanged file is a 304
 * with no body. A copy is kept at the edge for at most LIVE_EDGE_TTL_SECONDS,
 * and the browser is told to keep none it has not asked about again
 * (BROWSER_CACHE_CONTROL), so the two never add up: the map must never be
 * given an old file as the current one. A live host that fails, moves the file, or does not
 * answer within LIVE_UPSTREAM_TIMEOUT_MS, is a 502 that nothing keeps; any
 * other answer that is not a file (a 404 for one not published yet) is passed
 * on as its status alone, with no body, kept by nothing too. It reads nothing
 * else of the request, logs nothing and sets no cookie.
 *
 * Every request here, refused or not, counts against the Cloudflare account's
 * Workers limit on the free plan: 100,000 a day, shared with the status page's
 * own Function, the accounts API and the timer. Nothing is billed; what stops
 * at the limit, and the projected count, are in docs/status.md (What it costs).
 */

/** Where the live host publishes the files (.github/workflows/preview.yml VITE_SNOWLIGHT_LIVE_ROOT). */
export const LIVE_UPSTREAM = 'https://viaate.github.io/snowlight-live/v1/';

/** The prefix this site serves them under. */
export const LIVE_PREFIX = '/api/live/v1/';

/**
 * The files the map reads from the live root (web/src/data/files.ts withLiveRoot): the
 * closings, the chances and the season counts, and a day's closings by its date.
 */
export const LIVE_PATHS =
  /^(?:live\/closings\.json|predictions\/latest\.json|live\/season\.json|live\/days\/\d{4}-\d{2}-\d{2}\.json)$/;

/** The longest an answer is kept at the edge: a minute. */
export const LIVE_EDGE_TTL_SECONDS = 60;

/**
 * What the browser is told of a file: ask again before each use (with its ETag, so an unchanged
 * file is a 304). The edge's copy carries no Age to the browser, so a browser that kept it for
 * a while too could hold a file for longer than the edge's minute.
 */
export const BROWSER_CACHE_CONTROL = 'public, max-age=0, must-revalidate';

/** How long the live host may take to answer before the read is a 502. */
export const LIVE_UPSTREAM_TIMEOUT_MS = 5000;

/** The site's origins, the only ones a browser lets read the answers. */
export const SITE_ORIGINS: ReadonlySet<string> = new Set([
  'https://snowlightmap.com',
  'https://www.snowlightmap.com',
]);

/** The request headers sent on: only those that make a read conditional. */
const CONDITIONAL = ['if-none-match', 'if-modified-since'] as const;

/** The answer headers passed on from the live host. */
const PASSED = ['content-type', 'etag', 'last-modified'] as const;

type Fetcher = (input: string, init: RequestInit & { cf?: unknown }) => Promise<Response>;

function originHeaders(request: Request): Record<string, string> {
  const origin = request.headers.get('origin');
  return {
    vary: 'Origin',
    ...(origin !== null && SITE_ORIGINS.has(origin)
      ? { 'access-control-allow-origin': origin }
      : {}),
  };
}

function refusal(request: Request, status: number, extra: Record<string, string> = {}): Response {
  return new Response(null, {
    status,
    headers: {
      ...originHeaders(request),
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      ...extra,
    },
  });
}

/** The answer to `request`, with `fetcher` reading the live host. */
export async function serveLive(request: Request, fetcher: Fetcher = fetch): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return refusal(request, 405, { allow: 'GET, HEAD' });
  }
  const origin = request.headers.get('origin');
  // Another site's page: it is not this site's to read.
  if (origin !== null && !SITE_ORIGINS.has(origin)) return refusal(request, 403);
  const { pathname } = new URL(request.url);
  const path = pathname.startsWith(LIVE_PREFIX) ? pathname.slice(LIVE_PREFIX.length) : '';
  if (!LIVE_PATHS.test(path)) return refusal(request, 404);
  const ask: Record<string, string> = {};
  for (const name of CONDITIONAL) {
    const value = request.headers.get(name);
    if (value !== null) ask[name] = value;
  }
  let upstream: Response;
  try {
    upstream = await fetcher(`${LIVE_UPSTREAM}${path}`, {
      method: request.method,
      headers: ask,
      redirect: 'manual',
      signal: AbortSignal.timeout(LIVE_UPSTREAM_TIMEOUT_MS),
      // Cloudflare's edge keeps a success for at most a minute and never keeps anything else.
      cf: {
        cacheTtlByStatus: { '200-299': LIVE_EDGE_TTL_SECONDS, '300-599': -1 },
      },
    });
  } catch {
    return refusal(request, 502);
  }
  // A failure, or a move to somewhere else, is no file.
  if (
    upstream.status >= 500 ||
    (upstream.status >= 300 && upstream.status !== 304 && upstream.status < 400)
  ) {
    await upstream.body?.cancel();
    return refusal(request, 502);
  }
  // Any other answer that is not the file (a 404 for one not published yet): its status alone.
  // The live host's own page is never served from this origin.
  if (upstream.status !== 200 && upstream.status !== 304) {
    await upstream.body?.cancel();
    return refusal(request, upstream.status);
  }
  const headers: Record<string, string> = {
    ...originHeaders(request),
    'x-content-type-options': 'nosniff',
  };
  for (const name of PASSED) {
    const value = upstream.headers.get(name);
    if (value !== null) headers[name] = value;
  }
  headers['cache-control'] = BROWSER_CACHE_CONTROL;
  const empty = request.method === 'HEAD' || upstream.status === 304;
  if (empty) await upstream.body?.cancel();
  return new Response(empty ? null : upstream.body, {
    status: upstream.status,
    headers,
  });
}
