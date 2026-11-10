/**
 * The four probes. Each asks once, and once more on trouble; the second try stands. A probe
 * that fails is `unknown`, never `down`. Of a body only a stamp and a length are kept, and
 * nothing of it is logged.
 */

import {
  HEALTH_MAX_CHARS,
  REFUSAL_HEAD_BYTES,
  judgeAccounts,
  judgeFile,
  judgeSite,
  wantsSecondTry,
} from '../../shared/judge.ts';
import type { Answer } from '../../shared/judge.ts';
import { STAMP_MAX_BYTES, TAIL_BYTES } from '../../shared/stamp.ts';
import type { Part, Reading } from '../../shared/types.ts';

export const USER_AGENT = 'snowlight-status/1 (+https://status.snowlightmap.com)';
/** A request is given up after this long, body included. */
export const TIMEOUT_MS = 8000;
/** A second try starts this long after the first ends. */
export const RETRY_WAIT_MS = 1500;

/** What a probe needs of an answer: nothing a Worker has and Node has not. */
export interface Got {
  status: number;
  headers: { get(name: string): string | null };
  body: ReadableStream<Uint8Array> | null;
}

export interface Ask {
  method: 'GET' | 'HEAD';
  redirect: 'follow';
  cache: 'no-store';
  headers: Record<string, string>;
  signal: AbortSignal;
}

export interface Deps {
  fetch(url: string, init: Ask): Promise<Got>;
  /** The clock, in milliseconds. */
  now(): number;
  wait(ms: number): Promise<void>;
}

/** Where the four parts are. An empty `ACCOUNTS_HEALTH_URL`: accounts is not asked. */
export interface Where {
  SITE_URL: string;
  LIVE_ROOT: string;
  ACCOUNTS_HEALTH_URL: string;
}

export function urlOf(part: Part, where: Where): string {
  if (part === 'site') return where.SITE_URL;
  if (part === 'accounts') return where.ACCOUNTS_HEALTH_URL;
  const root = where.LIVE_ROOT.endsWith('/') ? where.LIVE_ROOT : `${where.LIVE_ROOT}/`;
  return `${root}${part === 'closings' ? 'live/closings.json' : 'predictions/stamp.json'}`;
}

function ask(method: 'GET' | 'HEAD'): Ask {
  return {
    method,
    redirect: 'follow',
    cache: 'no-store',
    headers: { 'User-Agent': USER_AGENT },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  };
}

async function drop(got: Got): Promise<void> {
  try {
    await got.body?.cancel();
  } catch {
    // Nothing to do: the body is not wanted.
  }
}

/** The first `max` bytes of a body, and whether there were more. The rest is not read. */
async function head(got: Got, max: number): Promise<{ bytes: Uint8Array; more: boolean }> {
  if (got.body === null) return { bytes: new Uint8Array(0), more: false };
  const reader = got.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  let more = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    length += value.length;
    if (length > max) {
      more = true;
      await reader.cancel();
      break;
    }
  }
  return { bytes: joined(chunks, length).subarray(0, max), more };
}

/** A whole body's length and its last `keep` bytes (all of it when it is no longer). */
async function tail(got: Got, keep: number): Promise<{ bytes: Uint8Array; length: number }> {
  if (got.body === null) return { bytes: new Uint8Array(0), length: 0 };
  const reader = got.body.getReader();
  let chunks: Uint8Array[] = [];
  let held = 0;
  let length = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    held += value.length;
    length += value.length;
    while (chunks.length > 1 && held - chunks[0]!.length >= keep + 1) {
      held -= chunks[0]!.length;
      chunks = chunks.slice(1);
    }
  }
  const all = joined(chunks, held);
  // One byte more than `keep` is held, so a body just over the limit is seen to be over it.
  return { bytes: length <= keep ? all : all.subarray(all.length - (keep + 1)), length };
}

function joined(chunks: readonly Uint8Array[], length: number): Uint8Array {
  const out = new Uint8Array(length);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

function text(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

interface Try {
  answer: Answer | null;
  reading: Reading;
}

const NO_ANSWER: Reading = { s: 'unknown', code: 0, ms: null, made: null, allow: 0, bytes: null };

async function trySite(url: string, deps: Deps): Promise<Try> {
  const began = deps.now();
  const got = await deps.fetch(url, ask('HEAD'));
  const answer = { code: got.status, ms: deps.now() - began };
  // The status code only: the body, if any is sent, is never read.
  await drop(got);
  return {
    answer,
    reading: { ...NO_ANSWER, s: judgeSite(answer), code: answer.code, ms: answer.ms },
  };
}

async function tryAccounts(url: string, deps: Deps): Promise<Try> {
  const began = deps.now();
  const got = await deps.fetch(url, ask('GET'));
  const answer = { code: got.status, ms: deps.now() - began };
  let body: string;
  if (answer.code === 200) {
    // 1,024 characters are 4,096 bytes at most: one byte more shows a longer body.
    const read = await head(got, HEALTH_MAX_CHARS * 4 + 1);
    body = read.more ? 'x'.repeat(HEALTH_MAX_CHARS + 1) : text(read.bytes);
  } else {
    body = text((await head(got, REFUSAL_HEAD_BYTES)).bytes);
  }
  const s = judgeAccounts(answer, body);
  return { answer, reading: { ...NO_ANSWER, s, code: answer.code, ms: answer.ms } };
}

async function tryFile(part: 'closings' | 'chances', url: string, deps: Deps): Promise<Try> {
  const began = deps.now();
  const got = await deps.fetch(url, ask('GET'));
  const answer = { code: got.status, ms: deps.now() - began };
  let body: Uint8Array | null = null;
  let bytes: number | null = null;
  if (answer.code !== 200) {
    await drop(got);
  } else if (part === 'closings') {
    const read = await tail(got, TAIL_BYTES);
    body = read.bytes;
    bytes = read.length;
  } else {
    const read = await head(got, STAMP_MAX_BYTES + 1);
    body = read.bytes;
  }
  const verdict = judgeFile(part, {
    code: answer.code,
    age: got.headers.get('age'),
    body,
    now: Math.floor(deps.now() / 1000),
  });
  return {
    answer,
    reading: {
      s: verdict.s,
      code: answer.code,
      ms: answer.ms,
      made: verdict.made,
      allow: verdict.allow,
      bytes,
    },
  };
}

async function once(part: Part, url: string, deps: Deps): Promise<Try> {
  try {
    if (part === 'site') return await trySite(url, deps);
    if (part === 'accounts') return await tryAccounts(url, deps);
    return await tryFile(part, url, deps);
  } catch {
    // No answer, a timeout, or a body that broke off: the check failed, not the part.
    return { answer: null, reading: NO_ANSWER };
  }
}

/** One part's reading at a tick: one request, two on trouble. */
export async function probe(part: Part, where: Where, deps: Deps): Promise<Reading> {
  const url = urlOf(part, where);
  if (part === 'accounts' && url === '') return NO_ANSWER;
  const first = await once(part, url, deps);
  if (!wantsSecondTry(part, first.answer)) return first.reading;
  await deps.wait(RETRY_WAIT_MS);
  return (await once(part, url, deps)).reading;
}
