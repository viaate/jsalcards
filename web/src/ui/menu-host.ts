/**
 * The menu, started by the app's services the first time its button is
 * pressed (app/boot.ts): the page's first script holds only the button. The
 * menu goes on the page's stage, after everything else on it, and keeps
 * itself: whether it is open, what it shows, and what it has the map show
 * (ui/MenuHost.svelte).
 */

import { mount, unmount } from 'svelte';

import type { MenuView } from '../app/menu';
import type { StatusCounts } from '../data/closings';
import type { Basemap } from '../map/basemap';
import type { MapFilter } from '../state/filter';
import MenuHost from './MenuHost.svelte';

export interface MenuOptions {
  /** The menu's button beside the search field. */
  readonly button: HTMLElement;
  /** Reads what the published files give the menu. */
  readonly read: () => Promise<MenuView>;
  /** Has the map show what the menu picks. */
  readonly show: (filter: MapFilter) => void;
  /** The map, once it is up. */
  readonly map: () => Basemap | undefined;
  /** How many schools the map lights in each status, of the kinds it shows; null while none is. */
  readonly counts: () => StatusCounts | null;
}

export interface Menu {
  /** Opens the menu, or closes it. */
  toggle(): void;
  /** Closes it, if it is open. */
  close(): void;
  /** Takes it off the page. */
  destroy(): void;
}

export function startMenu(options: MenuOptions): Menu {
  const stage = options.button.closest<HTMLElement>('.stage') ?? document.body;
  // What MenuHost.svelte exports.
  const host: Pick<Menu, 'toggle' | 'close'> = mount(MenuHost, {
    target: stage,
    props: { ...options, stage },
  });
  return {
    toggle: () => {
      host.toggle();
    },
    close: () => {
      host.close();
    },
    destroy: () => {
      void unmount(host);
    },
  };
}
