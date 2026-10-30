/**
 * Snowball's own rules, on top of its tokens (themes.ts): the cel-shaded
 * cartoon look. Cards and controls get a bold ink outline and a hard drop
 * offset in the same ink, corners grow rounder, and the type is Fredoka, a
 * round face licensed under the SIL Open Font License 1.1 (shipped as
 * fonts/fredoka-OFL.txt by tools/themes.ts), self-hosted from the build like Geist and
 * loaded only with this theme.
 *
 * The build writes these rules into the page (tools/themes.ts), and only a
 * build that may show Snowball does, with the face's files: a build that may
 * not ships neither.
 */
import unicode from '@fontsource-variable/fredoka/unicode.json' with { type: 'json' };

import { SNOWBALL_FONT } from './unreleased.ts';

export { SNOWBALL_FONT } from './unreleased.ts';

/** The ink outline's width on cards and controls, and the drop offset's. */
const OUTLINE = '2.5px';
const DROP = '4px';

/** Where the build put the face's two files: the Latin letters, and the rest of Latin. */
export interface SnowballFonts {
  readonly latin: string;
  readonly latinExt: string;
}

/** The face's files in @fontsource-variable/fredoka/files, by part. */
export const SNOWBALL_FONT_FILES: Readonly<Record<keyof SnowballFonts, string>> = {
  latin: 'fredoka-latin-wght-normal.woff2',
  latinExt: 'fredoka-latin-ext-wght-normal.woff2',
};

/** The face's @font-face rules. */
export function snowballFontFaces({ latin, latinExt }: SnowballFonts): readonly string[] {
  return [
    [latinExt, unicode['latin-ext']],
    [latin, unicode.latin],
  ].map(
    ([url, range]) =>
      `@font-face{font-family:'${SNOWBALL_FONT}';font-style:normal;font-display:swap;font-weight:300 700;src:url(${JSON.stringify(url)}) format('woff2-variations');unicode-range:${String(range)}}`,
  );
}

/** The rules, one by one, scoped to :root[data-theme='snowball']. */
export function snowballRules(fonts: SnowballFonts): readonly string[] {
  const root = ":root[data-theme='snowball']";
  const cards = [
    '.search',
    '.menu-button',
    '.locate',
    '.detail',
    '.menu',
    '.results',
    '.maplibregl-ctrl.maplibregl-ctrl-attrib',
  ]
    .map((card) => `${root} ${card}`)
    .join(',');
  return [
    ...snowballFontFaces(fonts),
    `${root}{--font-sans:'${SNOWBALL_FONT}','Geist Variable',system-ui,sans-serif}`,
    // Thick ink outlines and a hard offset, never a soft shadow.
    `${cards}{border-width:${OUTLINE};border-color:var(--border-2);box-shadow:${DROP} ${DROP} 0 0 var(--border-2)}`,
    `${root} .search:focus-within{border-color:var(--border-2);box-shadow:${DROP} ${DROP} 0 0 var(--accent),${DROP} ${DROP} 0 ${OUTLINE} var(--border-2)}`,
    `${root} .detail{border-radius:22px}`,
    `${root} .menu{border-radius:20px}`,
    `@media (max-width: 719px){${root} .detail{border-width:${OUTLINE} 0 0;border-radius:28px 28px 0 0;box-shadow:0 -${DROP} 0 0 var(--border-2),0 40px 0 0 var(--surface-1)}}`,
    // The wordmark and the words on the map: bold, inked, set on the snow (css.ts's halo), and
    // the update time on a sticker, as the key is.
    `${root} .wordmark{font-weight:700;letter-spacing:0}`,
    `${root} .updated{color:var(--text-1);text-shadow:none}`,
    `${root} .updated::before{inset:calc(50% - 14px) -9px;background:var(--surface-1);border:${OUTLINE} solid var(--border-2);border-radius:14px;box-shadow:3px 3px 0 0 var(--border-2)}`,
    `${root} .legend{font-weight:600;color:var(--text-1);text-shadow:none}`,
    `${root} .legend::before{background:var(--surface-1);border:${OUTLINE} solid var(--border-2);box-shadow:3px 3px 0 0 var(--border-2)}`,
    // The key's marks as the map draws them: each status ringed in ink.
    `${root} .glyph.is-closed{box-shadow:0 0 0 1.5px var(--border-2)}`,
    `${root} .glyph.is-delayed{box-shadow:inset 0 0 0 2px var(--status-delayed),0 0 0 1.5px var(--border-2)}`,
    `${root} .glyph.is-remote{box-shadow:0 0 0 1.5px var(--border-2)}`,
    `${root} .glyph.is-early-dismissal{box-shadow:inset 0 0 0 2px var(--status-early-dismissal),0 0 0 1.5px var(--border-2)}`,
  ];
}
