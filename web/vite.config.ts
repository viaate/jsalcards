import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defaultClientConditions } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

import { copy } from './src/copy.ts';
import { pwaHead, pwaOptions } from './src/pwa/config.ts';
import { htmlCopy } from './tools/html-copy.ts';

const isVitest = process.env.VITEST !== undefined;

export default defineConfig({
  // One static page and no client-side routes: unknown paths 404, as on GitHub Pages.
  appType: 'mpa',
  plugins: [
    svelte(),
    htmlCopy(copy),
    // Service worker and manifest links; the page registers the worker after load (src/pwa).
    isVitest ? [] : [VitePWA(pwaOptions()), pwaHead()],
  ],
  // Component tests mount into jsdom, so they need Svelte's browser build.
  resolve: isVitest ? { conditions: ['browser', ...defaultClientConditions] } : {},
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    include: [
      'tests/**/*.test.ts',
      // Link state and the map's limits: plain modules, tested where they live.
      'src/state/tests/**/*.test.ts',
      'src/map/basemap/tests/**/*.test.ts',
    ],
  },
});
