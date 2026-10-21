import { describe, expect, it } from 'vitest';

import { followKeyboard, keyboardLift, scrollToShow } from '../keyboard';

describe('keyboardLift', () => {
  it('lifts by the part of the layout viewport the keyboard covers', () => {
    // iPhone 15 portrait: 844 px tall, the keyboard and its bar take 336.
    expect(keyboardLift(844, { height: 508, offsetTop: 0 })).toEqual({ lift: 336, height: 508 });
  });

  it('counts a visual viewport that iOS scrolled down within the layout', () => {
    expect(keyboardLift(844, { height: 508, offsetTop: 120 })).toEqual({ lift: 216, height: 508 });
  });

  it('leaves the sheet alone with no keyboard, a one-pixel wobble, or no visual viewport', () => {
    expect(keyboardLift(844, { height: 844, offsetTop: 0 })).toBeNull();
    expect(keyboardLift(844, { height: 843.4, offsetTop: 0 })).toBeNull();
    expect(keyboardLift(844, null)).toBeNull();
    expect(keyboardLift(0, { height: 500, offsetTop: 0 })).toBeNull();
  });

  it('is nothing on a desktop window, whatever its size', () => {
    for (const h of [600, 900, 1440])
      expect(keyboardLift(h, { height: h, offsetTop: 0 })).toBeNull();
  });
});

describe('scrollToShow', () => {
  const box = { top: 100, bottom: 500 };

  it('keeps the scroll when the field shows', () => {
    expect(scrollToShow(40, box, { top: 200, bottom: 244 })).toBe(40);
  });

  it('scrolls down to a field under the visible part', () => {
    expect(scrollToShow(0, box, { top: 520, bottom: 564 })).toBe(76);
  });

  it('scrolls up to a field above it, not past the top', () => {
    expect(scrollToShow(80, box, { top: 60, bottom: 104 })).toBe(28);
    expect(scrollToShow(10, box, { top: 20, bottom: 64 })).toBe(0);
  });

  it('shows the top of a field taller than the box', () => {
    expect(scrollToShow(0, box, { top: 150, bottom: 900 })).toBe(38);
  });
});

describe('followKeyboard', () => {
  it('sets the lift on the sheet as the visual viewport shrinks and clears it after', () => {
    const viewport = Object.assign(new EventTarget(), { height: 800, offsetTop: 0 });
    const win = {
      visualViewport: viewport,
      innerHeight: 800,
      document: { documentElement: { clientHeight: 800 }, activeElement: null },
    } as unknown as Window;
    const sheet = document.createElement('div');
    const stop = followKeyboard(sheet, win);
    expect(sheet.style.getPropertyValue('--keyboard-lift')).toBe('');
    viewport.height = 460;
    viewport.dispatchEvent(new Event('resize'));
    expect(sheet.style.getPropertyValue('--keyboard-lift')).toBe('340px');
    expect(sheet.style.getPropertyValue('--visible-height')).toBe('460px');
    viewport.height = 800;
    viewport.dispatchEvent(new Event('resize'));
    expect(sheet.style.getPropertyValue('--keyboard-lift')).toBe('');
    stop();
    viewport.height = 400;
    viewport.dispatchEvent(new Event('resize'));
    expect(sheet.style.getPropertyValue('--keyboard-lift')).toBe('');
  });
});
