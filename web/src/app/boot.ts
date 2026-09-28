/**
 * Everything the app does besides drawing its shell and the map, loaded
 * after the first paint so none of it weighs on the first frame:
 *
 * - the pinned school, opened on a plain visit (src/state/pin.ts);
 * - a linked or pinned selection, placed on the map once the data allows;
 * - search: the index loads on the first focus of the search field;
 * - today's schools lit on the glow layer (App.svelte puts it on the map), and
 *   the time of the live file they come from, for the update time;
 * - the service worker, registered once the map is on screen;
 * - the school a pick or a link opens: its detail panel's view (app/school.ts,
 *   loaded when a school is first opened), and the pin.
 *
 * A build that ships no data requests nothing under data/: the glow stays
 * dark, search shows nothing and no selection moves the map.
 */

import type { Basemap, MapView } from '../map/basemap';
import type { Glow } from '../map/glow-mount';
import type { SearchHit } from '../search';
import { createPinStore } from '../state/pin';
import type { PinStore } from '../state/pin';
import type { Selection } from '../state/url';
import type { UrlStore } from '../state/url-store';
import type { SchoolId, UtcInstant } from '../types/generated';
import type { DetailsSource } from '../data/details';
import { DATA_PATHS } from '../data/files';
import { createAppData, locate, startLiveGlow } from './data';
import type { AppData, Target } from './data';
import { createSearchController, nearView, searchOptions } from './search';
import type { SearchController, SearchOption } from './search';
import type { SchoolHint, SchoolView, WatchOptions } from './school';
import { startServiceWorker } from './service-worker';
import { selectionForHit, startupSelection, viewForHit } from './startup';

export { clearOfPanel } from './frame';
export type { Target } from './data';
export type { SearchOption } from './search';
export type { NearbyView, SchoolHint, SchoolView } from './school';

export interface BootOptions {
  readonly links: UrlStore;
  /** The map once its first frame is up; undefined when it cannot start. */
  readonly map: Promise<Basemap | undefined>;
  /** The glow layer on that map; null when the map or the layer cannot start. */
  readonly glow: Promise<Glow | null>;
  /** Aborted when the app goes away. */
  readonly signal: AbortSignal;
  /** Moves the map to a place (the shell keeps it for later if the map is not up yet). */
  readonly show: (target: Target) => void;
  /**
   * The view that shows a place clear of what the page puts over the map for
   * what it opens (a school's panel); the view as it is by default.
   */
  readonly frame?: (view: MapView, selection: Selection | null) => MapView;
  /** The results list's element id; options are numbered under it. */
  readonly listId: string;
  /** The newest text's results as options, or null to show nothing. */
  readonly onResults: (options: readonly SearchOption[] | null) => void;
  /** The generated_at of the live file the map shows, for the update time; null when none is. */
  readonly onUpdated?: (generatedAt: UtcInstant | null) => void;
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
   */
  pick(hit: SearchHit): void;
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
}

export function boot(options: BootOptions): Services {
  const { links, signal } = options;
  const data = options.data ?? createAppData();
  const pins = createPinStore();
  const warmUrls: string[] = [];
  const search: SearchController = createSearchController({
    indexUrl: data.files.url(DATA_PATHS.searchIndex),
    onResults: (results) => {
      options.onResults(results === null ? null : searchOptions(results, options.listId));
    },
    onIndexLoaded: (url) => {
      warmUrls.push(url);
    },
  });

  // A link opens as sent; a plain visit opens the pinned school, without a history entry.
  const opening = startupSelection(links.state, pins.school);
  if (opening !== null && links.state.selection === null) links.select(opening, { replace: true });
  const selection = links.state.selection;
  if (selection !== null && links.state.view === null) {
    void goToSelection(data, selection, search, options);
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
  let stopLive: () => void = () => undefined;
  void glow.then(async (layer) => {
    if (layer === null || aborted()) return;
    stopLive = await startLiveGlow(data, glow, (generatedAt) => {
      if (!aborted()) options.onUpdated?.(generatedAt);
    });
    if (aborted()) stopLive();
  });

  // Once the map is on screen: installing the worker would otherwise run alongside its start.
  void startServiceWorker(warmUrls, options.map);

  signal.addEventListener('abort', () => {
    stopLive();
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
    schoolCode ??= import('./school').then((module) => ({
      watch: module.watchSchool,
      source: module.createDetailsSource(data.files),
    }));
    return schoolCode;
  };

  return {
    searchable: data.files.has(DATA_PATHS.searchIndex),
    pins,
    watchSchool(id, hint, onView) {
      let stop: (() => void) | null = null;
      let stopped = false;
      loadSchoolCode().then(
        ({ watch, source }) => {
          if (stopped || aborted()) return;
          stop = watch({ files: data.files, details: source, id, hint, onView });
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
      const frame = options.frame ?? ((view: MapView) => view);
      let view = frame(viewForHit(hit), selection);
      try {
        links.navigate({ selection, view });
      } catch {
        // An id a link cannot carry: the step keeps the place alone.
        view = viewForHit(hit);
        links.navigate({ selection: null, view });
      }
      options.show({ view });
    },
  };
}

/** A selection the app opened by itself (a link or the pin): go to it once it is placed. */
async function goToSelection(
  data: AppData,
  selection: Selection,
  search: SearchController,
  options: BootOptions,
): Promise<void> {
  const [target, map] = await Promise.all([locate(data, selection, search), options.map]);
  // Someone moved the map meanwhile, or opened something else: leave it.
  if (target === null || map === undefined || map.moved || options.signal.aborted) return;
  if (options.links.state.selection !== selection) return;
  const frame = options.frame;
  options.show(
    'view' in target && frame !== undefined ? { view: frame(target.view, selection) } : target,
  );
}
