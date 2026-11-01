/**
 * Builds the site into the folder given first, as `vite build` does, with a
 * stand-in theme waiting for approval listed (src/theme/unreleased.ts as the
 * stand-in's) and a shop that lists the themes (src/theme/shop.ts, imported
 * on demand, as the game lane will), for build.test.ts to read. Given
 * `preview` second, the build carries the waiting themes, as one whose
 * VITE_THEMES_PREVIEW names one does.
 *
 * Run by build.test.ts in a process of its own: Vite reads the app's config
 * as a build does, not as the tests do (vite.config.ts isVitest).
 */
import { fileURLToPath } from 'node:url';

import { build } from 'vite';

const [outDir, mode] = process.argv.slice(2);
if (outDir === undefined) throw new Error('Name the folder to build into');
const web = fileURLToPath(new URL('../../../', import.meta.url));

/** The stand-in's id, and the color only its palette has. */
const ID = 'next-frost';
const MARK = '#fa57e1';

/** unreleased.ts with the stand-in listed: the whole palette in its one color. */
const STAND_IN = `
const LISTED = ['${ID}'];
export const UNRELEASED_IDS = LISTED;
export const UNRELEASED_THEMES = {
  '${ID}': {
    id: '${ID}',
    scheme: 'dark',
    access: 'shop',
    tokens: { bg: '${MARK}', surface1: '${MARK}', text1: '${MARK}', accent: '${MARK}' },
    glow: { mode: 'glow', outline: '${MARK}', outlineWidth: 0, burst: false },
    lineWidths: null,
    roadScale: 1,
  },
};
`;

/** The page's code, with the shop's list asked for on demand, as a shop page would. */
const SHOP = `
if (globalThis.snowlightShop === true) {
  void import('./theme/shop.ts').then((shop) => shop.listedThemes());
}
`;

await build({
  configFile: `${web}vite.config.ts`,
  root: web,
  logLevel: 'error',
  // A preview build carries the waiting themes (vite.config.ts names them from the real list).
  ...(mode === 'preview' ? { define: { __UNRELEASED_THEMES__: 'true' } } : {}),
  plugins: [
    {
      name: 'stand-in-theme',
      enforce: 'pre',
      load(id) {
        if (/[\\/]src[\\/]theme[\\/]unreleased\.ts$/.test(id)) return STAND_IN;
        return null;
      },
      transform(code, id) {
        if (/[\\/]src[\\/]main\.ts$/.test(id)) return `${code}\n${SHOP}`;
        return null;
      },
    },
  ],
  build: { outDir, emptyOutDir: true, copyPublicDir: false },
});
