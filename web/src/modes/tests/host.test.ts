/**
 * The mode switch on a page (flights spec D2): a mode this build does not have (Boats) runs from
 * one more entry in the list and a module of its own, with no change to Schools or Flights, and
 * every round trip leaves Schools' strip and stage as they were.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Basemap } from '../../map/basemap';
import { startModes } from '../host';
import { MODES } from '../registry';
import type { ModeEntry, ModeModule } from '../registry';

/** A throwaway mode: one marker on the stage while it shows, and an address parameter of its own. */
const boatsModule: ModeModule = {
  start({ stage, header, signal }) {
    const marker = document.createElement('p');
    marker.className = 'boats-marker';
    stage.append(marker);
    const field = document.createElement('div');
    field.className = 'boats-search mode-own';
    header.append(field);
    signal.addEventListener('abort', () => {
      marker.remove();
      field.remove();
    });
  },
};
const boats: ModeEntry = {
  key: 'boats',
  label: 'Boats',
  glyph: 'M2 11h12l-2 3H4zM8 2v8M8 3l4 6H8',
  params: ['harbor'],
  load: () => Promise.resolve(boatsModule),
};

const canvas = document.createElement('canvas');

function stubMap(): Basemap {
  const map = {
    on: vi.fn(),
    off: vi.fn(),
    getLayersOrder: () => [],
    getLayer: () => undefined,
    getCanvas: () => canvas,
    getLayoutProperty: () => 'visible',
    setLayoutProperty: vi.fn(),
  };
  return { map, controlsChanged: vi.fn() } as unknown as Basemap;
}

const SCHOOLS_STRIP = ['H1.wordmark', 'FORM.search', 'BUTTON.menu-button', 'DIV.mode-switch'];
const SCHOOLS_STAGE = ['UL.legend', 'DIV.map'];

function names(parent: Element | null): string[] {
  return [...(parent?.children ?? [])].map((node) => `${node.tagName}.${node.classList[0] ?? ''}`);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function radio(key: string): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(`[data-mode-key="${key}"]`);
  if (button === null) throw new Error(`no ${key} button`);
  return button;
}

describe('the switch with a mode this build does not have', () => {
  let stop: AbortController;
  const closeSchools = vi.fn();

  beforeEach(() => {
    history.replaceState(null, '', '/');
    document.body.innerHTML = `
      <header class="bar"><h1 class="wordmark"></h1><form class="search"></form><button class="menu-button"></button></header>
      <main class="stage"><ul class="legend"></ul><div class="map"></div></main>`;
    stop = new AbortController();
    closeSchools.mockClear();
    // Flights reads no files here: every read fails, and it says so.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('offline'))),
    );
  });

  afterEach(() => {
    stop.abort();
    vi.unstubAllGlobals();
    delete document.documentElement.dataset.mode;
  });

  it('lists it, shows it, takes it away and leaves Schools as it was', async () => {
    startModes({ map: stubMap(), signal: stop.signal, closeSchools, modes: [...MODES, boats] });
    expect(names(document.querySelector('header.bar'))).toEqual(SCHOOLS_STRIP);
    expect(radio('boats').textContent.trim()).toBe('Boats');

    radio('boats').click();
    await settle();
    expect(new URL(location.href).searchParams.get('mode')).toBe('boats');
    expect(document.documentElement.dataset.mode).toBe('boats');
    expect(document.querySelector('.boats-marker')).not.toBeNull();
    expect(closeSchools).toHaveBeenCalledTimes(1);
    expect(radio('boats').getAttribute('aria-checked')).toBe('true');

    // Its own parameter goes as another mode shows.
    history.replaceState(null, '', '/?mode=boats&harbor=SEA');
    radio('flights').click();
    // Flights' chunk compiles on its first load here: on a busy machine that takes a while.
    await vi.waitFor(
      () => {
        expect(document.querySelector('header.bar .fl-head')).not.toBeNull();
      },
      { timeout: 10_000 },
    );
    const there = new URL(location.href).searchParams;
    expect(there.get('mode')).toBe('flights');
    expect(there.get('harbor')).toBeNull();
    expect(document.querySelector('.boats-marker')).toBeNull();
    expect(document.querySelector('header.bar .fl-head .search-input')).not.toBeNull();
    expect(document.querySelector('.stage > .mode-ui')).not.toBeNull();

    radio('schools').click();
    await settle();
    expect(location.search).toBe('');
    expect(document.documentElement.dataset.mode).toBeUndefined();
    expect(names(document.querySelector('header.bar'))).toEqual(SCHOOLS_STRIP);
    expect(names(document.querySelector('main.stage'))).toEqual(SCHOOLS_STAGE);
  });

  it('leaves Schools whole after Flights, by the switch and by Back', async () => {
    startModes({ map: stubMap(), signal: stop.signal, closeSchools, modes: [...MODES, boats] });
    for (const way of ['switch', 'back'] as const) {
      radio('flights').click();
      await vi.waitFor(
        () => {
          expect(document.querySelector('header.bar .fl-head')).not.toBeNull();
        },
        { timeout: 10_000 },
      );
      if (way === 'switch') radio('schools').click();
      else {
        history.replaceState(null, '', '/');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      await settle();
      expect(names(document.querySelector('header.bar'))).toEqual(SCHOOLS_STRIP);
      expect(names(document.querySelector('main.stage'))).toEqual(SCHOOLS_STAGE);
      expect(radio('schools').getAttribute('aria-checked')).toBe('true');
    }
  });

  it('writes the other mode before closing Schools’ school, so Back opens it again', () => {
    history.replaceState(null, '', '/?school=0100001');
    const seen: string[] = [];
    startModes({
      map: stubMap(),
      signal: stop.signal,
      closeSchools: () => seen.push(location.search),
      modes: [...MODES, boats],
    });
    const pushes = vi.spyOn(history, 'pushState');
    radio('boats').click();
    expect(seen).toEqual(['?mode=boats']);
    expect(pushes).toHaveBeenCalledTimes(1);
    pushes.mockRestore();
  });

  it('opens on the address the page opened on, never one Schools has cleared since', async () => {
    const opened = window as { snowlightOpening?: string };
    localStorage.setItem('snowlight:mode', 'boats');
    try {
      // A link to a school Schools does not know: Schools took it off the address already.
      opened.snowlightOpening = '?school=0100001';
      history.replaceState(null, '', '/');
      const first = new AbortController();
      startModes({ map: stubMap(), signal: first.signal, closeSchools, modes: [...MODES, boats] });
      await settle();
      expect(radio('schools').getAttribute('aria-checked')).toBe('true');
      expect(location.search).toBe('');
      expect(document.querySelector('.boats-marker')).toBeNull();
      first.abort();
      await settle();
      // The bare address as it opened: the mode kept on this device.
      opened.snowlightOpening = '';
      startModes({ map: stubMap(), signal: stop.signal, closeSchools, modes: [...MODES, boats] });
      await settle();
      expect(radio('boats').getAttribute('aria-checked')).toBe('true');
      expect(location.search).toBe('?mode=boats');
    } finally {
      delete opened.snowlightOpening;
      localStorage.removeItem('snowlight:mode');
    }
  });

  it('takes off a mode the page’s head marked that this build does not have', async () => {
    history.replaceState(null, '', '/?mode=gliders');
    document.documentElement.dataset.mode = 'gliders';
    startModes({ map: stubMap(), signal: stop.signal, closeSchools, modes: [...MODES, boats] });
    expect(document.documentElement.dataset.mode).toBeUndefined();
    await settle();
    expect(radio('schools').getAttribute('aria-checked')).toBe('true');
  });
});
