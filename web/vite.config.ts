import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defaultClientConditions, loadEnv } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

import { copy } from './src/copy.ts';
import { waitlistCopy } from './src/copy-waitlist.ts';
import { DATA_DIR, pwaHead, pwaOptions } from './src/pwa/config.ts';
import { compileHints } from './tools/compile-hints.ts';
import { dataFiles } from './tools/data-files.ts';
import { htmlCopy, pageCopy } from './tools/html-copy.ts';
import { copyFormatUrl, maplibreUrl, urlStoreUrl } from './tools/chunk-url.ts';
import { accounts } from './tools/accounts.ts';
import { usMask } from './tools/us-mask.ts';
import { schoolNames } from './tools/school-names.ts';
import { waitlist, waitlistPost, waitlistSettings } from './tools/waitlist.ts';

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

export default defineConfig(({ mode }) => {
  /**
   * The waitlist (tools/waitlist.ts): on when VITE_WAITLIST_KIT_FORM names a Kit form, from the
   * environment or a .env file. Unset, the build is the site as it was.
   */
  const waitlistOn = waitlistSettings(loadEnv(mode, import.meta.dirname, 'VITE_WAITLIST_'));
  return {
    // One static page and no client-side routes: unknown paths 404, as on GitHub Pages.
    appType: 'mpa',
    plugins: [
      svelte(),
      // In a build with an accounts API, the strip keeps the account control's room (tools/accounts.ts).
      accounts(loadEnv(mode, import.meta.dirname, 'VITE_API_')),
      // Before htmlCopy: keeps index.html's blocks for the waitlist or for the code screen.
      waitlist(waitlistOn, import.meta.dirname),
      htmlCopy(pageCopy(copy, waitlistCopy)),
      waitlistPost(waitlistOn, import.meta.dirname),
      // Lists the data files staged in public/data/, so the page asks only for files that exist.
      dataFiles(DATA_DIR, { ship: shipData }),
      // Names the staged directory says to show another way: cut off by NCES, or only generic words.
      schoolNames(DATA_DIR, { ship: shipData }),
      // Where MapLibre's page module is built to, for the map to ask for it ahead of running it.
      maplibreUrl(),
      // Where the address store is built to, for a page to ask for it again after a failed download.
      urlStoreUrl(),
      // Where the formatters are built to, for the page to fetch them, again after a failed download.
      copyFormatUrl(),
      // The US mask under a name that never changes too, for a page from an older build, and the
      // tiles wholly inside the US, which need no mask.
      usMask(),
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
  };
});
