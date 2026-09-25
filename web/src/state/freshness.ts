/**
 * Whether the page is online, and the update line for a data file.
 *
 * The time on the update line is always the file's own generated_at. The
 * clock only decides two things: whether the file is recent enough to call
 * live, and whether the line needs a date because the file is from another day.
 */

import { format } from '../copy';
import type { UtcInstant } from '../types/generated';

const UTC_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** A UtcInstant as a Date, or null when it is not one. */
export function parseInstant(value: unknown): Date | null {
  if (typeof value !== 'string' || !UTC_INSTANT.test(value)) return null;
  const instant = new Date(value);
  // Date accepts 2026-02-30 and rolls it over; a real instant prints back the same.
  return Number.isNaN(instant.getTime()) || instant.toISOString() !== value.replace('Z', '.000Z')
    ? null
    : instant;
}

export interface UpdateLineInput {
  /** The file's generated_at. */
  readonly generatedAt: UtcInstant;
  /** Whether the page is online now. */
  readonly online: boolean;
  /** A file generated at most this long ago counts as live, while online. */
  readonly liveWithinMs: number;
  /** The viewer's time zone, such as "America/Chicago". */
  readonly timeZone: string;
  /** Now; only used to judge age and to add a date to an older time. */
  readonly now: Date;
}

/**
 * "Live · 6:42 AM", "Updated 6:42 AM" or "Offline · Updated 6:42 AM", with the
 * date added when the file is from another day. Null when generatedAt is not a
 * valid instant, so nothing false is shown.
 */
export function updateLine(input: UpdateLineInput): string | null {
  const generated = parseInstant(input.generatedAt);
  if (generated === null) return null;
  const { online, liveWithinMs, timeZone, now } = input;
  if (!online) return format.offline(generated, timeZone, now);
  const age = now.getTime() - generated.getTime();
  // A file stamped in the future means a skewed clock here: not proof it is live.
  if (age >= 0 && age <= liveWithinMs) return format.liveAt(generated, timeZone);
  return format.updatedAt(generated, timeZone, now);
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
