/**
 * Runs the mode switch (flights spec D2): puts the switch in the top strip, opens the mode the
 * address names (or the one kept on this device, at the bare address), and starts and stops
 * each mode's module as the switch, Back and Forward change it.
 *
 * Started by the app's services (app/boot.ts) once the map is up, in a chunk of its own, so the
 * page's first script carries none of it. Schools is the page itself: while another mode shows,
 * the root carries `data-mode` (set by the page's head from the address before the first paint,
 * so a link to another mode never shows Schools' controls first), Schools' own controls step
 * aside (index.html's styles), its map layers are hidden (schools-layers.ts) and a tap on the
 * map opens no school (map/school-taps.ts).
 */
import { mount, unmount } from 'svelte';

import type { Basemap } from '../map/basemap';
import ModeSwitch from './ModeSwitch.svelte';
import {
  MODES,
  firstMode,
  keepMode,
  keptMode,
  modeHref,
  modeOfSearch,
  openingMode,
  otherParams,
} from './registry';
import type { ModeEntry } from './registry';
import { MODE_EVENT, showSchoolLayers } from './schools-layers';

export interface ModeHostOptions {
  readonly map: Basemap;
  readonly signal: AbortSignal;
  /**
   * Closes what Schools has open (its panel), after the other mode's address is written: so the
   * Schools entry keeps its school, and Back opens it again.
   */
  readonly closeSchools: () => void;
  /** The modes, the registry's own by default (a test adds one this build does not have). */
  readonly modes?: readonly ModeEntry[];
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function startModes(options: ModeHostOptions): void {
  const { map, signal } = options;
  const modes = options.modes ?? MODES;
  const first = firstMode(modes);
  const header = document.querySelector<HTMLElement>('header.bar');
  const stage = document.querySelector<HTMLElement>('main.stage');
  if (header === null || stage === null || signal.aborted) return;
  // From here the host shows the mode: a script that cannot load later no longer takes the head's
  // mark off (index.html); the mode's own failures are this host's to show.
  delete (window as { snowlightUnmark?: unknown }).snowlightUnmark;

  let current: ModeEntry = first;
  let running: AbortController | null = null;
  const switchProps = cell(first.key);
  const root = document.documentElement;

  /** Shows `mode`; `opening`: as the page opens, when the map's labels have nothing to move for. */
  const show = (mode: ModeEntry, opening = false): void => {
    if (mode.key === current.key && (running !== null || mode.load === null)) {
      // The first mode at the first show: the head may have marked a mode this build lacks.
      if (mode.load === null && root.dataset.mode !== undefined) delete root.dataset.mode;
      else return;
    }
    running?.abort();
    running = null;
    current = mode;
    switchProps.set(mode.key);
    if (mode.load === null) {
      delete root.dataset.mode;
      showSchoolLayers(map, true);
      // The layers Schools hides for reasons of its own (the later rings) look again.
      window.dispatchEvent(new Event(MODE_EVENT));
      if (!opening) map.controlsChanged();
      return;
    }
    root.dataset.mode = mode.key;
    showSchoolLayers(map, false);
    window.dispatchEvent(new Event(MODE_EVENT));
    const controller = new AbortController();
    running = controller;
    signal.addEventListener(
      'abort',
      () => {
        controller.abort();
      },
      { once: true },
    );
    void mode.load().then(
      (module) => {
        if (controller.signal.aborted) return;
        module.start({ map, header, stage, signal: controller.signal });
        if (!opening) map.controlsChanged();
      },
      () => {
        // The mode's code could not load (offline): back to the first mode, never a blank page,
        // and the address says so, so a reload or a shared copy opens what the page shows.
        if (controller.signal.aborted) return;
        try {
          history.replaceState(
            history.state,
            '',
            modeHref(location.href, first, otherParams(first, modes), modes),
          );
        } catch {
          // The address could not change (Safari's write limit): the first mode still shows.
        }
        show(first);
      },
    );
  };

  const pick = (key: string): void => {
    const mode = modes.find((entry) => entry.key === key);
    if (mode === undefined || mode.key === current.key) return;
    keepMode(storage(), mode);
    try {
      history.pushState(null, '', modeHref(location.href, mode, otherParams(mode, modes), modes));
    } catch {
      // The address could not change (Safari's write limit): the mode still shows.
    }
    // After the push: the entry left keeps Schools' school, which Back opens again.
    if (mode.key !== first.key) options.closeSchools();
    show(mode);
  };

  // The address the page opened on (index.html keeps it before Schools' code can change it).
  const opened = (window as { snowlightOpening?: unknown }).snowlightOpening;
  const search = typeof opened === 'string' ? opened : location.search;
  const opening = openingMode(search, keptMode(storage()), modes);
  if (opening.key !== first.key && modeOfSearch(location.search, modes) === null) {
    // The kept mode, at the bare address: the address says it, so a reload or a share keeps it.
    try {
      history.replaceState(history.state, '', modeHref(location.href, opening, [], modes));
    } catch {
      // As above.
    }
  }
  if (opening.key !== first.key) options.closeSchools();

  const switcher = mount(ModeSwitch, {
    target: header,
    props: { modes, current: switchProps, onpick: pick },
  });
  show(opening, true);

  // Back and Forward between modes.
  window.addEventListener(
    'popstate',
    () => {
      show(modeOfSearch(location.search, modes) ?? first);
    },
    { signal },
  );
  // A new theme puts the map's style on again, school layers and all: hidden again while hidden.
  const onStyle = (): void => {
    if (current.load !== null) showSchoolLayers(map, false);
  };
  map.map.on('styledata', onStyle);
  signal.addEventListener(
    'abort',
    () => {
      running?.abort();
      map.map.off('styledata', onStyle);
      void unmount(switcher);
    },
    { once: true },
  );
}

/** A value the switch reads and the host sets, without a store library. */
export interface Cell<T> {
  get(): T;
  set(value: T): void;
  subscribe(listener: (value: T) => void): () => void;
}

function cell<T>(initial: T): Cell<T> {
  let value = initial;
  const listeners = new Set<(value: T) => void>();
  return {
    get: () => value,
    set: (next) => {
      if (next === value) return;
      value = next;
      for (const listener of listeners) listener(value);
    },
    subscribe: (listener) => {
      listeners.add(listener);
      listener(value);
      return () => listeners.delete(listener);
    },
  };
}
