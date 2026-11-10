/**
 * Serves the built status page on 127.0.0.1:4190 for a look by eye and for scripts/shots.cjs.
 * `/api/status` answers a made-up state (test/fixtures/made-up.ts), the one last set by
 * `GET /__set?state=history|ok|first|stale|unreachable|worst|launch`. Nothing here is deployed.
 */

import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from '../page/build.mjs';
import { MADE, answerOf } from '../test/fixtures/made-up.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'page/dist');
const PORT = 4190;
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
};

await build(dist);

/** The headers `_headers` gives every path, so a look here runs under the real policy. */
const headers = readFileSync(join(dist, '_headers'), 'utf8')
  .split('\n')
  .filter((line) => line.startsWith('  '))
  .map((line) => line.trim())
  .map((line) => [line.slice(0, line.indexOf(':')), line.slice(line.indexOf(':') + 1).trim()]);

let state = 'history';
const cache = new Map();

function answer() {
  const tick = Math.floor(Date.now() / 300000);
  const key = `${state} ${tick}`;
  if (!cache.has(key)) {
    cache.clear();
    cache.set(key, answerOf(state, tick * 300 + 130));
  }
  const made = cache.get(key);
  if (made === null) return null;
  // The server's clock moves on between ticks, as the real one does.
  return { served: Math.floor(Date.now() / 1000), summary: made.summary };
}

createServer((request, response) => {
  const url = new URL(request.url ?? '/', `http://127.0.0.1:${PORT}`);
  for (const [name, value] of headers) response.setHeader(name, value);
  if (url.pathname === '/__set') {
    const wanted = url.searchParams.get('state') ?? '';
    if (!MADE.includes(wanted)) {
      response.writeHead(400).end('unknown state\n');
      return;
    }
    state = wanted;
    response.writeHead(200, { 'content-type': 'text/plain' }).end(`${state}\n`);
    return;
  }
  if (url.pathname === '/api/status') {
    const made = answer();
    if (made === null) {
      response
        .writeHead(503, { 'content-type': TYPES['.json'], 'cache-control': 'no-store' })
        .end('{"error":"store"}');
      return;
    }
    response
      .writeHead(200, { 'content-type': TYPES['.json'], 'cache-control': 'no-store' })
      .end(JSON.stringify(made));
    return;
  }
  const path = normalize(url.pathname === '/' ? '/index.html' : url.pathname);
  try {
    const body = readFileSync(join(dist, path));
    response
      .writeHead(200, { 'content-type': TYPES[extname(path)] ?? 'application/octet-stream' })
      .end(body);
  } catch {
    response.writeHead(404, { 'content-type': 'text/plain' }).end('not found\n');
  }
}).listen(PORT, '127.0.0.1', () => {
  console.log(`status preview on http://127.0.0.1:${PORT}/ (state: ${state})`);
});
