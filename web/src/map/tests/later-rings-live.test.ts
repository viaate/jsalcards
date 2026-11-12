// @vitest-environment node
/**
 * The later-day rings on a live map (map/later-rings.ts startLaterRings): when
 * the rings change, as today's lights are lit again, they are hidden in the
 * same turn and shown again only once the map holds the new rings, so no ring
 * shows for a moment where a new light now is.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { BASEMAP_IDS } from '../basemap/ids';
import { LATER_RING_LAYERS, LATER_SOURCE, startLaterRings } from '../later-rings';
import type { LaterMark } from '../../data/later-days';

/** A map with only what the rings use: its layers' visibility, its sources, its events. */
function fakeMap() {
  const layers = new Map<string, { visibility: string }>([
    [BASEMAP_IDS.glowSlotFlat, { visibility: 'visible' }],
  ]);
  const sources = new Map<string, { setData: (data: unknown) => Promise<void> }>();
  const listeners = new Map<string, Set<() => void>>();
  const pending: (() => void)[] = [];
  let loaded = true;
  const map = {
    getLayer: (id: string) => layers.get(id),
    addLayer: (layer: { id: string; layout?: { visibility?: string } }) => {
      layers.set(layer.id, { visibility: layer.layout?.visibility ?? 'visible' });
    },
    removeLayer: (id: string) => layers.delete(id),
    setLayoutProperty: (id: string, name: string, value: string) => {
      const layer = layers.get(id);
      if (layer !== undefined && name === 'visibility') layer.visibility = value;
    },
    getSource: (id: string) => sources.get(id),
    addSource: (id: string) => {
      sources.set(id, {
        // The worker takes the data in, and its tiles are made again after.
        setData: () =>
          new Promise<void>((resolve) => {
            pending.push(() => {
              loaded = false;
              resolve();
            });
          }),
      });
    },
    removeSource: (id: string) => sources.delete(id),
    isSourceLoaded: () => loaded,
    on: (type: string, listener: () => void) => {
      const set = listeners.get(type) ?? new Set();
      set.add(listener);
      listeners.set(type, set);
    },
    off: (type: string, listener: () => void) => listeners.get(type)?.delete(listener),
    hasImage: () => false,
    addImage: () => undefined,
    updateImage: () => undefined,
    setFeatureState: () => undefined,
    removeFeatureState: () => undefined,
  };
  return {
    map,
    /** Each ring layer's visibility. */
    visibility: () => LATER_RING_LAYERS.map((id) => layers.get(id)?.visibility),
    /** The worker done with the data handed it, and a turn for what waits on it. */
    async workerDone(): Promise<void> {
      for (const done of pending.splice(0)) done();
      await Promise.resolve();
      await Promise.resolve();
    },
    /** Every tile of the source made again. */
    tilesIn(): void {
      loaded = true;
      for (const listener of [...(listeners.get('sourcedata') ?? [])]) listener();
    },
  };
}

beforeAll(() => {
  // Only what the rings read of a page: its theme's colors and a canvas, none here, so each
  // ring's image is left out.
  vi.stubGlobal('document', {
    documentElement: {},
    createElement: () => ({ getContext: () => null }),
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  });
  vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }));
});

const DIRECTORY = {
  lngLat: Float64Array.from([-83.7, 38.1, -83.6, 38.2]),
  meta: { ids: ['a', 'b'] },
} as unknown as Parameters<ReturnType<typeof startLaterRings>['show']>[1];
const ONE: LaterMark[] = [{ school: 0, day: '2026-11-13', status: 0, near: Infinity }];
const TWO: LaterMark[] = [...ONE, { school: 1, day: '2026-11-13', status: 1, near: Infinity }];

describe('the later-day rings, as the lights are lit again', () => {
  it('hide in the same turn the rings change, and show again once every tile holds the new ones', async () => {
    const fake = fakeMap();
    const rings = startLaterRings(fake.map as never);
    expect(fake.map.getSource(LATER_SOURCE)).toBeDefined();
    expect(fake.visibility()).toEqual(['visible', 'visible', 'visible']);
    rings.show(ONE, DIRECTORY);
    // Hidden at once, before the map draws again.
    expect(fake.visibility()).toEqual(['none', 'none', 'none']);
    // The worker has the data, but the tiles are still being made: still hidden.
    await fake.workerDone();
    expect(fake.visibility()).toEqual(['none', 'none', 'none']);
    fake.tilesIn();
    expect(fake.visibility()).toEqual(['visible', 'visible', 'visible']);
    // The same rings again: nothing to hide.
    rings.show(ONE, DIRECTORY);
    expect(fake.visibility()).toEqual(['visible', 'visible', 'visible']);
  });

  it('show again only for the last of two changes made close together', async () => {
    const fake = fakeMap();
    const rings = startLaterRings(fake.map as never);
    rings.show(ONE, DIRECTORY);
    rings.show(TWO, DIRECTORY);
    expect(fake.visibility()).toEqual(['none', 'none', 'none']);
    await fake.workerDone();
    fake.tilesIn();
    expect(fake.visibility()).toEqual(['visible', 'visible', 'visible']);
    // Rings gone, as no school has a later day now: hidden until the map has none.
    rings.show([], DIRECTORY);
    expect(fake.visibility()).toEqual(['none', 'none', 'none']);
    await fake.workerDone();
    fake.tilesIn();
    expect(fake.visibility()).toEqual(['visible', 'visible', 'visible']);
  });
});
