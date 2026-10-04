/**
 * Everything the app does besides drawing its shell and the map, loaded
 * after the first paint so none of it weighs on the first frame:
 *
 * - the pinned school, opened on a plain visit (src/state/pin.ts);
 * - a linked or pinned selection, placed on the map once the data allows;
 * - search: the index loads on the first focus of the search field;
 * - today's schools lit on the glow layer (App.svelte puts it on the map), the
 *   time of the live file they come from, for the update time, and how many
 *   are lit in each status, for the legend; and every school as dust on it,
 *   read the first time the map shows the dust;
 * - the service worker, registered once the map is on screen;
 * - the school a pick or a link opens: its detail panel's view (app/school.ts,
 *   loaded when a school is first opened), and the pin;
 * - a school clicked or tapped on the map, once it is on screen
 *   (map/school-taps.ts), handed to the page to open as a pick of it, and a
 *   tap on several schools, which zooms the map in toward them.
 *
 * A build that ships no data requests nothing under data/: the glow stays
 * dark, search shows nothing and no selection moves the map.
 */

import type { Basemap, MapView } from '../map/basemap';
import type { Glow } from '../map/glow-mount';
import { keepClicks } from '../map/kept-clicks';
import type { SchoolHit, SchoolTaps } from '../map/school-taps';
import type { SearchHit } from '../search';
import { SHOW_ALL, showsSchool } from '../state/filter';
import type { MapFilter } from '../state/filter';
import { createPinStore } from '../state/pin-store';
import type { PinStore } from '../state/pin-store';
import type { Selection } from '../state/url';
import type { UrlStore } from '../state/url-store';
import type { SchoolId, UtcInstant } from '../types/generated';
import type { StatusCounts } from '../data/closings';
import type { DetailsSource } from '../data/details';
import { DATA_PATHS } from '../data/files';
import { createAppData, dustSource, locate, startLiveGlow } from './data';
import type { AppData, LiveGlow, Target } from './data';
import { clearOfPanel, mapInView } from './frame';
import type { Screen } from './frame';
import { createSearchController, nearView, searchOptions } from './search';
import type { SearchController, SearchOption } from './search';
import type { MenuView } from './menu';
import type { Menu } from '../ui/menu-host';
import type { SchoolHint, SchoolView, WatchOptions } from './school';
import { startServiceWorker } from './service-worker';
import { selectionForHit, startupSelection, viewForHit } from './startup';

export type { Screen } from './frame';
export type { StatusCounts } from '../data/closings';
export type { SchoolHit } from '../map/school-taps';
export type { Target } from './data';
export type { SearchOption } from './search';
export type { MenuView } from './menu';
export type { MapFilter } from '../state/filter';
export type { NearbyView, SchoolHint, SchoolView } from './school';

export interface BootOptions {
  readonly links: UrlStore;
  /**
   * Settles once the address is read, when its store's code came after the
   * app started (state/late-url-store.ts): true when it opens as a link would.
   * What the app opens with, the link or the pinned school, waits for it. By
   * default the address is read already.
   */
  readonly addressOpens?: Promise<boolean>;
  /**
   * Settles once the formatters are in (app/late-formats.ts). The menu's and
   * the panel's code import them, and are asked for only after it. By default
   * they are in already.
   */
  readonly formats?: Promise<unknown>;
  /** The map once its first frame is up; undefined when it cannot start. */
  readonly map: Promise<Basemap | undefined>;
  /**
   * The same map as soon as it takes input, before its first frame is up:
   * clicks on schools are kept from then. The map's first frame by default.
   */
  readonly mapCreated?: Promise<Basemap | undefined>;
  /** The glow layer on that map; null when the map or the layer cannot start. */
  readonly glow: Promise<Glow | null>;
  /** Aborted when the app goes away. */
  readonly signal: AbortSignal;
  /** Moves the map to a place (the shell keeps it for later if the map is not up yet). */
  readonly show: (target: Target) => void;
  /**
   * The screen, the foot of the search strip over the map and the panel shown
   * over it (frame.ts): a school a pick or a link opens is framed clear of its
   * panel on it, and a tap on several schools zooms them into the map the
   * panel shown, if any, leaves in view.
   */
  readonly screen?: () => Screen;
  /**
   * The view that shows a place clear of what the page puts over the map for
   * what it opens (a school's panel), for tests; by default a school is
   * framed clear of its panel on `screen`, and any other place, or any place
   * without one, is shown as it is.
   */
  readonly frame?: Frame;
  /** The results list's element id; options are numbered under it. */
  readonly listId: string;
  /** The newest text's results as options, or null to show nothing. */
  readonly onResults: (options: readonly SearchOption[] | null) => void;
  /** The generated_at of the live file the map shows, for the update time; null when none is. */
  readonly onUpdated?: (generatedAt: UtcInstant | null) => void;
  /**
   * How many schools the map lights in each status, of the kinds the menu's
   * filter shows, for the legend and the menu; null while none is lit.
   */
  readonly onCounts?: (counts: StatusCounts | null) => void;
  /**
   * A school clicked or tapped on the map, its dot, its dust, its name or its light:
   * the page opens it as a pick of it would. Without it, a click opens nothing.
   */
  readonly onSchool?: (school: SchoolHit) => void;
  /** Data files to read, for tests; defaults to the ones this build ships. */
  readonly data?: AppData;
}

export interface Services {
  /** Whether this build ships a search index; without one, search shows nothing. */
  readonly searchable: boolean;
  /** Starts loading the search index (first focus). */
  warmSearch(): void;
  /**
   * Searches `text`; results arrive through onResults. Good matches near
   * where the map is looking come first.
   */
  query(text: string): void;
  /**
   * Opens what a result names and moves the map to it, as one new history
   * entry (a city's holds its view alone), so Back returns to the place before.
   * Of a result, only what it is and where it is counts.
   */
  pick(hit: Pick<SearchHit, 'kind' | 'id' | 'lat' | 'lon'>): void;
  /**
   * Reads a school for its detail panel and keeps its view current:
   * `onView` hears each new view, and null when there is no such school.
   * `hint` is what a search pick already knows. Returns the function that stops it.
   */
  watchSchool(
    id: SchoolId,
    hint: SchoolHint | null,
    onView: (view: SchoolView | null) => void,
  ): () => void;
  /** The pinned school ("My school"). */
  readonly pins: PinStore;
  /**
   * What the menu shows beside About (app/menu.ts), read once, the first
   * time the menu opens; a part whose file this build does not ship, or that
   * cannot be read, is left out.
   */
  menu(): Promise<MenuView>;
  /**
   * Opens the menu under the search field from its button, or closes it; its
   * code loads with the first press (ui/menu-host.ts). `counts` gives how many
   * schools the map lights in each status, for its rows.
   */
  toggleMenu(button: HTMLElement, counts: () => StatusCounts | null): void;
  /**
   * Shows only what the menu's filter keeps: the lit schools of its status
   * and kinds on the glow, the school dots, dust and names of its kinds on
   * the map, and the open school's whatever its kind.
   */
  filter(filter: MapFilter): void;
}

/** Whether a school with these kind flags shows under this filter, for the glow's dust. */
function kindsShown(filter: MapFilter): (flags: number) => boolean {
  return (flags) => showsSchool(filter, flags);
}

/** A view, as it shows a place clear of what the page puts over the map for what it opens. */
type Frame = (view: MapView, selection: Selection | null) => MapView;

export function boot(options: BootOptions): Services {
  const { links, signal, screen, formats = Promise.resolve() } = options;
  const frame: Frame | undefined =
    options.frame ??
    (screen === undefined
      ? undefined
      : (view, selection) => (selection?.kind === 'school' ? clearOfPanel(view, screen()) : view));
  const data = options.data ?? createAppData();
  const pins = createPinStore();
  const warmUrls: string[] = [];
  /** The map from the moment it takes input. */
  let created: Basemap | undefined;
  void (options.mapCreated ?? options.map).then((map) => {
    created = map;
  });
  const search: SearchController = createSearchController({
    indexUrl: data.files.url(DATA_PATHS.searchIndex),
    onResults: (results) => {
      const shown = results === null ? null : searchOptions(results, options.listId);
      // What the streets a pick of the first place shown flies to need comes while they choose.
      const first = shown?.[0]?.hit;
      created?.prepareStreets(first === undefined ? undefined : viewForHit(first));
      options.onResults(shown);
    },
    onIndexLoaded: (url) => {
      warmUrls.push(url);
    },
  });

  // A link opens as sent; a plain visit opens the pinned school, without a history entry.
  const open = (): void => {
    const opening = startupSelection(links.state, pins.school);
    if (opening !== null && links.state.selection === null) {
      links.select(opening, { replace: true });
    }
    const selection = links.state.selection;
    if (selection !== null && links.state.view === null) {
      void goToSelection(data, selection, search, options, frame);
    }
  };
  if (options.addressOpens === undefined) open();
  else {
    void options.addressOpens.then((opens) => {
      if (opens && !signal.aborted) open();
    });
  }

  // A function, so each check reads the signal afresh after an await.
  const aborted = (): boolean => signal.aborted;
  /** The map, once it is up, for where the person is looking when they search. */
  let basemap: Basemap | undefined;
  void options.map.then((map) => {
    basemap = map;
  });
  const near = (): ReturnType<typeof nearView> => {
    if (basemap === undefined) return undefined;
    const container = basemap.map.getContainer();
    return nearView(basemap.view, container.clientWidth, container.clientHeight);
  };
  const glow = options.glow;
  let live: LiveGlow | null = null;
  /** The menu's filter, kept for the live glow while it starts: everything, as every visit opens. */
  let filter: MapFilter = SHOW_ALL;
  void glow.then(async (layer) => {
    if (layer === null || aborted()) return;
    // Every school as dust further out, read from the directory once the map shows it, of the
    // kinds the menu shows.
    layer.dust(dustSource(data));
    layer.showSchools(kindsShown(filter));
    // And the open school's whatever its kind, as its dot.
    const stopSelected = links.subscribe(({ selection }) => {
      layer.select(selection?.kind === 'school' ? selection.id : null);
    });
    signal.addEventListener('abort', stopSelected);
    const started = await startLiveGlow(
      data,
      glow,
      {
        onShown: (generatedAt) => {
          if (!aborted()) options.onUpdated?.(generatedAt);
        },
        // Once the page's face has loaded, so the counts are set in the face they keep. One
        // promise, so counts heard later are passed on later.
        onCounts: (counts) => {
          void document.fonts.ready.then(() => {
            if (!aborted()) options.onCounts?.(counts);
          });
        },
      },
      filter,
    );
    live = started;
    // A change made while it started.
    started.filter(filter);
    if (aborted()) started.stop();
  });

  // Once the map is on screen: installing the worker would otherwise run alongside its start.
  void startServiceWorker(warmUrls, options.map);

  /** The menu, started the first time its button is pressed (ui/menu-host.ts). */
  let menuHost: Promise<Menu | null> | null = null;

  signal.addEventListener('abort', () => {
    void menuHost?.then((menu) => menu?.destroy());
    taps?.stop();
    live?.stop();
    search.destroy();
    pins.destroy();
    void glow.then((layer) => {
      layer?.remove();
    });
  });

  /** The panel's code and the school records' reader, loaded when a school first opens. */
  let schoolCode: Promise<{
    source: DetailsSource;
    watch: (watchOptions: WatchOptions) => () => void;
  }> | null = null;
  const loadSchoolCode = (): NonNullable<typeof schoolCode> => {
    schoolCode ??= formats
      .then(() => import('./school'))
      .then((module) => ({
        watch: module.watchSchool,
        source: module.createDetailsSource(data.files),
      }));
    return schoolCode;
  };

  /** The menu's view, read the first time the menu opens. */
  let menuView: Promise<MenuView> | null = null;
  // Clicks on schools, from the moment the map takes input. Until their code is in (it loads
  // on the first click, or once the map is on screen) each is kept, and handed on only if the
  // map has not moved since (map/kept-clicks.ts). A lit school, and a school drawn as dust, is
  // found in the glow's own data, read as each click comes. A tap on several schools zooms in as
  // the map's own flights go.
  let taps: SchoolTaps | null = null;
  /** Where the last flight a pick or a tap set off was going: for a flight stopped short. */
  let flight: MapView | null = null;
  const onSchool = options.onSchool;
  if (onSchool !== undefined) {
    let layer: Glow | null = null;
    void glow.then((mounted) => {
      layer = mounted;
    });
    void (options.mapCreated ?? options.map)
      .then(async (map) => {
        if (map === undefined || aborted()) return;
        const kept = keepClicks(map.map);
        const code = Promise.race([options.map, kept.heard]).then(
          () => import('../map/school-taps'),
        );
        // Kept no longer once the code is in, or cannot be had.
        const clicks = await code.then(
          () => kept.stop(),
          (error: unknown) => {
            kept.stop();
            throw error;
          },
        );
        const { attachSchoolTaps } = await code;
        if (aborted()) return;
        taps = attachSchoolTaps(map.map, {
          lit: () => layer?.lit ?? null,
          dust: () => layer?.specks ?? null,
          onSchool,
          onZoom: (view) => {
            flight = view;
            map.flyTo(view);
          },
          onResume: () => {
            if (flight !== null) map.flyTo(flight);
          },
          // Pressed on, its light too: what its streets need comes before the click.
          onPress: (school) => {
            map.streetsAhead(viewForHit({ kind: 'school', lat: school.lat, lon: school.lon }));
          },
          // Shown picked at once, its ring on the map, its panel's code and record on their way;
          // the ring back on the school open, if any, when the tap turns out to be a double tap.
          onPending: (school) => {
            const open = links.state.selection;
            map.selectSchool(school?.id ?? (open?.kind === 'school' ? open.id : null));
            if (school === null) return;
            import('../ui/DetailPanel.svelte').catch(() => undefined);
            void loadSchoolCode()
              .then(({ source }) => source.get(school.id))
              .catch(() => undefined);
          },
          ...(screen === undefined ? {} : { area: () => mapInView(screen()) }),
        });
        for (const click of clicks) taps.click(click);
      })
      .catch(() => undefined);
  }

  const services: Services = {
    searchable: data.files.has(DATA_PATHS.searchIndex),
    pins,
    filter(next) {
      filter = next;
      live?.filter(next);
      // The dust too, as the dots.
      void glow.then((layer) => layer?.showSchools(kindsShown(next)));
      // The dots and names, on the map as soon as it takes input (it keeps them for layers to come).
      void (options.mapCreated ?? options.map).then((map) => map?.showSchools(next));
    },
    toggleMenu(button, counts) {
      menuHost ??= formats
        .then(() => import('../ui/menu-host'))
        .then(
          ({ startMenu }) =>
            startMenu({
              button,
              read: () => services.menu(),
              show: (next) => {
                services.filter(next);
              },
              map: () => basemap,
              counts,
            }),
          () => null,
        );
      void menuHost.then((menu) => {
        // Its code could not load: the next press tries again.
        if (menu === null) menuHost = null;
        else menu.toggle();
      });
    },
    menu() {
      if (menuView === null) {
        const reading = formats
          .then(() => import('./menu'))
          .then(({ readMenu }) => readMenu(data.files));
        menuView = reading;
        // Its code could not load (offline, a deploy in flight): About alone, and the next open tries again.
        reading.catch(() => {
          if (menuView === reading) menuView = null;
        });
      }
      return menuView.catch(() => ({ season: null, record: null, map: null }));
    },
    watchSchool(id, hint, onView) {
      let stop: (() => void) | null = null;
      let stopped = false;
      loadSchoolCode().then(
        ({ watch, source }) => {
          if (stopped || aborted()) return;
          stop = watch({
            files: data.files,
            details: source,
            id,
            hint,
            onView,
            // The districts next door, for the chance section: the directory the glow reads.
            directory: async (stamp) => (await (await data.directories())?.get(stamp)) ?? null,
          });
        },
        () => {
          if (!stopped) onView(null);
        },
      );
      return () => {
        stopped = true;
        stop?.();
      };
    },
    warmSearch: () => {
      search.warm();
    },
    query: (text) => {
      search.query(text, near());
    },
    pick(hit) {
      // Every pick is a step of its own, a city too: Back returns to the place before.
      const selection = selectionForHit(hit);
      let view = frame?.(viewForHit(hit), selection) ?? viewForHit(hit);
      try {
        links.navigate({ selection, view });
      } catch {
        // An id a link cannot carry: the step keeps the place alone.
        view = viewForHit(hit);
        links.navigate({ selection: null, view });
      }
      flight = view;
      options.show({ view });
    },
  };
  return services;
}

/** A selection the app opened by itself (a link or the pin): go to it once it is placed. */
async function goToSelection(
  data: AppData,
  selection: Selection,
  search: SearchController,
  options: BootOptions,
  frame: Frame | undefined,
): Promise<void> {
  const [target, map] = await Promise.all([locate(data, selection, search), options.map]);
  // Someone moved the map meanwhile, or opened something else: leave it.
  if (target === null || map === undefined || map.moved || options.signal.aborted) return;
  if (options.links.state.selection !== selection) return;
  options.show(
    'view' in target && frame !== undefined ? { view: frame(target.view, selection) } : target,
  );
}
