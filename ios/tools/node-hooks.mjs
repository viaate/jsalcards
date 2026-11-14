// node-hooks.mjs: lets plain Node import the site's TypeScript modules, so the iPhone
// app's golden answers are made by running the site's own code.
//
// Registered by node-register.mjs. Node runs these hooks on a thread of their own. They
// do five things:
//
//   1. resolve a relative import inside web/src that has no extension to its .ts file,
//      or to index.ts in a folder of that name, and then to the real file it is: through
//      every symbolic link on the way, file or folder, so a link inside web/src that
//      points elsewhere is judged where it points;
//   2. answer exactly two `virtual:` imports, the build-time name tables that
//      web/src/app/school.ts imports, with their empty forms (EMPTY_TABLES below): the
//      deployed tables are keyed by real ids, and no made-up id of the app's fixtures is
//      in them, so the empty forms give the deployed site's answers for those ids;
//   3. refuse every other `virtual:` import, every import of a package, and every import
//      of one of Node's built-in modules from a file under web/src (the site's modules are
//      code for the browser; through `node:module` one could load a file these hooks never
//      see), with a clear error. The site's modules that the app's tools call import none
//      of these; if one starts to, the generator must say so rather than load something
//      else in its place;
//   4. give `import.meta.env` the one value the deployed site is built with that these
//      modules read: a live root;
//   5. report every site file they resolved or loaded to the generator, over the port
//      that node-register.mjs passed in. A file a site module imports is reported as
//      loaded wherever it lies, inside web/ or not, so the generator can refuse a file
//      from outside what the words watch covers.
//
// Node's built-in modules only.

import { existsSync, realpathSync, statSync } from 'node:fs';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/**
 * The two build-time name tables web/src/app/school.ts imports, each in its empty form: no
 * district alike, no name fixed. Written as the site's build writes them for empty lists
 * (web/tools/school-names.ts `districtNamesModule([])` and `schoolNamesModule`), a frozen
 * empty list and two frozen empty tables.
 */
const EMPTY_TABLES = new Map([
  ['virtual:snowlight/district-names', 'export const ALIKE_DISTRICTS = Object.freeze([]);\n'],
  [
    'virtual:snowlight/school-names',
    'export const SCHOOL_NAME_FIXES = Object.freeze({});\nexport const DISTRICT_NAME_FIXES = Object.freeze({});\n',
  ],
]);
/** Where an empty table is served from: not a file, so no file is reported for it. */
const EMPTY_TABLE_SCHEME = 'snowlight-empty-table:';

/** Prepended to the first line of every web/src module, so line numbers stay true. */
const ENV_SHIM = "import.meta.env ??= { VITE_SNOWLIGHT_LIVE_ROOT: 'https://live.invalid/v1/' };";

let port = null;
/** Absolute path of web/, ending in a separator. */
let webRoot = null;
/** Absolute path of web/src/, ending in a separator. */
let siteRoot = null;
/** The URL of every file a site module's import was resolved to, wherever it lies. */
const resolvedFromSite = new Set();

export function initialize(data) {
  port = data.port;
  webRoot = data.webRoot;
  siteRoot = data.siteRoot;
}

function report(message) {
  if (port !== null) port.postMessage(message);
}

/** The file a `file:` URL names, or null for any other URL. */
function fileOf(url) {
  if (typeof url !== 'string' || !url.startsWith('file:')) return null;
  try {
    return fileURLToPath(url);
  } catch {
    return null;
  }
}

function isFile(path) {
  return existsSync(path) && statSync(path).isFile();
}

export async function resolve(specifier, context, nextResolve) {
  const parent = fileOf(context.parentURL);
  const fromSite = parent !== null && webRoot !== null && parent.startsWith(webRoot);
  if (!fromSite) return nextResolve(specifier, context);

  if (EMPTY_TABLES.has(specifier)) {
    return { url: `${EMPTY_TABLE_SCHEME}${specifier}`, shortCircuit: true };
  }
  if (specifier.startsWith('virtual:')) {
    throw new Error(
      `refused: ${parent} imports '${specifier}'. A virtual: module exists only inside the site's build, and the app's tools load none but the two empty name tables.`,
    );
  }
  if (specifier.startsWith('./') || specifier.startsWith('../')) {
    const base = resolvePath(dirname(parent), specifier);
    for (const candidate of [base, `${base}.ts`, join(base, 'index.ts')]) {
      if (isFile(candidate)) {
        // The real file, not the path as written: Node reads through a link to its target.
        const real = realpathSync(candidate);
        report({ kind: 'import', from: parent, to: real });
        const url = pathToFileURL(real).href;
        resolvedFromSite.add(url);
        return { url, shortCircuit: true };
      }
    }
    throw new Error(`refused: ${parent} imports '${specifier}', and no such file was found.`);
  }
  if (specifier.startsWith('node:')) {
    if (siteRoot !== null && parent.startsWith(siteRoot)) {
      throw new Error(
        `refused: ${parent} imports Node's '${specifier}'. The site's modules are code for the browser, and the app's tools let none of them use Node's own modules.`,
      );
    }
    return nextResolve(specifier, context);
  }
  throw new Error(
    `refused: ${parent} imports the package '${specifier}'. The app's tools load the site's own files and Node's built-in modules, and no package.`,
  );
}

export async function load(url, context, nextLoad) {
  if (typeof url === 'string' && url.startsWith(EMPTY_TABLE_SCHEME)) {
    const source = EMPTY_TABLES.get(url.slice(EMPTY_TABLE_SCHEME.length));
    if (source === undefined) throw new Error(`refused: no empty table is named ${url}`);
    return { format: 'module', source, shortCircuit: true };
  }
  const path = fileOf(url);
  if (path === null || webRoot === null) return nextLoad(url, context);
  if (!path.startsWith(webRoot)) {
    // A file outside web/ that a site module imports: reported, so the generator refuses it.
    if (resolvedFromSite.has(url)) report({ kind: 'load', path });
    return nextLoad(url, context);
  }

  report({ kind: 'load', path });
  if (siteRoot !== null && path.startsWith(siteRoot) && path.endsWith('.ts')) {
    const loaded = await nextLoad(url, context);
    const source = typeof loaded.source === 'string' ? loaded.source : Buffer.from(loaded.source).toString('utf8');
    return { ...loaded, source: ENV_SHIM + source };
  }
  return nextLoad(url, context);
}
