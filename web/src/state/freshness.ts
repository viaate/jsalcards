/**
 * Whether the page is online, and the update line for a data file.
 *
 * The time on the update line is always the file's own generated_at. The
 * clock only decides two things: whether the file is recent enough to call
 * live, and whether the line needs a date because the file is from another day.
 */

import { format } from '../copy';
import type { UtcInstant } from '../types/generated';
import { parseInstant } from './instant';

export { parseInstant } from './instant';

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
  const { online, liveWithinMs, timeZone, now } = input;
  if (!online) return { text: format.offline(generated, timeZone, now), live: false };
  const age = now.getTime() - generated.getTime();
  // A file stamped in the future means a skewed clock here: not proof it is live.
  if (age >= 0 && age <= liveWithinMs) {
    return { text: format.liveAt(generated, timeZone), live: true };
  }
  return { text: format.updatedAt(generated, timeZone, now), live: false };
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
