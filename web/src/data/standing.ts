/**
 * The standing file (predictions/standing/<stamp>.json, WHY-TRANSPARENT): every number the
 * why's steps say on a storm-class day, published beside predictions/latest.json, which names
 * it by its stamp (pipeline/snowlight/predict/standing.py). A stamp's file never changes, so a
 * page reads each stamp once and keeps it: as soon as a predictions file names it with a
 * storm-class day in it (prefetchStanding), so the panel has it when it opens, or else the
 * first time such a day's panel opens. It is read through the live roots, as
 * predictions/latest.json is (live-roots.ts). A read that fails is tried once more, a minute
 * on. Until it arrives, or where it cannot be read, the panel keeps today's why.
 */

import { PUBLISHED_PATHS } from '../types/generated/index.ts';
import type { PredictionsFile, StandingFile } from '../types/generated/index.ts';
import type { DataFiles, Fetch } from './files.ts';
import { liveFetch } from './live-roots.ts';

/** A stamp: the first 12 hex digits of the file's content hash. */
const STAMP = /^[0-9a-f]{12}$/;

/** How long after a failed read the one more try waits. */
export const STANDING_RETRY_MS = 60_000;

/** What each page's files hold: per stamp, the file once read (null: it could not be). */
const held = new WeakMap<DataFiles, Map<string, StandingFile | null>>();
const reading = new WeakMap<DataFiles, Map<string, Promise<StandingFile | null>>>();
/** Per stamp, when a read last failed and how many have. */
const failed = new WeakMap<DataFiles, Map<string, { at: number; count: number }>>();

/** Where a stamp's file is: beside predictions/latest.json, on the same root. */
export function standingUrl(files: DataFiles, stamp: string, page?: string): string | null {
  if (!STAMP.test(stamp)) return null;
  const latest = files.url(PUBLISHED_PATHS.predictions);
  if (latest === null) return null;
  const here = (globalThis as { location?: { href?: string } }).location?.href;
  const base = page ?? here ?? 'http://localhost/';
  try {
    return new URL(`standing/${stamp}.json`, new URL(latest, base)).href;
  } catch {
    return null;
  }
}

/** The stamp's file, as read; null before it is (or where it could not be). */
export function heldStanding(files: DataFiles, stamp: string): StandingFile | null {
  return held.get(files)?.get(stamp) ?? null;
}

/** Whether a read of the stamp's file would ask for it now: not once it is held, not while
 * one is on its way, and after a failure only once more, a minute on. */
function due(files: DataFiles, stamp: string, now: number): boolean {
  if (held.get(files)?.has(stamp) === true) return false;
  if (reading.get(files)?.has(stamp) === true) return false;
  const last = failed.get(files)?.get(stamp);
  if (last === undefined) return true;
  return last.count < 2 && (now - last.at >= STANDING_RETRY_MS || now < last.at);
}

/** Whether a panel waiting for the stamp's file should ask for it: a read now would start one
 * or join the one on its way (a prefetch's too), so the panel shows the steps when it comes. */
export function awaitStanding(files: DataFiles, stamp: string, now: number = Date.now()): boolean {
  return reading.get(files)?.has(stamp) === true || due(files, stamp, now);
}

/** Whether the stamp's file was read already, is on its way, or is not to be asked for now. */
export function triedStanding(files: DataFiles, stamp: string, now: number = Date.now()): boolean {
  return !due(files, stamp, now);
}

/** The shape a panel reads of the file: the parts its rows need, each where it should be. */
export function standingOf(value: unknown, stamp: string): StandingFile | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const file = value as Partial<StandingFile>;
  if (file.schema_version !== 1 || file.stamp !== stamp) return null;
  const count = file.directory?.districts;
  if (typeof count !== 'number') return null;
  const columns = [file.winter, file.flags, file.usual?.advisory, file.usual?.warning];
  if (!columns.every((column) => Array.isArray(column) && column.length === count)) return null;
  if (file.levels === undefined || file.ref === undefined || file.record === undefined) return null;
  return file as StandingFile;
}

/**
 * Reads the stamp's file once per page (a second ask waits for the first), and keeps it. A
 * file that cannot be read, or is not the stamp's, is null; it is asked for once more a
 * minute on, and then no more.
 */
export function readStanding(
  files: DataFiles,
  stamp: string,
  fetchImpl: Fetch = liveFetch,
  now: () => number = Date.now,
): Promise<StandingFile | null> {
  const known = held.get(files);
  if (known?.has(stamp) === true) return Promise.resolve(known.get(stamp) ?? null);
  const waiting = reading.get(files) ?? new Map<string, Promise<StandingFile | null>>();
  reading.set(files, waiting);
  const pending = waiting.get(stamp);
  if (pending !== undefined) return pending;
  if (!due(files, stamp, now())) return Promise.resolve(null);
  const url = standingUrl(files, stamp);
  const done = (
    url === null
      ? Promise.resolve(null)
      : fetchImpl(url)
          .then((response) => (response.ok ? (response.json() as Promise<unknown>) : null))
          .then((body) => standingOf(body, stamp))
  )
    .catch(() => null)
    .then((found) => {
      waiting.delete(stamp);
      if (found === null) {
        const misses = failed.get(files) ?? new Map<string, { at: number; count: number }>();
        failed.set(files, misses);
        misses.set(stamp, { at: now(), count: (misses.get(stamp)?.count ?? 0) + 1 });
        return null;
      }
      const kept = held.get(files) ?? new Map<string, StandingFile | null>();
      held.set(files, kept);
      kept.set(stamp, found);
      return found;
    });
  waiting.set(stamp, done);
  return done;
}

/** Whether a day of a predictions file is a storm-class one. */
function classed(day: unknown): boolean {
  return (day as { why?: { base?: { kind?: string } } } | null)?.why?.base?.kind === 'class';
}

/**
 * Starts the read of the standing file a predictions file names when it holds a storm-class
 * day, before any panel opens, so a panel opened later has the steps at once (no swap from
 * today's why). Off the page's own work: when the browser is idle.
 */
export function prefetchStanding(
  files: DataFiles,
  predictions: Pick<PredictionsFile, 'standing' | 'districts' | 'outlooks'>,
  later: (run: () => void) => void = whenIdle,
): void {
  const stamp = predictions.standing ?? null;
  if (stamp === null || !STAMP.test(stamp) || triedStanding(files, stamp)) return;
  const any =
    predictions.districts.some((entry) => entry.days.some(classed)) ||
    (predictions.outlooks ?? []).some(classed);
  if (!any) return;
  later(() => void readStanding(files, stamp));
}

function whenIdle(run: () => void): void {
  const idle = (globalThis as { requestIdleCallback?: (run: () => void, o?: object) => number })
    .requestIdleCallback;
  if (idle === undefined) setTimeout(run, 0);
  else idle(run, { timeout: 2000 });
}
