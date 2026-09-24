import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defaultClientConditions } from 'vite';
import { defineConfig } from 'vitest/config';

import { copy } from './src/copy.ts';
import { htmlCopy } from './tools/html-copy.ts';

const isVitest = process.env.VITEST !== undefined;

export default defineConfig({
  // One static page and no client-side routes: unknown paths 404, as on GitHub Pages.
  appType: 'mpa',
  plugins: [svelte(), htmlCopy(copy)],
  // Component tests mount into jsdom, so they need Svelte's browser build.
  resolve: isVitest ? { conditions: ['browser', ...defaultClientConditions] } : {},
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
  },
});
