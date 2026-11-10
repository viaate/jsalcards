/**
 * Builds the status page: `index.html` with the "Checking" render in `<main>`, the script
 * (`src/app.ts`, bundled and minified), the stylesheet and the files of `public/`.
 * `node page/build.mjs` writes `page/dist/`; a test calls `build()` with a folder of its own.
 */

import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build as bundle } from 'esbuild';
import { mainHtml, pageHtml } from './src/html.ts';
import { viewOf } from './src/view.ts';

const here = dirname(fileURLToPath(import.meta.url));

/** Writes the built page into `outDir`, replacing what is there. */
export async function build(outDir) {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  cpSync(join(here, 'public'), outDir, { recursive: true });
  writeFileSync(join(outDir, 'style.css'), readFileSync(join(here, 'src/style.css')));
  writeFileSync(join(outDir, 'index.html'), pageHtml(mainHtml(viewOf({ kind: 'wait' }))));
  await bundle({
    entryPoints: [join(here, 'src/app.ts')],
    outfile: join(outDir, 'app.js'),
    bundle: true,
    minify: true,
    format: 'iife',
    target: 'es2022',
    legalComments: 'none',
    logLevel: 'warning',
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await build(join(here, 'dist'));
}
