/**
 * The app's data, wired up: which files this build ships, the school
 * directory (loaded the first time something needs it), the live glow, and
 * where a school, district or ZIP code is.
 *
 * The data code loads only when this build ships the files it reads, so a
 * build without data downloads none of it and requests nothing under data/.
 */

import { DATA_FILES } from 'virtual:snowlight/data-files';

import type { StatusCounts } from '../data/closings';
import type { DirectorySource } from '../data/directory';
import { DATA_PATHS, createDataFiles, dataRootFor } from '../data/files';
import type { DataFiles } from '../data/files';
import type { MapView } from '../map/basemap/bounds';
import type { Glow } from '../map/glow-mount';
import type { Selection } from '../state/url';
import { PUBLISHED_PATHS } from '../types/generated';
import type { UtcInstant } from '../types/generated';
import type { SearchController } from './search';
import { ZOOM, viewForHit, zipHit } from './startup';

/** Where the map goes for a selection: a view, or a box to fit. */
export type Target =
  | { readonly view: MapView }
  | { readonly bounds: readonly [number, number, number, number]; readonly maxZoom: number };

export interface AppData {
  readonly files: DataFiles;
  /** The school directory's source, or null when this build ships no directory. */
  directories(): Promise<DirectorySource | null>;
}

/** The data files this build ships, at this page's data root. */
export function createAppData(
  paths: readonly string[] = DATA_FILES,
  base: string = import.meta.env.BASE_URL,
): AppData {
  const files = createDataFiles(paths, dataRootFor(base, location.href));
  const shipsDirectory = files.has(PUBLISHED_PATHS.schoolDirectory) && files.has(DATA_PATHS.points);
  let source: Promise<DirectorySource | null> | null = null;
  return {
    files,
    directories() {
      if (!shipsDirectory) return Promise.resolve(null);
      source ??= Promise.all([import('../data/directory'), import('../pwa/data')]).then(
        ([{ directorySource }, { evictStaticData }]) =>
          directorySource(files, { evict: (urls) => evictStaticData(urls) }),
        () => null,
      );
      return source;
    },
  };
}

/**
 * Where a selection is, from the directory (schools, districts) or the search
 * index (ZIP codes). Null when this build ships neither, or has no such place.
 */
export async function locate(
  data: AppData,
  selection: Selection,
  search: SearchController,
): Promise<Target | null> {
  if (selection.kind === 'zip') {
    const results = await search.lookup(selection.id);
    const hit = results === null ? null : zipHit(results.zips, selection.id);
    return hit === null ? null : { view: viewForHit(hit) };
  }
  const source = await data.directories();
  const directory = await source?.get();
  if (directory === undefined || directory === null) return null;
  const { districtBounds, schoolLocation } = await import('../data/directory');
  if (selection.kind === 'school') {
    const place = schoolLocation(directory, selection.id);
    return place === null ? null : { view: { ...place, zoom: ZOOM.school } };
  }
  const bounds = districtBounds(directory, selection.id);
  return bounds === null ? null : { bounds, maxZoom: ZOOM.districtMax };
}

/** What the live glow tells the page about the file it shows. */
export interface LiveGlowListeners {
  /** The generated_at of the file shown (null when none is), for the update time. */
  readonly onShown?: (generatedAt: UtcInstant | null) => void;
  /** How many schools are lit in each status (null while none is), for the legend. */
  readonly onCounts?: (counts: StatusCounts | null) => void;
}

/**
 * Lights today's affected schools on the glow, and keeps them current: a
 * build without live/closings.json never asks for it, and nothing glows.
 * Returns the function that stops it.
 */
export async function startLiveGlow(
  data: AppData,
  glow: Promise<Glow | null>,
  { onShown, onCounts }: LiveGlowListeners = {},
): Promise<() => void> {
  if (!data.files.has(PUBLISHED_PATHS.closings)) return () => undefined;
  const [{ closingsUrl, startLive }, { onDataUpdate }] = await Promise.all([
    import('../data/live'),
    import('../pwa/data'),
  ]);
  const live = startLive({
    files: data.files,
    directory: async (stamp) => (await (await data.directories())?.get(stamp)) ?? null,
    onLight: (lit) => {
      void glow.then((layer) => {
        layer?.light(lit);
      });
    },
    onShown: (generatedAt) => {
      onShown?.(generatedAt);
    },
    onCounts: (counts) => {
      onCounts?.(counts);
    },
  });
  const url = closingsUrl(data.files);
  // The worker fetched a newer copy in the background: read it (from its cache) and relight.
  const stopUpdates = onDataUpdate((updated) => {
    if (updated === url) void live.refresh();
  });
  return () => {
    live.stop();
    stopUpdates();
  };
}
