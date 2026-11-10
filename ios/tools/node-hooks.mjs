// node-hooks.mjs: lets plain Node import the site's TypeScript modules, so the iPhone
// app's golden answers are made by running the site's own code.
//
// Registered by node-register.mjs. Node runs these hooks on a thread of their own. They
// do four things:
//
//   1. resolve a relative import inside web/src that has no extension to its .ts file,
//      or to index.ts in a folder of that name;
//   2. refuse every `virtual:` import, and every import of a package, with a clear error.
//      The site's modules that the app's tools call import neither; if one starts to, the
//      generator must say so rather than load something else in its place;
//   3. give `import.meta.env` the one value the deployed site is built with that these
//      modules read: a live root;
//   4. report every site file they resolved or loaded to the generator, over the port
//      that node-register.mjs passed in.
//
// Node's built-in modules only.

import { existsSync, statSync } from 'node:fs';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** Prepended to the first line of every web/src module, so line numbers stay true. */
const ENV_SHIM = "import.meta.env ??= { VITE_SNOWLIGHT_LIVE_ROOT: 'https://live.invalid/v1/' };";

let port = null;
/** Absolute path of web/, ending in a separator. */
let webRoot = null;
/** Absolute path of web/src/, ending in a separator. */
let siteRoot = null;

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

  if (specifier.startsWith('virtual:')) {
    throw new Error(
      `refused: ${parent} imports '${specifier}'. A virtual: module exists only inside the site's build, and the app's tools load none.`,
    );
  }
  if (specifier.startsWith('./') || specifier.startsWith('../')) {
    const base = resolvePath(dirname(parent), specifier);
    for (const candidate of [base, `${base}.ts`, join(base, 'index.ts')]) {
      if (isFile(candidate)) {
        report({ kind: 'import', from: parent, to: candidate });
        return { url: pathToFileURL(candidate).href, shortCircuit: true };
      }
    }
    throw new Error(`refused: ${parent} imports '${specifier}', and no such file was found.`);
  }
  if (specifier.startsWith('node:')) return nextResolve(specifier, context);
  throw new Error(
    `refused: ${parent} imports the package '${specifier}'. The app's tools load the site's own files and Node's built-in modules, and no package.`,
  );
}

export async function load(url, context, nextLoad) {
  const path = fileOf(url);
  if (path === null || webRoot === null || !path.startsWith(webRoot)) return nextLoad(url, context);

  report({ kind: 'load', path });
  if (siteRoot !== null && path.startsWith(siteRoot) && path.endsWith('.ts')) {
    const loaded = await nextLoad(url, context);
    const source = typeof loaded.source === 'string' ? loaded.source : Buffer.from(loaded.source).toString('utf8');
    return { ...loaded, source: ENV_SHIM + source };
  }
  return nextLoad(url, context);
}
