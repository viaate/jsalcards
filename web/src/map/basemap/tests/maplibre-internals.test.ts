// @vitest-environment node
/**
 * The parts of MapLibre's insides the map leans on, none of them in its
 * public API: the healer drops a failed tile from its source's tile manager
 * and asks the map for a frame (heal.ts), and a flight holds a source's
 * tile requests while a glide moves (index.ts). An upgrade that renames or
 * drops any of them would silently stop failed tiles coming back, or leave a
 * source held, so this fails first. The tile managers are not exported: their
 * methods are looked for in the page module the app ships (maplibre.ts).
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const pageModule = readFileSync(require.resolve('maplibre-gl/dist/maplibre-gl.mjs'), 'utf8');

/** How many times the page module defines or does `pattern`. */
const count = (pattern: RegExp): number => pageModule.match(new RegExp(pattern, 'g'))?.length ?? 0;

describe('MapLibre, inside', () => {
  it('lets the map be asked for a frame with its style brought up to date', async () => {
    const { Map } = await import('maplibre-gl');
    expect(typeof Map.prototype._update).toBe('function');
    expect(Map.prototype._update.length).toBeLessThanOrEqual(1);
    expect(typeof Map.prototype.isSourceLoaded).toBe('function');
  });

  it("keeps each source's tile manager on the style, by source id (Style#tileManagers)", () => {
    expect(count(/this\.tileManagers=\{\}/)).toBeGreaterThan(0);
  });

  it('lets a tile manager list its tiles, give one by id, and drop one', () => {
    expect(count(/[{};]getIds\(\)\{/)).toBeGreaterThan(0);
    expect(count(/[{};]getTileByID\([\w$]+\)\{/)).toBeGreaterThan(0);
    expect(count(/[{};]getRenderableIds\([\w$,=!]*\)\{/)).toBeGreaterThan(0);
    expect(count(/[{};]_removeTile\([\w$]+\)\{/)).toBeGreaterThan(0);
  });

  it('lets a tile manager be held and let go, asking for nothing while held', () => {
    expect(count(/[{};]pause\(\)\{this\._paused=!0\}/)).toBe(1);
    expect(count(/[{};]resume\(\)\{if\(!this\._paused\)return/)).toBe(1);
    // Its update, where it asks for the tiles a view needs, does nothing while it is held.
    expect(
      count(/update\([\w$]+,[\w$]+\)\{if\(!this\._sourceLoaded\|\|this\._paused\)return/),
    ).toBe(1);
  });
});
