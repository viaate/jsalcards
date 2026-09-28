import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { STILL_HIDDEN_CLASS, retireStill } from '../still';

/** A still with index.html's fade, or none (as under reduced motion). */
function mountStill(fade: string | null): SVGSVGElement {
  const still = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  still.setAttribute('class', 'still');
  still.style.transitionDuration = fade ?? '0s';
  still.style.transitionDelay = '0s';
  document.body.append(still);
  return still;
}

describe('retireStill', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.replaceChildren();
  });

  it('fades the still out over the map, then removes it', () => {
    const still = mountStill('240ms');
    retireStill(still);
    expect(still.classList.contains(STILL_HIDDEN_CLASS)).toBe(true);
    expect(still.isConnected).toBe(true);
    still.dispatchEvent(new Event('transitionend'));
    expect(still.isConnected).toBe(false);
  });

  it('removes it after the fade even when no transitionend comes (a hidden tab)', () => {
    const still = mountStill('240ms');
    retireStill(still);
    vi.advanceTimersByTime(339);
    expect(still.isConnected).toBe(true);
    vi.advanceTimersByTime(1);
    expect(still.isConnected).toBe(false);
  });

  it('removes it at once for a map that opens somewhere else: no frame lays it over the streets', () => {
    const still = mountStill('240ms');
    retireStill(still, { fade: false });
    expect(still.isConnected).toBe(false);
  });

  it('removes it at once when asked partway through a fade', () => {
    const still = mountStill('240ms');
    retireStill(still);
    expect(still.isConnected).toBe(true);
    retireStill(still, { fade: false });
    expect(still.isConnected).toBe(false);
  });

  it('removes it at once where there is no fade (reduced motion)', () => {
    const still = mountStill(null);
    retireStill(still);
    expect(still.isConnected).toBe(false);
  });

  it('does nothing for a still already gone', () => {
    const still = mountStill(null);
    still.remove();
    expect(() => {
      retireStill(still);
      retireStill(still, { fade: false });
    }).not.toThrow();
  });
});
