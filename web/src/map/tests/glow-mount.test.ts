import type { Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import { NOTHING_LIT } from '../../data/closings';
import type { LitSchools } from '../../data/closings';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE } from '../basemap/ids';
import { mountGlow } from '../glow-mount';

type Call = readonly [what: 'set' | 'remove', id: string | number | undefined, value?: unknown];

/** Enough of a map for the glow: a style that loads when told, and the feature states set on it. */
class FakeMap {
  loaded = false;
  hasSchools: boolean;
  calls: Call[] = [];
  private onLoad: (() => void)[] = [];

  constructor({ hasSchools = true } = {}) {
    this.hasSchools = hasSchools;
  }

  load(): void {
    this.loaded = true;
    for (const listener of this.onLoad.splice(0)) listener();
  }

  isStyleLoaded(): boolean {
    return this.loaded;
  }
  once(_event: string, listener: () => void): void {
    this.onLoad.push(listener);
  }
  off(): void {
    this.onLoad = [];
  }
  getSource(id: string): object | undefined {
    return this.loaded && this.hasSchools && id === BASEMAP_IDS.schoolsSource ? {} : undefined;
  }
  getLayer(): undefined {
    return undefined;
  }
  getLayersOrder(): string[] {
    return [];
  }
  addLayer(): void {
    // The glow draws nothing without a GL context.
  }
  triggerRepaint(): void {
    // Nothing to draw.
  }
  setFeatureState(
    target: { source: string; sourceLayer?: string; id?: string | number },
    state: unknown,
  ): void {
    expect(target.source).toBe(BASEMAP_IDS.schoolsSource);
    expect(target.sourceLayer).toBe(SCHOOLS_TILE_LAYER);
    this.calls.push(['set', target.id, state]);
  }
  removeFeatureState(
    target: { source: string; sourceLayer?: string; id?: string | number },
    key?: string,
  ): void {
    expect(target.source).toBe(BASEMAP_IDS.schoolsSource);
    expect(target.sourceLayer).toBe(SCHOOLS_TILE_LAYER);
    this.calls.push(['remove', target.id, key]);
  }
}

/** Schools lit at these places in the directory, all closed. */
function lit(...schools: number[]): LitSchools {
  return {
    lngLat: new Float64Array(schools.flatMap(() => [-94.593, 39.036])),
    status: new Uint8Array(schools.length),
    kinds: new Uint8Array(schools.length),
    schools: new Set(schools),
    ids: schools.map((school) => `29000000000${String(school)}`),
    names: schools.map((school) => `School ${String(school)}`),
  };
}

function mount(map: FakeMap): ReturnType<typeof mountGlow> {
  return mountGlow(map as unknown as MapLibreMap);
}

describe('the glow on the map', () => {
  it('takes each school it lights off the quiet dots, by its place in the directory', () => {
    const map = new FakeMap();
    const glow = mount(map);
    // Lit before the style is in: marked as soon as it is.
    glow.light(lit(1, 5));
    expect(map.calls).toEqual([]);
    map.load();
    expect(map.calls).toEqual([
      ['set', 1, { [SCHOOL_LIT_STATE]: true }],
      ['set', 5, { [SCHOOL_LIT_STATE]: true }],
    ]);

    // The next file: a school no longer lit has its dot back; one still lit is left as it is.
    map.calls = [];
    glow.light(lit(5, 9));
    expect(map.calls).toEqual([
      ['remove', 1, SCHOOL_LIT_STATE],
      ['set', 9, { [SCHOOL_LIT_STATE]: true }],
    ]);

    // Nothing lit: every dot is back.
    map.calls = [];
    glow.light(NOTHING_LIT);
    expect(map.calls).toEqual([
      ['remove', 5, SCHOOL_LIT_STATE],
      ['remove', 9, SCHOOL_LIT_STATE],
    ]);
    map.calls = [];
    glow.light(NOTHING_LIT);
    expect(map.calls).toEqual([]);
  });

  it('keeps the schools it shows, for a tap on their light to find', () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    expect(glow.lit).toBeNull();
    const first = lit(1, 5);
    glow.light(first);
    expect(glow.lit).toBe(first);
    const next = lit(9);
    glow.light(next);
    expect(glow.lit).toBe(next);
    expect(glow.lit?.ids).toEqual(['290000000009']);
    glow.light(NOTHING_LIT);
    expect(glow.lit).toBe(NOTHING_LIT);
  });

  it('marks nothing on a map without the school tiles', () => {
    const map = new FakeMap({ hasSchools: false });
    map.load();
    const glow = mount(map);
    glow.light(lit(1, 5));
    glow.light(lit(2));
    expect(map.calls).toEqual([]);
  });
});
