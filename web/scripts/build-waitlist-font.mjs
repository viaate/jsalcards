#!/usr/bin/env node
// @ts-check
/**
 * The waitlist page's own cut of Geist: `npm run build:waitlist-font`.
 *
 * The waitlist sets its words in Geist, inline in the page (tools/waitlist.ts
 * puts this file into index.html as a data: address), so its first paint is
 * already in Geist and no web font arrives later to move a line. To keep the
 * page small the cut holds only what the page can show: printable ASCII (the
 * page's words and anything typed into its fields), the no-break space, the
 * curly apostrophe and the ellipsis, at the two weights the page uses, 400 to
 * 600 on the variable axis. Any other character falls back to the site's own
 * Geist file.
 *
 * Made from the Geist file the site already ships (@fontsource-variable/geist,
 * SIL Open Font License 1.1) with fonttools, run by uvx at a pinned version.
 * The same input gives the same bytes.
 *
 * Writes src/waitlist/art/geist-waitlist.woff2.
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, '..');
const SOURCE = path.join(
  WEB,
  'node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2',
);
const OUT = path.join(WEB, 'src/waitlist/art/geist-waitlist.woff2');
const FONTTOOLS = 'fonttools[woff]==4.55.3';
/** What the cut holds; index.html's @font-face for it names the same range. */
const UNICODES = 'U+0020-007E,U+00A0,U+2019,U+2026';

/** @param {string[]} args */
function fonttools(args) {
  // A fixed date for the font's own modified time, so the same input gives the same bytes.
  const run = spawnSync('uvx', ['--from', FONTTOOLS, ...args], {
    stdio: 'inherit',
    env: { ...process.env, SOURCE_DATE_EPOCH: '0' },
  });
  if (run.status !== 0) {
    process.stderr.write(`build-waitlist-font: ${args[0]} failed\n`);
    process.exit(1);
  }
}

const work = mkdtempSync(path.join(os.tmpdir(), 'waitlist-font-'));
try {
  const subset = path.join(work, 'subset.woff2');
  fonttools([
    'pyftsubset',
    SOURCE,
    `--unicodes=${UNICODES}`,
    '--layout-features=kern,liga,calt',
    '--flavor=woff2',
    `--output-file=${subset}`,
  ]);
  fonttools(['fonttools', 'varLib.instancer', subset, 'wght=400:600', '-o', OUT]);
} finally {
  rmSync(work, { recursive: true, force: true });
}
process.stdout.write(
  `build-waitlist-font: wrote ${path.relative(WEB, OUT)}, ${String(statSync(OUT).size)} bytes\n`,
);
