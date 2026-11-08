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
import {
  BASEMAP_IDS,
  SCHOOLS_TILE_LAYER,
  SCHOOL_COVERED_STATE,
  SCHOOL_LIT_STATE,
} from '../basemap/ids';
import type { GlowLayer } from '../glow';
import {
  DOT_COLOR,
  dustStyle,
  mountGlow,
  showsDust,
  srgbChannels,
  stateLineGray,
} from '../glow-mount';
import type { DustSource } from '../glow-mount';
import { SamePlacesBuild, atOnePlace, coveredBy, samePlacesNow } from '../same-places';
import type { SamePlaces } from '../same-places';
import { metresBetween } from '../../data/details-format';
import { format } from '../../copy-format';
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
    // On the map, as MapLibre puts it there, though it draws no frame here.
    this.layer = layer;
    layer.onAdd(this as unknown as MapLibreMap, {} as WebGL2RenderingContext);
  }
  getCanvasContainer(): Pick<HTMLElement, 'addEventListener' | 'removeEventListener'> {
    return { addEventListener: () => undefined, removeEventListener: () => undefined };
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

/** Each mounted glow's wait for the schools its light covers to be marked. */
const covering = new WeakMap<FakeMap, () => Promise<void>>();

/**
 * The glow on `map`, its covers worked out on the page (a test has no worker), and the wait
 * for them kept for `covered`.
 */
function mount(map: FakeMap): ReturnType<typeof mountGlow> {
  let busy = false;
  let waiting: (() => void)[] = [];
  const glow = mountGlow(map as unknown as MapLibreMap, {
    covers: {
      worker: () => null,
      covered: () => {
        busy = false;
        for (const call of waiting.splice(0)) call();
      },
    },
  });
  const light = glow.light.bind(glow);
  glow.light = (shown) => {
    busy = true;
    light(shown);
  };
  covering.set(map, () =>
    busy
      ? new Promise<void>((resolve) => {
          waiting.push(resolve);
        })
      : Promise.resolve(),
  );
  // Removed: nothing more is waited for.
  const remove = glow.remove.bind(glow);
  glow.remove = () => {
    busy = false;
    waiting = [];
    remove();
  };
  return glow;
}

/** The schools the last light on `map` covers, marked: in tasks after it, the index's first. */
async function covered(map: FakeMap): Promise<void> {
  await covering.get(map)?.();
}

/**
 * A directory's places, as points.bin gives them in millionths of a degree:
 * schools 0, 1 and 3 at one place, 2 and 4 at another, 5 a millionth east of
 * the first (a tenth of a metre), 6 alone, 7 a metre north of 6 (rounds to 1:
 * "Same place") and 8 two metres south of 6 (rounds to 2: not).
 */
function directoryPlaces(): Int32Array {
  const e6 = [
    [-94593001, 39036060],
    [-94593001, 39036060],
    [-71056000, 42358000],
    [-94593001, 39036060],
    [-71056000, 42358000],
    [-94593000, 39036060],
    [-100000000, 40000000],
    [-100000000, 40000009],
    [-100000000, 39999982],
  ];
  return Int32Array.from(e6.flat());
}

/** Schools lit at these places in a directory with these places, as data/closings.ts lights them. */
function litIn(places: Int32Array, ...schools: number[]): LitSchools {
  return {
    ...lit(...schools),
    lngLat: new Float64Array(
      schools.flatMap((school) => [
        (places[school * 2] ?? 0) * 1e-6,
        (places[school * 2 + 1] ?? 0) * 1e-6,
      ]),
    ),
    places,
  };
}

/** A place's degrees, as the directory reads them from its millionths. */
function degrees(places: Int32Array, school: number): [number, number] {
  return [(places[school * 2] ?? 0) * 1e-6, (places[school * 2 + 1] ?? 0) * 1e-6];
}

/** Feature-state calls, in an order of their own: the order schools at one place come in is none. */
function inAnyOrder(calls: readonly Call[]): string[] {
  return calls.map((call) => JSON.stringify(call)).sort();
}

/** The others at each school's place, from an index, in order. */
function listed(index: SamePlaces): number[][] {
  return Array.from({ length: index.start.length - 1 }, (_, i) =>
    [...index.near.subarray(index.start[i] ?? 0, index.start[i + 1] ?? 0)].sort((x, y) => x - y),
  );
}

describe('the schools at one place', () => {
  it('are those the panel calls at the same place: under 2 whole metres apart', () => {
    const places = directoryPlaces();
    expect(listed(samePlacesNow(places))).toEqual([
      [1, 3, 5],
      [0, 3, 5],
      [4],
      [0, 1, 5],
      [2],
      [0, 1, 3],
      [7],
      [6],
      [],
    ]);
    expect(samePlacesNow(places).shared).toBe(8);
    // As the panel rounds the details' metres (format.apart, scripts/stage-data.mjs).
    const metres = (a: number, b: number): number =>
      Math.round(metresBetween(...degrees(places, a), ...degrees(places, b)));
    for (let a = 0; a < 9; a++) {
      for (let b = 0; b < 9; b++) {
        if (a === b) continue;
        const said = format.apart(metres(a, b)) === 'Same place';
        expect(listed(samePlacesNow(places))[a]?.includes(b), `${String(a)}, ${String(b)}`).toBe(
          said,
        );
        expect(atOnePlace(...degrees(places, a), ...degrees(places, b))).toBe(said);
      }
    }
  });

  it('are judged by the metres the details give, to the same rounding, near the edge of it too', () => {
    // Pairs 1.3 to 1.7 m apart every way, across the country's latitudes.
    for (let n = 0; n < 2000; n++) {
      const lat = 19 + (n % 53);
      const lon = -160 + ((n * 7) % 93);
      const bearing = (n * 0.37) % (2 * Math.PI);
      const metres = 1.3 + ((n * 0.013) % 0.4);
      const dLat = (metres * Math.cos(bearing)) / 111_195;
      const dLon = (metres * Math.sin(bearing)) / (111_195 * Math.cos((lat * Math.PI) / 180));
      const [a, b, c, d] = [lon, lat, lon + dLon, lat + dLat];
      expect(atOnePlace(a, b, c, d)).toBe(Math.round(metresBetween(a, b, c, d)) < 2);
    }
  });

  it('are found across the edges of the cells the index buckets places in, and only there', () => {
    // A corner of the cells the index buckets places in (multiples of 2048 by 1024 millionths): schools
    // under half a metre apart across each edge and both diagonals, and others 1.4, 1.6, 2.2
    // and 2.6 m off, as Same place reads them (1, 2, 2 and 3 whole metres).
    const [x, y] = [-90001408, 40000512];
    const e6: [number, number][] = [
      [x, y],
      [x - 4, y],
      [x, y - 4],
      [x - 4, y - 4],
      [x - 4, y + 4],
      [x + 4, y - 4],
      [x, y - 13],
      [x, y - 14],
      [x, y + 20],
      [x - 30, y],
    ];
    const places = Int32Array.from(e6.flat());
    const index = samePlacesNow(places);
    expect(listed(index)[0]).toEqual([1, 2, 3, 4, 5, 6]);
    expect(listed(index)[4]).toContain(5);
    const count = e6.length;
    for (let a = 0; a < count; a++) {
      for (let b = 0; b < count; b++) {
        if (a === b) continue;
        const one = atOnePlace(...degrees(places, a), ...degrees(places, b));
        expect(listed(index)[a]?.includes(b), `${String(a)}, ${String(b)}`).toBe(one);
      }
    }
  });

  it('are built in slices that stop when told, to the same index', () => {
    const places = new Int32Array(6000 * 2);
    for (let i = 0; i < 6000; i++) {
      const spot = Math.floor(i / 3);
      places[i * 2] = -90000000 - spot * 37;
      places[i * 2 + 1] = 40000000 + spot * 11;
    }
    const build = new SamePlacesBuild(places);
    let slices = 0;
    let index: SamePlaces | null = null;
    while (index === null) {
      slices++;
      let looks = 0;
      index = build.step(() => ++looks > 1);
    }
    expect(slices).toBeGreaterThan(3);
    expect(listed(index)).toEqual(listed(samePlacesNow(places)));
  });

  it('that the glow does not light, beside one it lights, are covered; none where nothing is lit', () => {
    const places = directoryPlaces();
    const index = samePlacesNow(places);
    const at = (...schools: number[]): number[] =>
      [...coveredBy(index, Int32Array.from(schools))].sort((x, y) => x - y);
    expect(at(0)).toEqual([1, 3, 5]);
    expect(at(0, 1)).toEqual([3, 5]);
    expect(at(0, 1, 3, 4)).toEqual([2, 5]);
    expect(at(6)).toEqual([7]);
    expect(at(8)).toEqual([]);
    expect(at()).toEqual([]);
    // The menu's filter hides a lit school: the schools at its place are no longer covered.
    const today: LitSchools = { ...litIn(places, 0, 2), status: new Uint8Array([0, 1]) };
    const coveredIn = (shown: LitSchools): number[] =>
      [...coveredBy(index, Int32Array.from(shown.schools))].sort((x, y) => x - y);
    expect(coveredIn(filterLit(today, SHOW_ALL, false))).toEqual([1, 3, 4, 5]);
    expect(coveredIn(filterLit(today, { ...SHOW_ALL, status: 1 }, false))).toEqual([4]);
  });

  it('are covered however many share a place and however many are lit', () => {
    // 2,000 places, three schools at each; the first of each lit.
    const places = new Int32Array(6000 * 2);
    for (let i = 0; i < 6000; i++) {
      const spot = Math.floor(i / 3);
      places[i * 2] = -90000000 - spot * 37;
      places[i * 2 + 1] = 40000000 + spot * 11;
    }
    const lighted = Array.from({ length: 2000 }, (_, spot) => spot * 3);
    const found = coveredBy(samePlacesNow(places), Int32Array.from(lighted));
    expect(found.length).toBe(4000);
    expect(new Set(found).size).toBe(4000);
    expect([...found].every((school) => school % 3 !== 0)).toBe(true);
  });
});

describe('the glow on the map', () => {
  it('takes each school at the place of one it lights off the quiet dots too, once the index is in', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    const places = directoryPlaces();
    // The first light marks the lit school at once, and covers none until the directory's
    // index is built, in tasks after the light.
    glow.light(litIn(places, 0));
    expect(map.calls).toEqual([['set', 0, { [SCHOOL_LIT_STATE]: true }]]);
    map.calls = [];
    await covered(map);
    expect(inAnyOrder(map.calls)).toEqual(
      inAnyOrder([
        ['set', 1, { [SCHOOL_COVERED_STATE]: true }],
        ['set', 3, { [SCHOOL_COVERED_STATE]: true }],
        ['set', 5, { [SCHOOL_COVERED_STATE]: true }],
      ]),
    );
    // Another school at that place lit instead, with the index in: each dot takes its own state,
    // the lit ones at once, the covered in a task after it.
    map.calls = [];
    glow.light(litIn(places, 1));
    expect(inAnyOrder(map.calls)).toEqual(
      inAnyOrder([
        ['remove', 0, SCHOOL_LIT_STATE],
        ['set', 1, { [SCHOOL_LIT_STATE]: true }],
      ]),
    );
    await covered(map);
    expect(inAnyOrder(map.calls)).toEqual(
      inAnyOrder([
        ['remove', 0, SCHOOL_LIT_STATE],
        ['set', 1, { [SCHOOL_LIT_STATE]: true }],
        ['remove', 1, SCHOOL_COVERED_STATE],
        ['set', 0, { [SCHOOL_COVERED_STATE]: true }],
      ]),
    );
    // Nothing lit: every dot is back.
    map.calls = [];
    glow.light(NOTHING_LIT);
    await covered(map);
    expect(inAnyOrder(map.calls)).toEqual(
      inAnyOrder([
        ['remove', 1, SCHOOL_LIT_STATE],
        ['remove', 0, SCHOOL_COVERED_STATE],
        ['remove', 3, SCHOOL_COVERED_STATE],
        ['remove', 5, SCHOOL_COVERED_STATE],
      ]),
    );
    map.calls = [];
    glow.light(NOTHING_LIT);
    await covered(map);
    expect(map.calls).toEqual([]);
  });

  it('makes no worker for them as it goes on the map, nor until a light has schools lit', async () => {
    const map = new FakeMap();
    map.load();
    let made = 0;
    let waiting: (() => void)[] = [];
    const glow = mountGlow(map as unknown as MapLibreMap, {
      covers: {
        worker: () => {
          made++;
          return null;
        },
        covered: () => {
          for (const call of waiting.splice(0)) call();
        },
      },
    });
    const done = (): Promise<void> =>
      new Promise((resolve) => {
        waiting.push(resolve);
      });
    for (let n = 0; n < 20; n++) await settle();
    glow.light(NOTHING_LIT);
    await done();
    expect(made).toBe(0);
    const places = directoryPlaces();
    glow.light(litIn(places, 2));
    await done();
    expect(made).toBe(1);
    glow.remove();
    waiting = [];
  });

  it('covers them a few tasks after the first light on a page that is never idle', async () => {
    // A page drawing its map every frame: an idle callback never runs, and no timer comes due.
    const idle = vi.fn();
    vi.stubGlobal('requestIdleCallback', idle);
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    try {
      const map = new FakeMap();
      map.load();
      const glow = mount(map);
      const places = directoryPlaces();
      glow.light(litIn(places, 2));
      map.calls = [];
      await covered(map);
      expect(map.calls).toEqual([['set', 4, { [SCHOOL_COVERED_STATE]: true }]]);
      expect(idle).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  it('covers the schools of the light shown when the index comes in, not of one before it', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    const places = directoryPlaces();
    glow.light(litIn(places, 0));
    glow.light(litIn(places, 2));
    map.calls = [];
    await covered(map);
    expect(map.calls).toEqual([['set', 4, { [SCHOOL_COVERED_STATE]: true }]]);
    // Removed before it comes in: nothing more is marked.
    const other = new FakeMap();
    other.load();
    const gone = mount(other);
    const elsewhere = directoryPlaces();
    gone.light(litIn(elsewhere, 0));
    gone.remove();
    other.calls = [];
    for (let n = 0; n < 20; n++) await settle();
    expect(other.calls).toEqual([]);
  });

  it('covers a lit one’s neighbours only once the map has its school tiles', async () => {
    const map = new FakeMap();
    const glow = mount(map);
    const places = directoryPlaces();
    glow.light(litIn(places, 2));
    for (let n = 0; n < 20; n++) await settle();
    expect(map.calls).toEqual([]);
    map.load();
    await covered(map);
    expect(map.calls).toEqual([
      ['set', 2, { [SCHOOL_LIT_STATE]: true }],
      ['set', 4, { [SCHOOL_COVERED_STATE]: true }],
    ]);
  });

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

  it('reads the gray of the state lines from the style, once the map has them', () => {
    const colors = new Map<string, string>();
    const map = {
      getLayer: (id: string) => (colors.has(id) ? {} : undefined),
      getPaintProperty: (id: string, name: string) => {
        expect(name).toBe('line-color');
        return colors.get(id);
      },
    } as unknown as MapLibreMap;
    expect(stateLineGray(map)).toBeNull();
    colors.set(BASEMAP_IDS.usStates, '#4d4d4d');
    expect(stateLineGray(map)).toBeCloseTo(0x4d / 255, 12);
    colors.set(BASEMAP_IDS.usStates, 'rgba(1, 2, 3, 1)');
    expect(stateLineGray(map)).toBeNull();
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

  it('leaves a school at the very place of one it lights out of the dust too, and out of a tap’s reach', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    // Schools 0 and 1 at one place.
    const shared = {
      ...schools,
      lngLat: new Float64Array([-94.6, 39.1, -94.6, 39.1, -71.1, 42.4]),
    };
    glow.dust(source(() => Promise.resolve(shared)));
    map.zoomTo(8);
    await settle();
    const atKansasCity = (): number[] =>
      [
        ...(glow.specks?.near(mercatorXFromLng(-94.6), mercatorYFromLat(39.1), 0.0001) ?? []),
      ].sort();
    expect(atKansasCity()).toEqual([0, 1]);
    const sharedPlaces = Int32Array.from(shared.lngLat, (degrees) => Math.round(degrees * 1e6));
    glow.light(litIn(sharedPlaces, 0));
    expect(map.layer?.stats.dustHidden).toBe(1);
    await covered(map);
    expect(map.layer?.stats.dustHidden).toBe(2);
    expect(atKansasCity()).toEqual([]);
    glow.light(NOTHING_LIT);
    expect(map.layer?.stats.dustHidden).toBe(1);
    await covered(map);
    expect(map.layer?.stats.dustHidden).toBe(0);
    expect(atKansasCity()).toEqual([0, 1]);
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

  it('follows the directory the schools lit are places in, once it reads the dust', async () => {
    const map = new FakeMap();
    map.load();
    const glow = mount(map);
    // The copy read first, then the one the live file names: the same schools, Boston first.
    const fresh = {
      lngLat: new Float64Array([-71.1, 42.4, -94.6, 39.1, -94.5, 39.0]),
      kind: new Uint8Array([0, 0, 1]),
      ids: ['c', 'a', 'b'],
      names: ['C', 'A', 'B'],
    };
    let copy = schools;
    const read = source(() => Promise.resolve(copy));
    glow.dust(read);
    // Lit at the national view: the dust is not read for it.
    glow.light(lit(0));
    await settle();
    expect(read).not.toHaveBeenCalled();
    map.zoomTo(8);
    await settle();
    expect(glow.specks?.ids).toEqual(schools.ids);
    // Lit again from the same copy: read, not drawn again.
    if (map.layer === null) throw new Error('No glow layer on the map');
    const setDust = vi.spyOn(map.layer, 'setDust');
    glow.light(lit(1));
    await settle();
    expect(read).toHaveBeenCalledTimes(2);
    expect(setDust).not.toHaveBeenCalled();
    // Lit from the copy the live file names: the dust is that copy, with the school lit left out.
    copy = fresh;
    glow.light(lit(0));
    await settle();
    expect(setDust).toHaveBeenCalledOnce();
    expect(glow.specks?.ids).toEqual(fresh.ids);
    const near = (lon: number, lat: number): number[] => [
      ...(glow.specks?.near(mercatorXFromLng(lon), mercatorYFromLat(lat), 0.001) ?? []),
    ];
    expect(near(-71.1, 42.4)).toEqual([]);
    expect(near(-94.55, 39.05).sort()).toEqual([1, 2]);
    expect(map.layer.stats.dustHidden).toBe(1);
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
