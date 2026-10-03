import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { lateUrlStore } from '../late-url-store';
import type { LateUrlStore, UrlStoreModule } from '../late-url-store';
import { createUrlStore } from '../url-store';
import type { StateOrigin, UrlStoreHost } from '../url-store';
import type { UrlState } from '../url';

const SCHOOL = '010000500870';
const OTHER = '010000500871';
const EMPTY: UrlState = { selection: null, view: null };

/** A tab's session history: entries, pushState, replaceState, and Back that fires popstate. */
class FakeTab extends EventTarget implements UrlStoreHost {
  entries: string[];
  index = 0;
  pushes = 0;
  constructor(url: string) {
    super();
    this.entries = [url];
  }
  get location(): { href: string } {
    return { href: this.entries[this.index] ?? '' };
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
  back(): void {
    if (this.index === 0) return;
    this.index -= 1;
    this.dispatchEvent(new Event('popstate'));
  }
  urls(): string[] {
    return this.entries.map((entry) => new URL(entry).search);
  }
}

/**
 * A store whose code is refused `refusals` times, then comes, for a tab
 * opened at `url`, and what its subscriber hears.
 */
function open(url: string, refusals = 0) {
  const tab = new FakeTab(url);
  const tries: number[] = [];
  const load = (attempt: number): Promise<UrlStoreModule> => {
    tries.push(attempt);
    if (tries.length <= refusals) {
      return Promise.reject(new TypeError('Failed to fetch dynamically imported module'));
    }
    return Promise.resolve({ createUrlStore: () => createUrlStore({ host: tab }) });
  };
  const store: LateUrlStore = lateUrlStore({ load });
  const heard: [UrlState, StateOrigin][] = [];
  store.subscribe((state, origin) => heard.push([state, origin]));
  return { tab, tries, store, heard };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('with its code at the first try', () => {
  it('asks for it only once the page has painted', async () => {
    const tab = new FakeTab('https://snow.test/');
    const tries: number[] = [];
    let paint: () => void = () => undefined;
    const store = lateUrlStore({
      after: new Promise<void>((resolve) => {
        paint = resolve;
      }),
      load: (attempt) => {
        tries.push(attempt);
        return Promise.resolve({ createUrlStore: () => createUrlStore({ host: tab }) });
      },
    });
    await vi.advanceTimersByTimeAsync(5_000);
    expect(tries).toEqual([]);
    expect(store.read).toBe(false);
    paint();
    await store.tried;
    expect(tries).toEqual([0]);
    expect(store.read).toBe(true);
    store.destroy();
  });

  it('reads the address before the app starts, as a store that came with the page', async () => {
    const { tab, store, heard } = open(`https://snow.test/?school=${SCHOOL}&at=40,-90,6`);
    expect(store.read).toBe(false);
    expect(store.state).toEqual(EMPTY);
    await store.tried;
    const linked = {
      selection: { kind: 'school', id: SCHOOL },
      view: { lat: 40, lon: -90, zoom: 6 },
    };
    expect(store.read).toBe(true);
    expect(store.state).toEqual(linked);
    expect(heard).toEqual([
      [EMPTY, 'initial'],
      [linked, 'initial'],
    ]);
    await expect(store.opens).resolves.toBe(true);
    expect(store.shareUrl()).toBe(`https://snow.test/?school=${SCHOOL}`);
    expect(tab.pushes).toBe(0);
    store.destroy();
  });

  it('passes on what the store does, and hears from it, with their origins', async () => {
    const { tab, store, heard } = open('https://snow.test/');
    await store.tried;
    store.select({ kind: 'school', id: OTHER });
    expect(tab.urls()).toEqual(['', `?school=${OTHER}`]);
    expect(heard.at(-1)).toEqual([store.state, 'app']);
    tab.back();
    expect(store.state).toEqual(EMPTY);
    expect(heard.at(-1)).toEqual([EMPTY, 'history']);
    store.destroy();
  });
});

describe('without its code', () => {
  it('starts on a plain visit’s state, keeps what the app opens in memory, and leaves the address', async () => {
    const { tab, store, heard } = open('https://snow.test/?zip=64111', Infinity);
    await store.tried;
    expect(store.read).toBe(false);
    expect(store.state).toEqual(EMPTY);
    const picked: UrlState = {
      selection: { kind: 'school', id: SCHOOL },
      view: { lat: 39.03, lon: -94.59, zoom: 15 },
    };
    store.navigate(picked);
    expect(store.state).toEqual(picked);
    expect(heard.at(-1)).toEqual([picked, 'app']);
    store.select(null);
    expect(store.state).toEqual({ ...picked, selection: null });
    expect(() => store.shareUrl()).toThrow();
    expect(tab.urls()).toEqual(['?zip=64111']);
    store.destroy();
  });

  it('asks for it again, less and less often, under a new try each time, and no more once the page goes', async () => {
    const { store, tries } = open('https://snow.test/', Infinity);
    await store.tried;
    expect(tries).toEqual([0]);
    await vi.advanceTimersByTimeAsync(999);
    expect(tries).toEqual([0]);
    await vi.advanceTimersByTimeAsync(1);
    expect(tries).toEqual([0, 1]);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(tries).toEqual([0, 1, 2]);
    await vi.advanceTimersByTimeAsync(4_000 + 8_000 + 16_000);
    expect(tries).toEqual([0, 1, 2, 3, 4, 5]);
    // At most every 30 seconds from then on.
    await vi.advanceTimersByTimeAsync(29_999);
    expect(tries).toHaveLength(6);
    await vi.advanceTimersByTimeAsync(1);
    expect(tries).toHaveLength(7);
    store.destroy();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(tries).toHaveLength(7);
  });
});

describe('once its code comes late', () => {
  it('opens the address as a link would, when the app has not moved from its start', async () => {
    const { store, heard } = open(`https://snow.test/?school=${SCHOOL}`, 1);
    await store.tried;
    // The map at the national view records no view: that is no move.
    store.setView(null);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.read).toBe(true);
    const linked = { selection: { kind: 'school', id: SCHOOL }, view: null };
    expect(store.state).toEqual(linked);
    expect(heard).toEqual([
      [EMPTY, 'initial'],
      [linked, 'address'],
    ]);
    await expect(store.opens).resolves.toBe(true);
    store.destroy();
  });

  it('takes what the app opened meanwhile as one step on from the link, which Back returns to', async () => {
    const { tab, store, heard } = open(`https://snow.test/?school=${SCHOOL}&utm_source=x`, 1);
    await store.tried;
    const picked: UrlState = {
      selection: { kind: 'school', id: OTHER },
      view: { lat: 39.03, lon: -94.59, zoom: 15 },
    };
    store.navigate(picked);
    store.setView({ lat: 39.04, lon: -94.6, zoom: 14 });
    const shown: UrlState = { ...picked, view: { lat: 39.04, lon: -94.6, zoom: 14 } };
    const before = heard.length;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.read).toBe(true);
    expect(store.state).toEqual(shown);
    // Nothing new to hear: the app shows it already.
    expect(heard).toHaveLength(before);
    await expect(store.opens).resolves.toBe(false);
    expect(tab.urls()).toEqual([
      `?school=${SCHOOL}&utm_source=x`,
      `?school=${OTHER}&at=39.04,-94.6,14&utm_source=x`,
    ]);
    expect(tab.pushes).toBe(1);
    tab.back();
    const linked = { selection: { kind: 'school', id: SCHOOL }, view: null };
    expect(store.state).toEqual(linked);
    expect(heard.at(-1)).toEqual([linked, 'history']);
    store.destroy();
  });

  it('takes the view the map was moved to in place of the link, when nothing was opened', async () => {
    const { tab, store } = open(`https://snow.test/?school=${SCHOOL}`, 1);
    await store.tried;
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.state).toEqual({ selection: null, view: { lat: 40, lon: -90, zoom: 6 } });
    expect(tab.urls()).toEqual(['?at=40,-90,6']);
    expect(tab.pushes).toBe(0);
    await expect(store.opens).resolves.toBe(false);
    store.destroy();
  });

  it('writes what the app opened in place of the link, not as a step, when it opened it in place', async () => {
    const { tab, store } = open('https://snow.test/', 1);
    await store.tried;
    store.select({ kind: 'school', id: OTHER }, { replace: true });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.state).toEqual({ selection: { kind: 'school', id: OTHER }, view: null });
    expect(tab.urls()).toEqual([`?school=${OTHER}`]);
    expect(tab.pushes).toBe(0);
    store.destroy();
  });

  it('drops an id a link cannot carry from the step, and keeps the place', async () => {
    const { tab, store } = open(`https://snow.test/?school=${SCHOOL}`, 1);
    await store.tried;
    store.select({ kind: 'school', id: 'not an id' });
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.state).toEqual({ selection: null, view: { lat: 40, lon: -90, zoom: 6 } });
    expect(tab.urls()).toEqual([`?school=${SCHOOL}`, '?at=40,-90,6']);
    await expect(store.opens).resolves.toBe(false);
    store.destroy();
  });
});

describe('when its code hangs', () => {
  /** A store whose first try never answers until `answer` is called; later tries per `later`. */
  function hanging(url: string, later: 'refused' | 'come') {
    const tab = new FakeTab(url);
    const tries: number[] = [];
    let answer: () => void = () => undefined;
    const module: UrlStoreModule = { createUrlStore: () => createUrlStore({ host: tab }) };
    const load = (attempt: number): Promise<UrlStoreModule> => {
      tries.push(attempt);
      if (attempt === 0) {
        return new Promise((resolve) => {
          answer = () => {
            resolve(module);
          };
        });
      }
      return later === 'come'
        ? Promise.resolve(module)
        : Promise.reject(new TypeError('Failed to fetch dynamically imported module'));
    };
    const store = lateUrlStore({ load });
    const heard: [UrlState, StateOrigin][] = [];
    store.subscribe((state, origin) => heard.push([state, origin]));
    return {
      tab,
      tries,
      store,
      heard,
      answer: () => {
        answer();
      },
    };
  }

  it('starts without it at the first try’s deadline, and opens the address once a later try brings it', async () => {
    const { store, tries, heard } = hanging(`https://snow.test/?school=${SCHOOL}`, 'come');
    let tried = false;
    void store.tried.then(() => (tried = true));
    await vi.advanceTimersByTimeAsync(1_999);
    expect(tried).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(tried).toBe(true);
    expect(store.read).toBe(false);
    expect(store.state).toEqual(EMPTY);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(tries).toEqual([0, 1]);
    expect(store.read).toBe(true);
    const linked = { selection: { kind: 'school', id: SCHOOL }, view: null };
    expect(heard).toEqual([
      [EMPTY, 'initial'],
      [linked, 'address'],
    ]);
    await expect(store.opens).resolves.toBe(true);
    store.destroy();
  });

  it('takes the first try when it comes late, before any other has', async () => {
    const { store, tries, heard, answer } = hanging(
      `https://snow.test/?school=${SCHOOL}`,
      'refused',
    );
    await vi.advanceTimersByTimeAsync(2_000);
    await store.tried;
    expect(store.read).toBe(false);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(tries).toEqual([0, 1]);
    answer();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.read).toBe(true);
    expect(heard.at(-1)).toEqual([
      { selection: { kind: 'school', id: SCHOOL }, view: null },
      'address',
    ]);
    // Asked for no more.
    await vi.advanceTimersByTimeAsync(120_000);
    expect(tries).toEqual([0, 1]);
    store.destroy();
  });
});
