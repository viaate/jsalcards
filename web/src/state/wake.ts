/**
 * Tells when the page may have been asleep, so what it shows as of now is
 * worked out again at once: the update line (ui/UpdateTime.svelte) and the
 * live reads (data/live.ts pollWhileVisible).
 *
 * A device that sleeps with the page open (a laptop's lid shut, a phone's
 * screen off) holds the page's timers back, and on some systems their clock
 * stands still while it sleeps, so a timer can come due well after the page
 * is back. The wall clock does not stand still: a check every few seconds
 * that finds it moved far more than that tells a sleep apart.
 *
 * The page keeps one such check, however many parts of it listen: the map's
 * poll, an open panel's and the update line share it.
 */

/** How often the wall clock is looked at for a sleep: every 5 seconds. */
export const WAKE_CHECK_MS = 5_000;

/**
 * How much further than WAKE_CHECK_MS the wall clock must have moved between
 * two looks to count as a sleep: 10 seconds, so a gap of over 15 seconds.
 */
export const WAKE_GAP_MS = 10_000;

/** The parts of `window` the wake watch uses. */
export interface WakeHost {
  readonly document: Pick<Document, 'addEventListener' | 'removeEventListener'>;
  setInterval(handler: () => void, timeout: number): number;
  clearInterval(id: number | undefined): void;
  readonly addEventListener?: Window['addEventListener'];
  readonly removeEventListener?: Window['removeEventListener'];
}

/** Date.now(), the page's wall clock: the one every listener on the page shares a watch by. */
export const wallClock = (): number => Date.now();

/** One watch: its listeners, and how to stop it once none is left. */
interface Watch {
  readonly listeners: Set<{ readonly onWake: () => void }>;
  readonly stop: () => void;
}

/** The page's watches, one for each host and wall clock (tests hand their own). */
const watches = new WeakMap<WakeHost, Map<() => number, Watch>>();

function startWatch(host: WakeHost, wall: () => number): Watch {
  const listeners = new Set<{ readonly onWake: () => void }>();
  const wake = (): void => {
    for (const listener of [...listeners]) listener.onWake();
  };
  let last = wall();
  const check = host.setInterval(() => {
    const at = wall();
    const gap = at - last;
    last = at;
    if (gap > WAKE_CHECK_MS + WAKE_GAP_MS) wake();
  }, WAKE_CHECK_MS);
  const woke = (): void => {
    last = wall();
    wake();
  };
  host.addEventListener?.('pageshow', woke);
  host.addEventListener?.('focus', woke);
  host.document.addEventListener('resume', woke);
  return {
    listeners,
    stop: () => {
      host.clearInterval(check);
      host.removeEventListener?.('pageshow', woke);
      host.removeEventListener?.('focus', woke);
      host.document.removeEventListener('resume', woke);
    },
  };
}

/**
 * Calls `onWake` when the page may have been asleep: the page is shown from
 * the back-forward cache, gets focus or is resumed, or the wall clock moved
 * well past what a few seconds' check expects, as it does after the device
 * slept with the page open. Every listener on one host shares one check.
 * Returns the function that stops it; the check stops with its last listener.
 */
export function watchWake(
  onWake: () => void,
  host: WakeHost = window,
  wall: () => number = wallClock,
): () => void {
  let byWall = watches.get(host);
  if (byWall === undefined) {
    byWall = new Map();
    watches.set(host, byWall);
  }
  const shared = byWall;
  const watch = shared.get(wall) ?? startWatch(host, wall);
  shared.set(wall, watch);
  const listener = { onWake };
  watch.listeners.add(listener);
  return () => {
    if (!watch.listeners.delete(listener) || watch.listeners.size > 0) return;
    watch.stop();
    if (shared.get(wall) === watch) shared.delete(wall);
  };
}
