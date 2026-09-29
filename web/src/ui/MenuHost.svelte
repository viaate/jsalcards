<script lang="ts">
  import type { MenuView } from '../app/menu';
  import type { StatusCounts } from '../data/closings';
  import type { Basemap } from '../map/basemap';
  import { SHOW_ALL, sameFilter, showsAll } from '../state/filter';
  import type { MapFilter } from '../state/filter';
  import MenuPanel from './MenuPanel.svelte';

  interface Props {
    /** The menu's button beside the search field: it says whether the menu is open, and names it. */
    button: HTMLElement;
    /** The page's stage: the key at its foot and the button follow what the map shows. */
    stage: HTMLElement;
    /** Reads what the published files give the menu (app/menu.ts). */
    read: () => Promise<MenuView>;
    /** Has the map show what the menu picks: the glow's lights, the school dots and names. */
    show: (filter: MapFilter) => void;
    /** The map, once it is up: its labels keep clear of the menu. */
    map: () => Basemap | undefined;
    /** How many schools the map lights in each status, of the kinds it shows; null while none is. */
    counts: () => StatusCounts | null;
  }

  let { button, stage, read, show, map, counts }: Props = $props();

  /** The panel's id, which the button names while it shows. */
  const ID = 'menu';
  /** What the menu shows when the files cannot be read: its controls and About. */
  const NOTHING_READ: MenuView = { season: null, record: null, map: null };

  let open = $state(false);
  /** What the published files give it, read the first time it opens. */
  let view = $state<MenuView | null>(null);
  let reading = false;
  /** What the map shows: everything, as every visit opens, until it is changed here. */
  let filter = $state<MapFilter>(SHOW_ALL);

  /** It shows once what it shows is read, whole: nothing in it moves as a part comes in. */
  const shown = $derived(open && view !== null);

  /** Opens the menu, or closes it. */
  export function toggle(): void {
    if (open) {
      close();
      return;
    }
    open = true;
    if (view !== null || reading) return;
    reading = true;
    read().then(
      (found) => {
        view = found;
      },
      () => {
        view = NOTHING_READ;
      },
    );
  }

  /** Closes the menu; with `refocus`, the keyboard goes back to its button. */
  export function close(refocus = false): void {
    open = false;
    if (refocus) button.focus();
  }

  // The button says whether the menu is open, and names it while it shows.
  $effect(() => {
    button.setAttribute('aria-expanded', String(open));
    if (shown) button.setAttribute('aria-controls', ID);
    else button.removeAttribute('aria-controls');
  });

  // The menu comes or goes over the map: its labels keep clear of it.
  let wasShown = false;
  $effect(() => {
    if (shown === wasShown) return;
    wasShown = shown;
    map()?.controlsChanged();
  });

  // Back or Forward (a school opening or closing) takes the menu's place.
  $effect(() => {
    const onHistory = (): void => {
      close();
    };
    window.addEventListener('popstate', onHistory);
    return () => {
      window.removeEventListener('popstate', onHistory);
    };
  });

  // The key steps back from the statuses the map leaves off, and a dot on the button says the
  // map shows less than everything (index.html).
  $effect(() => {
    if (filter.status === null) delete stage.dataset.status;
    else stage.dataset.status = String(filter.status);
    stage.toggleAttribute('data-filtered', !showsAll(filter));
  });

  /** Has the map show what the menu picks, and the menu with it. */
  function pick(next: MapFilter): void {
    filter = sameFilter(next, SHOW_ALL) ? SHOW_ALL : next;
    show(filter);
  }
</script>

<!--
  The menu, started by the app once its button is first pressed
  (ui/menu-host.ts): whether it is open, what the published files give it, and
  what it has the map show. The page keeps nothing of it but the button, so
  none of this is in the page's first script.
-->
{#if shown && view !== null}
  <MenuPanel {view} id={ID} {filter} counts={counts()} {button} onfilter={pick} onclose={close} />
{/if}
