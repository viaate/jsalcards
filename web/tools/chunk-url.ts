/**
 * The URL of the chunk a module is built into, as a module of its own:
 *
 * - `virtual:snowlight/maplibre-url`, MapLibre's page module
 *   (src/map/basemap/load.ts), which the map asks for ahead of running it,
 *   with a module preload, so its download starts with the map's others; it
 *   runs only once MapLibre's shared module has run, in a task of its own.
 * - `virtual:snowlight/url-store-url`, the address store
 *   (src/state/late-url-store.ts), asked for again under a new address after
 *   a failed download, as a browser keeps a module that failed for good.
 * - `virtual:snowlight/copy-format-url`, the formatters (src/copy-format.ts),
 *   which the page fetches, again after a failed download, before it imports
 *   them and the menu, the panel and the update time that run them
 *   (src/app/late-formats.ts).
 *
 * The build names a chunk after its content: the module holds a marker that
 * each chunk carrying it has replaced, as the chunks are written, by the
 * chunk's file name as the bundler has it then (a placeholder it fills in
 * with the final name, and counts in the name of the chunk that refers to
 * it). The dev server serves the module under its source path.
 */
import path from 'node:path';

import type { Plugin } from 'vite';

export const MAPLIBRE_URL_MODULE = 'virtual:snowlight/maplibre-url';
export const URL_STORE_URL_MODULE = 'virtual:snowlight/url-store-url';
export const COPY_FORMAT_URL_MODULE = 'virtual:snowlight/copy-format-url';

/** The URL of the chunk built from `source` (from the web root), as the module `id`. */
export function chunkUrl(id: string, source: string): Plugin {
  const resolvedId = `\0${id}`;
  const name = path.posix.basename(source).replace(/\.\w+$/u, '');
  /** Stands for the chunk's path relative to the chunk that asks for it, until the chunks are written. */
  const marker = `__SNOWLIGHT_${name.toUpperCase().replace(/\W/gu, '_')}_CHUNK__`;
  let root = '';
  let building = false;
  return {
    name: `snowlight:${name}-url`,
    configResolved(config) {
      root = config.root;
      building = config.command === 'build';
    },
    resolveId(request) {
      return request === id ? resolvedId : null;
    },
    load(request) {
      if (request !== resolvedId) return null;
      if (!building) {
        return `export default new URL(${JSON.stringify(source)}, new URL(import.meta.env.BASE_URL, location.href)).href;\n`;
      }
      // Through a name, not a literal: Vite takes a literal there for a file it copies over.
      return `const chunk = ${JSON.stringify(marker)};\nexport default new URL(chunk, import.meta.url).href;\n`;
    },
    renderChunk(code, chunk, _options, meta) {
      if (!code.includes(marker)) return null;
      const module = path.join(root, source);
      const chunks = Object.values(meta.chunks);
      // The chunk built from it, or else the one it is shared in (the formatters').
      const target =
        chunks.find((candidate) => candidate.facadeModuleId === module) ??
        chunks.find((candidate) => candidate.moduleIds.includes(module));
      if (target === undefined) {
        throw new Error(`snowlight:${name}-url: no chunk is built from ${source}`);
      }
      let relative = path.posix.relative(path.posix.dirname(chunk.fileName), target.fileName);
      if (!relative.startsWith('.')) relative = `./${relative}`;
      return { code: code.split(marker).join(relative), map: null };
    },
  };
}

/** MapLibre's page module, as the site imports it (src/map/basemap/maplibre.ts). */
export function maplibreUrl(): Plugin {
  return chunkUrl(MAPLIBRE_URL_MODULE, 'src/map/basemap/maplibre.ts');
}

/** The address store, as the site imports it (src/state/url-store.ts). */
export function urlStoreUrl(): Plugin {
  return chunkUrl(URL_STORE_URL_MODULE, 'src/state/url-store.ts');
}

/** The formatters, as the site imports them (src/copy-format.ts). */
export function copyFormatUrl(): Plugin {
  return chunkUrl(COPY_FORMAT_URL_MODULE, 'src/copy-format.ts');
}
