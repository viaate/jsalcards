import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { themeOf, type ThemeId } from '../../../theme/themes';
import ThemeTile from '../ThemeTile.svelte';
import {
  PREVIEW_HEIGHT,
  PREVIEW_MARKS,
  PREVIEW_SPECKS,
  PREVIEW_WIDTH,
  clearMarks,
  spacedMarks,
} from '../preview';

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
  vi.restoreAllMocks();
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

  it('draws Snowball’s night as soft lights over pale specks, never ink-ringed marks', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', 'snowball');
    // As a phone lays the tile out: the picture 320 px wide, the corner card 80 by 48.
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains('pv') ? 320 : 80;
    });
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(48);
    const { target, destroy } = tile('snowball');
    const snowball = themeOf('snowball');
    const lights = [...target.querySelectorAll('g.lights circle')];
    expect(lights.length).toBeGreaterThan(3);
    for (const light of lights)
      expect(light.getAttribute('fill')).toMatch(/^url\(#tile-glow-snowball-[0-3]\)$/);
    // Each light's halo is one of the four statuses' colors, solid at its middle.
    const centers = [...target.querySelectorAll('radialGradient stop[offset="0"]')].map((stop) =>
      stop.getAttribute('stop-color'),
    );
    expect(centers.slice(0, 4)).toEqual([
      snowball.tokens.closed,
      snowball.tokens.delayed,
      snowball.tokens.remote,
      snowball.tokens.early,
    ]);
    // The open schools are faint specks, and no mark anywhere is stroked in ink.
    expect(target.querySelectorAll(`circle[r="1"][fill="${snowball.tokens.dot}"]`)).toHaveLength(
      PREVIEW_SPECKS.length,
    );
    for (const ink of [snowball.tokens.border2, '#0a64c8'])
      expect(target.querySelector(`svg [stroke="${ink}"]`)).toBeNull();
    destroy();
  });

  it('draws every other theme’s marks as it did', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    const { target, destroy } = tile('aurora');
    expect(target.querySelector('g.lights')).toBeNull();
    expect(target.querySelector('radialGradient')).toBeNull();
    expect(target.querySelectorAll('svg circle').length).toBeGreaterThanOrEqual(
      PREVIEW_MARKS.length,
    );
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

describe('the cartoon night’s lights', () => {
  it('keeps every light at least its gap from the others, and no open school among them', () => {
    for (const gap of [8, 12, 20]) {
      const kept = spacedMarks(gap);
      expect(kept.length).toBeGreaterThan(3);
      for (const [i, a] of kept.entries()) {
        expect(a.status).not.toBe(4);
        for (const b of kept.slice(i + 1))
          expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(gap);
      }
    }
  });

  it('sets the open specks inside the picture, under the river', () => {
    for (const { x, y } of PREVIEW_SPECKS) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(PREVIEW_WIDTH);
      expect(y).toBeGreaterThanOrEqual(56);
      expect(y).toBeLessThanOrEqual(PREVIEW_HEIGHT);
    }
  });
});
