import { afterEach, describe, expect, it, vi } from 'vitest';

import { CLOSE_SHARE, FLICK, OVERDRAG, attachSheet, settle, speed, stretch } from '../sheet';
import type { Detents } from '../sheet';
import { OPEN_SHARE, openHeight } from '../sheet-geometry';

/** A 390 × 844 phone's detents: the name alone, half the screen, and up to under the search field. */
const DETENTS: Detents = { peek: 160, open: 422, full: 728 };

describe('openHeight', () => {
  it('opens the sheet to half the screen, never past its full height', () => {
    expect(OPEN_SHARE).toBe(0.5);
    expect(openHeight(844)).toBe(422);
    expect(openHeight(915)).toBe(458);
    expect(openHeight(667, 300)).toBe(300);
    expect(openHeight(0)).toBe(0);
  });
});

describe('settle', () => {
  const release = (visible: number, velocity: number, from: 'peek' | 'open' | 'full') =>
    settle({ visible, velocity, from, detents: DETENTS });

  it('rests at the detent nearest to where a slow drag is let go', () => {
    expect(release(430, 0, 'open')).toBe('open');
    expect(release(600, 0, 'open')).toBe('full');
    expect(release(250, 0, 'open')).toBe('peek');
    expect(release(700, 0, 'full')).toBe('full');
    expect(release(200, 0, 'peek')).toBe('peek');
  });

  it('goes one detent at most from where the drag started', () => {
    expect(release(700, 0, 'peek')).toBe('open');
    expect(release(170, 0, 'full')).toBe('open');
  });

  it('goes a step the way of a flick, however short the drag', () => {
    expect(release(440, FLICK + 0.1, 'open')).toBe('full');
    expect(release(410, -(FLICK + 0.1), 'open')).toBe('peek');
    expect(release(180, FLICK + 0.1, 'peek')).toBe('open');
    expect(release(720, -(FLICK + 0.1), 'full')).toBe('open');
    // Nothing is past full.
    expect(release(740, 3, 'full')).toBe('full');
  });

  it('closes down past the peek: let go well under it, or flicked down from it', () => {
    expect(release(DETENTS.peek * CLOSE_SHARE - 1, 0, 'open')).toBe('close');
    expect(release(150, -(FLICK + 0.1), 'peek')).toBe('close');
    expect(release(140, -0.1, 'peek')).toBe('peek');
    // A flick down from open stops at the peek.
    expect(release(300, -3, 'open')).toBe('peek');
  });
});

describe('stretch', () => {
  it('follows the finger up to full height, then gives less and less', () => {
    expect(stretch(300, DETENTS)).toBe(300);
    expect(stretch(-20, DETENTS)).toBe(0);
    expect(stretch(DETENTS.full, DETENTS)).toBe(DETENTS.full);
    const little = stretch(DETENTS.full + 10, DETENTS) - DETENTS.full;
    const far = stretch(DETENTS.full + 1000, DETENTS) - DETENTS.full;
    expect(little).toBeGreaterThan(0);
    expect(little).toBeLessThan(10);
    expect(far).toBeLessThan(OVERDRAG);
    expect(far).toBeGreaterThan(OVERDRAG * 0.9);
  });
});

describe('speed', () => {
  it('reads the last moves, rising positive, in pixels a millisecond', () => {
    expect(speed([])).toBe(0);
    expect(speed([{ t: 0, y: 500 }])).toBe(0);
    expect(
      speed([
        { t: 0, y: 500 },
        { t: 100, y: 400 },
        { t: 150, y: 300 },
      ]),
      // Only the moves of the last 90 ms: the drag's end, not its start.
    ).toBeCloseTo(2);
    expect(
      speed([
        { t: 0, y: 300 },
        { t: 16, y: 332 },
      ]),
    ).toBeCloseTo(-2);
  });
});

describe('attachSheet', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  function sheetElements() {
    const sheet = document.createElement('aside');
    const body = document.createElement('div');
    const head = document.createElement('header');
    body.append(head);
    sheet.append(body);
    document.body.append(sheet);
    return { sheet, body, head };
  }

  it('rises to its opening height, says where it goes, and leaves the element as it was', () => {
    vi.useFakeTimers();
    const { sheet, body, head } = sheetElements();
    const changes: string[] = [];
    const settled: string[] = [];
    const control = attachSheet({
      sheet,
      body,
      head: () => head,
      handles: () => [head],
      onclose: vi.fn(),
      onchange: (detent) => changes.push(detent),
      onsettle: (detent) => settled.push(detent),
    });
    expect(control.detent).toBe('open');
    expect(sheet.dataset.detent).toBe('open');
    expect(sheet.style.transform).toMatch(/^translate3d\(0(px)?, /);
    expect(changes).toEqual(['open']);
    // No transition ends here: the glide is said to be over all the same.
    vi.advanceTimersByTime(600);
    expect(settled).toEqual(['open']);

    control.toggle();
    expect(control.detent).toBe('full');
    control.toggle();
    expect(control.detent).toBe('open');
    expect(changes).toEqual(['open', 'full', 'open']);

    control.destroy();
    expect(sheet.dataset.detent).toBeUndefined();
    expect(sheet.style.transform).toBe('');
    expect(sheet.style.getPropertyValue('--sheet-offset')).toBe('');
  });

  it('glides away before the school closes', () => {
    vi.useFakeTimers();
    const { sheet, body, head } = sheetElements();
    const onclose = vi.fn();
    const settled: string[] = [];
    const control = attachSheet({
      sheet,
      body,
      head: () => head,
      handles: () => [head],
      onclose,
      onsettle: (detent) => settled.push(detent),
    });
    control.dismiss();
    expect(onclose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(600);
    expect(onclose).toHaveBeenCalledTimes(1);
    // Once going, nothing brings it back but another school.
    control.toggle();
    expect(control.detent).toBe('open');
    expect(settled).toEqual([]);
    control.destroy();
  });

  it('opens again at its opening height for another school', () => {
    const { sheet, body, head } = sheetElements();
    const control = attachSheet({
      sheet,
      body,
      head: () => head,
      handles: () => [head],
      onclose: vi.fn(),
    });
    control.toggle();
    expect(control.detent).toBe('full');
    control.reset();
    expect(control.detent).toBe('open');
    control.destroy();
  });
});
