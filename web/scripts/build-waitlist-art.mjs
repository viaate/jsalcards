#!/usr/bin/env node
// @ts-check
/**
 * The waitlist page's pictures: `npm run build:waitlist-art -- <points.bin>`.
 *
 * Draws every school in the continental US as a point of light on the dark
 * map, the way the site's map lights a closed school, from the school
 * directory's points.bin (the file the site ships, `npm run stage` puts it in
 * public/data/schools/). It shows where the schools are, not what any of them
 * is doing: no status, no storm, no count.
 *
 * Writes, to src/waitlist/art/:
 *
 * - map.webp     the continental outline and the state lines, as the still in
 *                index.html draws them (its own path data, between the
 *                geo:still markers), with every school lit softly;
 * - sweep-N.webp four bands of the same lights, west to east, on a clear
 *                ground: the page fades each in and out in turn, so a slow
 *                band of brighter light crosses the country;
 * - social.jpg   the 1200 × 630 share card (Open Graph and Twitter): the whole
 *                map, dimmed, behind the chrome wordmark (chrome-wordmark.webp,
 *                from scripts/build-waitlist-chrome.mjs, which runs first) and
 *                the headline, set in Geist by Chromium, all centred so a
 *                small preview still reads. A JPEG under SOCIAL_MAX_BYTES,
 *                since some apps drop a link's preview when its picture is
 *                larger;
 * - art.json     the pictures' sizes, and the words the share card draws, which
 *                a unit test holds to src/copy-waitlist.ts.
 *
 * Every picture is a pure function of its inputs: the same points.bin and
 * index.html give the same bytes (the share card is drawn by Chromium, so it
 * matches only on the same Chromium).
 *
 * Usage: node scripts/build-waitlist-art.mjs <points.bin> [--out <dir>]
 */
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');

/** West, south, east, north of the continental US lines (src/map/basemap/us-geo.ts US_BOUNDS). */
const BOUNDS = /** @type {const} */ ([-124.734, 24.515, -66.982, 49.385]);
/** The still's viewBox width (scripts/build-geo.mjs STILL_WIDTH). */
const STILL_WIDTH = 8000;

/** The pictures' width in pixels; the height follows the still's shape. */
const WIDTH = 1600;
/** The phone map's width. */
const SMALL_WIDTH = 1000;
/** The sweep's pictures' width: they are soft light, so half size is enough. */
const SWEEP_WIDTH = 800;
/** How many bands the sweep has. */
const BANDS = 4;
/** The share card's largest size: some apps (WhatsApp among them) drop a larger picture. */
const SOCIAL_MAX_BYTES = 300_000;

/** The site's colours (index.html :root). */
const CLOSED_BLUE = [0x7f, 0xd4, 0xff];
const CORE_WHITE = [0xf4, 0xfb, 0xff];
const LINE_OUTLINE = '#6b6b6b';
const LINE_STATE = '#2a2a2a';

/** Web Mercator, in world units [0, 1], the formulas MapLibre and build-geo.mjs use. */
const mercatorX = (/** @type {number} */ lng) => (180 + lng) / 360;
const mercatorY = (/** @type {number} */ lat) =>
  (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;

const X0 = mercatorX(BOUNDS[0]);
const Y0 = mercatorY(BOUNDS[3]);
const SCALE = WIDTH / (mercatorX(BOUNDS[2]) - X0);
const HEIGHT = Math.round((mercatorY(BOUNDS[1]) - Y0) * SCALE);

/**
 * The schools' places from points.bin (src/data/directory.ts has the format),
 * leaving out the exclusively virtual ones, which have no building to light.
 * @param {Buffer} bytes
 * @returns {Array<[x: number, y: number]>} picture pixels, continental US only
 */
export function schoolPixels(bytes) {
  if (bytes.toString('latin1', 0, 4) !== 'SLPT') throw new Error('not a points.bin file');
  const recordBytes = bytes.readUInt16LE(6);
  const count = bytes.readUInt32LE(8);
  /** @type {Array<[number, number]>} */
  const out = [];
  for (let i = 0; i < count; i++) {
    const at = 16 + i * recordBytes;
    const lng = bytes.readInt32LE(at) * 1e-6;
    const lat = bytes.readInt32LE(at + 4) * 1e-6;
    const kind = bytes.readUInt8(at + 12);
    if ((kind & 0x04) !== 0) continue;
    if (lng < BOUNDS[0] || lng > BOUNDS[2] || lat < BOUNDS[1] || lat > BOUNDS[3]) continue;
    out.push([(mercatorX(lng) - X0) * SCALE, (mercatorY(lat) - Y0) * SCALE]);
  }
  return out;
}

/** A small, seeded random number generator (mulberry32), so the bands come out the same every run. */
function random(seed = 0x5eed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Splats each point into a float field, shared bilinearly between the four
 * pixels around it.
 * @param {Array<[number, number]>} points
 */
function field(points) {
  const out = new Float32Array(WIDTH * HEIGHT);
  for (const [x, y] of points) {
    const ix = Math.floor(x - 0.5);
    const iy = Math.floor(y - 0.5);
    const fx = x - 0.5 - ix;
    const fy = y - 0.5 - iy;
    /** @param {number} px @param {number} py @param {number} w */
    const add = (px, py, w) => {
      if (px >= 0 && py >= 0 && px < WIDTH && py < HEIGHT) out[py * WIDTH + px] += w;
    };
    add(ix, iy, (1 - fx) * (1 - fy));
    add(ix + 1, iy, fx * (1 - fy));
    add(ix, iy + 1, (1 - fx) * fy);
    add(ix + 1, iy + 1, fx * fy);
  }
  return out;
}

/**
 * A Gaussian blur, one pass across and one down.
 * @param {Float32Array} input
 * @param {number} sigma
 */
function blur(input, sigma) {
  const radius = Math.ceil(sigma * 3);
  const kernel = new Float32Array(radius * 2 + 1);
  let sum = 0;
  for (let i = -radius; i <= radius; i++) {
    kernel[i + radius] = Math.exp(-(i * i) / (2 * sigma * sigma));
    sum += kernel[i + radius];
  }
  for (let i = 0; i < kernel.length; i++) kernel[i] /= sum;
  const across = new Float32Array(input.length);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) {
      let v = 0;
      for (let k = -radius; k <= radius; k++) {
        const sx = x + k;
        if (sx >= 0 && sx < WIDTH) v += input[y * WIDTH + sx] * kernel[k + radius];
      }
      across[y * WIDTH + x] = v;
    }
  }
  const down = new Float32Array(input.length);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) {
      let v = 0;
      for (let k = -radius; k <= radius; k++) {
        const sy = y + k;
        if (sy >= 0 && sy < HEIGHT) v += across[sy * WIDTH + x] * kernel[k + radius];
      }
      down[y * WIDTH + x] = v;
    }
  }
  return down;
}

/**
 * Light from a field of points: a tight core for each school and a wide halo
 * where many sit together, tone-mapped so a city burns white and a lone rural
 * school still shows as a faint blue point.
 * @param {Array<[number, number]>} points
 * @param {{ gain: number, core: number, halo: number }} weights
 * @returns {Float32Array} light in [0, 1]
 */
function light(points, { gain, core: coreWeight, halo: haloWeight }) {
  const raw = field(points);
  const core = coreWeight > 0 ? blur(raw, 0.65) : raw;
  const halo = blur(raw, 6);
  const out = new Float32Array(raw.length);
  for (let i = 0; i < raw.length; i++) {
    const v = (core[i] ?? 0) * coreWeight + (halo[i] ?? 0) * haloWeight;
    out[i] = 1 - Math.exp(-v * gain);
  }
  return out;
}

/**
 * RGBA pixels of a light field on a clear ground: blue where it is faint,
 * white where it burns.
 * @param {Float32Array} lit
 */
function rgba(lit) {
  const out = Buffer.alloc(WIDTH * HEIGHT * 4);
  for (let i = 0; i < lit.length; i++) {
    const v = Math.min(1, Math.max(0, lit[i]));
    const hot = Math.min(1, Math.max(0, (v - 0.45) / 0.55)) ** 1.5;
    for (let c = 0; c < 3; c++)
      out[i * 4 + c] = Math.round(CLOSED_BLUE[c] + (CORE_WHITE[c] - CLOSED_BLUE[c]) * hot);
    out[i * 4 + 3] = Math.round(v * 255);
  }
  return out;
}

/** The still's path data, from index.html's geo:still block. */
function stillSvg() {
  const html = readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const start = html.indexOf('<!-- geo:still:start -->');
  const end = html.indexOf('<!-- geo:still:end -->');
  if (start < 0 || end < 0) throw new Error('index.html has no geo:still block');
  const block = html.slice(start, end);
  const land = /id="still-land"[^>]*?\sd="([^"]+)"/su.exec(block)?.[1];
  const state = /class="still-state"[^>]*?\sd="([^"]+)"/su.exec(block)?.[1];
  const viewBox = /viewBox="([^"]+)"/u.exec(block)?.[1];
  if (land === undefined || state === undefined || viewBox === undefined) {
    throw new Error('index.html geo:still block has no land, state lines or viewBox');
  }
  // A hairline at the picture's size: the viewBox is STILL_WIDTH wide, the picture WIDTH.
  const hair = STILL_WIDTH / WIDTH;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${String(WIDTH)}" height="${String(HEIGHT)}" viewBox="${viewBox}" preserveAspectRatio="none">` +
    `<rect x="0" y="0" width="100%" height="100%" fill="#000"/>` +
    `<path d="${state}" fill="none" stroke="${LINE_STATE}" stroke-width="${String(hair)}"/>` +
    `<path d="${land}" fill="none" stroke="${LINE_OUTLINE}" stroke-opacity="0.7" stroke-width="${String(hair)}"/>` +
    `</svg>`
  );
}

/**
 * Splits the schools into bands from west to east, softly: a school's band
 * is drawn by chance from the bands near it, so no seam shows between two.
 * @param {Array<[number, number]>} points
 */
function bands(points) {
  const next = random();
  /** @type {Array<Array<[number, number]>>} */
  const out = Array.from({ length: BANDS }, () => []);
  for (const point of points) {
    const at = (point[0] / WIDTH) * BANDS - 0.5;
    const jitter = (next() + next() + next() - 1.5) * 0.6;
    const band = Math.min(BANDS - 1, Math.max(0, Math.round(at + jitter)));
    out[band]?.push(point);
  }
  return out;
}

/**
 * The share card, 1200 × 630: the whole lit map from coast to coast, dimmed,
 * with the chrome wordmark and the headline from src/copy-waitlist.ts set in
 * Geist over it, centred, drawn by Playwright's Chromium (the one the e2e
 * tests use). Returns the words it drew.
 * @param {Buffer} mapPng
 * @param {Buffer} wordmarkPng
 * @param {string} file
 * @returns {Promise<{ wordmark: string, headline: string, when: string }>}
 */
async function shareCard(mapPng, wordmarkPng, file) {
  const { chromium } = await import('@playwright/test');
  const { waitlistCopy } = await import('../src/copy-waitlist.ts');
  const { copy } = await import('../src/copy.ts');
  const font = readFileSync(
    path.join(WEB, 'node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2'),
  );
  /** @param {string} text */
  const escape = (text) =>
    text.replace(
      /[&<>"]/gu,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c,
    );
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: Geist; src: url(data:font/woff2;base64,${font.toString('base64')}) format('woff2'); font-weight: 100 900; }
html, body { margin: 0; width: 1200px; height: 630px; background: #000; overflow: hidden; }
body { position: relative; font-family: Geist; color: #f5f5f5; -webkit-font-smoothing: antialiased; }
.map { position: absolute; left: 30px; top: 8px; width: 1140px; opacity: 0.95;
  -webkit-mask-image: radial-gradient(closest-side, #000 70%, transparent); }
.shade { position: absolute; inset: 0; background: radial-gradient(ellipse 620px 300px at 50% 52%, rgb(0 0 0 / 0.74), rgb(0 0 0 / 0.5) 60%, rgb(0 0 0 / 0.08)); }
.mark { position: absolute; left: 50%; top: 58px; width: 820px; transform: translateX(-50%); }
h1 { position: absolute; left: 50%; top: 292px; width: 980px; transform: translateX(-50%); text-align: center; text-wrap: balance; margin: 0; font-size: 64px; font-weight: 600; line-height: 1.06; letter-spacing: -0.035em; }
p { position: absolute; left: 0; right: 0; top: 470px; text-align: center; margin: 0; font-size: 30px; color: #b5b5b5; letter-spacing: -0.01em; }
</style></head><body>
<img class="map" src="data:image/png;base64,${mapPng.toString('base64')}">
<div class="shade"></div>
<img class="mark" alt="${escape(copy.appName)}" src="data:image/png;base64,${wordmarkPng.toString('base64')}">
<h1>${escape(waitlistCopy.headline)}</h1>
<p>${escape(waitlistCopy.when)}</p>
</body></html>`;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 630 },
      deviceScaleFactor: 1,
    });
    await page.setContent(html, { waitUntil: 'load' });
    await page.evaluate('document.fonts.ready.then(() => undefined)');
    const shot = await page.screenshot({ type: 'png' });
    const { size } = await sharp(shot)
      .jpeg({ quality: 85, mozjpeg: true, chromaSubsampling: '4:4:4' })
      .toFile(file);
    if (size > SOCIAL_MAX_BYTES) {
      throw new Error(`the share card is ${String(size)} bytes, over ${String(SOCIAL_MAX_BYTES)}`);
    }
  } finally {
    await browser.close();
  }
  return { wordmark: copy.appName, headline: waitlistCopy.headline, when: waitlistCopy.when };
}

async function main() {
  const args = process.argv.slice(2);
  const pointsFile = args[0];
  if (pointsFile === undefined) {
    throw new Error('usage: build-waitlist-art.mjs <points.bin> [--out <dir>]');
  }
  const outIndex = args.indexOf('--out');
  const outDir =
    outIndex >= 0 ? path.resolve(args[outIndex + 1] ?? '') : path.join(WEB, 'src/waitlist/art');
  mkdirSync(outDir, { recursive: true });

  const points = schoolPixels(readFileSync(pointsFile));
  const webp = { quality: 70, alphaQuality: 80, effort: 6, smartSubsample: true };

  // The map: lines, and every school lit softly.
  const ground = await sharp(Buffer.from(stillSvg())).removeAlpha().raw().toBuffer();
  const base = rgba(light(points, { gain: 0.5, core: 1.4, halo: 3 }));
  const map = Buffer.alloc(WIDTH * HEIGHT * 3);
  for (let i = 0; i < WIDTH * HEIGHT; i++) {
    const a = (base[i * 4 + 3] ?? 0) / 255;
    for (let c = 0; c < 3; c++) {
      map[i * 3 + c] = Math.round((ground[i * 3 + c] ?? 0) * (1 - a) + (base[i * 4 + c] ?? 0) * a);
    }
  }
  const mapImage = sharp(map, { raw: { width: WIDTH, height: HEIGHT, channels: 3 } });
  await mapImage
    .clone()
    .webp({ quality: 74, effort: 6, smartSubsample: true })
    .toFile(path.join(outDir, 'map.webp'));
  // For phones: what a phone's screen shows of the map needs about this many pixels.
  await mapImage
    .clone()
    .resize(SMALL_WIDTH)
    .webp({ quality: 72, effort: 6, smartSubsample: true })
    .toFile(path.join(outDir, 'map-small.webp'));
  const mapPng = await mapImage.clone().png().toBuffer();

  // The sweep: each band brighter, on a clear ground.
  for (const [index, band] of bands(points).entries()) {
    // Halo only, and at half size: a soft band of light over the points, which the map draws.
    await sharp(rgba(light(band, { gain: 0.9, core: 0, halo: 12 })), {
      raw: { width: WIDTH, height: HEIGHT, channels: 4 },
    })
      .resize(SWEEP_WIDTH)
      .webp(webp)
      .toFile(path.join(outDir, `sweep-${String(index)}.webp`));
  }
  const wordmarkPng = await sharp(path.join(outDir, 'chrome-wordmark.webp')).png().toBuffer();
  const social = await shareCard(mapPng, wordmarkPng, path.join(outDir, 'social.jpg'));
  writeFileSync(
    path.join(outDir, 'art.json'),
    `${JSON.stringify({ width: WIDTH, height: HEIGHT, bands: BANDS, schools: points.length, social }, null, 2)}\n`,
  );
  process.stdout.write(
    `build-waitlist-art: ${String(points.length)} schools, ${String(WIDTH)}×${String(HEIGHT)}, ${String(BANDS)} bands -> ${outDir}\n`,
  );
}

const invoked = process.argv[1];
if (invoked !== undefined && path.resolve(invoked) === fileURLToPath(import.meta.url)) {
  main().catch((/** @type {unknown} */ error) => {
    process.stderr.write(
      `build-waitlist-art: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`,
    );
    process.exitCode = 1;
  });
}
