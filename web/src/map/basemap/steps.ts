/**
 * The map's start, step by step: the marks it is timed by, and the yields
 * that keep its pieces of work in tasks of their own. The page's first script
 * starts the map with these; the reveal itself (reveal.ts) loads with the
 * map's code.
 */

/**
 * Steps of the map's start, recorded as User Timing marks ("snowlight:" plus
 * the step) so the handover can be timed in DevTools, Lighthouse and tests.
 */
export type MapStep = 'map-loaded' | 'map-created' | 'map-load' | 'map-live' | 'map-takeover';

export function markStep(step: MapStep): void {
  if (typeof performance.mark === 'function') performance.mark(`snowlight:${step}`);
}

/** Yields to the event loop so the next piece of work starts a fresh task. */
export function yieldToMain(): Promise<void> {
  const scheduler = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  if (typeof scheduler?.yield === 'function') return scheduler.yield();
  return new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
}
