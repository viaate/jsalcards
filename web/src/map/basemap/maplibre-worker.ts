/**
 * MapLibre's worker, started from its published source with one import
 * pointed at the shared chunk the page already downloaded.
 *
 * MapLibre's worker module is 19 KB of code that imports the 516 KB shared
 * module by the relative name './maplibre-gl-shared.mjs'. Built as a separate
 * worker bundle (Vite's `?worker`), it would carry a second copy of the shared
 * module. Instead the worker runs the untouched source from a blob URL, with
 * that one specifier replaced by the URL of the chunk that holds the shared
 * module (maplibre-shared.ts). The page imports that chunk too, so it is
 * downloaded once and every worker takes it from the HTTP cache.
 *
 * A worker started from a same-origin blob is still same-origin, and a module
 * worker's absolute imports resolve as usual.
 */
import source from 'maplibre-gl/dist/maplibre-gl-worker.mjs?raw';

/** The one static import in MapLibre's worker module, of its shared module. */
const SHARED_IMPORT = /(\bfrom\s*)(["'])\.\/maplibre-gl-shared\.mjs\2/g;
/** Its source map comment points next to the published file, which a blob URL has no notion of. */
const SOURCE_MAP_COMMENT = /\n\/\/# sourceMappingURL=\S*\s*$/;

const urls = new Map<string, string>();

/** The worker module's source, importing its shared module from `sharedUrl`. */
export function workerSource(sharedUrl: string): string {
  let imports = 0;
  const code = source.replace(SHARED_IMPORT, (_match, from: string) => {
    imports += 1;
    return `${from}${JSON.stringify(sharedUrl)}`;
  });
  if (imports !== 1) {
    throw new Error(
      `MapLibre worker: expected one import of the shared module, found ${String(imports)}`,
    );
  }
  return code.replace(SOURCE_MAP_COMMENT, '\n');
}

/**
 * A blob URL for the worker module. It lives as long as the page: MapLibre
 * starts workers again from it whenever a map is created after all were removed.
 */
export function workerUrl(sharedUrl: string): string {
  let url = urls.get(sharedUrl);
  if (url === undefined) {
    const blob = new Blob([workerSource(sharedUrl)], { type: 'text/javascript' });
    url = URL.createObjectURL(blob);
    urls.set(sharedUrl, url);
  }
  return url;
}
