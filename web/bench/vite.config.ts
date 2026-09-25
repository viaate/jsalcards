import { resolve } from 'node:path';

import { defineConfig } from 'vite';

/**
 * Builds the glow bench page on its own, into bench/out/site, never into the
 * app's dist/. The headers make the page cross-origin isolated so
 * performance.now() has microsecond resolution for the per-frame CPU timings.
 */
const here = import.meta.dirname;

const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
};

export default defineConfig({
  root: here,
  base: './',
  publicDir: false,
  build: {
    outDir: resolve(here, 'out/site'),
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: true,
    rollupOptions: { input: resolve(here, 'glow.html') },
  },
  worker: { format: 'es' },
  server: { headers: isolation, fs: { allow: [resolve(here, '..')] } },
  preview: { headers: isolation },
});
