/** Runs the Worker in Miniflare (workerd) with a fresh local D1 database per test file. */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

export const ORIGIN = 'https://snowlightmap.com';
export const API = 'https://api.test';

/** A key the browser would send: base64url of 32 bytes. Tests do not need real PBKDF2 output. */
export function fakeKey(seed: string): string {
  const bytes = Buffer.alloc(32);
  Buffer.from(seed).copy(bytes);
  return bytes.toString('base64url');
}

export const ADMIN_KEY = fakeKey('admin-secret');

export interface Api {
  mf: Miniflare;
  /** The bundled Worker, for a test that restarts it with other bindings. */
  script: string;
  call(
    method: string,
    path: string,
    options?: {
      body?: unknown;
      token?: string;
      ip?: string;
      origin?: string | null;
      headers?: Record<string, string>;
    },
  ): Promise<{ status: number; body: any; headers: Headers }>;
  sql(query: string, ...params: unknown[]): Promise<any[]>;
  close(): Promise<void>;
}

export async function startApi(bindings: Record<string, string> = {}): Promise<Api> {
  const bundle = await build({
    entryPoints: [join(root, 'src/index.ts')],
    bundle: true,
    format: 'esm',
    target: 'es2022',
    write: false,
    platform: 'neutral',
  });
  // Miniflare 5 takes a new options shape; the v4 one converts directly.
  const mf = new Miniflare(
    convertV4MiniflareOptions({
      modules: true,
      script: bundle.outputFiles[0]!.text,
      compatibilityDate: '2026-08-01',
      d1Databases: ['DB'],
      bindings: {
        ADMIN_USERNAME: 'Olivia',
        ADMIN_KEY,
        ALLOWED_ORIGINS: `${ORIGIN},https://www.snowlightmap.com`,
        ...bindings,
      },
    }),
  );
  const db = await mf.getD1Database('DB');
  for (const file of readdirSync(join(root, 'migrations')).sort()) {
    const text = readFileSync(join(root, 'migrations', file), 'utf8').replace(/--[^\n]*/g, '');
    const statements = text
      .split(';')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    await db.batch(statements.map((s) => db.prepare(s)));
  }
  return {
    mf,
    script: bundle.outputFiles[0]!.text,
    async call(method, path, options = {}) {
      const headers: Record<string, string> = {
        'CF-Connecting-IP': options.ip ?? '203.0.113.1',
        ...options.headers,
      };
      if (options.origin !== null) headers.Origin = options.origin ?? ORIGIN;
      if (options.token !== undefined) headers.Authorization = `Bearer ${options.token}`;
      let body: string | undefined;
      if (options.body !== undefined) {
        body = JSON.stringify(options.body);
        headers['Content-Type'] ??= 'application/json';
      }
      const response = await mf.dispatchFetch(`${API}${path}`, { method, headers, body });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = text;
      }
      return {
        status: response.status,
        body: parsed,
        headers: response.headers as unknown as Headers,
      };
    },
    async sql(query, ...params) {
      const { results } = await db
        .prepare(query)
        .bind(...params)
        .all();
      return results;
    },
    close: () => mf.dispose(),
  };
}
