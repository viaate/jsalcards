/**
 * Snowlight accounts API (Cloudflare Worker, D1). Routes are all under /v1.
 *
 * CPU budget: the free plan allows 10 ms of CPU per request. Every route here
 * is a few D1 queries and at most a couple of SHA-256s over short inputs; the
 * slow password work (PBKDF2, 600,000 iterations) happens in the browser, so
 * the Worker never sees a password. Keep it that way: no slow hashing and no
 * parsing of large files in this Worker.
 */

import * as account from './account';
import * as admin from './admin';
import { HttpError, allowedOrigin, corsHeaders, json, type Env } from './http';

export type { Env } from './http';

type Handler = (env: Env, request: Request, now: number, param: string) => Promise<Response>;

const routes: [method: string, pattern: RegExp, handler: Handler][] = [
  ['POST', /^\/v1\/signup$/, account.signup],
  ['POST', /^\/v1\/login$/, account.login],
  ['POST', /^\/v1\/logout$/, account.logout],
  ['GET', /^\/v1\/me$/, account.me],
  ['PATCH', /^\/v1\/me$/, account.updateMe],
  ['DELETE', /^\/v1\/me$/, account.deleteMe],
  ['PUT', /^\/v1\/me\/schools$/, account.putSchools],
  ['GET', /^\/v1\/admin\/summary$/, admin.summary],
  ['GET', /^\/v1\/admin\/users$/, admin.users],
  ['POST', /^\/v1\/admin\/users\/([^/]+)\/reset-password$/, admin.resetPassword],
  [
    'POST',
    /^\/v1\/admin\/users\/([^/]+)\/disable$/,
    (e, r, n, id) => admin.setDisabled(e, r, n, id, true),
  ],
  [
    'POST',
    /^\/v1\/admin\/users\/([^/]+)\/enable$/,
    (e, r, n, id) => admin.setDisabled(e, r, n, id, false),
  ],
  ['DELETE', /^\/v1\/admin\/users\/([^/]+)$/, admin.deleteUser],
  ['GET', /^\/v1\/admin\/overrides$/, admin.listOverrides],
  ['PUT', /^\/v1\/admin\/overrides$/, admin.putOverride],
  ['DELETE', /^\/v1\/admin\/overrides\/([^/]+)$/, admin.deleteOverride],
  ['GET', /^\/v1\/admin\/audit$/, admin.auditLog],
];

export async function handle(request: Request, env: Env, now = Date.now()): Promise<Response> {
  const url = new URL(request.url);
  const originHeader = request.headers.get('Origin');
  const origin = allowedOrigin(env, originHeader);
  const cors = corsHeaders(origin);
  // A browser on another site gets no CORS grant; a state-changing call from one is refused outright.
  if (originHeader !== null && origin === null && request.method !== 'GET')
    return json(403, { error: 'origin' });
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

  try {
    if (request.method === 'GET' && url.pathname === '/v1/health')
      return json(200, { ok: true, api: 1 }, cors);
    if (request.method === 'GET' && url.pathname === '/v1/overrides')
      return await admin.publicOverrides(env, now, cors);
    for (const [method, pattern, handler] of routes) {
      const match = pattern.exec(url.pathname);
      if (match === null) continue;
      if (request.method !== method) continue;
      let param = '';
      try {
        param = match[1] === undefined ? '' : decodeURIComponent(match[1]);
      } catch {
        throw new HttpError(404, 'not_found');
      }
      const response = await handler(env, request, now, param);
      for (const [name, value] of Object.entries(cors)) response.headers.set(name, value);
      return response;
    }
    return json(404, { error: 'not_found' }, cors);
  } catch (error) {
    if (error instanceof HttpError) return json(error.status, { error: error.code }, cors);
    console.error('unhandled', error instanceof Error ? error.message : 'error');
    return json(500, { error: 'server' }, cors);
  }
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handle(request, env);
  },
} satisfies ExportedHandler<Env>;
