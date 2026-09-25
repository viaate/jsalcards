/**
 * The inline still is the continental outline drawn as SVG in index.html, so
 * the first frame shows the map before any script runs. Once the WebGL map
 * draws the same lines in the same place, the still fades out and goes away.
 */

export const STILL_HIDDEN_CLASS = 'is-hidden';

function transitionMs(element: Element): number {
  const style = getComputedStyle(element);
  const toMs = (value: string): number =>
    value.trim().endsWith('ms') ? parseFloat(value) : parseFloat(value) * 1000;
  const durations = style.transitionDuration.split(',').map(toMs);
  const delays = style.transitionDelay.split(',').map(toMs);
  return Math.max(0, ...durations.map((d, i) => (d || 0) + (delays[i] ?? 0)));
}

/** Fades the still out, then removes it from the document. Safe to call more than once. */
export function retireStill(still: Element): void {
  if (!still.isConnected || still.classList.contains(STILL_HIDDEN_CLASS)) return;
  still.classList.add(STILL_HIDDEN_CLASS);
  const duration = transitionMs(still);
  if (duration === 0) {
    still.remove();
    return;
  }
  const done = (): void => {
    still.remove();
  };
  still.addEventListener('transitionend', done, { once: true });
  // transitionend does not fire when the tab is hidden mid-fade.
  setTimeout(done, duration + 100);
}
