import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { defineConfig } from 'vite';

/**
 * Builds the search bench page on its own, outside the app's dist/. The
 * headers make the page cross-origin isolated so performance.now() has
 * microsecond resolution in the page and the worker.
 */
const here = import.meta.dirname;

export const benchOutDir = process.env.SEARCH_BENCH_OUT ?? join(tmpdir(), 'snowlight-search-bench');

const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
};

export default defineConfig({
  root: here,
  base: './',
  publicDir: false,
  build: {
    outDir: join(benchOutDir, 'site'),
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: true,
    rollupOptions: { input: resolve(here, 'bench.html') },
  },
  worker: { format: 'es' },
  server: { headers: isolation, fs: { allow: [resolve(here, '../..')] } },
  preview: { headers: isolation },
});
