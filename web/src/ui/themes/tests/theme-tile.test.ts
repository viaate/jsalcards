import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { themeOf, type ThemeId } from '../../../theme/themes';
import ThemeTile from '../ThemeTile.svelte';
import { PREVIEW_HEIGHT, PREVIEW_MARKS, PREVIEW_WIDTH, clearMarks } from '../preview';

function tile(id: ThemeId): { target: HTMLElement; destroy: () => void } {
  const target = document.createElement('div');
  document.body.append(target);
  const component = mount(ThemeTile, { target, props: { theme: themeOf(id) } });
  flushSync();
  return {
    target,
    destroy: () => {
      void unmount(component);
      target.remove();
    },
  };
}

beforeEach(() => {
  // The tile measures its picture (bind:clientWidth), which jsdom cannot.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    },
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  document.getElementById('sl-theme-tile-fonts')?.remove();
});

describe('a theme tile', () => {
  it('draws a theme this build may show', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    const { target, destroy } = tile('daylight');
    expect(target.querySelector('[data-theme-tile="daylight"]')).not.toBeNull();
    destroy();
  });

  it('draws nothing, and fetches no face, for a theme waiting for approval', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    const { target, destroy } = tile('snowball');
    expect(target.innerHTML.trim().replace(/<!---->/g, '')).toBe('');
    expect(document.getElementById('sl-theme-tile-fonts')).toBeNull();
    destroy();
  });

  it('draws it in a build that names it', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', 'snowball');
    const { target, destroy } = tile('snowball');
    expect(target.querySelector('[data-theme-tile="snowball"]')).not.toBeNull();
    destroy();
  });
});

describe('the tile’s marks', () => {
  const card = { left: 8, bottom: 8, width: 80, height: 48 };

  it('keeps every mark whole, clear of the edges and the corner card', () => {
    for (const width of [180, 260, PREVIEW_WIDTH]) {
      const reach = 6;
      const left = (PREVIEW_WIDTH - Math.min(width, PREVIEW_WIDTH)) / 2;
      const shown = clearMarks(PREVIEW_MARKS, { width, card }, reach);
      expect(shown.length).toBeGreaterThan(5);
      for (const { x, y } of shown) {
        expect(x - reach).toBeGreaterThanOrEqual(left);
        expect(x + reach).toBeLessThanOrEqual(left + Math.min(width, PREVIEW_WIDTH));
        expect(y - reach).toBeGreaterThanOrEqual(0);
        expect(y + reach).toBeLessThanOrEqual(PREVIEW_HEIGHT);
        const underCard =
          x >= left + card.left - reach &&
          x <= left + card.left + card.width + reach &&
          y >= PREVIEW_HEIGHT - card.bottom - card.height - reach;
        expect(underCard).toBe(false);
      }
    }
  });
});
