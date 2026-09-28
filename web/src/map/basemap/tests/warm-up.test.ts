/**
 * The GPU work of the map's start, each part in a task of its own: MapLibre's
 * canvas handed over ready, and the programs its first frames draw with
 * built ahead of them.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { prepareCanvas, warmFirstPrograms, warmTilePrograms, withCanvas } from '../warm-up';

describe('the canvas made ahead of the map', () => {
  it('is the first canvas the document creates while the map is made, and only that one', () => {
    const prepared = document.createElement('canvas');
    const made = withCanvas(prepared, () => [
      document.createElement('canvas'),
      document.createElement('div'),
      document.createElement('canvas'),
    ]);
    expect(made[0]).toBe(prepared);
    expect(made[1]?.tagName).toBe('DIV');
    expect(made[2]).not.toBe(prepared);
    expect(made[2]?.tagName).toBe('CANVAS');
    // Afterwards the document creates canvases as usual.
    expect(document.createElement('canvas')).not.toBe(prepared);
    expect(Object.hasOwn(document, 'createElement')).toBe(false);
  });

  it('leaves the document as it was when making the map fails', () => {
    const prepared = document.createElement('canvas');
    expect(() =>
      withCanvas(prepared, () => {
        throw new Error('no WebGL');
      }),
    ).toThrow('no WebGL');
    expect(Object.hasOwn(document, 'createElement')).toBe(false);
    expect(document.createElement('canvas')).not.toBe(prepared);
  });

  it('is nothing to hand over where there is no WebGL2: the map is made as usual', async () => {
    // jsdom has no WebGL: MapLibre fails on its own canvas, as it would anyway.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    await expect(prepareCanvas({ width: 400, height: 800 }, 2)).resolves.toBeNull();
    vi.restoreAllMocks();
    const canvas = withCanvas(null, () => document.createElement('canvas'));
    expect(canvas.tagName).toBe('CANVAS');
  });
});

/** A map as the warm-ups see it: its painter, its style and its events. */
function fakeMap(
  layers: Record<
    string,
    { type: string; paint?: Record<string, unknown>; layout?: Record<string, unknown> }
  > = {},
) {
  const built: { name: string; configuration: unknown }[] = [];
  const listeners = new Map<string, ((event: unknown) => void)[]>();
  const style = { loaded: true };
  const painter: { style?: unknown; useProgram: (name: string, configuration?: unknown) => void } =
    {
      useProgram: (name, configuration) => {
        expect(painter.style).toBe(style);
        built.push({ name, configuration });
      },
    };
  const map = {
    painter,
    style,
    getLayer: (id: string) => layers[id],
    getPaintProperty: (id: string, name: string) => layers[id]?.paint?.[name],
    getLayoutProperty: (id: string, name: string) => layers[id]?.layout?.[name],
    on: (type: string, listener: (event: unknown) => void) => {
      listeners.set(type, [...(listeners.get(type) ?? []), listener]);
    },
    off: (type: string, listener: (event: unknown) => void) => {
      listeners.set(
        type,
        (listeners.get(type) ?? []).filter((candidate) => candidate !== listener),
      );
    },
  };
  const fire = (type: string, event: unknown): void => {
    for (const listener of listeners.get(type) ?? []) listener(event);
  };
  return { map: map as unknown as MapLibreMap, built, fire, listeners };
}

describe('the programs built ahead of the frames', () => {
  it('builds the first frame’s, each in a task of its own, with the style in hand', () => {
    const { map, built } = fakeMap();
    const tasks: (() => void)[] = [];
    warmFirstPrograms(map, (run) => tasks.push(run));
    expect(built).toEqual([]);
    expect(tasks).toHaveLength(2);
    for (const task of tasks) task();
    expect(built.map(({ name }) => name)).toEqual(['background', 'clippingMask']);
  });

  it('leaves a program MapLibre cannot build yet for it to build as it draws', () => {
    const { map } = fakeMap();
    (map.painter as unknown as { useProgram: () => void }).useProgram = () => {
      throw new Error('style not ready');
    };
    warmFirstPrograms(map, (run) => {
      expect(run).not.toThrow();
    });
  });

  it('builds each tile’s plain lines and names with the tile’s own configuration, once each', () => {
    const { map, built, fire, listeners } = fakeMap({
      lines: { type: 'line' },
      dashed: { type: 'line', paint: { 'line-dasharray': [2, 2] } },
      names: { type: 'symbol', layout: { 'text-field': ['get', 'name'] } },
      spaces: { type: 'symbol', layout: { 'icon-image': 'space' } },
      land: { type: 'fill' },
    });
    const tasks: (() => void)[] = [];
    const stop = warmTilePrograms(map, (run) => tasks.push(run));
    const lineConfiguration = { cacheKey: '/u_line-color' };
    const textConfiguration = { cacheKey: '/u_text-color' };
    const tile = {
      buckets: {
        lines: { programConfigurations: { get: () => lineConfiguration } },
        dashed: { programConfigurations: { get: () => ({ cacheKey: '/dash' }) } },
        names: { text: { programConfigurations: { get: () => textConfiguration } } },
        spaces: { text: { programConfigurations: { get: () => ({ cacheKey: '/icon' }) } } },
        land: { programConfigurations: { get: () => ({ cacheKey: '/fill' }) } },
      },
    };
    fire('sourcedata', { tile });
    // A second tile with the same programs builds nothing more; an event without a tile, nothing.
    fire('sourcedata', { tile });
    fire('sourcedata', {});
    for (const task of tasks) task();
    expect(built).toEqual([
      { name: 'line', configuration: lineConfiguration },
      { name: 'symbolSDF', configuration: textConfiguration },
    ]);
    stop();
    expect(listeners.get('sourcedata')).toEqual([]);
  });
});
