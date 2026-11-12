import { loadEnv } from 'vite';
import { defineConfig } from 'vite';

import { copy } from './src/copy.ts';
import { getCopy } from './src/copy-get.ts';
import { getPage, getPageSettings } from './tools/get-page.ts';
import { htmlCopy, pageCopy } from './tools/html-copy.ts';

/**
 * The getsnowlight landing (get/, docs/getsnowlight.md), built on its own to dist-get/ for
 * https://www.getsnowlight.com (.github/workflows/getsnowlight.yml): one page, its pictures and
 * fonts, and no script but the lock's. The map's build (vite.config.ts) never carries it.
 * VITE_APP_STORE_URL, once the app is out, shows Apple's badge in place of the live map's links.
 */
const ROOT = `${import.meta.dirname}/get`;

export default defineConfig(({ mode }) => ({
  root: ROOT,
  // The font's license, beside the font (get/public/).
  publicDir: 'public',
  appType: 'mpa',
  plugins: [
    htmlCopy(pageCopy(copy, undefined, getCopy)),
    getPage(getPageSettings(loadEnv(mode, import.meta.dirname, 'VITE_APP_STORE_')), ROOT),
  ],
  build: {
    outDir: `${import.meta.dirname}/dist-get`,
    emptyOutDir: true,
    target: 'es2022',
    // Small pictures stay files, so the page's own bytes stay small.
    assetsInlineLimit: 0,
  },
}));
