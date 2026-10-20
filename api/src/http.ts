/** CORS, JSON bodies and responses. */

export interface Env {
  DB: D1Database;
  /** The admin's login name (case-insensitive). Reserved: no signup can take it. */
  ADMIN_USERNAME?: string;
  /** base64url key derived from the admin password in the deploy runner; unset means no admin login. */
  ADMIN_KEY?: string;
  /** Comma-separated exact origins the site is served from. */
  ALLOWED_ORIGINS?: string;
  /** "1" only under `wrangler dev`: also allows http://localhost and http://127.0.0.1 on any port. */
  LOCAL_DEV?: string;
}

export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

/** Largest JSON body accepted. The biggest real one (five saved schools) is well under 1 KB. */
export const MAX_BODY = 4096;

const LOCAL_ORIGIN = /^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d{1,5})?$/;

export function allowedOrigin(env: Env, origin: string | null): string | null {
  if (origin === null) return null;
  const list = (env.ALLOWED_ORIGINS ?? '')
    .split(',')
    .map((o) => o.trim())
    .filter((o) => o.length > 0);
  if (list.includes(origin)) return origin;
  if (env.LOCAL_DEV === '1' && LOCAL_ORIGIN.test(origin)) return origin;
  return null;
}

export function corsHeaders(origin: string | null): Record<string, string> {
  if (origin === null) return {};
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Max-Age': '600',
    Vary: 'Origin',
  };
}

export function json(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      ...headers,
    },
  });
}

/** The request's JSON object body: JSON content type, at most MAX_BODY bytes, an object. */
export async function readBody(request: Request): Promise<Record<string, unknown>> {
  const type = request.headers.get('Content-Type') ?? '';
  if (!/^application\/json(?:\s*;|$)/i.test(type)) throw new HttpError(415, 'json_only');
  const declared = Number(request.headers.get('Content-Length') ?? '0');
  if (declared > MAX_BODY) throw new HttpError(413, 'too_large');
  const reader = request.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY) {
        await reader.cancel();
        throw new HttpError(413, 'too_large');
      }
      chunks.push(value);
    }
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, at);
    at += chunk.byteLength;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new HttpError(400, 'bad_json');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))
    throw new HttpError(400, 'bad_json');
  return parsed as Record<string, unknown>;
}

export function clientIp(request: Request): string {
  return request.headers.get('CF-Connecting-IP') ?? 'unknown';
}

/**
 * The network a client address belongs to: an IPv4 address's /24 or an IPv6
 * address's /64, written in one fixed form. An address it cannot read stands
 * for itself.
 */
export function networkOf(ip: string): string {
  const v4 = /^(?:::ffff:)?(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}$/i.exec(ip);
  if (v4) return `${v4[1]}.${v4[2]}.${v4[3]}.0/24`;
  if (!/^[0-9a-f:]+$/i.test(ip) || ip.split('::').length > 2) return ip;
  const [head = '', tail] = ip.split('::');
  const left = head === '' ? [] : head.split(':');
  const right = tail === undefined || tail === '' ? [] : tail.split(':');
  const fill = tail === undefined ? 0 : 8 - left.length - right.length;
  const groups = [...left, ...Array<string>(Math.max(fill, 0)).fill('0'), ...right];
  if (groups.length !== 8 || groups.some((g) => g.length === 0 || g.length > 4)) return ip;
  return `${groups
    .slice(0, 4)
    .map((g) => parseInt(g, 16).toString(16))
    .join(':')}::/64`;
}
