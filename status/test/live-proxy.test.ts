import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, test } from 'node:test';
import { onRequest } from '../page/functions/api/live/v1/[[path]].ts';
import {
  LIVE_EDGE_TTL_SECONDS,
  LIVE_UPSTREAM,
  LIVE_UPSTREAM_TIMEOUT_MS,
  keptFor,
  serveLive,
} from '../shared/live-proxy.ts';
import { root } from './harness.ts';

const SITE = 'https://snowlightmap.com';
const HERE = 'https://status.snowlightmap.com/api/live/v1/';
/** SYNTHETIC: a made-up closings file. */
const FILE = '{"schema_version":1,"generated_at":"2026-01-12T12:42:00Z","days":[]}';

interface Asked {
  url: string;
  init: RequestInit & { cf?: unknown };
}

/** A made-up live host: answers each read with `answer`, and records what it was asked. */
function host(answer: () => Response | Promise<Response>): {
  asked: Asked[];
  fetch: (url: string, init: RequestInit & { cf?: unknown }) => Promise<Response>;
} {
  const asked: Asked[] = [];
  return {
    asked,
    fetch: (url, init) => {
      asked.push({ url, init });
      return Promise.resolve(answer());
    },
  };
}

const ok = (headers: Record<string, string> = {}): Response =>
  new Response(FILE, {
    status: 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      etag: '"6afdc836-384"',
      'last-modified': 'Mon, 12 Jan 2026 12:42:05 GMT',
      'cache-control': 'max-age=600',
      'set-cookie': 'a=b',
      'access-control-allow-origin': '*',
      ...headers,
    },
  });

const ask = (path: string, init: RequestInit = {}): Request =>
  new Request(`${HERE}${path}`, {
    ...init,
    headers: { origin: SITE, ...init.headers },
  });

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test('an allowlisted file is read from the live host and passed on with its headers', async () => {
  for (const path of [
    'live/closings.json',
    'predictions/latest.json',
    'live/season.json',
    'live/days/2026-01-12.json',
  ]) {
    const live = host(() => ok());
    const response = await serveLive(ask(path), live.fetch);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), FILE);
    assert.equal(live.asked.length, 1);
    assert.equal(live.asked[0]!.url, `${LIVE_UPSTREAM}${path}`);
    assert.equal(live.asked[0]!.init.method, 'GET');
    assert.equal(response.headers.get('content-type'), 'application/json; charset=utf-8');
    assert.equal(response.headers.get('etag'), '"6afdc836-384"');
    assert.equal(response.headers.get('last-modified'), 'Mon, 12 Jan 2026 12:42:05 GMT');
    assert.equal(response.headers.get('access-control-allow-origin'), SITE);
    assert.equal(response.headers.get('vary'), 'Origin');
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    assert.equal(response.headers.get('set-cookie'), null);
  }
});

test('the Pages Function answers with the live host it reads through fetch', async () => {
  const live = host(() => ok());
  globalThis.fetch = live.fetch as typeof fetch;
  type Context = Parameters<typeof onRequest>[0];
  const response = await onRequest({
    request: ask('live/closings.json'),
  } as unknown as Context);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), FILE);
  assert.equal(live.asked[0]!.url, `${LIVE_UPSTREAM}live/closings.json`);
});

test('any other path is a 404 that never reaches the live host', async () => {
  for (const path of [
    '',
    'live/',
    'live/closings.json/',
    'live/closings.jsonx',
    'live/alerts.json',
    'live/days/2026-1-12.json',
    'live/days/2026-01-12.json.bak',
    '%2e%2e/secret',
    'live%2fclosings.json',
    'predictions/hold.json',
    'v1/live/closings.json',
  ]) {
    const live = host(() => ok());
    const response = await serveLive(ask(path), live.fetch);
    assert.equal(response.status, 404, path);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(await response.text(), '');
    assert.equal(live.asked.length, 0, path);
  }
  // Under another prefix too.
  const live = host(() => ok());
  const response = await serveLive(
    new Request('https://status.snowlightmap.com/api/live/v2/live/closings.json'),
    live.fetch,
  );
  assert.equal(response.status, 404);
  assert.equal(live.asked.length, 0);
});

test('a query is not sent on', async () => {
  const live = host(() => ok());
  await serveLive(ask('live/closings.json?watch=1&x=2'), live.fetch);
  assert.equal(live.asked[0]!.url, `${LIVE_UPSTREAM}live/closings.json`);
});

test('HEAD is answered without a body, and every other method is refused', async () => {
  const live = host(() => ok());
  const head = await serveLive(ask('live/closings.json', { method: 'HEAD' }), live.fetch);
  assert.equal(head.status, 200);
  assert.equal(live.asked[0]!.init.method, 'HEAD');
  assert.equal(head.headers.get('etag'), '"6afdc836-384"');
  assert.equal(await head.text(), '');
  for (const method of ['POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH']) {
    const refused = await serveLive(ask('live/closings.json', { method }), live.fetch);
    assert.equal(refused.status, 405, method);
    assert.equal(refused.headers.get('allow'), 'GET, HEAD');
    assert.equal(refused.headers.get('cache-control'), 'no-store');
  }
  assert.equal(live.asked.length, 1);
});

test('only the conditional headers are sent on, and a 304 passes with its ETag and no body', async () => {
  const live = host(
    () =>
      new Response(null, {
        status: 304,
        headers: { etag: '"6afdc836-384"', 'cache-control': 'max-age=600' },
      }),
  );
  const response = await serveLive(
    ask('live/closings.json', {
      headers: {
        'if-none-match': '"6afdc836-384"',
        'if-modified-since': 'Mon, 12 Jan 2026 12:42:05 GMT',
        cookie: 'session=secret',
        authorization: 'Bearer secret',
        'user-agent': 'a phone',
      },
    }),
    live.fetch,
  );
  assert.deepEqual(live.asked[0]!.init.headers, {
    'if-none-match': '"6afdc836-384"',
    'if-modified-since': 'Mon, 12 Jan 2026 12:42:05 GMT',
  });
  assert.equal(response.status, 304);
  assert.equal(response.headers.get('etag'), '"6afdc836-384"');
  assert.equal(response.headers.get('cache-control'), `public, max-age=60`);
  assert.equal(await response.text(), '');
});

test('the edge and the browser keep a file for at most 60 seconds', async () => {
  assert.equal(LIVE_EDGE_TTL_SECONDS, 60);
  for (const [own, kept] of [
    ['max-age=600', 60],
    ['public, max-age=15, stale-while-revalidate=15', 15],
    ['max-age=0', 0],
    [null, 60],
    ['no-cache', 60],
    ['max-age=86400000', 60],
  ] as const) {
    assert.equal(keptFor(own), kept, String(own));
    const live = host(() => ok(own === null ? {} : { 'cache-control': own }));
    if (own === null) {
      live.fetch = (url, init) => {
        live.asked.push({ url, init });
        const answer = ok();
        answer.headers.delete('cache-control');
        return Promise.resolve(answer);
      };
    }
    const response = await serveLive(ask('live/closings.json'), live.fetch);
    assert.equal(response.headers.get('cache-control'), `public, max-age=${String(kept)}`);
  }
  // At the edge: a success for at most a minute, anything else never.
  const live = host(() => ok());
  await serveLive(ask('live/closings.json'), live.fetch);
  assert.deepEqual(live.asked[0]!.init.cf, {
    cacheTtlByStatus: { '200-299': 60, '300-599': -1 },
  });
});

test('a live host that fails, moves the file or does not answer is a 502 nothing keeps', async () => {
  const answers: (() => Response | Promise<Response>)[] = [
    () =>
      new Response('oops', {
        status: 500,
        headers: { 'cache-control': 'max-age=600' },
      }),
    () => new Response('', { status: 503 }),
    () =>
      new Response(null, {
        status: 301,
        headers: { location: 'https://elsewhere.example/' },
      }),
    () => Promise.reject(new TypeError('connection closed')),
    () => Promise.reject(new DOMException('The operation timed out.', 'TimeoutError')),
  ];
  for (const answer of answers) {
    const live = host(answer);
    const response = await serveLive(ask('live/closings.json'), live.fetch);
    assert.equal(response.status, 502);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(response.headers.get('access-control-allow-origin'), SITE);
    assert.equal(response.headers.get('location'), null);
    assert.equal(await response.text(), '');
  }
  // The read is given up after LIVE_UPSTREAM_TIMEOUT_MS, and never follows a move.
  const live = host(() => ok());
  await serveLive(ask('live/closings.json'), live.fetch);
  assert.equal(live.asked[0]!.init.signal instanceof AbortSignal, true);
  assert.equal(live.asked[0]!.init.redirect, 'manual');
  assert.equal(LIVE_UPSTREAM_TIMEOUT_MS, 5000);
});

test('an answer that is not the file is passed on as its status alone, with no body, that nothing keeps', async () => {
  for (const status of [400, 403, 404, 410, 429]) {
    const live = host(
      () =>
        new Response('<!DOCTYPE html><html><body>The live host page</body></html>', {
          status,
          headers: {
            'content-type': 'text/html; charset=utf-8',
            'cache-control': 'max-age=600',
            etag: '"page"',
          },
        }),
    );
    const response = await serveLive(ask('live/days/2026-11-20.json'), live.fetch);
    assert.equal(response.status, status);
    assert.equal(response.headers.get('cache-control'), 'no-store', String(status));
    assert.equal(response.headers.get('content-type'), null, String(status));
    assert.equal(response.headers.get('etag'), null, String(status));
    assert.equal(response.headers.get('access-control-allow-origin'), SITE);
    assert.equal(await response.text(), '', String(status));
  }
});

test('only the site lets a browser read the answers, and another site is refused before the live host is asked', async () => {
  for (const origin of [SITE, 'https://www.snowlightmap.com']) {
    const live = host(() => ok());
    const response = await serveLive(
      new Request(`${HERE}live/closings.json`, { headers: { origin } }),
      live.fetch,
    );
    assert.equal(response.status, 200, origin);
    assert.equal(response.headers.get('access-control-allow-origin'), origin);
    assert.equal(live.asked.length, 1, origin);
  }
  for (const origin of [
    'https://evil.example',
    'https://snowlightmap.com.evil.example',
    'http://snowlightmap.com',
    'null',
  ]) {
    const live = host(() => ok());
    const response = await serveLive(
      new Request(`${HERE}live/closings.json`, { headers: { origin } }),
      live.fetch,
    );
    assert.equal(response.status, 403, origin);
    assert.equal(response.headers.get('access-control-allow-origin'), null, origin);
    assert.equal(response.headers.get('cache-control'), 'no-store', origin);
    assert.equal(await response.text(), '', origin);
    assert.equal(live.asked.length, 0, origin);
  }
  // A read with no origin (a curl, the address bar) is answered, and no browser page may read it.
  const live = host(() => ok());
  const bare = await serveLive(new Request(`${HERE}live/closings.json`), live.fetch);
  assert.equal(bare.status, 200);
  assert.equal(bare.headers.get('access-control-allow-origin'), null);
});

test('the Function is under /api/, the one route the page runs Functions for', async () => {
  const routes = JSON.parse(readFileSync(join(root, 'page/public/_routes.json'), 'utf8')) as {
    include: string[];
  };
  assert.deepEqual(routes.include, ['/api/*']);
  assert.equal(new URL(HERE).pathname.startsWith('/api/'), true);
  // The old place, outside /api/, is never served.
  const live = host(() => ok());
  const response = await serveLive(
    new Request('https://status.snowlightmap.com/live/v1/live/closings.json'),
    live.fetch,
  );
  assert.equal(response.status, 404);
  assert.equal(live.asked.length, 0);
});
