import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

import type { Plugin } from 'vite';

import { themeRules } from '../src/theme/css.ts';
import { PAGE_THEMES_ID, type PageTheme, type PageThemes } from '../src/theme/page.ts';
import {
  SNOWBALL_FONT,
  SNOWBALL_FONT_FILES,
  snowballRules,
  type SnowballFonts,
} from '../src/theme/snowball.ts';
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

/**
 * Whether a build that may show `preview` carries any unreleased theme in its
 * scripts (vite.config.ts __UNRELEASED_THEMES__): only where it names one.
 */
export function carriesUnreleased(preview: string | undefined): boolean {
  return shownThemes(preview).some((id) => THEMES_UNRELEASED.has(id));
}

/**
 * The themes whose rules the page does not carry: a look of their own, too
 * large to download on every visit (e2e/shell.spec.ts PAGE_THEMES_GZIP_BUDGET).
 * Each is a style sheet of its own (themeSheet), which a device fetches only
 * where the theme goes on or is tried, and the page carries its address.
 */
export const SHEET_THEMES: ReadonlySet<ThemeId> = new Set<ThemeId>(['snowball']);

/** `id`'s rules, Snowball's with its face at `fonts`. */
function rulesOf(id: ThemeId, fonts: SnowballFonts): readonly string[] {
  return themeRules(themeOf(id), id === 'snowball' ? snowballRules(fonts) : []);
}

/** A sheet theme's style sheet: its rules, one to a line. */
export function themeSheet(id: ThemeId, fonts: SnowballFonts): string {
  return `${rulesOf(id, fonts).join('\n')}\n`;
}

/**
 * Each of `ids` as the page carries it: its rules, or, for a sheet theme,
 * the address `sheets` gives its style sheet; Snowball with its face at `fonts`.
 */
export function pageThemes(
  ids: readonly ThemeId[],
  fonts: SnowballFonts,
  sheets: Partial<Record<ThemeId, string>> = {},
): PageThemes {
  return Object.fromEntries(
    ids.map((id): [ThemeId, PageTheme] => {
      const color = themeOf(id).tokens.bg;
      const face = id === 'snowball' ? { font: fonts.latin, family: SNOWBALL_FONT } : {};
      const sheet = SHEET_THEMES.has(id) ? sheets[id] : undefined;
      return [
        id,
        sheet === undefined
          ? { rules: rulesOf(id, fonts), color, ...face }
          : { sheet, color, ...face },
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
 * Where a sheet theme's style sheet is served: under a folder of its own,
 * which the service worker does not precache (src/pwa/config.ts
 * PRECACHE_GLOBS takes assets/*.css only), so a device that never puts the
 * theme on never downloads it. Built, the name carries a hash of the sheet.
 */
export function sheetPath(id: ThemeId, hash: string | null): string {
  return `assets/themes/${id}${hash === null ? '' : `-${hash}`}.css`;
}

/**
 * Writes the themes this build may show into index.html (#sl-themes), and,
 * where it may show Snowball, ships its face's files under names of their
 * own, with the face's license, and each sheet theme's style sheet
 * (SHEET_THEMES). A build that may not show a theme carries none of it: its
 * CSS, its face, its license, or its name (vite.config.ts keeps it out of
 * the scripts too).
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
  /** Each sheet theme this build may show: its style sheet, and where it is served. */
  const sheets = (): { id: ThemeId; css: string; file: string }[] =>
    ids
      .filter((id) => SHEET_THEMES.has(id))
      .map((id) => {
        const css = themeSheet(id, fonts());
        const hash = build ? createHash('sha256').update(css).digest('hex').slice(0, 8) : null;
        return { id, css, file: sheetPath(id, hash) };
      });
  return {
    name: 'snowlight:themes',
    configResolved(config) {
      base = config.base;
      build = config.command === 'build';
    },
    configureServer(server) {
      // The dev server serves each sheet as the build would write it.
      server.middlewares.use((request, response, next) => {
        const sheet = sheets().find((entry) => request.url?.split('?')[0] === base + entry.file);
        if (sheet === undefined) {
          next();
          return;
        }
        response.setHeader('Content-Type', 'text/css');
        response.end(sheet.css);
      });
    },
    buildStart() {
      if (!build) return;
      for (const sheet of sheets()) {
        this.emitFile({ type: 'asset', fileName: sheet.file, source: sheet.css });
      }
      if (!toon) return;
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
        html.replace(PAGE_THEMES_BLOCK, () => {
          const addresses = Object.fromEntries(
            sheets().map((sheet) => [sheet.id, base + sheet.file]),
          );
          return `<script type="application/json" id="${PAGE_THEMES_ID}">${pageThemesJson(pageThemes(ids, fonts(), addresses))}</script>`;
        }),
    },
  };
}
