/** What the tests share: a local D1 database in Miniflare, and a made-up network with a clock. */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
import type { Ask, Deps, Got } from '../prober/src/probe.ts';

export const root = join(dirname(fileURLToPath(import.meta.url)), '..');

export interface Store {
  db: D1Database;
  sql<T = Record<string, unknown>>(query: string, ...params: unknown[]): Promise<T[]>;
  close(): Promise<void>;
}

/** A fresh D1 database with the checker's migrations applied. */
export async function startStore(): Promise<Store> {
  // Miniflare 5 takes a new options shape; the v4 one converts directly.
  const mf = new Miniflare(
    convertV4MiniflareOptions({
      modules: true,
      script: 'export default { fetch() { return new Response("") } }',
      compatibilityDate: '2026-08-01',
      d1Databases: ['DB'],
    }),
  );
  const db = (await mf.getD1Database('DB')) as unknown as D1Database;
  const folder = join(root, 'prober/migrations');
  for (const file of readdirSync(folder).sort()) {
    const text = readFileSync(join(folder, file), 'utf8').replace(/--[^\n]*/g, '');
    const statements = text
      .split(';')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    await db.batch(statements.map((s) => db.prepare(s)));
  }
  return {
    db,
    async sql<T>(query: string, ...params: unknown[]): Promise<T[]> {
      return (
        await db
          .prepare(query)
          .bind(...params)
          .all<T>()
      ).results;
    },
    close: () => mf.dispose(),
  };
}

/** What a made-up host does with one request. */
export type Step =
  | { status: number; body?: string | Uint8Array; headers?: Record<string, string>; ms?: number }
  | 'none'
  | 'timeout';

export interface Call {
  url: string;
  init: Ask;
}

/** A made-up network: each URL answers its steps in turn (the last one again after that). */
export class Net implements Deps {
  calls: Call[] = [];
  waits: number[] = [];
  /** How many chunks of a body were read, by URL. */
  read = new Map<string, number>();
  clock: number;
  private plan = new Map<string, Step[]>();

  constructor(clock = 1_800_000_000_000) {
    this.clock = clock;
  }

  on(url: string, ...steps: Step[]): this {
    this.plan.set(url, steps);
    return this;
  }

  now(): number {
    return this.clock;
  }

  async wait(ms: number): Promise<void> {
    this.waits.push(ms);
    this.clock += ms;
  }

  async fetch(url: string, init: Ask): Promise<Got> {
    this.calls.push({ url, init });
    const steps = this.plan.get(url);
    if (steps === undefined) throw new Error(`no plan for ${url}`);
    const step = steps.length > 1 ? steps.shift()! : steps[0]!;
    if (step === 'none') throw new TypeError('fetch failed');
    if (step === 'timeout') {
      this.clock += 8000;
      throw new DOMException('The operation timed out.', 'TimeoutError');
    }
    this.clock += step.ms ?? 100;
    const bytes =
      step.body === undefined
        ? null
        : typeof step.body === 'string'
          ? new TextEncoder().encode(step.body)
          : step.body;
    const headers = new Map(
      Object.entries(step.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]),
    );
    return {
      status: step.status,
      headers: { get: (name) => headers.get(name.toLowerCase()) ?? null },
      body: bytes === null ? null : this.stream(url, bytes),
    };
  }

  private stream(url: string, bytes: Uint8Array): ReadableStream<Uint8Array> {
    let at = 0;
    const count = (): void => {
      this.read.set(url, (this.read.get(url) ?? 0) + 1);
    };
    return new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          count();
          if (at >= bytes.length) {
            controller.close();
            return;
          }
          const next = bytes.subarray(at, at + 16384);
          at += next.length;
          controller.enqueue(next);
        },
      },
      { highWaterMark: 0 },
    );
  }
}

export const WHERE = {
  SITE_URL: 'https://site.test/',
  LIVE_ROOT: 'https://live.test/v1/',
  ACCOUNTS_HEALTH_URL: 'https://accounts.test/v1/health',
};
export const CLOSINGS_URL = 'https://live.test/v1/live/closings.json';
export const STAMP_URL = 'https://live.test/v1/predictions/stamp.json';

/** An instant `seconds` before the clock, as the files write it. */
export function stampAt(clockMs: number, seconds: number): string {
  return `${new Date(Math.floor(clockMs / 1000 - seconds) * 1000).toISOString().slice(0, 19)}Z`;
}

/** A small closings file and a stamp file made `seconds` before the clock. */
export function closingsBody(clockMs: number, seconds: number): string {
  return `{"closings":[],"generated_at":"${stampAt(clockMs, seconds)}","schema_version":1}`;
}
export function stampBody(clockMs: number, seconds: number, districts = 13000): string {
  return `{"districts":${districts},"generated_at":"${stampAt(clockMs, seconds)}","schema_version":1}\n`;
}

/** A network where all four parts work. */
export function healthy(net: Net): Net {
  return net
    .on(WHERE.SITE_URL, { status: 200 })
    .on(WHERE.ACCOUNTS_HEALTH_URL, { status: 200, body: '{"ok":true}' })
    .on(CLOSINGS_URL, { status: 200, body: closingsBody(net.clock, 200) })
    .on(STAMP_URL, { status: 200, body: stampBody(net.clock, 600) });
}
