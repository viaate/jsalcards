// @vitest-environment node
import { readFileSync } from 'node:fs';

import type { Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { NOTHING_LIT, filterLit } from '../../data/closings';
import type { LitSchools } from '../../data/closings';
import {
  SCHOOL_DOT_OPACITY,
  SCHOOL_DOT_RADIUS,
  SCHOOL_DUST_FROM,
  SCHOOL_DUST_UNTIL,
} from '../basemap/dots';
import { BASEMAP_IDS, SCHOOLS_TILE_LAYER, SCHOOL_LIT_STATE } from '../basemap/ids';
import type { GlowLayer } from '../glow';
import { DOT_COLOR, dustStyle, mountGlow, showsDust, srgbChannels } from '../glow-mount';
import type { DustSource } from '../glow-mount';
import { SHOW_ALL, showsSchool } from '../../state/filter';
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';

type Call = readonly [what: 'set' | 'remove', id: string | number | undefined, value?: unknown];

/**
 * Enough of a map for the glow: a style that loads when told, a zoom that moves when told, the
 * layer put on it and the feature states set on it.
 */
class FakeMap {
  loaded = false;
  hasSchools: boolean;
  calls: Call[] = [];
  zoom = 4;
  layer: GlowLayer | null = null;
  private onLoad: (() => void)[] = [];
  private onZoom: (() => void)[] = [];

  constructor({ hasSchools = true } = {}) {
    this.hasSchools = hasSchools;
  }

  load(): void {
    this.loaded = true;
    for (const listener of this.onLoad.splice(0)) listener();
  }

  zoomTo(zoom: number): void {
    this.zoom = zoom;
    for (const listener of [...this.onZoom]) listener();
  }

  /** Whether anything still listens to the zoom. */
  get watchingZoom(): boolean {
    return this.onZoom.length > 0;
  }

  isStyleLoaded(): boolean {
    return this.loaded;
  }
  getZoom(): number {
    return this.zoom;
  }
  once(_event: string, listener: () => void): void {
    this.onLoad.push(listener);
  }
  on(event: string, listener: () => void): void {
    if (event === 'zoom') this.onZoom.push(listener);
  }
  off(event: string, listener: () => void): void {
    if (event === 'zoom') this.onZoom = this.onZoom.filter((l) => l !== listener);
    else this.onLoad = this.onLoad.filter((l) => l !== listener);
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
  addLayer(layer: GlowLayer): void {
    // The glow draws nothing without a GL context.
    this.layer = layer;
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

/** Every promise callback so far run. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('the dust', () => {
  // Kansas City, beside it (private), and Boston.
  const schools = {
    lngLat: new Float64Array([-94.6, 39.1, -94.5, 39.0, -71.1, 42.4]),
    kind: new Uint8Array([0, 1, 0]),
    ids: ['a', 'b', 'c'],
    names: ['A', 'B', 'C'],
  };
  /** A source of the dust that says how often it was read. */
  function source(read: DustSource = () => Promise.resolve(schools)) {
    return vi.fn(read);
  }

  it('reads every school only once the map is at a zoom that shows it, and only once', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    const read = source();
    glow.dust(read);
    // The national view: nothing read.
    await settle();
    expect(read).not.toHaveBeenCalled();
    map.zoomTo(SCHOOL_DUST_FROM);
    expect(read).not.toHaveBeenCalled();
    // Zoomed in to where the dust shows: where each school is and who it is, and on the layer.
    map.zoomTo(6);
    expect(read).toHaveBeenCalledOnce();
    expect(map.watchingZoom).toBe(false);
    await settle();
    expect(map.layer?.stats.dust).toBe(3);
    map.zoomTo(7);
    glow.dust(read);
    expect(read).toHaveBeenCalledOnce();
  });

  it('reads it at once on a map that opens where it shows, and never where the tiles draw alone', () => {
    const inMetro = new FakeMap();
    inMetro.zoom = 12;
    const read = source();
    mount(inMetro).dust(read);
    expect(read).not.toHaveBeenCalled();
    const inState = new FakeMap();
    inState.zoom = 6.5;
    mount(inState).dust(read);
    expect(read).toHaveBeenCalledOnce();
    expect(showsDust(SCHOOL_DUST_UNTIL)).toBe(false);
    expect(showsDust(SCHOOL_DUST_UNTIL - 0.01)).toBe(true);
  });

  it('leaves each school the glow lights out of the dust, before the dust is in or after', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    glow.light(lit(0));
    glow.dust(source());
    map.zoomTo(8);
    await settle();
    expect(map.layer?.stats).toMatchObject({ dust: 3, dustHidden: 1 });
    glow.light(lit(1, 2));
    expect(map.layer?.stats.dustHidden).toBe(2);
    glow.light(NOTHING_LIT);
    expect(map.layer?.stats.dustHidden).toBe(0);
  });

  it('takes a school lit in a status or of a kind the menu hides back into the dust, as its dot is', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    glow.dust(source());
    map.zoomTo(8);
    await settle();
    // Kansas City closed, beside it delayed (a private school), and Boston closed.
    const today: LitSchools = {
      ...lit(0, 1, 2),
      status: new Uint8Array([0, 1, 0]),
      kinds: schools.kind,
    };
    const nearKansasCity = (): number[] =>
      [
        ...(glow.specks?.near(mercatorXFromLng(-94.55), mercatorYFromLat(39.05), 0.001) ?? []),
      ].sort();
    glow.light(filterLit(today, SHOW_ALL, false));
    expect(map.layer?.stats.dustHidden).toBe(3);
    expect(nearKansasCity()).toEqual([]);
    // Closed alone: the delayed school is a dot again, and a speck.
    const closed = filterLit(today, { ...SHOW_ALL, status: 0 }, false);
    glow.light(closed);
    expect(map.calls.at(-1)).toEqual(['remove', 1, SCHOOL_LIT_STATE]);
    expect(map.layer?.stats.dustHidden).toBe(2);
    expect(nearKansasCity()).toEqual([1]);
    // Public schools alone: no light, dot or speck for it.
    glow.showSchools((flags) => showsSchool({ ...SHOW_ALL, private: false }, flags));
    glow.light(filterLit(today, { ...SHOW_ALL, private: false }, false));
    expect(nearKansasCity()).toEqual([]);
    // Everything again.
    glow.showSchools((flags) => showsSchool(SHOW_ALL, flags));
    glow.light(filterLit(today, SHOW_ALL, false));
    expect(map.layer?.stats.dustHidden).toBe(3);
    expect(nearKansasCity()).toEqual([]);
  });

  it('shows the kinds of school the menu shows, before the dust is in or after', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    glow.showSchools((flags) => showsSchool({ ...SHOW_ALL, private: false }, flags));
    glow.dust(source());
    map.zoomTo(8);
    await settle();
    expect(map.layer?.stats.dustHidden).toBe(1);
    glow.showSchools((flags) => showsSchool({ ...SHOW_ALL, public: false }, flags));
    expect(map.layer?.stats.dustHidden).toBe(2);
    glow.showSchools((flags) => showsSchool(SHOW_ALL, flags));
    expect(map.layer?.stats.dustHidden).toBe(0);
  });

  it('shows the open school whatever its kind, as the dots do, before the dust is in or after', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    glow.showSchools((flags) => showsSchool({ ...SHOW_ALL, private: false }, flags));
    glow.select('b');
    glow.dust(source());
    map.zoomTo(8);
    await settle();
    const nearKansasCity = (): number[] =>
      [
        ...(glow.specks?.near(mercatorXFromLng(-94.55), mercatorYFromLat(39.05), 0.001) ?? []),
      ].sort();
    expect(map.layer?.stats.dustHidden).toBe(0);
    expect(nearKansasCity()).toEqual([0, 1]);
    glow.select(null);
    expect(map.layer?.stats.dustHidden).toBe(1);
    expect(nearKansasCity()).toEqual([0]);
    glow.select('b');
    expect(nearKansasCity()).toEqual([0, 1]);
    // A school the directory does not have keeps none.
    glow.select('z');
    expect(nearKansasCity()).toEqual([0]);
  });

  it('finds the schools drawn near a point, and who each is, as a tap reads them', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    expect(glow.specks).toBeNull();
    glow.dust(source());
    map.zoomTo(8);
    await settle();
    const specks = glow.specks;
    expect(specks).toMatchObject({ ids: schools.ids, names: schools.names });
    expect(specks?.lngLat).toBe(schools.lngLat);
    const nearKansasCity = (): number[] =>
      [...(specks?.near(mercatorXFromLng(-94.55), mercatorYFromLat(39.05), 0.001) ?? [])].sort();
    expect(nearKansasCity()).toEqual([0, 1]);
    // Not a school the glow lights, nor one of a kind the menu hides.
    glow.light(lit(0));
    expect(nearKansasCity()).toEqual([1]);
    glow.showSchools((flags) => showsSchool({ ...SHOW_ALL, private: false }, flags));
    expect(nearKansasCity()).toEqual([]);
  });

  it('is drawn only once the directory is in, where each school is and who it is together', async () => {
    let read: (value: typeof schools) => void = () => undefined;
    const map = new FakeMap();
    map.load();
    map.zoom = 7;
    const glow = mount(map);
    glow.dust(source(() => new Promise((resolve) => (read = resolve))));
    await settle();
    expect(map.layer?.stats.dust).toBe(0);
    expect(glow.specks).toBeNull();
    read(schools);
    await settle();
    expect(map.layer?.stats.dust).toBe(3);
    expect(glow.specks?.ids).toEqual(schools.ids);
  });

  it('shows nothing when there is no directory, or reading it fails, and nothing once removed', async () => {
    const map = new FakeMap();
    map.load();
    map.zoom = 7;
    mount(map).dust(source(() => Promise.resolve(null)));
    const failing = new FakeMap();
    failing.load();
    failing.zoom = 7;
    mount(failing).dust(source(() => Promise.reject(new Error('offline'))));
    const gone = new FakeMap();
    gone.load();
    const glow = mount(gone);
    glow.dust(source());
    glow.remove();
    gone.zoomTo(7);
    await settle();
    expect(map.layer?.stats.dust).toBe(0);
    expect(failing.layer?.stats.dust).toBe(0);
    expect(gone.layer?.stats.dust).toBe(0);
    expect(glow.specks).toBeNull();
  });

  it('draws with the dots’ own curves, in their white', () => {
    const style = dustStyle();
    expect(style).toMatchObject({
      from: SCHOOL_DUST_FROM,
      until: SCHOOL_DUST_UNTIL,
      radius: SCHOOL_DOT_RADIUS,
      opacity: SCHOOL_DOT_OPACITY,
    });
    expect(style.color.map((c) => Math.round(c * 255))).toEqual([0xf5, 0xf5, 0xf5]);
    expect(srgbChannels('rgb(1, 2, 3)')).toBeNull();
    // The white the basemap draws the dots in: the page's --text-1.
    const css = readFileSync(new URL('../../styles/global.css', import.meta.url), 'utf8');
    expect(css).toContain(`--text-1: ${DOT_COLOR};`);
  });
});
