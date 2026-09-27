import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createDirectory, parsePoints } from '../../data/directory';
import type { DirectorySource } from '../../data/directory';
import { createDataFiles } from '../../data/files';
import { testMeta, testPoints } from '../../data/tests/builders';
import type { Basemap } from '../../map/basemap';
import type { Glow } from '../../map/glow-mount';
import type { SearchHit } from '../../search';
import { PIN_KEY, encodePin } from '../../state/pin';
import { createUrlStore } from '../../state/url-store';
import type { UrlStoreHost } from '../../state/url-store';
import { boot } from '../boot';
import type { BootOptions } from '../boot';
import type { AppData, Target } from '../data';
import { ZOOM } from '../startup';

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
  const source: DirectorySource = { get: () => Promise.resolve(directory) };
  return {
    files: createDataFiles(['schools/meta.json', 'schools/points.bin'], ROOT),
    directories: () => Promise.resolve(source),
  };
}

const NO_DATA: AppData = {
  files: createDataFiles([], ROOT),
  directories: () => Promise.resolve(null),
};

function start(url: string, data: AppData, moved = false, glow: Glow | null = null) {
  const tab = new FakeTab(url);
  const links = createUrlStore({ host: tab });
  const controller = new AbortController();
  const shown: Target[] = [];
  const results: unknown[] = [];
  // A map that is up but never finishes its first frame, and no glow layer on it.
  const map = { moved, ready: new Promise<void>(() => undefined) } as unknown as Basemap;
  const options: BootOptions = {
    links,
    map: Promise.resolve(map),
    glow: Promise.resolve(glow),
    signal: controller.signal,
    show: (target) => shown.push(target),
    listId: 'list',
    onResults: (next) => results.push(next),
    data,
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
    const glow = { light: vi.fn(), remove: vi.fn() };
    const { controller } = start('https://snow.test/', withDirectory(), false, glow);
    await settle();
    expect(glow.light).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    controller.abort();
    await settle();
    expect(glow.remove).toHaveBeenCalledOnce();
    fetchSpy.mockRestore();
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
