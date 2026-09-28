/**
 * The view a cut leaves (held-frame.ts): copied onto a canvas right over the
 * map's, still, and let go at once or faded out once the map has drawn the
 * new place.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HELD_FRAME_CLASS, HELD_FRAME_FADE_MS, heldFrame } from '../held-frame';

describe('the held frame', () => {
  let source: HTMLCanvasElement;
  const drawn: unknown[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '<div class="maplibregl-canvas-container"></div>';
    source = document.createElement('canvas');
    source.width = 2880;
    source.height = 1800;
    document.querySelector('.maplibregl-canvas-container')?.append(source);
    drawn.length = 0;
    // jsdom draws nothing: a 2D context that records what it is asked to copy.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
      () =>
        ({
          drawImage: (image: unknown) => drawn.push(image),
        }) as unknown as CanvasRenderingContext2D,
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  const copies = (): HTMLCanvasElement[] => [
    ...document.querySelectorAll<HTMLCanvasElement>(`canvas.${HELD_FRAME_CLASS}`),
  ];

  it('copies the map’s frame at its full size onto a canvas right over it, taking no pointer', () => {
    const frame = heldFrame();
    expect(frame.hold(source)).toBe(true);
    expect(frame.held).toBe(true);
    expect(drawn).toEqual([source]);
    const [copy] = copies();
    expect(copy).toBeDefined();
    expect(source.nextElementSibling).toBe(copy);
    expect(copy?.width).toBe(2880);
    expect(copy?.height).toBe(1800);
    expect(copy?.style.position).toBe('absolute');
    expect(copy?.style.width).toBe('100%');
    expect(copy?.style.height).toBe('100%');
    expect(copy?.style.pointerEvents).toBe('none');
    expect(copy?.style.opacity).toBe('1');
    expect(copy?.getAttribute('aria-hidden')).toBe('true');
    // Nothing over the map filters or blends it.
    expect(copy?.style.filter).toBe('');
    expect(copy?.style.mixBlendMode).toBe('');
  });

  it('holds one frame at a time', () => {
    const frame = heldFrame();
    frame.hold(source);
    frame.hold(source);
    expect(copies()).toHaveLength(1);
  });

  it('lets go at once, or fades out and then lets go', () => {
    const frame = heldFrame();
    frame.hold(source);
    frame.release(false);
    expect(copies()).toHaveLength(0);
    expect(frame.held).toBe(false);

    frame.hold(source);
    frame.release(true);
    const [copy] = copies();
    expect(copy?.style.transition).toContain(`${String(HELD_FRAME_FADE_MS)}ms`);
    vi.advanceTimersByTime(20);
    expect(copy?.style.opacity).toBe('0');
    expect(frame.held).toBe(true);
    vi.advanceTimersByTime(HELD_FRAME_FADE_MS + 50);
    expect(copies()).toHaveLength(0);
    expect(frame.held).toBe(false);
  });

  it('holds nothing where the page cannot copy the frame', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const frame = heldFrame();
    expect(frame.hold(source)).toBe(false);
    expect(frame.held).toBe(false);
    expect(copies()).toHaveLength(0);
    frame.release(true);
    expect(copies()).toHaveLength(0);
  });
});
