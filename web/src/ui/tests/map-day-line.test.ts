import { flushSync } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MapDays } from '../../data/live';
import { startDayLine, type DayLine } from '../map-day-host';

const TUESDAY: MapDays = {
  days: [{ day: '2026-11-10', zones: ['America/Chicago'], today: false }],
  viewerToday: '2026-11-09',
};

/** A box with only its top and bottom set, as the line reads them. */
function box(top: number, bottom: number): DOMRect {
  return {
    top,
    bottom,
    left: 0,
    right: 0,
    width: 0,
    height: bottom - top,
    x: 0,
    y: top,
  } as DOMRect;
}

describe('the day line over the key', () => {
  let line: DayLine | undefined;

  afterEach(() => {
    line?.destroy();
    line = undefined;
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  /** A stage with the map's credits on it, open or closed, at these heights. */
  function stageWithCredits(open: boolean): { stage: HTMLElement; credits: HTMLElement } {
    const stage = document.createElement('div');
    stage.className = 'stage';
    stage.getBoundingClientRect = () => box(0, 800);
    document.body.append(stage);
    const credits = document.createElement('div');
    credits.className = open
      ? 'maplibregl-ctrl-attrib maplibregl-compact-show'
      : 'maplibregl-ctrl-attrib';
    credits.getBoundingClientRect = () => box(740, 780);
    stage.append(credits);
    return { stage, credits };
  }

  const shown = (stage: HTMLElement): HTMLElement | null => stage.querySelector('.map-day');

  it('starts, names the day and keeps clear of the credits in a browser with no ResizeObserver', () => {
    // jsdom has none, as some browsers the page still runs in do not: the line starts all the same.
    vi.stubGlobal('ResizeObserver', undefined);
    expect(typeof ResizeObserver).toBe('undefined');
    const { stage, credits } = stageWithCredits(true);
    line = startDayLine(stage);
    line.show(TUESDAY);
    flushSync();
    expect(shown(stage)?.textContent).toBe('Showing Tuesday');
    // Over the open credits: the stage's foot (800) less their top (740), and the gap.
    expect(shown(stage)?.style.bottom).toBe('66px');
    // The credits wrap anew as the window's width changes: heard by the window's resize.
    credits.getBoundingClientRect = () => box(700, 780);
    window.dispatchEvent(new Event('resize'));
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('106px');
  });

  it('hears the credits close and open with no ResizeObserver', async () => {
    vi.stubGlobal('ResizeObserver', undefined);
    const { stage, credits } = stageWithCredits(false);
    line = startDayLine(stage);
    line.show(TUESDAY);
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('');
    credits.classList.add('maplibregl-compact-show');
    await Promise.resolve();
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('66px');
    credits.classList.remove('maplibregl-compact-show');
    await Promise.resolve();
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('');
    // Stopped: the window's resize is no longer heard (nothing left to throw on).
    line.destroy();
    line = undefined;
    window.dispatchEvent(new Event('resize'));
  });

  it('finds the credits once the map puts them on the stage, with no ResizeObserver', async () => {
    vi.stubGlobal('ResizeObserver', undefined);
    const stage = document.createElement('div');
    stage.getBoundingClientRect = () => box(0, 800);
    document.body.append(stage);
    line = startDayLine(stage);
    line.show(TUESDAY);
    flushSync();
    const credits = document.createElement('div');
    credits.className = 'maplibregl-ctrl-attrib maplibregl-compact-show';
    credits.getBoundingClientRect = () => box(740, 780);
    stage.append(credits);
    await Promise.resolve();
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('66px');
  });

  it('watches the credits’ size with a ResizeObserver where the browser has one', () => {
    const observed: Element[] = [];
    let heard: (() => void) | null = null;
    let disconnected = false;
    class Sized {
      constructor(callback: () => void) {
        heard = callback;
      }
      observe(target: Element): void {
        observed.push(target);
      }
      disconnect(): void {
        disconnected = true;
      }
    }
    vi.stubGlobal('ResizeObserver', Sized);
    const { stage, credits } = stageWithCredits(true);
    line = startDayLine(stage);
    line.show(TUESDAY);
    flushSync();
    expect(observed).toEqual([credits]);
    credits.getBoundingClientRect = () => box(700, 780);
    (heard as (() => void) | null)?.();
    flushSync();
    expect(shown(stage)?.style.bottom).toBe('106px');
    line.destroy();
    line = undefined;
    expect(disconnected).toBe(true);
  });
});
