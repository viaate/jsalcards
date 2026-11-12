#!/usr/bin/env node
// @ts-check
/**
 * The phone pictures of the getsnowlight landing (get/index.html), from the one list that names
 * them, get/phones.json: each slot's picture (`from`, an app screen already in Apple's iPhone
 * bezel, under the design folder given here) is written to get/img/<file> as WebP at `width`
 * pixels, twice the width the page shows it at, and to get/img/<file3x> at `width3x`, as near
 * three times as the source allows (never wider than it). To show another set, change `from` in the list
 * and run this again; the page reads the file names from the same list (tools/get-page.ts).
 *
 * Usage: node scripts/build-get-phones.mjs <design folder>
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const from = process.argv[2];
if (from === undefined) {
  console.error('usage: node scripts/build-get-phones.mjs <design folder>');
  process.exit(2);
}
/** @type {Record<string, { from: string, file: string, width: number, file3x: string, width3x: number }>} */
const phones = JSON.parse(readFileSync(path.join(WEB, 'get', 'phones.json'), 'utf8'));
for (const [slot, phone] of Object.entries(phones)) {
  for (const [file, width] of [
    [phone.file, phone.width],
    [phone.file3x, phone.width3x],
  ]) {
    const out = path.join(WEB, 'get', 'img', file);
    const info = await sharp(path.join(from, phone.from))
      .resize({ width, withoutEnlargement: true })
      .webp({ quality: 78, alphaQuality: 90, effort: 6 })
      .toFile(out);
    console.log(
      `${slot}: ${file} ${String(info.width)}x${String(info.height)} ${String(info.size)} B`,
    );
  }
}
