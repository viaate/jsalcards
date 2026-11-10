// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';
import { describe, expect, it } from 'vitest';

import { copy } from '../../copy';
import {
  APPLE_TOUCH_ICON,
  FAVICONS,
  ICON_SET,
  MANIFEST_FILE,
  NOTIFY_ICON,
  PRECACHE_GLOBS,
} from '../config';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const PUBLIC = path.join(WEB, 'public');
const { problems } = (await import(
  /* @vite-ignore */ path.join(WEB, 'scripts', 'check-copy.mjs')
)) as { problems: (text: string) => string[] };

interface ScriptIcon {
  file: string;
  size: number;
  make: 'copy' | 'tile' | 'maskable';
  source: string | null;
  rounded: boolean;
  purpose: 'any' | 'maskable' | null;
  old: string | null;
}
interface Drawing {
  data: Buffer;
  side: number;
}
/** scripts/build-icons.mjs: the table of icons it writes, and how it draws the logo. */
const script = (await import(/* @vite-ignore */ path.join(WEB, 'scripts', 'build-icons.mjs'))) as {
  ICONS: readonly ScriptIcon[];
  ICON_SET: string;
  LOGO: string;
  TILE_SIDE: number;
  MASKABLE_SIDE: number;
  draw: (svg: string, side: number) => Promise<Drawing>;
  maskableSvg: (svg: string) => string;
};

/** The logo's colors: the top of its sky, its crystal, and the pale ice at the foot of its snow. */
const SKY = [11, 15, 23];
const CRYSTAL = [127, 212, 255];
const ICE = [189, 217, 238];

/** Whether a pixel is the crystal's blue: no part of the sky or the snow is. */
function isCrystal(red: number, green: number, blue: number): boolean {
  return blue - red > 90 && green > 150;
}

function expectNear(actual: readonly number[], expected: readonly number[], within = 3): void {
  expect(actual.length).toBeGreaterThanOrEqual(expected.length);
  expected.forEach((value, index) => {
    expect(
      Math.abs((actual[index] ?? Number.NaN) - value),
      JSON.stringify(actual),
    ).toBeLessThanOrEqual(within);
  });
}

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
    const any = path.join(PUBLIC, `icons/icon-512.${ICON_SET}.png`);
    const maskable = path.join(PUBLIC, `icons/icon-maskable-512.${ICON_SET}.png`);
    // The corner of a rounded tile is clear; its edge midpoint and a maskable corner are the logo's sky.
    expect((await pixel(any, 0, 0))[3]).toBe(0);
    expect(await pixel(any, 256, 1)).toEqual([...SKY, 255]);
    expect(await pixel(maskable, 0, 0)).toEqual([...SKY, 255]);
    // The crystal's upright arm crosses the center.
    expect(await pixel(maskable, 256, 256)).toEqual([...CRYSTAL, 255]);
  });

  it('keeps the maskable crystal inside the safe zone', async () => {
    const file = path.join(PUBLIC, `icons/icon-maskable-512.${ICON_SET}.png`);
    const { data, info } = await sharp(file).raw().toBuffer({ resolveWithObject: true });
    const safe = 0.4 * info.width;
    let inside = 0;
    let outside = 0;
    for (let y = 0; y < info.height; y++) {
      for (let x = 0; x < info.width; x++) {
        const at = (y * info.width + x) * info.channels;
        if (!isCrystal(data[at] ?? 0, data[at + 1] ?? 0, data[at + 2] ?? 0)) continue;
        if (Math.hypot(x + 0.5 - info.width / 2, y + 0.5 - info.height / 2) <= safe) inside++;
        else outside++;
      }
    }
    // Every mask shape keeps the crystal whole; the snow runs past the zone by design.
    expect(inside).toBeGreaterThan(10_000);
    expect(outside).toBe(0);
  });

  it("is what scripts/build-icons.mjs makes from the logo's sources and copy.ts", () => {
    const output = execFileSync(process.execPath, ['scripts/build-icons.mjs', '--check'], {
      cwd: WEB,
      encoding: 'utf8',
    });
    expect(output).toContain('up to date');
  });
});

describe('the logo in every icon', () => {
  const file = (name: string): string => path.join(PUBLIC, name);
  const sha256 = (name: string): string =>
    createHash('sha256').update(readFileSync(name)).digest('hex');

  it("keeps the design's own files as its sources, byte for byte", () => {
    expect(
      ['icon.svg', 'favicon-16.png', 'favicon-32.png', 'mark.svg'].map((name) => [
        name,
        sha256(path.join(script.LOGO, name)),
      ]),
    ).toEqual([
      ['icon.svg', 'ab856834aea5bfd1edab761f1a6dd4136973dad71f093c529601992543540613'],
      ['favicon-16.png', 'a0b37d4a624f841ba7408777fa4a3ac792a900d1bde9fa664af855262b37ac1a'],
      ['favicon-32.png', 'ad6c4a7906e639440c71cb7c25224e0d7f755953bb2a12d1f30515000467dcd8'],
      ['mark.svg', '99f988cf64b28729589064964d01c123e5e6f69c8133eedc8e2f4770b524dc97'],
    ]);
  });

  it("shows a tab the design's own pixels at 16 and 32, never a shrunk icon, and the tile at 48", async () => {
    for (const size of [16, 32]) {
      const made = file(`favicon-${String(size)}.${ICON_SET}.png`);
      const source = path.join(script.LOGO, `favicon-${String(size)}.png`);
      expect(readFileSync(made).equals(readFileSync(source)), made).toBe(true);
      const meta = await sharp(made).metadata();
      expect([meta.width, meta.height, meta.format]).toEqual([size, size, 'png']);
    }
    const tile = file(`favicon-48.${ICON_SET}.png`);
    const meta = await sharp(tile).metadata();
    expect([meta.width, meta.height, meta.format]).toEqual([48, 48, 'png']);
    expect((await pixel(tile, 0, 0))[3]).toBe(0);
    expect((await pixel(tile, 24, 2))[3]).toBe(255);
  });

  it('draws the tile: sky at the top, the crystal across the center, snow shading to pale ice at the foot', async () => {
    const tile = file(`icons/icon-512.${ICON_SET}.png`);
    expect((await pixel(tile, 0, 0))[3]).toBe(0);
    expect((await pixel(tile, 511, 511))[3]).toBe(0);
    expectNear(await pixel(tile, 256, 5), [...SKY, 255]);
    expectNear(await pixel(tile, 256, 256), [...CRYSTAL, 255]);
    // The foot of the snow is tinted, so the tile keeps its bottom edge on a white page.
    const [red = 0, , blue = 0, alpha] = await pixel(tile, 256, 505);
    expect(alpha).toBe(255);
    expect(red).toBeGreaterThanOrEqual(180);
    expect(red).toBeLessThanOrEqual(200);
    expect(blue - red).toBeGreaterThanOrEqual(30);
    // The home-screen icon is the same tile on a full square: iOS rounds it.
    const apple = file(APPLE_TOUCH_ICON);
    const meta = await sharp(apple).metadata();
    expect([meta.width, meta.height, meta.hasAlpha]).toEqual([180, 180, false]);
    expectNear(await pixel(apple, 90, 90), [...CRYSTAL, 255]);
    expectNear(await pixel(apple, 0, 0), [...SKY, 255]);
  });

  it('draws the maskable icon as the tile seen from further back, its sky and snow run on', async () => {
    const maskable = file(`icons/icon-maskable-512.${ICON_SET}.png`);
    expect((await sharp(maskable).metadata()).hasAlpha).toBe(false);
    expect(await pixel(maskable, 0, 0)).toEqual([...SKY, 255]);
    expectNear(await pixel(maskable, 256, 256), [...CRYSTAL, 255]);
    expectNear(await pixel(maskable, 256, 511), [...ICE, 255]);

    // Drawn at full size, its middle is the tile itself.
    const svg = readFileSync(path.join(script.LOGO, 'icon.svg'), 'utf8');
    const tile = await script.draw(svg, script.TILE_SIDE);
    const wide = await script.draw(script.maskableSvg(svg), script.MASKABLE_SIDE);
    expect([script.TILE_SIDE, script.MASKABLE_SIDE]).toEqual([1024, 1280]);
    const inset = (script.MASKABLE_SIDE - script.TILE_SIDE) / 2;
    let differ = 0;
    for (let y = 0; y < tile.side; y++) {
      for (let x = 0; x < tile.side; x++) {
        const a = (y * tile.side + x) * 3;
        const b = ((y + inset) * wide.side + x + inset) * 3;
        const off = Math.max(
          Math.abs((tile.data[a] ?? 0) - (wide.data[b] ?? 0)),
          Math.abs((tile.data[a + 1] ?? 0) - (wide.data[b + 1] ?? 0)),
          Math.abs((tile.data[a + 2] ?? 0) - (wide.data[b + 2] ?? 0)),
        );
        if (off > 8) differ++;
      }
    }
    expect(differ / (tile.side * tile.side)).toBeLessThan(0.005);
  });

  it('refuses to make a maskable icon from a drawing its edits do not fit', () => {
    const svg = readFileSync(path.join(script.LOGO, 'icon.svg'), 'utf8');
    expect(() => script.maskableSvg(svg.replace('M0 792Q512 640', 'M0 790Q512 640'))).toThrow(
      /once/,
    );
    expect(() => script.maskableSvg(`${svg}${svg}`)).toThrow(/once/);
  });

  it('answers at the addresses an earlier build named with the new picture', async () => {
    const old = script.ICONS.filter((icon) => icon.old !== null);
    expect(old.map((icon) => icon.old)).toEqual([
      'icons/icon-192.png',
      'icons/icon-512.png',
      'icons/icon-maskable-512.png',
      'icons/apple-touch-icon.png',
    ]);
    for (const icon of old) {
      const [was, now] = await Promise.all(
        [icon.old ?? '', icon.file].map((name) =>
          sharp(file(name)).raw().toBuffer({ resolveWithObject: true }),
        ),
      );
      expect([was?.info.width, was?.info.height, was?.info.channels], icon.file).toEqual([
        now?.info.width,
        now?.info.height,
        now?.info.channels,
      ]);
      expect(was?.data.equals(now?.data ?? Buffer.alloc(0)), icon.file).toBe(true);
    }
  });

  it('names one set of icons everywhere, each address carrying the set', () => {
    expect(script.ICON_SET).toBe(ICON_SET);
    const suffix = `.${ICON_SET}.png`;
    const names = script.ICONS.map((icon) => icon.file);
    for (const name of [...names, ...FAVICONS, NOTIFY_ICON, APPLE_TOUCH_ICON]) {
      expect(name.endsWith(suffix), name).toBe(true);
    }
    // The pages link the three tab icons in this order: the 32 last, for a browser that ignores sizes.
    const sizeOf = (name: string): number =>
      script.ICONS.find((icon) => icon.file === name)?.size ?? Number.NaN;
    expect(FAVICONS.map(sizeOf)).toEqual([16, 48, 32]);
    expect([...FAVICONS].sort()).toEqual(names.filter((name) => !name.includes('/')).sort());
    const links = FAVICONS.map((name) => {
      const size = String(sizeOf(name));
      return `<link rel="icon" href="/${name}" type="image/png" sizes="${size}x${size}" />`;
    });
    for (const page of ['index.html', 'privacy.html']) {
      const html = readFileSync(path.join(WEB, page), 'utf8');
      expect(html.match(/<link\s[^>]*rel="(?:shortcut )?icon"[^>]*>/g), page).toEqual(links);
      // One after another, nothing between them.
      expect(html, page).toContain(links.join('\n    '));
    }
    // The manifest, the notification and the home-screen link name the script's own files.
    expect(manifest.icons.map((icon) => [icon.src, icon.sizes, icon.purpose])).toEqual(
      script.ICONS.filter((icon) => icon.purpose !== null).map((icon) => [
        icon.file,
        `${String(icon.size)}x${String(icon.size)}`,
        icon.purpose,
      ]),
    );
    expect(NOTIFY_ICON).toBe(
      script.ICONS.find((icon) => icon.size === 192 && icon.purpose === 'any')?.file,
    );
    expect(APPLE_TOUCH_ICON).toBe(
      script.ICONS.find((icon) => icon.size === 180 && icon.purpose === null)?.file,
    );
    // The worker keeps the tab icons with the shell, and no app icon.
    expect(PRECACHE_GLOBS).toContain('favicon-*.png');
    expect(PRECACHE_GLOBS.some((glob) => glob.includes('icons') || glob.includes('.svg'))).toBe(
      false,
    );
    expect(PRECACHE_GLOBS).toContain(MANIFEST_FILE);
  });

  it('leaves no trace of the icons it replaced', () => {
    const gone = ['favicon.svg', 'icons/glyph.svg'];
    for (const name of gone) expect(existsSync(file(name)), name).toBe(false);
    const tracked = execFileSync(
      'git',
      [
        'ls-files',
        '-z',
        '--',
        'index.html',
        'privacy.html',
        'vite.config.ts',
        'public',
        'tools',
        'scripts',
        'src',
      ],
      { cwd: WEB, encoding: 'utf8' },
    )
      .split('\0')
      .filter(
        (name) =>
          name !== '' &&
          !name.startsWith('scripts/logo/') &&
          !/(?:^|\/)tests\//.test(name) &&
          !name.endsWith('.test.ts'),
      );
    expect(tracked).toEqual(
      expect.arrayContaining(['index.html', 'privacy.html', 'src/pwa/config.ts']),
    );
    const naming = tracked.filter((name) => {
      // A file the work has deleted is still listed until the change is committed.
      if (!existsSync(path.join(WEB, name))) return false;
      const text = readFileSync(path.join(WEB, name), 'latin1');
      return text.includes('favicon.svg') || text.includes('glyph.svg');
    });
    expect(naming).toEqual([]);
  });
});
