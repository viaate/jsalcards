/**
 * Snowball's own rules, on top of its tokens (themes.ts): the cel-shaded
 * cartoon look over its night map. Cards and controls get a bold ink outline and a hard drop
 * offset in the same ink, corners grow rounder, and the type is Fredoka, a
 * round face licensed under the SIL Open Font License 1.1 (shipped as
 * fonts/fredoka-OFL.txt by tools/themes.ts), self-hosted from the build like Geist and
 * loaded only with this theme.
 *
 * The build writes these rules into a style sheet of Snowball's own, which
 * a device fetches only where Snowball goes on or is tried, and ships the
 * face's files beside it (tools/themes.ts): a device on another theme loads
 * neither.
 */
import unicode from '@fontsource-variable/fredoka/unicode.json' with { type: 'json' };

import { SNOWBALL_FONT } from './themes.ts';

export { SNOWBALL_FONT } from './themes.ts';

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

/** A sticker under the words it backs: a card in the ink, drawn in full by its own rule. */
function sticker(inset: string, radius: string): string {
  return `position:absolute;inset:${inset};z-index:-1;pointer-events:none;content:'';background:var(--surface-1);border:${OUTLINE} solid var(--border-2);border-radius:${radius};box-shadow:3px 3px 0 0 var(--border-2)`;
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
    // The info button over the bare sea: filled like the menu's and the locate buttons, so its ink
    // outline frames a card (open, it keeps the page's own fill).
    `${root} .maplibregl-ctrl.maplibregl-ctrl-attrib:not(.maplibregl-compact-show){background:var(--surface-1)}`,
    // The wordmark and the words on the map: bold, set on the night, and the update time and the
    // key each on a sticker. Every sticker is whole in these rules, whatever the page draws there:
    // a word whose halo goes has a card that renders under it (tests/engine.test.ts). The update
    // time keeps its halo as well, since a long line of it wraps past its sticker. The key's marks
    // are the page's own glowing glyphs (index.html), as the night map lights them: no ink ring.
    `${root} .wordmark{font-weight:700;letter-spacing:0}`,
    `${root} .updated{color:var(--text-1)}`,
    `${root} .updated::before{${sticker('calc(50% - 14px) -9px', '14px')}}`,
    `${root} .legend{font-weight:600;color:var(--text-1);text-shadow:none}`,
    `${root} .legend::before{${sticker('0 -8px', 'calc(var(--control-height) / 2)')}}`,
  ];
}
