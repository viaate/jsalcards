/**
 * Map labels in Geist, the face the rest of the page is set in.
 *
 * The style names no glyph server, so MapLibre draws each label glyph itself
 * (a signed distance field, on a canvas) from the CSS font family its
 * `text-font` names, and reads the weight from that name ("Regular",
 * "Medium"). These faces give it those families: the variable Geist files the
 * page already ships and the service worker precaches, under one family name
 * per weight. Nothing downloads until MapLibre draws its first label glyph,
 * and only the street tiles, which start at zoom 7, carry text.
 *
 * Geist is licensed under the SIL Open Font License 1.1; the license ships
 * with the site as public/fonts/geist-OFL.txt.
 */
import latin from '@fontsource-variable/geist/files/geist-latin-wght-normal.woff2?url';
import latinExt from '@fontsource-variable/geist/files/geist-latin-ext-wght-normal.woff2?url';
import unicode from '@fontsource-variable/geist/unicode.json';

/** The families the style's `text-font` names; MapLibre reads the weight from the name. */
export const MAP_FONTS = Object.freeze({
  regular: 'Geist Map Regular',
  medium: 'Geist Map Medium',
} as const);

/**
 * The Latin subsets of the variable Geist files, in the order they are added,
 * and the codepoints each covers.
 *
 * Before it draws a glyph, MapLibre waits for `document.fonts.load()` of the
 * label's font, which loads only the faces that cover a space. The Latin
 * Extended face claims the space too, so it loads in that same wait and no
 * glyph is ever drawn in a fallback font and kept. Both files draw the
 * space alike.
 */
export const MAP_FONT_FILES: readonly { readonly url: string; readonly unicodeRange: string }[] =
  Object.freeze([
    { url: latinExt, unicodeRange: `U+0020,${unicode['latin-ext']}` },
    { url: latin, unicodeRange: unicode.latin },
  ]);

/** The weight axis the variable files cover. */
const WEIGHTS = '100 900';

const added = new WeakMap<FontFaceSet, readonly FontFace[]>();

/**
 * Registers the label faces with the document, once. Nothing downloads until
 * MapLibre draws a label.
 */
export function addMapFonts(fonts: FontFaceSet = document.fonts): readonly FontFace[] {
  const existing = added.get(fonts);
  if (existing !== undefined) return existing;
  const faces = Object.values(MAP_FONTS).flatMap((family) =>
    MAP_FONT_FILES.map(
      ({ url, unicodeRange }) =>
        new FontFace(family, `url(${JSON.stringify(url)}) format('woff2')`, {
          weight: WEIGHTS,
          style: 'normal',
          unicodeRange,
          display: 'block',
        }),
    ),
  );
  for (const face of faces) fonts.add(face);
  added.set(fonts, faces);
  return faces;
}
