/**
 * Whether the page is online, and the update line for a data file.
 *
 * The time on the update line is always the file's own generated_at. The
 * clock only decides two things: whether the file is recent enough to call
 * live, and whether the line needs a date because the file is from another day.
 */

import { format } from '../copy-format';
import type { UtcInstant } from '../types/generated';
import { parseInstant } from './instant';

export { parseInstant } from './instant';

/**
 * How long after its generated_at a live file still counts as live, in
 * milliseconds, while the page is online. The one threshold the page uses.
 *
 * Set from the live ingest's cadence: while healthy, the ingest publishes the
 * file at least every 5 minutes (a heartbeat when nothing changed), and only
 * when its checks pass. Twenty minutes covers about two missed heartbeats and
 * the handoff between two ingest runs, so an older file means the ingest has
 * stopped or is holding back, and the file is no longer called live.
 */
export const LIVE_FRESH_MS = 20 * 60_000;

/**
 * How far ahead of the viewer's clock a live file's generated_at may be and
 * still count as live, in milliseconds. The ingest may stamp a file up to a
 * minute ahead of the true time (its clock check, S8 spec G12c), and a
 * viewer's clock may run a little slow; a fresh file is then not called old.
 * A file stamped further ahead says a clock is wrong, not that it is live.
 *
 * Only a build that reads its closings file from a live root allows it
 * (VITE_SNOWLIGHT_LIVE_ROOT): that file is the S8 ingest's. A build without
 * one calls no file stamped ahead live, as before S8.
 */
export const LIVE_LEAD_MS = 2 * 60_000;

export interface UpdateLineInput {
  /** The file's generated_at. */
  readonly generatedAt: UtcInstant;
  /** Whether the page is online now. */
  readonly online: boolean;
  /** A file generated at most this long ago counts as live, while online. Default LIVE_FRESH_MS. */
  readonly liveWithinMs?: number;
  /** The viewer's time zone, such as "America/Chicago". */
  readonly timeZone: string;
  /** Now; only used to judge age and to add a date to an older time. */
  readonly now: Date;
  /**
   * How long the page has held this same file, by its own clocks (heldFor).
   * A file held longer than liveWithinMs is no longer live, whatever the
   * device's clock says of its age: it was generated before the page took it.
   */
  readonly heldMs?: number;
}

/** The update line, and whether it calls the file live. */
export interface UpdateState {
  readonly text: string;
  readonly live: boolean;
}

/**
 * "Live · 6:42 AM", "Updated 6:42 AM" or "Offline · Updated 6:42 AM", with the
 * date added when the file is from another day. Null when generatedAt is not a
 * valid instant, so nothing false is shown.
 */
export function updateState(input: UpdateLineInput): UpdateState | null {
  const generated = parseInstant(input.generatedAt);
  if (generated === null) return null;
  const { online, liveWithinMs = LIVE_FRESH_MS, timeZone, now, heldMs = 0 } = input;
  if (!online) return { text: format.offline(generated, timeZone, now), live: false };
  const age = now.getTime() - generated.getTime();
  // A file stamped in the future means a skewed clock here: not proof it is live. From a live
  // root, one stamped a little ahead is fresh from the ingest's clock (LIVE_LEAD_MS).
  const lead =
    import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT !== undefined &&
    import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT !== ''
      ? LIVE_LEAD_MS
      : 0;
  if ((age >= 0 || age >= -lead) && age <= liveWithinMs && heldMs <= liveWithinMs) {
    return { text: format.liveAt(generated, timeZone), live: true };
  }
  return { text: format.updatedAt(generated, timeZone, now), live: false };
}

/** When the page took a file, by both its clocks (Date.now() and performance.now()). */
export interface HeldSince {
  readonly wall: number;
  readonly monotonic: number;
}

/**
 * How long the page has held a file it took at `since`: the larger of what
 * the clock that only moves forward and the wall clock (which also counts a
 * sleep) say has passed. A wall clock set back counts nothing, so a device
 * clock set back, or one that runs slow, never makes a held file look newer
 * than the page's own count of how long it has had it.
 */
export function heldFor(since: HeldSince, now: HeldSince): number {
  return Math.max(0, now.monotonic - since.monotonic, now.wall - since.wall);
}

/** How many files' first holds the page keeps: it never shows an older file again. */
const HELD_KEPT = 8;
/** When the page first held each of its newest files, by both its clocks, for the page's life. */
const firstHeld = new Map<string, HeldSince>();

/**
 * When the page first held the file stamped `generatedAt`, by both its
 * clocks: `now()` the first time it is asked, and the same answer for the
 * page's life after that. Kept here, not in the line, so a line shown again
 * (after a replay, or a moment with no file) holds on from when the file was
 * first taken, never from when the line came back.
 */
export function heldSince(generatedAt: string, now: () => HeldSince): HeldSince {
  const known = firstHeld.get(generatedAt);
  if (known !== undefined) return known;
  const since = now();
  firstHeld.set(generatedAt, since);
  for (const stamp of firstHeld.keys()) {
    if (firstHeld.size <= HELD_KEPT) break;
    firstHeld.delete(stamp);
  }
  return since;
}

/** Forgets every hold, as a page that has just loaded: for tests. */
export function forgetHolds(): void {
  firstHeld.clear();
}

/**
 * The moment a file stops counting as live, in milliseconds since the epoch,
 * or null when generatedAt is not a valid instant.
 */
export function liveUntil(generatedAt: UtcInstant, liveWithinMs = LIVE_FRESH_MS): number | null {
  const generated = parseInstant(generatedAt);
  return generated === null ? null : generated.getTime() + liveWithinMs;
}

/** updateState's line alone. */
export function updateLine(input: UpdateLineInput): string | null {
  return updateState(input)?.text ?? null;
}

/** The parts of `window` connectivity uses, so tests can hand it a fake. */
export interface ConnectivityHost extends EventTarget {
  readonly navigator: { readonly onLine: boolean };
}

export interface Connectivity {
  readonly online: boolean;
  /** Calls `listener` now and on every change. Also a Svelte store. */
  subscribe(listener: (online: boolean) => void): () => void;
  destroy(): void;
}

/** navigator.onLine, kept current by the online and offline events. */
export function createConnectivity(host: ConnectivityHost = window): Connectivity {
  const listeners = new Set<(online: boolean) => void>();
  let online = host.navigator.onLine;
  const update = (): void => {
    const next = host.navigator.onLine;
    if (next === online) return;
    online = next;
    for (const listener of [...listeners]) listener(online);
  };
  host.addEventListener('online', update);
  host.addEventListener('offline', update);
  return {
    get online() {
      return online;
    },
    subscribe(listener) {
      listeners.add(listener);
      listener(online);
      return () => {
        listeners.delete(listener);
      };
    },
    destroy() {
      listeners.clear();
      host.removeEventListener('online', update);
      host.removeEventListener('offline', update);
    },
  };
}
