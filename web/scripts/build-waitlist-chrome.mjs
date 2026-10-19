#!/usr/bin/env node
// @ts-check
/* global document -- the functions given to page.evaluate run in Chromium's page */
/**
 * The waitlist page's chrome lettering: `npm run build:waitlist-chrome -- <inter-900.woff2>`.
 *
 * The teaser video's SNOWLIGHT reveal sets the name in polished chrome
 * balloon letters (Inter Black, an extruded stack for depth, a vertical
 * chrome gradient, a bevel of specular light, a soft under-glow). This draws
 * the same lettering with Playwright's Chromium, once, into transparent
 * pictures, so the page shows it without a font file, a filter or a script:
 *
 * - chrome-wordmark.webp, chrome-wordmark-small.webp  SNOWLIGHT, the page's
 *   hero, for wide screens and for phones;
 * - chrome-headline.webp, chrome-headline-small.webp  the headline in the
 *   same lettering, broken into lines for wide screens and for phones (the
 *   look a VITE_WAITLIST_HEADLINE=chrome build shows; the default sets the
 *   headline as text);
 * - chrome.json  what each picture says and its size, which the build reads
 *   to reserve each picture's box and the tests check against the copy.
 *
 * The words come from src/copy.ts and src/copy-waitlist.ts. The page keeps
 * the real words as text for screen readers and search.
 *
 * The font is Inter at weight 900 (SIL Open Font License 1.1), the teaser's
 * own: @fontsource/inter 5.1.0, files/inter-latin-900-normal.woff2. It is
 * drawn into the pictures, never shipped.
 *
 * Usage: node scripts/build-waitlist-chrome.mjs <inter-latin-900-normal.woff2> [--out <dir>]
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');

/** The lettering's size in the drawing; each picture is scaled down from it. */
const SIZE = 240;
/** Clear room around the letters for the glow and the bevel, in drawing pixels. */
const PAD = Math.round(SIZE * 0.14);

/**
 * The pictures: what they say, how wide the lines may run (in drawing
 * pixels at SIZE) and the widths they are written at.
 * @type {ReadonlyArray<{ name: string; text: 'wordmark' | 'headline'; measure: number; widths: Readonly<Record<string, number>> }>}
 */
const PIECES = [
  // Also the share card's wordmark (scripts/build-waitlist-art.mjs).
  { name: 'wordmark', text: 'wordmark', measure: Infinity, widths: { '': 1600, '-small': 1000 } },
  // Wide screens: two lines, as the text headline breaks at 1024 px and up.
  { name: 'headline', text: 'headline', measure: SIZE * 15.5, widths: { '': 1800 } },
  // Phones: short lines, so the letters stay big on a narrow screen.
  { name: 'headline-small', text: 'headline', measure: SIZE * 8.4, widths: { '': 960 } },
];

/**
 * The teaser's Chrome lettering (video/promo/src/ui.tsx Chrome), as SVG
 * markup for one or more lines, with its glint left out: the page runs its
 * own. Line boxes are SIZE * 1.45 tall and LINE apart.
 * @param {string[]} lines
 * @param {number} width
 */
function chromeSvg(lines, width) {
  const size = SIZE;
  const lineGap = Math.round(size * 1.08);
  const h = Math.round(size * 1.45) + lineGap * (lines.length - 1);
  const depth = Math.max(6, Math.round(size / 13));
  // The teaser's depth: one layer a pixel apart for every 13 pixels of size.
  const step = 1;
  const font = `font-family: Inter; font-weight: 900; font-size: ${String(size)}px; letter-spacing: -0.03em;`;
  /** @param {string} s */
  const esc = (s) =>
    s.replace(
      /[&<>"]/gu,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c,
    );
  let defs = `
    <linearGradient id="chrome" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/><stop offset="0.28" stop-color="#f1f5f8"/>
      <stop offset="0.47" stop-color="#a9b2bb"/><stop offset="0.5" stop-color="#3a4048"/>
      <stop offset="0.56" stop-color="#1c2026"/><stop offset="0.68" stop-color="#8d97a1"/>
      <stop offset="0.84" stop-color="#f3f6f9"/><stop offset="1" stop-color="#c3cad1"/>
    </linearGradient>
    <linearGradient id="side" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#5b636c"/><stop offset="1" stop-color="#0d0f12"/>
    </linearGradient>
    <filter id="soft"><feGaussianBlur stdDeviation="${String(size / 30)}"/></filter>`;
  let body = '';
  lines.forEach((line, index) => {
    const base = Math.round(size * 1.05) + lineGap * index;
    const top = lineGap * index;
    defs += `
    <filter id="bevel${String(index)}" x="-5%" y="-20%" width="110%" height="140%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="${String(size / 45)}" result="blur"/>
      <feSpecularLighting in="blur" surfaceScale="${String(size / 28)}" specularConstant="1.25" specularExponent="22" lighting-color="#ffffff" result="spec">
        <fePointLight x="${String(width * 0.3)}" y="${String(top - size * 0.6)}" z="${String(size * 2.2)}"/>
      </feSpecularLighting>
      <feComposite in="spec" in2="SourceAlpha" operator="in" result="specIn"/>
      <feComposite in="SourceGraphic" in2="specIn" operator="arithmetic" k1="0" k2="1" k3="0.9" k4="0"/>
    </filter>`;
    const t = esc(line);
    const x = width / 2;
    for (let i = 0; i < depth; i++) {
      body += `<text x="${String(x + (i + 1) * 0.35 * step)}" y="${String(base + (i + 1) * 1.15 * step)}" text-anchor="middle" fill="url(#side)" style="${font}">${t}</text>`;
    }
    body += `<text x="${String(x)}" y="${String(base)}" text-anchor="middle" fill="#9fb4c6" opacity="0.25" filter="url(#soft)" style="${font}">${t}</text>`;
    // The teaser's bright rim, drawn under the face so only its outer half shows: drawn over
    // it, it also traced the font's overlapping outlines inside the letters.
    body += `<text x="${String(x)}" y="${String(base)}" text-anchor="middle" fill="none" stroke="rgba(255,255,255,0.55)" stroke-width="${String(Math.max(2, size / 55))}" style="${font}">${t}</text>`;
    body += `<text x="${String(x)}" y="${String(base)}" text-anchor="middle" fill="url(#chrome)" filter="url(#bevel${String(index)})" style="${font}">${t}</text>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${String(width)}" height="${String(h)}" viewBox="0 0 ${String(width)} ${String(h)}" style="overflow: visible"><defs>${defs}</defs><g id="all">${body}</g></svg>`;
}

/**
 * Breaks words into lines no wider than `measure`, as a person would set
 * them: greedily, then evened out so the last line is not left short.
 * @param {string[]} words
 * @param {number} measure
 * @param {(text: string) => number} widthOf
 */
export function breakLines(words, measure, widthOf) {
  if (!Number.isFinite(measure)) return [words.join(' ')];
  /** @param {number} limit */
  const greedy = (limit) => {
    /** @type {string[]} */
    const lines = [];
    let line = '';
    for (const word of words) {
      const next = line === '' ? word : `${line} ${word}`;
      if (line !== '' && widthOf(next) > limit) {
        lines.push(line);
        line = word;
      } else line = next;
    }
    if (line !== '') lines.push(line);
    return lines;
  };
  const first = greedy(measure);
  // The narrowest measure that keeps the same number of lines balances them.
  let best = first;
  for (let limit = measure; limit > measure * 0.5; limit -= measure / 100) {
    const lines = greedy(limit);
    if (lines.length !== first.length) break;
    best = lines;
  }
  return best;
}

async function main() {
  const args = process.argv.slice(2);
  const fontFile = args[0];
  if (fontFile === undefined) {
    throw new Error(
      'usage: build-waitlist-chrome.mjs <inter-latin-900-normal.woff2> [--out <dir>]',
    );
  }
  const outIndex = args.indexOf('--out');
  const outDir =
    outIndex >= 0 ? path.resolve(args[outIndex + 1] ?? '') : path.join(WEB, 'src/waitlist/art');
  mkdirSync(outDir, { recursive: true });

  const { chromium } = await import('@playwright/test');
  const { waitlistCopy } = await import('../src/copy-waitlist.ts');
  const { copy } = await import('../src/copy.ts');
  const texts = {
    wordmark: copy.appName.toLocaleUpperCase('en-US'),
    headline: waitlistCopy.headline,
  };
  const font = readFileSync(fontFile).toString('base64');

  const browser = await chromium.launch();
  /** @type {Record<string, unknown>} */
  const manifest = { size: SIZE, font: 'Inter 900 (@fontsource/inter 5.1.0)' };
  try {
    const page = await browser.newPage({
      viewport: { width: 4000, height: 2000 },
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: Inter; font-weight: 900; src: url(data:font/woff2;base64,${font}) format('woff2'); }
html, body { margin: 0; background: transparent; }
#stage { position: absolute; left: 0; top: 0; }
</style></head><body><div id="stage"></div></body></html>`,
    );
    await page.evaluate(`document.fonts.load("900 ${String(SIZE)}px Inter")`);
    /** @param {string} text */
    const widthOf = async (text) =>
      /** @type {number} */ (
        await page.evaluate(
          ([t, s]) => {
            const c = document.createElement('canvas').getContext('2d');
            if (c === null) throw new Error('no canvas');
            c.font = `900 ${String(s)}px Inter`;
            c.letterSpacing = `${String(Number(s) * -0.03)}px`;
            return c.measureText(String(t)).width;
          },
          [text, SIZE],
        )
      );

    for (const piece of PIECES) {
      const words = texts[piece.text].split(' ');
      /** @type {Map<string, number>} */
      const widths = new Map();
      for (let i = 0; i < words.length; i++) {
        for (let j = i + 1; j <= words.length; j++) {
          const t = words.slice(i, j).join(' ');
          widths.set(t, await widthOf(t));
        }
      }
      const lines = breakLines(words, piece.measure, (t) => widths.get(t) ?? Infinity);
      const widest = Math.max(...lines.map((l) => widths.get(l) ?? 0));
      const width = Math.ceil(widest + PAD * 2 + SIZE * 0.2);
      await page.evaluate(
        ([svg]) => {
          const stage = document.getElementById('stage');
          if (stage !== null) stage.innerHTML = String(svg);
        },
        [chromeSvg(lines, width)],
      );
      const box = /** @type {{ x: number; y: number; width: number; height: number }} */ (
        await page.evaluate(() => {
          const all = /** @type {SVGGElement | null} */ (document.getElementById('all'));
          if (all === null) throw new Error('no drawing');
          const b = all.getBBox();
          return { x: b.x, y: b.y, width: b.width, height: b.height };
        })
      );
      const clip = {
        x: Math.max(0, Math.floor(box.x - PAD)),
        y: Math.max(0, Math.floor(box.y - PAD * 0.6)),
        width: Math.ceil(box.width + PAD * 2),
        height: Math.ceil(box.height + PAD * 1.2),
      };
      const shot = await page.screenshot({ type: 'png', omitBackground: true, clip });
      /** @type {Record<string, { file: string; width: number; height: number }>} */
      const files = {};
      for (const [suffix, w] of Object.entries(piece.widths)) {
        const file = `chrome-${piece.name}${suffix}.webp`;
        const h = Math.round((clip.height * w) / clip.width);
        await sharp(shot)
          .resize(w, h, { kernel: 'lanczos3' })
          .webp({ quality: 74, alphaQuality: 85, effort: 6, smartSubsample: true })
          .toFile(path.join(outDir, file));
        files[suffix === '' ? 'large' : 'small'] = { file, width: w, height: h };
      }
      manifest[piece.name] = { text: texts[piece.text], lines, ...files };
    }
  } finally {
    await browser.close();
  }
  // Set out as the repository's Prettier sets JSON, so the file passes its format check.
  const prettier = await import('prettier');
  const manifestFile = path.join(outDir, 'chrome.json');
  const options = (await prettier.resolveConfig(path.join(WEB, 'package.json'))) ?? {};
  writeFileSync(
    manifestFile,
    await prettier.format(JSON.stringify(manifest, null, 2), { ...options, parser: 'json' }),
  );
  process.stdout.write(`build-waitlist-chrome: wrote ${outDir}\n`);
}

const invoked = process.argv[1];
if (invoked !== undefined && path.resolve(invoked) === fileURLToPath(import.meta.url)) {
  main().catch((/** @type {unknown} */ error) => {
    process.stderr.write(
      `build-waitlist-chrome: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`,
    );
    process.exitCode = 1;
  });
}
