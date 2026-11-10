#!/usr/bin/env node
// @ts-check
/**
 * The share card's sample pictures: `npm run cards:samples -- <dir> [design dir] [--hinting]`.
 *
 * Renders every sample card (src/ui/tests/share-card-samples.ts: the design's
 * seven and the cards it did not sample) from the site's own code, in Chromium
 * with the site's face: starts Vite's dev server, opens a page on it, adds the
 * Geist file as a FontFace, imports src/ui/share-card.ts and writes each card's
 * PNG into <dir> as the page makes it (renderCard). Prints each card's figures
 * (K, the big line's size and lines, the ticks' height, the crystal's arm, the
 * lines left out) and every line that ends cut or reaches past the right edge.
 * With a second folder (the design's own pictures, named as the samples are),
 * each of the design's samples is also pasted beside its picture as
 * <dir>/pair-<name>.png. With --hinting, Chromium sets type as it does on
 * desktop Linux and in the test suite, each advance fitted to a whole pixel,
 * to look at the cards as such a browser draws them. The pictures are proof
 * for the eye and are never committed: every school, status and chance in
 * them is made up.
 */
/* global FontFace, btoa, document, location, window -- the page's own, inside page.evaluate */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';
import sharp from 'sharp';
import { createServer } from 'vite';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FONT = '/node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2';

const args = process.argv.slice(2);
const hinting = args.includes('--hinting');
const [out, design] = args.filter((arg) => arg !== '--hinting');
if (out === undefined) {
  console.error('usage: npm run cards:samples -- <dir> [design dir] [--hinting]');
  process.exit(2);
}
mkdirSync(out, { recursive: true });

const server = await createServer({
  root: WEB,
  logLevel: 'error',
  server: { port: 0, host: '127.0.0.1', strictPort: false },
});
await server.listen();
const address = server.httpServer?.address();
if (address === null || address === undefined || typeof address === 'string') {
  throw new Error('no dev server address');
}
const origin = `http://127.0.0.1:${String(address.port)}`;
// Letters as a phone or a Mac sets them, at their own widths: this Chromium on Linux would
// otherwise fit each letter's advance to a whole pixel (font hinting), which no phone does.
const browser = await chromium.launch({ args: hinting ? [] : ['--font-render-hinting=none'] });
let failed = false;
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  page.on('pageerror', (error) => {
    failed = true;
    console.error('PAGE ERROR', error.message);
  });
  // The privacy page: the site's own origin and style, without the app starting.
  await page.goto(`${origin}/privacy.html`);
  const names = await page.evaluate(async (font) => {
    const face = new FontFace('Geist Variable', `url(${font})`, { weight: '100 900' });
    document.fonts.add(await face.load());
    const samples = await import(
      /* @vite-ignore */ `${location.origin}/src/ui/tests/share-card-samples.ts`
    );
    const card = await import(/* @vite-ignore */ `${location.origin}/src/ui/share-card.ts`);
    Object.assign(window, { __samples: samples.SAMPLES, __card: card });
    return samples.SAMPLES.map((/** @type {{ name: string }} */ sample) => sample.name);
  }, FONT);
  for (const [index, name] of names.entries()) {
    const made = await page.evaluate(async (at) => {
      const { __samples: samples, __card: card } = /** @type {any} */ (window);
      const { kind, model, designed } = samples[at];
      const blob = await card.renderCard(model, kind);
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      }
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      let measured = 0;
      const face = card.canvasFace(ctx);
      const layout = card.layoutCard(
        model,
        kind,
        (/** @type {string} */ text, /** @type {number} */ weight) => {
          measured++;
          return face(text, weight);
        },
      );
      return {
        png: btoa(binary),
        kind,
        designed,
        figures: {
          K: layout.K,
          big: layout.big.size,
          lines: layout.big.lines,
          ticks: layout.ticks?.height ?? 0,
          arm: Math.round(layout.art.r),
          crystal: layout.art.crystal,
          left_out: layout.dropped,
          measured,
        },
        sizes: Object.fromEntries(
          ['name', 'season', 'place', 'reason', 'words', 'more'].map((role) => {
            const runs = layout.runs.filter(
              (/** @type {{ role: string }} */ run) => run.role === role,
            );
            return [
              role,
              runs.length === 0 ? null : `${String(runs[0].size)}x${String(runs.length)}`,
            ];
          }),
        ),
        season: layout.runs
          .filter((/** @type {{ role: string }} */ run) => run.role === 'season')
          .map((/** @type {{ text: string }} */ run) => run.text),
        cut: layout.runs
          .filter((/** @type {{ text: string }} */ run) => run.text.endsWith('…'))
          .map(
            (/** @type {{ role: string, text: string, size: number }} */ run) =>
              `${run.role} ${String(run.size)}: ${run.text}`,
          ),
        past: layout.runs
          .filter((/** @type {{ x: number, width: number }} */ run) => run.x + run.width > 996.05)
          .map((/** @type {{ role: string, text: string }} */ run) => `${run.role}: ${run.text}`),
      };
    }, index);
    const file = path.join(out, `${name}.png`);
    writeFileSync(file, Buffer.from(made.png, 'base64'));
    console.log(name.padEnd(30), JSON.stringify(made.figures), JSON.stringify(made.sizes));
    if (made.season.length > 1) console.log('   SEASON', JSON.stringify(made.season));
    for (const line of made.cut) console.log('   CUT', line);
    for (const line of made.past) {
      failed = true;
      console.log('   PAST 996', line);
    }
    const drawn = design === undefined ? null : path.join(design, `${name}.png`);
    if (made.designed && drawn !== null && existsSync(drawn)) {
      // The design's picture on the left, the built card on the right, a gap of the page between.
      const { width = 1080, height = 1920 } = await sharp(file).metadata();
      await sharp({
        create: { width: width * 2 + 40, height, channels: 3, background: '#0d0e12' },
      })
        .composite([
          {
            input: await sharp(drawn).resize(width, height, { fit: 'fill' }).toBuffer(),
            left: 0,
            top: 0,
          },
          { input: file, left: width + 40, top: 0 },
        ])
        .png()
        .toFile(path.join(out, `pair-${name}.png`));
    }
  }
} finally {
  await browser.close();
  await server.close();
}
process.exit(failed ? 1 : 0);
