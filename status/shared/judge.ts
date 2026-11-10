/** From an answer to one of the four words. Pure: the numbers of the rules are named here. */

import { readStamp } from './stamp.ts';
import type { Part, State } from './types.ts';

/** The website and accounts are slow past this many milliseconds to the answer's headers. */
export const SLOW_MS = 3000;
/** A health answer longer than this many characters is not one. */
export const HEALTH_MAX_CHARS = 1024;
/** How much of an answer that is not 200 is looked at for Cloudflare's own refusal. */
export const REFUSAL_HEAD_BYTES = 512;
/** Cloudflare refusing the checker's own request to another Worker, or no Worker at the URL. */
export const REFUSAL = /error(?: code:)? ?1042/i;
/** The CDN's `Age` is allowed up to this many seconds (its copy lives 10 minutes at most). */
export const AGE_MAX = 600;
/** A file stamped further ahead of the clock than this is late. */
export const AHEAD_MAX = 900;
/** Seconds after which each file is late, and after which it is down. */
export const CLOSINGS_LATE = 900;
export const CLOSINGS_DOWN = 3600;
export const CHANCES_LATE = 2700;
export const CHANCES_DOWN = 5400;

/** An answer's headers. `null` where one is used: no answer came. */
export interface Answer {
  code: number;
  ms: number;
}

/** The website: the status code and the time to it, nothing else. */
export function judgeSite(answer: Answer | null): State {
  if (answer === null || answer.code === 429) return 'unknown';
  if (answer.code !== 200) return 'down';
  return answer.ms <= SLOW_MS ? 'ok' : 'late';
}

/**
 * Accounts: its health answer. `body` is the text of a 200, or the first bytes of any other
 * answer, read as text; null when the body could not be read.
 */
export function judgeAccounts(answer: Answer | null, body: string | null): State {
  if (answer === null || answer.code === 429) return 'unknown';
  if (answer.code !== 200) return body !== null && REFUSAL.test(body) ? 'unknown' : 'down';
  if (body === null || body.length > HEALTH_MAX_CHARS) return 'down';
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return 'down';
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return 'down';
  if ((parsed as Record<string, unknown>)['ok'] !== true) return 'down';
  return answer.ms <= SLOW_MS ? 'ok' : 'late';
}

/** The seconds of the answer's `Age` header that count: 1 to 9 digits, 600 at most, else 0. */
export function allowance(age: string | null): number {
  if (age === null || !/^[0-9]{1,9}$/.test(age)) return 0;
  return Math.min(Number(age), AGE_MAX);
}

export interface FileAnswer {
  code: number;
  /** The `Age` header as sent, or null. */
  age: string | null;
  /** The body of a 200 (for a large closings file, its last bytes), or null. */
  body: Uint8Array | null;
  /** The clock when the body ended, in Unix seconds. */
  now: number;
}

export interface FileVerdict {
  s: State;
  made: number | null;
  allow: number;
}

/** A file part: is the served file there, whole, and fresh by its own stamp. */
export function judgeFile(part: 'closings' | 'chances', answer: FileAnswer | null): FileVerdict {
  const none = (s: State): FileVerdict => ({ s, made: null, allow: 0 });
  if (answer === null || answer.code === 429) return none('unknown');
  // No stamp on the host (none uploaded yet): that says nothing about the chances.
  if (part === 'chances' && answer.code === 404) return none('unknown');
  if (answer.code !== 200) return none('down');
  if (answer.body === null) return none('unknown');
  const stamp = readStamp(part, answer.body);
  const allow = allowance(answer.age);
  if (stamp.bad) return { s: 'down', made: null, allow };
  if (stamp.made === null) return { s: 'unknown', made: null, allow };
  if (stamp.blank) return { s: 'down', made: stamp.made, allow };
  const late = part === 'closings' ? CLOSINGS_LATE : CHANCES_LATE;
  const down = part === 'closings' ? CLOSINGS_DOWN : CHANCES_DOWN;
  const plain = answer.now - stamp.made;
  if (plain < -AHEAD_MAX) return { s: 'late', made: stamp.made, allow };
  const age = Math.max(0, plain) - allow;
  const s: State = age > down ? 'down' : age > late ? 'late' : 'ok';
  return { s, made: stamp.made, allow };
}

/**
 * Whether the first try earns a second. The website and accounts: anything but a 200 in time.
 * A file: no answer, 429 or 5xx.
 */
export function wantsSecondTry(part: Part, first: Answer | null): boolean {
  if (part === 'site' || part === 'accounts') {
    return first === null || first.code !== 200 || first.ms > SLOW_MS;
  }
  return first === null || first.code === 429 || (first.code >= 500 && first.code <= 599);
}
