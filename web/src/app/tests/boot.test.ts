import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createDirectory, parsePoints } from '../../data/directory';
import type { DirectorySource } from '../../data/directory';
import { createDataFiles } from '../../data/files';
import { testMeta, testPoints } from '../../data/tests/builders';
import { DETAILS_INDEX_PATH } from '../../data/details-format';
import type { Basemap } from '../../map/basemap';
import type { DustSource, Glow } from '../../map/glow-mount';
import type { SchoolTapOptions } from '../../map/school-taps';
import type { SearchHit } from '../../search';
import { SHOW_ALL } from '../../state/filter';
import { PIN_KEY, encodePin } from '../../state/pin';
import { createUrlStore } from '../../state/url-store';
import type { UrlStoreHost } from '../../state/url-store';
import { boot } from '../boot';
// Loaded here as well as on demand, so a busy machine's first transform does not run out a wait.
import '../school';
import type { BootOptions } from '../boot';
import type { AppData, Target } from '../data';
import type { Screen } from '../frame';
import { PANEL_EDGE, clearOfPanel, openArea, panelWidth } from '../frame';
import { ZOOM, viewForHit } from '../startup';

/**
 * The taps on the map, as boot wires them (map/school-taps.ts has its own
 * tests): what they are attached with, and the clicks handed to them.
 */
const taps = vi.hoisted(() => ({ attach: vi.fn(), click: vi.fn(), stop: vi.fn() }));
vi.mock('../../map/school-taps', () => ({
  attachSchoolTaps: (...args: unknown[]) => {
    taps.attach(...args);
    return { click: taps.click, stop: taps.stop };
  },
}));

/** How long a test waits for code loaded on demand, on a busy machine. */
const WAIT = { timeout: 4_000 };
const PEMBROKE_HILL = 'A1902690';
const ROOT = 'https://snow.test/data/';

/** A tab's session history: entries, pushState, replaceState, and Back and Forward that fire popstate. */
class FakeTab extends EventTarget implements UrlStoreHost {
  entries: string[];
  index = 0;
  pushes = 0;
  constructor(url: string) {
    super();
    this.entries = [url];
  }
  get url(): string {
    return this.entries[this.index] ?? '';
  }
  get location(): { href: string } {
    return { href: this.url };
  }
  readonly history: UrlStoreHost['history'] = ((tab: FakeTab) => ({
    state: null,
    pushState(_state: unknown, _unused: string, url?: string | URL | null): void {
      tab.pushes += 1;
      tab.entries.splice(tab.index + 1, Infinity, String(url));
      tab.index += 1;
    },
    replaceState(_state: unknown, _unused: string, url?: string | URL | null): void {
      tab.entries[tab.index] = String(url);
    },
  }))(this);
  setTimeout(handler: () => void, timeout: number): number {
    return setTimeout(handler, timeout) as unknown as number;
  }
  clearTimeout(id: number | undefined): void {
    clearTimeout(id);
  }
  /** Back; false when it would leave the page. */
  back(): boolean {
    if (this.index === 0) return false;
    this.index -= 1;
    this.dispatchEvent(new Event('popstate'));
    return true;
  }
  forward(): void {
    if (this.index + 1 >= this.entries.length) return;
    this.index += 1;
    this.dispatchEvent(new Event('popstate'));
  }
  urls(): string[] {
    return this.entries.map((entry) => new URL(entry).search);
  }
}

function withDirectory(): AppData {
  const schools = [
    { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: 0 },
    { id: PEMBROKE_HILL, name: 'Second', lon: -94.593001, lat: 39.03606, district: -1 },
  ];
  const meta = testMeta(schools, ['0100005']);
  const points = parsePoints(testPoints(schools, 1), meta);
  if (points === null) throw new Error('points did not parse');
  const directory = createDirectory(meta, points);
  const source: DirectorySource = {
    get: () => Promise.resolve(directory),
    positions: () => Promise.resolve({ lngLat: points.lngLat, kind: points.kind }),
  };
  return {
    files: createDataFiles(['schools/meta.json', 'schools/points.bin'], ROOT),
    directories: () => Promise.resolve(source),
  };
}

/** A glow layer that draws nothing, and hears what it is told. */
function fakeGlow() {
  return {
    light: vi.fn(),
    lit: null,
    dust: vi.fn<(source: DustSource) => void>(),
    showSchools: vi.fn<(shows: (flags: number) => boolean) => void>(),
    select: vi.fn<(id: string | null) => void>(),
    specks: null,
    remove: vi.fn(),
  };
}

const NO_DATA: AppData = {
  files: createDataFiles([], ROOT),
  directories: () => Promise.resolve(null),
};

function start(
  url: string,
  data: AppData,
  moved = false,
  glow: Glow | null = null,
  frame?: BootOptions['frame'],
  late: Pick<BootOptions, 'addressOpens' | 'formats'> = {},
) {
  const tab = new FakeTab(url);
  const links = createUrlStore({ host: tab });
  const controller = new AbortController();
  const shown: Target[] = [];
  const results: unknown[] = [];
  // A map that is up but never finishes its first frame, and no glow layer on it.
  const map = {
    moved,
    ready: new Promise<void>(() => undefined),
    showSchools: () => undefined,
  } as unknown as Basemap;
  const options: BootOptions = {
    links,
    map: Promise.resolve(map),
    glow: Promise.resolve(glow),
    signal: controller.signal,
    show: (target) => shown.push(target),
    listId: 'list',
    onResults: (next) => results.push(next),
    data,
    ...(frame === undefined ? {} : { frame }),
    ...late,
  };
  const services = boot(options);
  return { tab, links, controller, shown, results, services };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe('at startup', () => {
  it('a plain visit opens the pinned school without a history entry, and goes to it', async () => {
    localStorage.setItem(PIN_KEY, encodePin(PEMBROKE_HILL));
    const { tab, links, shown, controller } = start('https://snow.test/', withDirectory());
    expect(links.state.selection).toEqual({ kind: 'school', id: PEMBROKE_HILL });
    expect(tab.url).toBe(`https://snow.test/?school=${PEMBROKE_HILL}`);
    expect(tab.pushes).toBe(0);
    await settle();
    expect(shown).toEqual([{ view: { lon: -94.593001, lat: 39.03606, zoom: ZOOM.school } }]);
    controller.abort();
  });

  it('a link with a view opens as sent: no pin, no move', async () => {
    localStorage.setItem(PIN_KEY, encodePin(PEMBROKE_HILL));
    const { links, shown, controller } = start(
      'https://snow.test/?at=39.045,-94.595,13.2',
      withDirectory(),
    );
    await settle();
    expect(links.state.selection).toBeNull();
    expect(shown).toEqual([]);
    controller.abort();
  });

  it('a linked school the directory places moves the map, unless someone moved it first', async () => {
    const first = start(`https://snow.test/?school=${PEMBROKE_HILL}`, withDirectory());
    await settle();
    expect(first.shown).toHaveLength(1);
    first.controller.abort();

    const moved = start(`https://snow.test/?school=${PEMBROKE_HILL}`, withDirectory(), true);
    await settle();
    expect(moved.shown).toEqual([]);
    moved.controller.abort();
  });

  it('with the address read late, opens the pinned school once it opens, and nothing when it took the app’s', async () => {
    localStorage.setItem(PIN_KEY, encodePin(PEMBROKE_HILL));
    let read: (opens: boolean) => void = () => undefined;
    const reading = new Promise<boolean>((resolve) => {
      read = resolve;
    });
    const late = start('https://snow.test/', withDirectory(), false, null, undefined, {
      addressOpens: reading,
    });
    await settle();
    expect(late.links.state.selection).toBeNull();
    expect(late.shown).toEqual([]);
    read(true);
    await settle();
    expect(late.links.state.selection).toEqual({ kind: 'school', id: PEMBROKE_HILL });
    expect(late.tab.pushes).toBe(0);
    expect(late.shown).toEqual([{ view: { lon: -94.593001, lat: 39.03606, zoom: ZOOM.school } }]);
    late.controller.abort();

    const taken = start('https://snow.test/', withDirectory(), false, null, undefined, {
      addressOpens: Promise.resolve(false),
    });
    await settle();
    expect(taken.links.state.selection).toBeNull();
    expect(taken.shown).toEqual([]);
    taken.controller.abort();
  });

  it('with no data shipped, a linked school stays linked and the map stays put', async () => {
    const { links, shown, controller } = start(
      `https://snow.test/?school=${PEMBROKE_HILL}`,
      NO_DATA,
    );
    await settle();
    expect(links.state.selection).toEqual({ kind: 'school', id: PEMBROKE_HILL });
    expect(shown).toEqual([]);
    controller.abort();
  });
});

describe('search', () => {
  it('is off, and shows nothing, when no index is published', async () => {
    const { services, results, controller } = start('https://snow.test/', NO_DATA);
    expect(services.searchable).toBe(false);
    services.warmSearch();
    services.query('kansas city');
    await settle();
    expect(results.every((next) => next === null)).toBe(true);
    controller.abort();
  });

  const SCHOOL_HIT: SearchHit = {
    kind: 'school',
    id: PEMBROKE_HILL,
    name: 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
    sub: '',
    state: 'MO',
    lat: 39.03606,
    lon: -94.593001,
    match: 'prefix',
    highlight: [],
  };
  const ZIP_HIT: SearchHit = {
    ...SCHOOL_HIT,
    kind: 'zip',
    id: '64113',
    name: '64113',
    lat: 39.01414,
    lon: -94.595493,
  };
  const CITY_HIT: SearchHit = {
    ...SCHOOL_HIT,
    kind: 'city',
    id: '2938000',
    name: 'Kansas City',
    lat: 39.125155,
    lon: -94.550313,
  };

  it('a picked result opens what it names and moves the map there', () => {
    const { services, links, tab, shown, controller } = start('https://snow.test/', NO_DATA);
    services.pick(SCHOOL_HIT);
    expect(links.state).toEqual({
      selection: { kind: 'school', id: PEMBROKE_HILL },
      view: { lat: 39.03606, lon: -94.593, zoom: ZOOM.school },
    });
    expect(tab.pushes).toBe(1);
    expect(shown).toEqual([{ view: { lat: 39.03606, lon: -94.593001, zoom: ZOOM.school } }]);
    controller.abort();
  });

  it('a picked school is framed clear of its panel, in the link and on the map alike', () => {
    const frame = vi.fn((view: { lat: number; lon: number; zoom: number }, opened: unknown) =>
      opened === null ? view : { ...view, lon: view.lon - 0.004 },
    );
    const { services, links, shown, controller } = start(
      'https://snow.test/',
      NO_DATA,
      false,
      null,
      frame,
    );
    services.pick(SCHOOL_HIT);
    expect(frame).toHaveBeenCalledWith(
      { lat: 39.03606, lon: -94.593001, zoom: ZOOM.school },
      { kind: 'school', id: PEMBROKE_HILL },
    );
    expect(links.state.view).toEqual({ lat: 39.03606, lon: -94.597, zoom: ZOOM.school });
    expect(shown).toEqual([{ view: { lat: 39.03606, lon: -94.597001, zoom: ZOOM.school } }]);
    // A city opens no panel: its view is its own.
    services.pick(CITY_HIT);
    expect(shown[1]).toEqual({ view: { lat: 39.125155, lon: -94.550313, zoom: ZOOM.city } });
    controller.abort();
  });

  it('a linked school the map goes to by itself is framed clear of its panel too', async () => {
    const frame = (view: { lat: number; lon: number; zoom: number }) => ({ ...view, lat: 0 });
    const { shown, controller } = start(
      `https://snow.test/?school=${PEMBROKE_HILL}`,
      withDirectory(),
      false,
      null,
      frame,
    );
    await settle();
    expect(shown).toEqual([{ view: { lon: -94.593001, lat: 0, zoom: ZOOM.school } }]);
    controller.abort();
  });

  it('on a screen, frames a picked school clear of its panel, and a city as it is', () => {
    const tab = new FakeTab('https://snow.test/');
    const shown: Target[] = [];
    const screen = { width: 1440, height: 900, top: 64 };
    const controller = new AbortController();
    const services = boot({
      links: createUrlStore({ host: tab }),
      map: Promise.resolve(undefined),
      glow: Promise.resolve(null),
      signal: controller.signal,
      show: (target) => shown.push(target),
      screen: () => screen,
      listId: 'list',
      onResults: () => undefined,
      data: NO_DATA,
    });
    services.pick(SCHOOL_HIT);
    expect(shown[0]).toEqual({ view: clearOfPanel(viewForHit(SCHOOL_HIT), screen) });
    services.pick(CITY_HIT);
    expect(shown[1]).toEqual({ view: viewForHit(CITY_HIT) });
    controller.abort();
  });

  it('reads a school for its panel, and says there is none without its record', async () => {
    const { services, controller } = start('https://snow.test/', NO_DATA);
    const views: unknown[] = [];
    const hint = { id: PEMBROKE_HILL, name: 'The Pembroke Hill School', sub: 'Kansas City, MO' };
    const stop = services.watchSchool(PEMBROKE_HILL, hint, (view) => views.push(view));
    await vi.waitFor(() => {
      expect(views).toHaveLength(2);
    }, WAIT);
    // What the pick knew, then that, for good: this build ships no records.
    expect(views[0]).toMatchObject({ name: 'The Pembroke Hill School', loading: true });
    expect(views[1]).toMatchObject({ name: 'The Pembroke Hill School', loading: false, facts: [] });
    stop();
    const none: unknown[] = [];
    services.watchSchool(PEMBROKE_HILL, null, (view) => none.push(view));
    await vi.waitFor(() => {
      expect(none).toEqual([null]);
    }, WAIT);
    expect(services.pins.school).toBeNull();
    controller.abort();
  });

  it('asks for the panel’s and the menu’s code only once the formatters they import are in', async () => {
    let formatted: () => void = () => undefined;
    const formats = new Promise<void>((resolve) => {
      formatted = resolve;
    });
    const { services, controller } = start('https://snow.test/', NO_DATA, false, null, undefined, {
      formats,
    });
    const views: unknown[] = [];
    const hint = { id: PEMBROKE_HILL, name: 'The Pembroke Hill School', sub: 'Kansas City, MO' };
    services.watchSchool(PEMBROKE_HILL, hint, (view) => views.push(view));
    let read = false;
    void services.menu().then(() => {
      read = true;
    });
    await settle();
    expect(views).toEqual([]);
    expect(read).toBe(false);
    formatted();
    await vi.waitFor(() => {
      expect(views).toHaveLength(2);
      expect(read).toBe(true);
    }, WAIT);
    controller.abort();
  });

  it('a picked city is a step of its own: Back returns to the ZIP code before it, then to the start', () => {
    const { services, links, tab, shown, controller } = start('https://snow.test/', NO_DATA);
    services.pick(ZIP_HIT);
    expect(tab.pushes).toBe(1);
    services.pick(CITY_HIT);
    // The city closes the ZIP code in a new entry, which holds where the map went.
    expect(tab.pushes).toBe(2);
    expect(links.state).toEqual({
      selection: null,
      view: { lat: 39.1252, lon: -94.5503, zoom: ZOOM.city },
    });
    expect(tab.urls()).toEqual([
      '',
      '?zip=64113&at=39.0141,-94.5955,12',
      '?at=39.1252,-94.5503,11',
    ]);
    expect(shown).toEqual([
      { view: { lat: 39.01414, lon: -94.595493, zoom: ZOOM.zip } },
      { view: { lat: 39.125155, lon: -94.550313, zoom: ZOOM.city } },
    ]);

    expect(tab.back()).toBe(true);
    expect(links.state).toEqual({
      selection: { kind: 'zip', id: '64113' },
      view: { lat: 39.0141, lon: -94.5955, zoom: ZOOM.zip },
    });
    expect(tab.back()).toBe(true);
    expect(links.state).toEqual({ selection: null, view: null });
    tab.forward();
    tab.forward();
    expect(links.state.view).toEqual({ lat: 39.1252, lon: -94.5503, zoom: ZOOM.city });
    controller.abort();
  });

  it('a city picked from a fresh visit leaves the start one Back away', () => {
    const { services, tab, controller } = start('https://snow.test/', NO_DATA);
    services.pick(CITY_HIT);
    expect(tab.pushes).toBe(1);
    expect(tab.back()).toBe(true);
    expect(tab.url).toBe('https://snow.test/');
    controller.abort();
  });

  it('picking the city the map is already on adds nothing', () => {
    const { services, tab, controller } = start('https://snow.test/', NO_DATA);
    services.pick(CITY_HIT);
    services.pick(CITY_HIT);
    expect(tab.pushes).toBe(1);
    controller.abort();
  });

  it('a result whose id a link cannot carry still takes the map there, as a step of its own', () => {
    const { services, links, tab, shown, controller } = start(
      `https://snow.test/?zip=64113`,
      NO_DATA,
    );
    services.pick({ ...SCHOOL_HIT, id: 'not-an-id' });
    expect(tab.pushes).toBe(1);
    expect(links.state.selection).toBeNull();
    expect(shown).toHaveLength(1);
    expect(tab.back()).toBe(true);
    expect(links.state.selection).toEqual({ kind: 'zip', id: '64113' });
    controller.abort();
  });
});

describe('the glow', () => {
  it('stays dark, and nothing is fetched, when no live file is shipped', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const glow = fakeGlow();
    const { controller } = start('https://snow.test/', withDirectory(), false, glow);
    await settle();
    expect(glow.light).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    controller.abort();
    await settle();
    expect(glow.remove).toHaveBeenCalledOnce();
    fetchSpy.mockRestore();
  });

  it('is given every school for its dust, read from the directory only when it asks', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const glow = fakeGlow();
    const { controller } = start('https://snow.test/', withDirectory(), false, glow);
    await settle();
    expect(glow.dust).toHaveBeenCalledOnce();
    const [source] = glow.dust.mock.calls[0] as [DustSource];
    const positions = await source.positions();
    expect(Array.from(positions?.lngLat ?? [])).toEqual([-86.8, 33.5, -94.593001, 39.03606]);
    expect(positions?.kind).toHaveLength(2);
    // Then who each school is, for a tap on its speck.
    expect(await source.names()).toEqual({
      ids: ['010000500870', PEMBROKE_HILL],
      names: ['First', 'Second'],
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    controller.abort();
    fetchSpy.mockRestore();
  });

  it('has no dust where the build ships no directory', async () => {
    const glow = fakeGlow();
    const { controller } = start('https://snow.test/', NO_DATA, false, glow);
    await settle();
    const [source] = glow.dust.mock.calls[0] as [DustSource];
    expect(await source.positions()).toBeNull();
    expect(await source.names()).toBeNull();
    controller.abort();
  });

  it('shows the dust of the kinds the menu shows, as it opens and as it changes', async () => {
    const glow = fakeGlow();
    const { controller, services } = start('https://snow.test/', withDirectory(), false, glow);
    /** Whether the dust shows a public school and a private one (kind flag 0x01), as told last. */
    const shown = (): boolean[] => {
      const [shows] = glow.showSchools.mock.lastCall as [(flags: number) => boolean];
      return [shows(0), shows(1)];
    };
    await settle();
    expect(shown()).toEqual([true, true]);
    services.filter({ ...SHOW_ALL, public: false });
    await settle();
    expect(shown()).toEqual([false, true]);
    services.filter({ ...SHOW_ALL, private: false });
    await settle();
    expect(shown()).toEqual([true, false]);
    controller.abort();
  });

  it('shows the open school in the dust whatever its kind, as the address changes', async () => {
    const glow = fakeGlow();
    const { controller, links } = start(
      `https://snow.test/?school=${PEMBROKE_HILL}`,
      withDirectory(),
      false,
      glow,
    );
    await settle();
    expect(glow.select).toHaveBeenLastCalledWith(PEMBROKE_HILL);
    links.select(null);
    expect(glow.select).toHaveBeenLastCalledWith(null);
    links.select({ kind: 'school', id: '010000500870' });
    expect(glow.select).toHaveBeenLastCalledWith('010000500870');
    controller.abort();
    const calls = glow.select.mock.calls.length;
    links.select(null);
    expect(glow.select).toHaveBeenCalledTimes(calls);
  });
});

describe('a school clicked on the map', () => {
  /**
   * A map that keeps its listeners by type and flies where it is told: taking
   * input when told (created), and on screen when told (up). Its view is a
   * center, one degree to 100 pixels.
   */
  function withTaps(onSchool?: BootOptions['onSchool'], extra: Partial<BootOptions> = {}) {
    const listeners = new Map<string, (event: object) => void>();
    const flights: unknown[] = [];
    const ahead: unknown[] = [];
    const shown: Target[] = [];
    const inner = {
      center: { lng: -94.6, lat: 39 },
      on: (type: string, listener: (event: object) => void) => listeners.set(type, listener),
      off: (type: string) => listeners.delete(type),
      getCenter: () => inner.center,
      getZoom: () => 14,
      project: ([lng, lat]: [number, number]) => ({
        x: 400 + (lng - inner.center.lng) * 100,
        y: 300 - (lat - inner.center.lat) * 100,
      }),
    };
    const rings: (string | null)[] = [];
    const map = {
      moved: false,
      ready: new Promise<void>(() => undefined),
      map: inner,
      flyTo: (view: unknown) => flights.push(view),
      streetsAhead: (view: unknown) => ahead.push(view),
      selectSchool: (id: string | null) => rings.push(id),
    } as unknown as Basemap;
    let created: (map: Basemap) => void = () => undefined;
    let up: (map: Basemap) => void = () => undefined;
    const controller = new AbortController();
    const services = boot({
      links: createUrlStore({ host: new FakeTab('https://snow.test/') }),
      map: new Promise((resolve) => {
        up = resolve;
      }),
      mapCreated: new Promise((resolve) => {
        created = resolve;
      }),
      glow: Promise.resolve(fakeGlow()),
      signal: controller.signal,
      show: (target) => shown.push(target),
      listId: 'list',
      onResults: () => undefined,
      data: NO_DATA,
      ...(onSchool === undefined ? {} : { onSchool }),
      ...extra,
    });
    /** A click on the map at a point on the screen, as MapLibre fires it. */
    const click = (x: number, y: number) => {
      const originalEvent = { type: 'click', x, y };
      listeners.get('click')?.({
        point: { x, y },
        lngLat: {
          lng: inner.center.lng + (x - 400) / 100,
          lat: inner.center.lat - (y - 300) / 100,
        },
        originalEvent,
      });
      return originalEvent;
    };
    return {
      listeners,
      flights,
      ahead,
      rings,
      shown,
      inner,
      services,
      controller,
      click,
      created: () => {
        created(map);
      },
      up: () => {
        up(map);
      },
    };
  }

  /** The options the taps were attached with. */
  async function attached(): Promise<SchoolTapOptions> {
    await vi.waitFor(() => {
      expect(taps.attach).toHaveBeenCalledOnce();
    }, WAIT);
    return taps.attach.mock.calls[0]?.[1] as SchoolTapOptions;
  }

  beforeEach(() => {
    taps.attach.mockClear();
    taps.click.mockClear();
    taps.stop.mockClear();
  });

  it('loads its code once the map is on screen, and stops listening once the page goes', async () => {
    const onSchool = vi.fn();
    const { inner, controller, created, up } = withTaps(onSchool);
    created();
    await settle();
    expect(taps.attach).not.toHaveBeenCalled();
    up();
    const options = await attached();
    expect(taps.attach.mock.calls[0]?.[0]).toBe(inner);
    expect(options).toMatchObject({ onSchool });
    expect(taps.stop).not.toHaveBeenCalled();
    controller.abort();
    expect(taps.stop).toHaveBeenCalledOnce();
  });

  it('keeps clicks from the moment the map takes input, loads its code on the first, and hands it on', async () => {
    const { listeners, controller, created, click } = withTaps(vi.fn());
    created();
    await settle();
    // The map is not on screen yet: a click on it loads the code all the same.
    const original = click(450, 250);
    await attached();
    await vi.waitFor(() => {
      expect(taps.click).toHaveBeenCalledOnce();
    }, WAIT);
    expect(taps.click).toHaveBeenCalledWith({ point: { x: 450, y: 250 }, originalEvent: original });
    // Kept no longer: the taps listen for themselves.
    expect(listeners.has('click')).toBe(false);
    controller.abort();
  });

  it('drops a kept click once the map has moved since: its point is another place now', async () => {
    const { inner, controller, created, click } = withTaps(vi.fn());
    created();
    await settle();
    click(450, 250);
    // A hand drags the map before the code is in.
    inner.center = { lng: inner.center.lng + 0.5, lat: inner.center.lat };
    await attached();
    await settle();
    expect(taps.click).not.toHaveBeenCalled();
    controller.abort();
  });

  it('zooms the map in as its own flights go, and has a flight stopped short fly on', async () => {
    const { flights, services, shown, controller, created, up } = withTaps(vi.fn());
    created();
    up();
    const options = await attached();
    const view = { lat: 39.03, lon: -94.59, zoom: 11 };
    options.onZoom(view);
    expect(flights).toEqual([view]);
    options.onResume?.();
    expect(flights).toEqual([view, view]);
    // A pick's flight, too: the one it set off, framed as it was.
    services.pick({ kind: 'school', id: PEMBROKE_HILL, lat: 39.03606, lon: -94.593001 });
    const picked = shown.at(-1);
    options.onResume?.();
    expect(picked).toBeDefined();
    expect(flights.at(-1)).toEqual((picked as { view: unknown }).view);
    controller.abort();
  });

  it('fits a zoom toward several schools into the map in view: clear of a panel only while one shows', async () => {
    let screen: Screen = { width: 1440, height: 900, top: 64 };
    const { controller, created, up } = withTaps(vi.fn(), { screen: () => screen });
    created();
    up();
    const { area } = await attached();
    expect(area?.()).toEqual({ left: 0, top: 64, right: 1440, bottom: 900 });
    // Read as each tap comes: a school's panel beside the map, as a pick frames its school, then
    // a phone's sheet down to its name.
    screen = {
      ...screen,
      panel: { left: PANEL_EDGE, top: 84, right: PANEL_EDGE + panelWidth(1440), bottom: 880 },
    };
    expect(area?.()).toEqual(openArea(screen));
    screen = {
      width: 390,
      height: 844,
      top: 104,
      panel: { left: 0, top: 744, right: 390, bottom: 1500 },
    };
    expect(area?.()).toEqual({ left: 0, top: 104, right: 390, bottom: 744 });
    controller.abort();
  });

  it('shows a finger’s tap waiting to open a school picked, and reads its record meanwhile', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 404 }));
    const { rings, controller, created, up } = withTaps(vi.fn(), {
      data: {
        files: createDataFiles([DETAILS_INDEX_PATH], ROOT),
        directories: () => Promise.resolve(null),
      },
    });
    created();
    up();
    const options = await attached();
    const school = { id: PEMBROKE_HILL, name: 'Pembroke Hill', lon: -94.593001, lat: 39.03606 };
    // Its ring at once; no school is open, so none once the tap turns out to be a double tap.
    options.onPending?.(school);
    options.onPending?.(null);
    expect(rings).toEqual([PEMBROKE_HILL, null]);
    // Its record's shard index, on its way before the tap opens anything.
    await vi.waitFor(() => {
      expect(
        fetchSpy.mock.calls.map(([url]) => (url instanceof Request ? url.url : String(url))),
      ).toContain(`${ROOT}${DETAILS_INDEX_PATH}`);
    }, WAIT);
    fetchSpy.mockRestore();
    controller.abort();
  });

  it('has what a pressed school’s streets need come before its click, as a pick flies there', async () => {
    const { ahead, controller, created, up } = withTaps(vi.fn());
    created();
    up();
    const options = await attached();
    const school = { id: PEMBROKE_HILL, name: 'Pembroke Hill', lon: -94.593001, lat: 39.03606 };
    options.onPress?.(school);
    expect(ahead).toEqual([{ lat: 39.03606, lon: -94.593001, zoom: ZOOM.school }]);
    controller.abort();
  });

  it('puts the ring back on the school open when a waiting tap turns out to be a double tap', async () => {
    const { rings, controller, created, up } = withTaps(vi.fn(), {
      links: createUrlStore({ host: new FakeTab(`https://snow.test/?school=${PEMBROKE_HILL}`) }),
    });
    created();
    up();
    const options = await attached();
    const other = { id: '290000000001', name: 'Next Door', lon: -94.59, lat: 39.03 };
    options.onPending?.(other);
    options.onPending?.(null);
    expect(rings).toEqual([other.id, PEMBROKE_HILL]);
    controller.abort();
  });

  it('is not listened for by a page that opens nothing from the map', async () => {
    const { listeners, controller, created, up } = withTaps();
    created();
    up();
    await settle();
    expect(listeners.size).toBe(0);
    expect(taps.attach).not.toHaveBeenCalled();
    controller.abort();
  });
});

describe('the pinned school', () => {
  it('is read once, at startup', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem');
    const { controller } = start('https://snow.test/', NO_DATA);
    expect(spy).toHaveBeenCalledWith(PIN_KEY);
    spy.mockRestore();
    controller.abort();
  });
});
