// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';
import { describe, expect, it } from 'vitest';

import { copy } from '../../copy';
import { APPLE_TOUCH_ICON } from '../config';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const PUBLIC = path.join(WEB, 'public');
const { problems } = (await import(
  /* @vite-ignore */ path.join(WEB, 'scripts', 'check-copy.mjs')
)) as { problems: (text: string) => string[] };

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose: string;
}

const manifest = JSON.parse(readFileSync(path.join(PUBLIC, 'manifest.webmanifest'), 'utf8')) as {
  id?: string;
  name: string;
  short_name: string;
  description: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  lang: string;
  icons: ManifestIcon[];
};

async function pixel(file: string, x: number, y: number): Promise<number[]> {
  const { data, info } = await sharp(file)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const at = (y * info.width + x) * 4;
  return [...data.subarray(at, at + 4)];
}

describe('manifest.webmanifest', () => {
  it('takes its words from copy.ts, in the house style', () => {
    expect(manifest.name).toBe(copy.manifest.name);
    expect(manifest.name).toBe('Snowlight');
    expect(manifest.short_name).toBe(copy.manifest.shortName);
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
    expect(manifest.description).toBe(copy.manifest.description);
    for (const text of [manifest.name, manifest.short_name, manifest.description]) {
      expect(problems(text)).toEqual([]);
    }
  });

  it('opens standalone on black', () => {
    expect(manifest).toMatchObject({
      display: 'standalone',
      theme_color: '#000000',
      background_color: '#000000',
      lang: 'en',
    });
  });

  // The page links the manifest at <base>manifest.webmanifest (pwaHead), so
  // URLs in it resolve against the base, whatever the build's base is.
  it.each([
    ['a domain of its own', 'https://snowlight.example/'],
    ['a GitHub Pages project site', 'https://viaate.github.io/jsalcards/'],
  ])('opens at the site base and keeps to it, on %s', (_, site) => {
    const manifestUrl = new URL('manifest.webmanifest', site);
    const startUrl = new URL(manifest.start_url, manifestUrl).href;
    const scope = new URL(manifest.scope, manifestUrl).href;
    expect([startUrl, scope]).toEqual([site, site]);
    for (const icon of manifest.icons) {
      expect(new URL(icon.src, manifestUrl).href.startsWith(site)).toBe(true);
    }
  });

  it('leaves the id to default to the start URL, one per deployment', () => {
    // An id resolves against the origin alone: "./" would be the host's root on
    // every project site. Left out, it is the start URL, base included.
    expect(manifest.id).toBeUndefined();
  });

  it('lists 192 and 512 icons and a maskable one', () => {
    const summary = manifest.icons.map((icon) => `${icon.sizes} ${icon.purpose} ${icon.type}`);
    expect(summary).toEqual([
      '192x192 any image/png',
      '512x512 any image/png',
      '512x512 maskable image/png',
    ]);
  });

  it('points at icons of the stated size', async () => {
    for (const icon of manifest.icons) {
      const file = path.join(PUBLIC, icon.src);
      const meta = await sharp(file).metadata();
      expect([icon.src, `${String(meta.width)}x${String(meta.height)}`, meta.format]).toEqual([
        icon.src,
        icon.sizes,
        'png',
      ]);
    }
    const apple = await sharp(path.join(PUBLIC, APPLE_TOUCH_ICON)).metadata();
    expect([apple.width, apple.height, apple.hasAlpha]).toEqual([180, 180, false]);
  });

  it('draws a rounded tile for "any" and a full-bleed one for "maskable"', async () => {
    const any = path.join(PUBLIC, 'icons/icon-512.png');
    const maskable = path.join(PUBLIC, 'icons/icon-maskable-512.png');
    // The corner of a rounded tile is clear; its edge midpoint and a maskable corner are black.
    expect((await pixel(any, 0, 0))[3]).toBe(0);
    expect(await pixel(any, 256, 1)).toEqual([0, 0, 0, 255]);
    expect(await pixel(maskable, 0, 0)).toEqual([0, 0, 0, 255]);
    // The bloom burns near white at the center.
    const center = await pixel(maskable, 256, 256);
    expect(Math.min(...center.slice(0, 3))).toBeGreaterThan(230);
  });

  it('keeps the maskable bloom inside the safe zone', async () => {
    const file = path.join(PUBLIC, 'icons/icon-maskable-512.png');
    const { data, info } = await sharp(file).raw().toBuffer({ resolveWithObject: true });
    const safe = 0.4 * info.width;
    let outside = 0;
    for (let y = 0; y < info.height; y++) {
      for (let x = 0; x < info.width; x++) {
        if (Math.hypot(x + 0.5 - info.width / 2, y + 0.5 - info.height / 2) <= safe) continue;
        const at = (y * info.width + x) * info.channels;
        outside = Math.max(outside, data[at] ?? 0, data[at + 1] ?? 0, data[at + 2] ?? 0);
      }
    }
    // Only the last trace of the halo reaches past the safe zone.
    expect(outside).toBeLessThanOrEqual(12);
  });

  it('is what scripts/build-icons.mjs makes from the glyph and copy.ts', () => {
    const output = execFileSync(process.execPath, ['scripts/build-icons.mjs', '--check'], {
      cwd: WEB,
      encoding: 'utf8',
    });
    expect(output).toContain('up to date');
  });
});
