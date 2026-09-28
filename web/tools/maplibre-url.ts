/**
 * The URL of the chunk MapLibre's page module is built into, as the module
 * `virtual:snowlight/maplibre-url` (src/map/basemap/load.ts).
 *
 * The map asks for MapLibre's page module ahead of running it, with a
 * module preload, so its download starts with the map's others; it runs only
 * once MapLibre's shared module has run, in a task of its own. The build
 * names the chunk after its content: the module holds a marker that each
 * chunk carrying it has replaced, as the chunks are written, by the chunk's
 * file name as the bundler has it then (a placeholder it fills in with the
 * final name, and counts in the name of the chunk that refers to it). The
 * dev server serves the module under its source path.
 */
import path from 'node:path';

import type { Plugin } from 'vite';

export const MAPLIBRE_URL_MODULE = 'virtual:snowlight/maplibre-url';
const RESOLVED_ID = `\0${MAPLIBRE_URL_MODULE}`;
/** MapLibre's page module, as the site imports it (src/map/basemap/maplibre.ts). */
const PAGE_MODULE = 'src/map/basemap/maplibre.ts';
/** Stands for the chunk's path relative to the chunk that asks for it, until the chunks are written. */
const MARKER = '__SNOWLIGHT_MAPLIBRE_CHUNK__';

export function maplibreUrl(): Plugin {
  let root = '';
  let building = false;
  return {
    name: 'snowlight:maplibre-url',
    configResolved(config) {
      root = config.root;
      building = config.command === 'build';
    },
    resolveId(id) {
      return id === MAPLIBRE_URL_MODULE ? RESOLVED_ID : null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      if (!building) {
        return `export default new URL(${JSON.stringify(PAGE_MODULE)}, new URL(import.meta.env.BASE_URL, location.href)).href;\n`;
      }
      // Through a name, not a literal: Vite takes a literal there for a file it copies over.
      return `const chunk = ${JSON.stringify(MARKER)};\nexport default new URL(chunk, import.meta.url).href;\n`;
    },
    renderChunk(code, chunk, _options, meta) {
      if (!code.includes(MARKER)) return null;
      const page = path.join(root, PAGE_MODULE);
      const target = Object.values(meta.chunks).find(
        (candidate) => candidate.facadeModuleId === page,
      );
      if (target === undefined) {
        throw new Error(`snowlight:maplibre-url: no chunk is built from ${PAGE_MODULE}`);
      }
      let relative = path.posix.relative(path.posix.dirname(chunk.fileName), target.fileName);
      if (!relative.startsWith('.')) relative = `./${relative}`;
      return { code: code.split(MARKER).join(relative), map: null };
    },
  };
}
