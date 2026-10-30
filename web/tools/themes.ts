import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

import type { Plugin } from 'vite';

import { themeRules } from '../src/theme/css.ts';
import { PAGE_THEMES_ID, type PageTheme, type PageThemes } from '../src/theme/page.ts';
import { SNOWBALL_FONT_FILES, snowballRules, type SnowballFonts } from '../src/theme/snowball.ts';
import { THEMES_UNRELEASED, THEME_IDS, themeOf, type ThemeId } from '../src/theme/themes.ts';

/**
 * The themes a build may show: every released one, and the unreleased ones
 * `preview` names (VITE_THEMES_PREVIEW, comma-separated). Midnight is the
 * page's own CSS and needs none.
 */
export function shownThemes(preview: string | undefined): readonly ThemeId[] {
  const named = new Set(
    (preview ?? '')
      .split(',')
      .map((name) => name.trim())
      .filter((name) => name !== ''),
  );
  return THEME_IDS.filter(
    (id) => id !== 'midnight' && (!THEMES_UNRELEASED.has(id) || named.has(id)),
  );
}

/** Each of `ids` as the page carries it, Snowball's rules with its face at `fonts`. */
export function pageThemes(ids: readonly ThemeId[], fonts: SnowballFonts): PageThemes {
  return Object.fromEntries(
    ids.map((id): [ThemeId, PageTheme] => {
      const theme = themeOf(id);
      const toon = id === 'snowball';
      return [
        id,
        {
          rules: themeRules(theme, toon ? snowballRules(fonts) : []),
          color: theme.tokens.bg,
          ...(toon ? { font: fonts.latin } : {}),
        },
      ];
    }),
  );
}

/** The page's themes as the JSON index.html carries, safe inside a <script>. */
export function pageThemesJson(themes: PageThemes): string {
  return JSON.stringify(themes).replace(/</g, '\\u003c');
}

/** index.html's empty block, which the build fills, however it is laid out. */
export const PAGE_THEMES_BLOCK = new RegExp(
  `<script type="application/json" id="${PAGE_THEMES_ID}">\\s*\\{\\}\\s*</script>`,
);

const require = createRequire(import.meta.url);

/** Where a build that may show Snowball ships its face's license (the SIL Open Font License). */
export const SNOWBALL_FONT_LICENSE = 'fonts/fredoka-OFL.txt';

/**
 * Writes the themes this build may show into index.html (#sl-themes), and,
 * where it may show Snowball, ships its face's files under names of their
 * own, with the face's license. A build that may not show a theme carries
 * none of it: its CSS, its face, its license, or its name (vite.config.ts
 * keeps it out of the scripts too).
 */
export function themes(preview: string | undefined): Plugin {
  const ids = shownThemes(preview);
  const toon = ids.includes('snowball');
  const files = Object.entries(SNOWBALL_FONT_FILES).map(([part, name]) => {
    const file = require.resolve(`@fontsource-variable/fredoka/files/${name}`);
    const source = readFileSync(file);
    const hash = createHash('sha256').update(source).digest('hex').slice(0, 8);
    const built = `assets/${path.basename(name, '.woff2')}-${hash}.woff2`;
    return { part: part as keyof SnowballFonts, name, source, built };
  });
  let base = '/';
  let build = false;
  const fonts = (): SnowballFonts => {
    const url = (part: keyof SnowballFonts): string => {
      const file = files.find((entry) => entry.part === part);
      if (file === undefined) throw new Error(`themes: no ${part} face`);
      // The dev server serves the package's own file.
      return build
        ? `${base}${file.built}`
        : `${base}node_modules/@fontsource-variable/fredoka/files/${file.name}`;
    };
    return { latin: url('latin'), latinExt: url('latinExt') };
  };
  return {
    name: 'snowlight:themes',
    configResolved(config) {
      base = config.base;
      build = config.command === 'build';
    },
    buildStart() {
      if (!build || !toon) return;
      for (const file of files) {
        this.emitFile({ type: 'asset', fileName: file.built, source: file.source });
      }
      // The face's license, beside Geist's (public/fonts/geist-OFL.txt).
      this.emitFile({
        type: 'asset',
        fileName: SNOWBALL_FONT_LICENSE,
        source: readFileSync(require.resolve('@fontsource-variable/fredoka/LICENSE')),
      });
    },
    transformIndexHtml: {
      order: 'pre',
      // index.html's block (tests/themes-page.test.ts checks it is there); other pages have none.
      handler: (html) =>
        html.replace(
          PAGE_THEMES_BLOCK,
          () =>
            `<script type="application/json" id="${PAGE_THEMES_ID}">${pageThemesJson(pageThemes(ids, fonts()))}</script>`,
        ),
    },
  };
}
