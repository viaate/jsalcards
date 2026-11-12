/**
 * Closings announced for later days, on the map and in its key: the map's
 * quiet dashed rings (map/later-rings.ts) and the key's "Later days" line
 * (ui/LaterKey.svelte), started by the app's services with the first later
 * day the live file names (app/boot.ts): the page's first script holds none
 * of it. Each file shown, and each change of the menu's filter, shows them
 * afresh; none while no file is shown, or a replay is on.
 */

import { mount, unmount } from 'svelte';
import type { Map as MapLibreMap } from 'maplibre-gl';

import { laterView } from '../data/later-days';
import { NO_LATER } from '../data/later-days';
import type { LaterView } from '../data/later-days';
import type { LaterRows } from '../data/live';
import { startLaterRings } from '../map/later-rings';
import type { LaterRings } from '../map/later-rings';
import type { MapFilter } from '../state/filter';
import LaterKey from './LaterKey.svelte';

export interface LaterHost {
  /** Shows the later days of the file shown, by the menu's filter; none for null. */
  show(rows: LaterRows | null, filter: MapFilter): void;
  destroy(): void;
}

export function startLater(stage: HTMLElement, map: MapLibreMap): LaterHost {
  // What LaterKey.svelte exports.
  // Before the key in the page's order, as the key is before a panel: a panel opened over the
  // map's foot covers the line, as it covers the key.
  const anchor = stage.querySelector(':scope > .legend') ?? stage.firstChild;
  const key: { show(view: LaterView): void } = mount(
    LaterKey,
    anchor === null ? { target: stage } : { target: stage, anchor },
  );
  let rings: LaterRings | null = null;
  try {
    rings = startLaterRings(map);
  } catch (error) {
    // No line for rings that are not drawn: the key names only what the map shows.
    console.warn('Snowlight: later-day rings unavailable', error);
  }
  return {
    show(rows, filter) {
      const view = laterView(rows, filter);
      key.show(rings === null ? NO_LATER : view);
      rings?.show(view.marks, rows?.directory ?? null);
    },
    destroy() {
      rings?.remove();
      void unmount(key);
    },
  };
}
