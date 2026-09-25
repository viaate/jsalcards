#!/usr/bin/env node
// @ts-check
/**
 * Builds the app icons and the web app manifest: `npm run build:icons`.
 *
 * Input: public/icons/glyph.svg, the Snowlight bloom as a vector (a white core
 * fading through Closed blue to nothing, the same gradient as favicon.svg),
 * and the manifest strings in src/copy.ts.
 *
 * Output, committed:
 *   public/icons/icon-192.png           purpose "any": the bloom on a rounded black tile
 *   public/icons/icon-512.png           purpose "any"
 *   public/icons/icon-maskable-512.png  purpose "maskable": full-bleed black, bloom inside the safe zone
 *   public/icons/apple-touch-icon.png   180 px, full-bleed black (iOS rounds the corners)
 *   public/manifest.webmanifest
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
 * by pixel, so a different zlib build does not count as a change).
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
const GLYPH = join(PUBLIC, 'icons', 'glyph.svg');
const MANIFEST = join(PUBLIC, 'manifest.webmanifest');

/** Design tokens: the background and the theme are pure black. */
const BLACK = '#000000';

/**
 * Icon layouts, as fractions of the icon's side.
 * - glyph: radius of the bloom. Its light is mostly within the inner third
 *   of that radius; the rest is a faint halo.
 * - corner: tile corner radius (favicon.svg's 14 on 64), or 0 for full bleed.
 * The maskable bloom keeps its visible light well inside the 40%-radius
 * safe zone that every mask shape keeps.
 * @typedef {{ file: string, size: number, glyph: number, corner: number, purpose: 'any' | 'maskable' | null }} Icon
 * @type {readonly Icon[]}
 */
export const ICONS = Object.freeze([
  { file: 'icons/icon-192.png', size: 192, glyph: 0.46, corner: 14 / 64, purpose: 'any' },
  { file: 'icons/icon-512.png', size: 512, glyph: 0.46, corner: 14 / 64, purpose: 'any' },
  { file: 'icons/icon-maskable-512.png', size: 512, glyph: 0.4, corner: 0, purpose: 'maskable' },
  { file: 'icons/apple-touch-icon.png', size: 180, glyph: 0.46, corner: 0, purpose: null },
]);

/**
 * The glyph's inner SVG (everything inside its root <svg>) and its viewBox.
 * @param {string} svg
 * @returns {{ viewBox: string, body: string }}
 */
function parseGlyph(svg) {
  const root = /<svg\b([^>]*)>([\s\S]*)<\/svg>\s*$/u.exec(svg.trim());
  const viewBox = root?.[1] !== undefined ? /\bviewBox="([^"]+)"/u.exec(root[1])?.[1] : undefined;
  if (root?.[2] === undefined || viewBox === undefined) {
    throw new Error('build-icons: glyph.svg needs a root <svg> with a viewBox');
  }
  return { viewBox, body: root[2].trim() };
}

/**
 * One icon as SVG: a black tile (rounded or full bleed) with the glyph centered.
 * @param {{ viewBox: string, body: string }} glyph
 * @param {Icon} icon
 */
export function iconSvg(glyph, icon) {
  const { size } = icon;
  const radius = icon.glyph * size;
  const corner = icon.corner * size;
  const offset = size / 2 - radius;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${String(size)}" height="${String(size)}" viewBox="0 0 ${String(size)} ${String(size)}">`,
    `<rect width="${String(size)}" height="${String(size)}" rx="${String(corner)}" fill="${BLACK}"/>`,
    `<svg x="${String(offset)}" y="${String(offset)}" width="${String(2 * radius)}" height="${String(2 * radius)}" viewBox="${glyph.viewBox}">`,
    glyph.body,
    '</svg>',
    '</svg>',
  ].join('');
}

/**
 * @param {{ viewBox: string, body: string }} glyph
 * @param {Icon} icon
 * @returns {Promise<Buffer>}
 */
async function renderIcon(glyph, icon) {
  let image = sharp(Buffer.from(iconSvg(glyph, icon)));
  // A full-bleed icon has no transparent pixels, so it needs no alpha channel.
  if (icon.corner === 0) image = image.flatten({ background: BLACK });
  return image.png({ compressionLevel: 9, adaptiveFiltering: false, palette: false }).toBuffer();
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
  const glyph = parseGlyph(await readFile(GLYPH, 'utf8'));

  /** @type {Array<{ file: string, data: Buffer, png: boolean }>} */
  const outputs = [];
  for (const icon of ICONS) {
    outputs.push({ file: join(PUBLIC, icon.file), data: await renderIcon(glyph, icon), png: true });
  }
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
