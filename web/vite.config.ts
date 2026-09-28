import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defaultClientConditions } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

import { copy } from './src/copy.ts';
import { DATA_DIR, pwaHead, pwaOptions } from './src/pwa/config.ts';
import { compileHints } from './tools/compile-hints.ts';
import { dataFiles } from './tools/data-files.ts';
import { htmlCopy } from './tools/html-copy.ts';
import { maplibreUrl } from './tools/maplibre-url.ts';
import { schoolNames } from './tools/school-names.ts';

const isVitest = process.env.VITEST !== undefined;
/**
 * The chunks the browser compiles whole as it downloads them (tools/compile-hints.ts): the shell,
 * and the map's code and MapLibre's, which run all at once as the map starts.
 */
const EAGER_CHUNKS: ReadonlySet<string> = new Set([
  'index',
  'basemap',
  'maplibre',
  'maplibre-shared',
]);
/**
 * The build ships the data staged in public/data/ (npm run stage), if any.
 * SNOWLIGHT_DATA=none builds without it, whatever is staged.
 */
const shipData = process.env.SNOWLIGHT_DATA !== 'none';

export default defineConfig({
  // One static page and no client-side routes: unknown paths 404, as on GitHub Pages.
  appType: 'mpa',
  plugins: [
    svelte(),
    htmlCopy(copy),
    // Lists the data files staged in public/data/, so the page asks only for files that exist.
    dataFiles(DATA_DIR, { ship: shipData }),
    // Names the staged directory says to show another way: cut off by NCES, or only generic words.
    schoolNames(DATA_DIR, { ship: shipData }),
    // Where MapLibre's page module is built to, for the map to ask for it ahead of running it.
    maplibreUrl(),
    // The code the page runs as it starts, compiled as it downloads, off the main thread.
    compileHints(EAGER_CHUNKS),
    // Service worker and manifest links; the page registers the worker after load (src/pwa).
    isVitest ? [] : [VitePWA(pwaOptions()), pwaHead()],
  ],
  // Component tests mount into jsdom, so they need Svelte's browser build.
  resolve: isVitest ? { conditions: ['browser', ...defaultClientConditions] } : {},
  build: {
    target: 'es2022',
    sourcemap: true,
    // Every browser the app supports preloads modules itself; the polyfill would watch every
    // change to the page for as long as it is open.
    modulePreload: { polyfill: false },
  },
  test: {
    environment: 'jsdom',
    include: [
      'tests/**/*.test.ts',
      // Every module's own tests, where they live: state, data, app wiring, map, search, offline.
      'src/**/tests/**/*.test.ts',
    ],
  },
});
