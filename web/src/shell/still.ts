/**
 * The inline still is the continental outline drawn as SVG in index.html, so
 * the first frame shows the map before any script runs. It is the national
 * view. Where the WebGL map opens on that view, it draws the same lines in
 * the same place and the still fades out over them. Where the map opens
 * anywhere else (a link's view, or a phone's own area), the still goes at
 * once, in the frame the map first shows: the country is never laid over a
 * street.
 */

export const STILL_HIDDEN_CLASS = 'is-hidden';

export interface RetireOptions {
  /**
   * Fade out first (the default), for a map under it that draws the same
   * lines; false removes it now, for a map that shows somewhere else.
   */
  fade?: boolean;
}

function transitionMs(element: Element): number {
  const style = getComputedStyle(element);
  const toMs = (value: string): number =>
    value.trim().endsWith('ms') ? parseFloat(value) : parseFloat(value) * 1000;
  const durations = style.transitionDuration.split(',').map(toMs);
  const delays = style.transitionDelay.split(',').map(toMs);
  return Math.max(0, ...durations.map((d, i) => (d || 0) + (delays[i] ?? 0)));
}

/**
 * Takes the still away: fades it out, then removes it from the document, or
 * removes it now with `{ fade: false }`, even partway through a fade. Safe to
 * call more than once.
 */
export function retireStill(still: Element, { fade = true }: RetireOptions = {}): void {
  if (!still.isConnected) return;
  if (!fade) {
    still.remove();
    return;
  }
  if (still.classList.contains(STILL_HIDDEN_CLASS)) return;
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
