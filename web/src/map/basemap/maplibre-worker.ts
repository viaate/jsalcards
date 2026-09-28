/**
 * MapLibre's worker, started from its published source with one import
 * pointed at the shared chunk the page already downloaded, and the street
 * tile protocol (street-tiles.ts) registered in it.
 *
 * MapLibre's worker module is 19 KB of code that imports the 516 KB shared
 * module by the relative name './maplibre-gl-shared.mjs'. Built as a separate
 * worker bundle (Vite's `?worker`), it would carry a second copy of the shared
 * module. Instead the worker runs its published source from a blob URL, with
 * that one specifier replaced by the URL of the chunk that holds the shared
 * module (maplibre-shared.ts). The page imports that chunk too, so it is
 * downloaded once and every worker takes it from the HTTP cache. One other
 * change: GeoJSON the worker reads from a URL stays in the worker, instead of
 * going back to the page (DATA_RETURNED).
 *
 * Lines are added at the end: imports of the street tiles and school tiles
 * chunks, and calls that register their protocols on the worker's scope once
 * MapLibre's worker has set that scope up. Street tiles then load, and are
 * cut to the US, in the worker that parses them; school tiles load from the
 * directory's archive, their names as the page shows them.
 *
 * A worker started from a same-origin blob is still same-origin, and a module
 * worker's absolute imports resolve as usual.
 */
import source from 'maplibre-gl/dist/maplibre-gl-worker.mjs?raw';

/** The one static import in MapLibre's worker module, of its shared module. */
const SHARED_IMPORT = /(\bfrom\s*)(["'])\.\/maplibre-gl-shared\.mjs\2/g;
/** Its source map comment points next to the published file, which a blob URL has no notion of. */
const SOURCE_MAP_COMMENT = /\n\/\/# sourceMappingURL=\S*\s*$/;
/**
 * Where its GeoJSON worker source, having read a source's data from a URL,
 * puts that data in its answer to the page (maplibre-gl 6.11
 * GeoJSONWorkerSource.loadData: `params.request && (result.data =
 * params.data)`), for the source's getData(). The page would then copy all
 * of it in, a property at a time, on its main thread. The only GeoJSON the
 * map reads from a URL is the bundled lines (load.ts), and the page never
 * asks a source for its data: the worker keeps it.
 */
const DATA_RETURNED = /\b(\w+)\.request&&\((\w+)\.data=\1\.data\)/g;

const urls = new Map<string, string>();

/** Where the worker's added code comes from. */
export interface WorkerUrls {
  /** The chunk holding MapLibre's shared module (maplibre-shared.ts). */
  readonly shared: string;
  /** The chunk of street-tiles.ts. */
  readonly streetTiles: string;
  /** The chunk of school-tiles.ts. */
  readonly schoolTiles: string;
  /** The US mask archive. */
  readonly mask: string;
}

/**
 * The worker module's source: importing its shared module from its chunk,
 * and registering the street and school tile protocols at the end.
 */
export function workerSource({ shared, streetTiles, schoolTiles, mask }: WorkerUrls): string {
  let imports = 0;
  const code = source.replace(SHARED_IMPORT, (_match, from: string) => {
    imports += 1;
    return `${from}${JSON.stringify(shared)}`;
  });
  if (imports !== 1) {
    throw new Error(
      `MapLibre worker: expected one import of the shared module, found ${String(imports)}`,
    );
  }
  let returns = 0;
  const kept = code.replace(DATA_RETURNED, () => {
    returns += 1;
    return '!1';
  });
  if (returns !== 1) {
    throw new Error(
      `MapLibre worker: expected one place GeoJSON data goes back to the page, found ${String(returns)}`,
    );
  }
  return `${kept.replace(SOURCE_MAP_COMMENT, '\n')}
import { registerStreetTiles as snowlightRegisterStreetTiles } from ${JSON.stringify(streetTiles)};
import { registerSchoolTiles as snowlightRegisterSchoolTiles } from ${JSON.stringify(schoolTiles)};
snowlightRegisterStreetTiles(self, ${JSON.stringify(mask)});
snowlightRegisterSchoolTiles(self);
`;
}

/**
 * A blob URL for the worker module. It lives as long as the page: MapLibre
 * starts workers again from it whenever a map is created after all were removed.
 */
export function workerUrl(sources: WorkerUrls): string {
  const key = JSON.stringify(sources);
  let url = urls.get(key);
  if (url === undefined) {
    const blob = new Blob([workerSource(sources)], { type: 'text/javascript' });
    url = URL.createObjectURL(blob);
    urls.set(key, url);
  }
  return url;
}
