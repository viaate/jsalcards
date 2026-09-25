import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createUrlStore } from '../url-store';
import type { StateOrigin, UrlStore, UrlStoreHost } from '../url-store';
import type { UrlState } from '../url';

const SCHOOL = '010000500870';
const OTHER = '010000500871';
const DISTRICT = '0100005';

class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = 'visible';
}

/**
 * A browser tab's session history: entries, the current index, pushState and
 * replaceState with their real effect on later entries, and Back and Forward
 * that fire popstate. Timers are Vitest's fake ones.
 */
class FakeTab extends EventTarget implements UrlStoreHost {
  entries: { url: string; state: unknown }[];
  index = 0;
  pushes = 0;
  replaces = 0;
  /** Throw from replaceState this many more times, as Safari does when called too often. */
  refuseReplaces = 0;
  readonly document = new FakeDocument();

  constructor(url: string) {
    super();
    this.entries = [{ url, state: null }];
  }

  get location(): { href: string } {
    return { href: this.entries[this.index]?.url ?? '' };
  }

  readonly history: UrlStoreHost['history'] = ((tab: FakeTab) => ({
    get state(): unknown {
      return tab.entries[tab.index]?.state ?? null;
    },
    pushState(state: unknown, _unused: string, url?: string | URL | null): void {
      tab.pushes += 1;
      tab.entries.splice(tab.index + 1, Infinity, {
        url: new URL(String(url), tab.location.href).href,
        state,
      });
      tab.index += 1;
    },
    replaceState(state: unknown, _unused: string, url?: string | URL | null): void {
      if (tab.refuseReplaces > 0) {
        tab.refuseReplaces -= 1;
        throw new DOMException('Too many calls to replaceState', 'SecurityError');
      }
      tab.replaces += 1;
      tab.entries[tab.index] = { url: new URL(String(url), tab.location.href).href, state };
    },
  }))(this);

  setTimeout(handler: () => void, timeout: number): number {
    return setTimeout(handler, timeout) as unknown as number;
  }

  clearTimeout(id: number | undefined): void {
    clearTimeout(id);
  }

  back(): void {
    this.go(-1);
  }

  forward(): void {
    this.go(1);
  }

  go(delta: number): void {
    const next = this.index + delta;
    if (next < 0 || next >= this.entries.length) return;
    this.index = next;
    this.dispatchEvent(new Event('popstate'));
  }

  hide(): void {
    this.document.visibilityState = 'hidden';
    this.document.dispatchEvent(new Event('visibilitychange'));
  }

  get search(): string {
    return new URL(this.location.href).search;
  }

  urls(): string[] {
    return this.entries.map((entry) => new URL(entry.url).search);
  }
}

function open(url: string): { tab: FakeTab; store: UrlStore; seen: [UrlState, StateOrigin][] } {
  const tab = new FakeTab(url);
  const store = createUrlStore({ host: tab, debounceMs: 300 });
  const seen: [UrlState, StateOrigin][] = [];
  store.subscribe((state, origin) => seen.push([state, origin]));
  return { tab, store, seen };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('opening a link', () => {
  it('reads the state and tells a new subscriber at once', () => {
    const { store, seen } = open(`https://snow.test/?school=${SCHOOL}&at=40,-90,6`);
    expect(store.state).toEqual({
      selection: { kind: 'school', id: SCHOOL },
      view: { lat: 40, lon: -90, zoom: 6 },
    });
    expect(seen).toEqual([[store.state, 'initial']]);
  });

  it('drops junk values from the address without adding history', () => {
    const { tab: t } = open('https://snow.test/?school=abc&at=nope&utm_source=x#top');
    expect(t.location.href).toBe('https://snow.test/?utm_source=x#top');
    expect(t.entries).toHaveLength(1);
    expect(t.pushes).toBe(0);
  });

  it('leaves a clean address untouched', () => {
    const { tab: t } = open(`https://snow.test/?school=${SCHOOL}`);
    expect(t.replaces).toBe(0);
  });
});

describe('map moves', () => {
  it('are written once the map has been still, with replaceState only', () => {
    const { tab: t, store } = open('https://snow.test/');
    for (let i = 0; i < 20; i++) {
      store.setView({ lat: 40 + i / 10, lon: -90, zoom: 6 });
      vi.advanceTimersByTime(50);
    }
    expect(t.replaces).toBe(0);
    vi.advanceTimersByTime(300);
    expect(t.replaces).toBe(1);
    expect(t.pushes).toBe(0);
    expect(t.search).toBe('?at=41.9,-90,6');
    expect(t.entries).toHaveLength(1);
  });

  it('skip views that round to the same link', () => {
    const { tab: t, store, seen } = open('https://snow.test/?at=40,-90,6');
    store.setView({ lat: 40.0001, lon: -90.0001, zoom: 6.001 });
    vi.runAllTimers();
    expect(t.replaces).toBe(0);
    expect(seen).toHaveLength(1);
  });

  it('are written when the page is hidden or closed', () => {
    const { tab: t, store } = open('https://snow.test/');
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    t.hide();
    expect(t.search).toBe('?at=40,-90,6');
    store.setView({ lat: 41, lon: -90, zoom: 6 });
    t.dispatchEvent(new Event('pagehide'));
    expect(t.search).toBe('?at=41,-90,6');
  });

  it('survive Safari refusing a write', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { tab: t, store } = open('https://snow.test/');
    t.refuseReplaces = 2;
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    vi.advanceTimersByTime(300);
    expect(t.search).toBe('');
    vi.runAllTimers();
    expect(t.search).toBe('?at=40,-90,6');
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });
});

describe('selection and history', () => {
  it('opening pushes one entry that keeps the view; Back returns to the entry before', () => {
    const { tab: t, store, seen } = open('https://snow.test/?at=40,-90,6');
    store.setView({ lat: 41, lon: -91, zoom: 7 });
    store.select({ kind: 'school', id: SCHOOL });
    // The pending view went to the entry being left, then the school got its own entry.
    expect(t.urls()).toEqual(['?at=41,-91,7', `?school=${SCHOOL}&at=41,-91,7`]);
    expect(t.pushes).toBe(1);

    t.back();
    expect(store.state).toEqual({ selection: null, view: { lat: 41, lon: -91, zoom: 7 } });
    expect(seen.at(-1)?.[1]).toBe('history');

    t.forward();
    expect(store.state.selection).toEqual({ kind: 'school', id: SCHOOL });
    expect(seen.at(-1)?.[1]).toBe('history');
  });

  it('switching between schools pushes, so Back goes to the previous school', () => {
    const { tab: t, store } = open('https://snow.test/');
    store.select({ kind: 'school', id: SCHOOL });
    store.select({ kind: 'district', id: DISTRICT });
    store.select({ kind: 'school', id: OTHER });
    expect(t.urls()).toEqual([
      '',
      `?school=${SCHOOL}`,
      `?district=${DISTRICT}`,
      `?school=${OTHER}`,
    ]);
    t.back();
    expect(store.state.selection).toEqual({ kind: 'district', id: DISTRICT });
  });

  it('closing replaces, so Forward never reopens what was closed', () => {
    const { tab: t, store } = open('https://snow.test/');
    store.select({ kind: 'school', id: SCHOOL });
    store.select(null);
    expect(t.urls()).toEqual(['', '']);
    expect(t.index).toBe(1);
    t.back();
    t.forward();
    expect(store.state.selection).toBeNull();
  });

  it('selecting what is already open does nothing', () => {
    const { tab: t, store, seen } = open(`https://snow.test/?school=${SCHOOL}`);
    store.select({ kind: 'school', id: SCHOOL });
    expect(t.pushes + t.replaces).toBe(0);
    expect(seen).toHaveLength(1);
  });

  it('a view still waiting when Back is pressed never lands on the other entry', () => {
    const { tab: t, store } = open('https://snow.test/?at=40,-90,6');
    store.select({ kind: 'school', id: SCHOOL });
    store.setView({ lat: 33, lon: -86, zoom: 9 });
    t.back();
    vi.runAllTimers();
    expect(t.urls()).toEqual(['?at=40,-90,6', `?school=${SCHOOL}&at=40,-90,6`]);
    expect(store.state.view).toEqual({ lat: 40, lon: -90, zoom: 6 });
  });

  it('stays quiet when Back only changes the hash', () => {
    const { tab: t, seen } = open(`https://snow.test/?school=${SCHOOL}`);
    t.entries.push({ url: `https://snow.test/?school=${SCHOOL}#legend`, state: null });
    t.forward();
    t.back();
    expect(seen).toHaveLength(1);
  });

  it('cleans junk out of an entry reached with Back', () => {
    const { tab: t, store } = open('https://snow.test/');
    t.entries.unshift({ url: 'https://snow.test/?zip=nope&keep=1', state: null });
    t.index = 1;
    t.back();
    expect(t.location.href).toBe('https://snow.test/?keep=1');
    expect(store.state.selection).toBeNull();
  });

  it('keeps foreign parameters and the hash through every write', () => {
    const { tab: t, store } = open('https://snow.test/?replay=2026-01-12#list');
    store.select({ kind: 'zip', id: '02139' });
    store.setView({ lat: 42.37, lon: -71.1, zoom: 12 });
    vi.runAllTimers();
    expect(t.location.href).toBe(
      'https://snow.test/?zip=02139&at=42.37,-71.1,12&replay=2026-01-12#list',
    );
  });

  it('throws on a malformed id, which only a bug could pass', () => {
    const { store } = open('https://snow.test/');
    expect(() => {
      store.select({ kind: 'school', id: '42' });
    }).toThrow(RangeError);
  });
});

describe('share links', () => {
  it('carry the selection alone, or the view when nothing is selected', () => {
    const { store } = open('https://snow.test/?utm_source=x&at=40,-90,6#legend');
    expect(store.shareUrl()).toBe('https://snow.test/?at=40,-90,6');
    store.select({ kind: 'school', id: SCHOOL });
    expect(store.shareUrl()).toBe(`https://snow.test/?school=${SCHOOL}`);
    expect(store.shareUrl({ view: true })).toBe(`https://snow.test/?school=${SCHOOL}&at=40,-90,6`);
  });
});

describe('destroy', () => {
  it('writes what is pending and stops listening', () => {
    const { tab: t, store, seen } = open('https://snow.test/');
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    store.destroy();
    expect(t.search).toBe('?at=40,-90,6');
    const count = seen.length;
    t.entries.unshift({ url: 'https://snow.test/?zip=02139', state: null });
    t.index = 1;
    t.back();
    expect(seen).toHaveLength(count);
    store.setView({ lat: 1, lon: 1, zoom: 3 });
    vi.runAllTimers();
    expect(t.search).toBe('?zip=02139');
  });
});

describe('in a real document', () => {
  it('uses window by default', () => {
    window.history.replaceState(null, '', '/?keep=1&school=junk');
    const store = createUrlStore();
    expect(window.location.search).toBe('?keep=1');
    store.select({ kind: 'school', id: SCHOOL });
    expect(window.location.search).toBe(`?school=${SCHOOL}&keep=1`);
    store.setView({ lat: 40, lon: -90, zoom: 6 });
    store.flush();
    expect(window.location.search).toBe(`?school=${SCHOOL}&at=40,-90,6&keep=1`);
    store.destroy();
  });
});
