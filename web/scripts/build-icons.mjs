#!/usr/bin/env node
// @ts-check
/**
 * Builds the site's icons and the web app manifest: `npm run build:icons`.
 *
 * Input: the logo's sources in scripts/logo/ (docs/live.md, "The logo and the
 * icons"), byte copies of the design's files, and the manifest strings in
 * src/copy.ts.
 *   icon.svg        the app icon: a snow crystal coming up over a snowy hill
 *   favicon-16.png  the tab icon at 16 real pixels, drawn pixel by pixel
 *   favicon-32.png  the same at 32
 *   mark.svg        the logo in one color (the share card's foot draws its
 *                   shapes from src/ui/share-card-art.ts; a test compares them)
 *
 * Output, committed, under public/. Every address carries ICON_SET, so a
 * browser that kept an earlier picture never answers with it:
 *   favicon-16.v2.png, favicon-32.v2.png  byte copies of the pixel drawings, never a shrunk icon
 *   favicon-48.v2.png                     the tile, rounded
 *   icons/icon-192.v2.png                 purpose "any": the tile, rounded
 *   icons/icon-512.v2.png                 purpose "any"
 *   icons/icon-maskable-512.v2.png        purpose "maskable": the tile at 0.8 on a full square
 *   icons/apple-touch-icon.v2.png         180 px, the tile on a full square (iOS rounds the corners)
 *   icons/icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png
 *                                         the addresses an earlier build named, each the same
 *                                         bytes as its twin above
 *   manifest.webmanifest
 *
 * The tile is one drawing, shrunk: icon.svg at 1024 px, then resized. The
 * maskable drawing is icon.svg seen from further back (0.8 about its center),
 * its sky and snow run on by the hill's own curve, so the crystal sits inside
 * the 40%-radius circle every mask shape keeps.
 *
 * The manifest works at any site base, so the build never has to rewrite it:
 * start_url, scope and the icons are relative to the manifest, which the page
 * links at <base>manifest.webmanifest. At "/" they resolve to "/"; on a
 * GitHub Pages project site, "/<repo>/". The manifest names no id, so the
 * app's id is its start URL, which is unique to each deployment (an id is
 * resolved against the origin alone, so "./" would give every project site on
 * one github.io host the same id).
 *
 * The same input always gives the same files. --check builds everything in
 * memory and exits 1 if any committed file differs (PNGs are compared pixel
 * by pixel, so a different zlib build does not count as a change; the two
 * copied favicons byte by byte).
 *
 *   node scripts/build-icons.mjs [--check]
 */
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = join(WEB, 'public');
/** The logo's sources. */
export const LOGO = join(WEB, 'scripts', 'logo');
const MANIFEST = join(PUBLIC, 'manifest.webmanifest');

/** The manifest's background and theme: pure black, as the page's. */
const BLACK = '#000000';
/** The foot of the tile's sky, under anything the drawing leaves clear. */
const SKY = '#04060a';
/** The side icon.svg is drawn at before it is shrunk. */
export const TILE_SIDE = 1024;
/** The side the maskable drawing is drawn at: the tile is its middle 1024. */
export const MASKABLE_SIDE = 1280;
/** A rounded tile's corner radius, as a fraction of its side (the lockup's corner). */
export const CORNER = 0.224;

/** The icon set's version, in every address (src/pwa/config.ts ICON_SET; a test holds the two equal). */
export const ICON_SET = 'v2';

/**
 * Every icon the script writes.
 * - make: 'copy' is the named source's own bytes; 'tile' is icon.svg shrunk;
 *   'maskable' is the maskable drawing shrunk.
 * - rounded: corners cut to CORNER, clear outside; a full square otherwise, with no alpha.
 * - purpose: the manifest's, or null for an icon the manifest does not list.
 * - old: the address an earlier build named, which answers with the same bytes.
 * @typedef {{ file: string, size: number, make: 'copy' | 'tile' | 'maskable', source: string | null, rounded: boolean, purpose: 'any' | 'maskable' | null, old: string | null }} Icon
 * @type {readonly Icon[]}
 */
export const ICONS = Object.freeze([
  {
    file: `favicon-16.${ICON_SET}.png`,
    size: 16,
    make: 'copy',
    source: 'favicon-16.png',
    rounded: false,
    purpose: null,
    old: null,
  },
  {
    file: `favicon-32.${ICON_SET}.png`,
    size: 32,
    make: 'copy',
    source: 'favicon-32.png',
    rounded: false,
    purpose: null,
    old: null,
  },
  {
    file: `favicon-48.${ICON_SET}.png`,
    size: 48,
    make: 'tile',
    source: null,
    rounded: true,
    purpose: null,
    old: null,
  },
  {
    file: `icons/icon-192.${ICON_SET}.png`,
    size: 192,
    make: 'tile',
    source: null,
    rounded: true,
    purpose: 'any',
    old: 'icons/icon-192.png',
  },
  {
    file: `icons/icon-512.${ICON_SET}.png`,
    size: 512,
    make: 'tile',
    source: null,
    rounded: true,
    purpose: 'any',
    old: 'icons/icon-512.png',
  },
  {
    file: `icons/icon-maskable-512.${ICON_SET}.png`,
    size: 512,
    make: 'maskable',
    source: null,
    rounded: false,
    purpose: 'maskable',
    old: 'icons/icon-maskable-512.png',
  },
  {
    file: `icons/apple-touch-icon.${ICON_SET}.png`,
    size: 180,
    make: 'tile',
    source: null,
    rounded: false,
    purpose: null,
    old: 'icons/apple-touch-icon.png',
  },
]);

/**
 * What turns icon.svg into the maskable drawing: the view steps back to 0.8
 * about the tile's center, and the sky, the snow line and the snow run on to
 * the wider square by the hill's own curve (716 + 76 x ((x - 512) / 512)^2
 * for the snow, 50 higher for the line the crystal is cut at). The sky's
 * gradient is pinned to the tile so its middle 1024 is the tile itself.
 * @type {ReadonlyArray<readonly [string, string]>}
 */
const MASKABLE_EDITS = Object.freeze([
  ['viewBox="0 0 1024 1024"', 'viewBox="-128 -128 1280 1280"'],
  ['x1="0" y1="0" x2="0" y2="1"', 'gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="1024"'],
  ['M0 742Q512 590 1024 742V0H0Z', 'M-128 784.75Q512 547.25 1152 784.75V-128H-128Z'],
  ['<rect width="1024" height="1024"', '<rect x="-128" y="-128" width="1280" height="1280"'],
  ['M0 792Q512 640 1024 792V1024H0Z', 'M-128 834.75Q512 597.25 1152 834.75V1152H-128Z'],
]);

/**
 * The maskable drawing, from icon.svg's text. Each edit must find its text
 * exactly once: a redrawn icon.svg fails here, never quietly keeps a tile
 * that fills a round mask wall to wall.
 * @param {string} svg
 */
export function maskableSvg(svg) {
  let out = svg;
  for (const [from, to] of MASKABLE_EDITS) {
    const found = out.split(from).length - 1;
    if (found !== 1) {
      throw new Error(
        `build-icons: icon.svg should hold ${JSON.stringify(from)} once, and holds it ${String(found)} times`,
      );
    }
    out = out.replace(from, () => to);
  }
  return out;
}

/** @typedef {{ data: Buffer, side: number }} Drawing raw RGB pixels, `side` square */

/**
 * An SVG drawn at its own size, which must be `side` square, on the sky's
 * foot color, without alpha.
 * @param {string} svg
 * @param {number} side
 * @returns {Promise<Drawing>}
 */
export async function draw(svg, side) {
  const { data, info } = await sharp(Buffer.from(svg))
    .flatten({ background: SKY })
    .raw()
    .toBuffer({ resolveWithObject: true });
  if (info.width !== side || info.height !== side || info.channels !== 3) {
    throw new Error(
      `build-icons: drew ${String(info.width)}x${String(info.height)}x${String(info.channels)}, not ${String(side)} square RGB`,
    );
  }
  return { data, side };
}

/**
 * One icon as a PNG: the drawing shrunk to the icon's size, and its corners cut where it is rounded.
 * @param {Drawing} drawing
 * @param {Icon} icon
 * @returns {Promise<Buffer>}
 */
async function renderIcon(drawing, icon) {
  const { size } = icon;
  const small = await sharp(drawing.data, {
    raw: { width: drawing.side, height: drawing.side, channels: 3 },
  })
    .resize(size, size, { kernel: 'lanczos3' })
    .raw()
    .toBuffer();
  let image = sharp(small, { raw: { width: size, height: size, channels: 3 } });
  if (icon.rounded) {
    const px = String(size);
    const mask = `<svg xmlns="http://www.w3.org/2000/svg" width="${px}" height="${px}"><rect width="${px}" height="${px}" rx="${String(CORNER * size)}"/></svg>`;
    image = image.ensureAlpha().composite([{ input: Buffer.from(mask), blend: 'dest-in' }]);
  }
  return image.png({ compressionLevel: 9, adaptiveFiltering: false, palette: false }).toBuffer();
}

/**
 * Every icon file, by its path under public/: each icon, and its old address where it has one.
 * @returns {Promise<Array<{ file: string, data: Buffer, png: boolean }>>}
 */
export async function iconFiles() {
  const svg = await readFile(join(LOGO, 'icon.svg'), 'utf8');
  const tile = await draw(svg, TILE_SIDE);
  const maskable = await draw(maskableSvg(svg), MASKABLE_SIDE);
  /** @type {Array<{ file: string, data: Buffer, png: boolean }>} */
  const files = [];
  for (const icon of ICONS) {
    // A copied favicon is the design's own file: compared byte by byte, never redrawn.
    const copied = icon.make === 'copy';
    const data =
      icon.source !== null
        ? await readFile(join(LOGO, icon.source))
        : await renderIcon(icon.make === 'maskable' ? maskable : tile, icon);
    files.push({ file: icon.file, data, png: !copied });
    if (icon.old !== null) files.push({ file: icon.old, data, png: !copied });
  }
  return files;
}

/** start_url and scope: the folder the manifest is served from, which is the site base. */
export const SITE_ROOT = './';

/**
 * The web app manifest. Its words come from copy.manifest; nothing else in it is shown.
 * @param {{ name: string, shortName: string, description: string }} words
 */
export function manifest(words) {
  return {
    name: words.name,
    short_name: words.shortName,
    description: words.description,
    lang: 'en',
    dir: 'ltr',
    start_url: SITE_ROOT,
    scope: SITE_ROOT,
    display: 'standalone',
    background_color: BLACK,
    theme_color: BLACK,
    icons: ICONS.flatMap((icon) =>
      icon.purpose === null
        ? []
        : [
            {
              src: icon.file,
              sizes: `${String(icon.size)}x${String(icon.size)}`,
              type: 'image/png',
              purpose: icon.purpose,
            },
          ],
    ),
  };
}

/** @param {Buffer} a @param {Buffer} b */
async function samePixels(a, b) {
  if (a.equals(b)) return true;
  const [left, right] = await Promise.all(
    [a, b].map((buffer) => sharp(buffer).raw().toBuffer({ resolveWithObject: true })),
  );
  return (
    left !== undefined &&
    right !== undefined &&
    left.info.width === right.info.width &&
    left.info.height === right.info.height &&
    left.info.channels === right.info.channels &&
    left.data.equals(right.data)
  );
}

/** @param {string} file */
async function readOrNull(file) {
  try {
    return await readFile(file);
  } catch {
    return null;
  }
}

async function main() {
  const args = process.argv.slice(2);
  const unknown = args.filter((arg) => arg !== '--check');
  if (unknown.length > 0) {
    throw new Error(`build-icons: unknown arguments: ${unknown.join(' ')}. Usage: [--check]`);
  }
  const check = args.includes('--check');

  const { copy } = await import('../src/copy.ts');

  /** @type {Array<{ file: string, data: Buffer, png: boolean }>} */
  const outputs = (await iconFiles()).map((icon) => ({ ...icon, file: join(PUBLIC, icon.file) }));
  outputs.push({
    file: MANIFEST,
    data: Buffer.from(`${JSON.stringify(manifest(copy.manifest), null, 2)}\n`),
    png: false,
  });

  const stale = [];
  for (const { file, data, png } of outputs) {
    const name = relative(WEB, file);
    if (check) {
      const current = await readOrNull(file);
      const same =
        current !== null && (png ? await samePixels(current, data) : current.equals(data));
      if (!same) stale.push(name);
    } else {
      await writeFile(file, data);
      console.log(`wrote ${name} (${String(data.length)} bytes)`);
    }
  }
  if (stale.length > 0) {
    console.error(`build-icons: out of date: ${stale.join(', ')}. Run npm run build:icons.`);
    process.exitCode = 1;
  } else if (check) {
    console.log(`build-icons: ${String(outputs.length)} files up to date`);
  }
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main();
}
