/**
 * The data files this build ships, listed for the page at build time.
 *
 * The pipeline's outputs are staged into public/data/ before a build; Vite
 * serves that folder in dev and preview and copies it into the build as
 * data/. This plugin lists what is there as the module
 * `virtual:snowlight/data-files`, so the page only ever asks for files that
 * exist: a request for a missing one is a 404, which the browser reports as a
 * console error. With nothing staged the list is empty, and the page reads
 * no data at all: no closings, no directory, no search index.
 *
 * Files the pipeline keeps next to its outputs for itself (*.internal.json)
 * and dotfiles are never published: they are left off the list, removed from
 * the build's data/ after Vite copies the folder in, and not served in dev.
 */
import { readdirSync, rmSync } from 'node:fs';
import path from 'node:path';

import type { Plugin } from 'vite';

export const DATA_FILES_MODULE = 'virtual:snowlight/data-files';
const RESOLVED_ID = `\0${DATA_FILES_MODULE}`;

/** The pipeline's own records: never published. */
const INTERNAL_SUFFIX = '.internal.json';

/** Whether a file or folder name under data/ is one the site publishes. */
export function isPublished(name: string): boolean {
  return !name.startsWith('.') && !name.endsWith(INTERNAL_SUFFIX);
}

/**
 * Every file under `dir`, as sorted POSIX paths relative to it; [] when it
 * does not exist. `published` picks the files the site publishes (the
 * default) or the ones it never does, with the unpublished folders' contents.
 */
export function listDataFiles(dir: string, published = true): string[] {
  const found: string[] = [];
  const walk = (folder: string, prefix: string, inside: boolean): void => {
    let entries;
    try {
      entries = readdirSync(folder, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const relative = `${prefix}${entry.name}`;
      const kept = inside && isPublished(entry.name);
      if (entry.isDirectory()) walk(path.join(folder, entry.name), `${relative}/`, kept);
      else if (entry.isFile() && kept === published) found.push(relative);
    }
  };
  walk(dir, '', true);
  return found.sort();
}

/** Removes from a copy of data/ what the site never publishes; returns the files removed. */
export function removeUnpublished(dir: string): string[] {
  const removed = listDataFiles(dir, false);
  const walk = (folder: string): void => {
    let entries;
    try {
      entries = readdirSync(folder, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const at = path.join(folder, entry.name);
      if (!isPublished(entry.name)) rmSync(at, { recursive: true, force: true });
      else if (entry.isDirectory()) walk(at);
    }
  };
  walk(dir);
  return removed;
}

/** The module's source for a list of files. */
export function dataFilesModule(files: readonly string[]): string {
  return `export const DATA_FILES = Object.freeze(${JSON.stringify(files)});\n`;
}

/** A request's path, decoded; the raw path when it does not decode. */
function sitePath(url: string): string {
  const raw = url.split(/[?#]/, 1)[0] ?? '';
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/** The plugin, for data published under `dataDir` ("data/") of the site. */
export function dataFiles(dataDir: string): Plugin {
  let dir = '';
  /** data/ in the build output, when the build copies the public folder there. */
  let builtDir = '';
  /** The site path of data/, for the dev server. */
  let dataPath = '';
  return {
    name: 'snowlight:data-files',
    configResolved(config) {
      dir = config.publicDir === '' ? '' : path.join(config.publicDir, dataDir);
      builtDir =
        dir !== '' && config.build.copyPublicDir
          ? path.join(path.resolve(config.root, config.build.outDir), dataDir)
          : '';
      dataPath = `${config.base.endsWith('/') ? config.base : `${config.base}/`}${dataDir}`;
    },
    // Vite copies the whole public folder into the build before it writes: take back what is not published.
    writeBundle() {
      if (builtDir !== '') removeUnpublished(builtDir);
    },
    resolveId(id) {
      return id === DATA_FILES_MODULE ? RESOLVED_ID : null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      return dataFilesModule(dir === '' ? [] : listDataFiles(dir));
    },
    configureServer(server) {
      if (dir === '') return;
      // What the build leaves out, the dev server does not serve either.
      server.middlewares.use((request, response, next) => {
        const pathname = sitePath(request.url ?? '');
        if (!pathname.startsWith(dataPath)) {
          next();
          return;
        }
        const names = pathname.slice(dataPath.length).split('/');
        if (names.every((name) => name === '' || isPublished(name))) {
          next();
          return;
        }
        response.statusCode = 404;
        response.end();
      });
      // Staging data while the dev server runs changes the list: reload the page with the new one.
      const onChange = (file: string): void => {
        if (!path.resolve(file).startsWith(path.resolve(dir) + path.sep)) return;
        const module = server.moduleGraph.getModuleById(RESOLVED_ID);
        if (module !== undefined) server.moduleGraph.invalidateModule(module);
        server.ws.send({ type: 'full-reload' });
      };
      server.watcher.on('add', onChange);
      server.watcher.on('unlink', onChange);
    },
  };
}
