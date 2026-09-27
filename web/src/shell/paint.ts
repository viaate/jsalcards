/**
 * Resolves once the first contentful paint has reached the screen, so work
 * started afterwards (loading the map) cannot delay it.
 *
 * Uses the paint timing entry, which is recorded when the frame is presented.
 * Where paint timing is missing, it falls back to the task after the next
 * rendered frame; where requestAnimationFrame is missing too (tests), to a
 * plain task.
 */
export function afterFirstPaint(): Promise<void> {
  return new Promise((resolve) => {
    const painted = (): boolean =>
      typeof performance.getEntriesByName === 'function' &&
      performance.getEntriesByName('first-contentful-paint').length > 0;
    if (painted()) {
      setTimeout(resolve, 0);
      return;
    }
    if (
      typeof PerformanceObserver === 'function' &&
      PerformanceObserver.supportedEntryTypes.includes('paint')
    ) {
      // The entries the observer is handed, not performance's own list: the two agree in a
      // browser, but only the first is there when a test clock stands in for performance.
      const observer = new PerformanceObserver((list) => {
        if (list.getEntriesByName('first-contentful-paint').length === 0) return;
        observer.disconnect();
        setTimeout(resolve, 0);
      });
      observer.observe({ type: 'paint', buffered: true });
      return;
    }
    const next = (): void => {
      setTimeout(resolve, 0);
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(next);
    else next();
  });
}
