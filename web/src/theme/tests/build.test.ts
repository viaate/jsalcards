// @vitest-environment node
/**
 * What the built site carries of the themes (vite.config.ts), with a
 * stand-in theme waiting for approval listed and a shop that lists the
 * themes, as the game lane will mount one (stand-in-build.mjs):
 *
 * - a default build carries nothing of a waiting theme, in no file, source
 *   maps included: not its name, not its palette, not its module;
 * - no script a device runs before it opens the shop carries any theme's
 *   palette, and the shop's, which does, is in a folder the service worker
 *   does not precache, as Snowball's style sheet is: a device on another
 *   theme never downloads Snowball's palette;
 * - a build that previews the waiting theme carries it, so none of this
 *   passes for want of the stand-in.
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { THEMES } from '../themes';

const ID = 'next-frost';
const MARK = '#fa57e1';
/** Colors only Snowball's palette has, and Aurora's. */
const SNOWBALL_ONLY = [THEMES.snowball.tokens.surface1, THEMES.snowball.tokens.border1];
const AURORA_ONLY = [THEMES.aurora.tokens.accent, THEMES.aurora.tokens.surface1];

const root = mkdtempSync(join(tmpdir(), 'snowlight-theme-build-'));

interface Built {
  readonly dir: string;
  /** Every file, by its path in the build. */
  readonly files: ReadonlyMap<string, string>;
}

function built(mode: 'default' | 'preview'): Built {
  const dir = join(root, mode);
  const env: NodeJS.ProcessEnv = { ...process.env, SNOWLIGHT_DATA: 'none' };
  delete env.VITEST;
  delete env.VITE_THEMES_PREVIEW;
  const run = spawnSync(
    process.execPath,
    [join(import.meta.dirname, 'stand-in-build.mjs'), dir, mode],
    { env, encoding: 'utf8' },
  );
  if (run.status !== 0) throw new Error(`The ${mode} build failed:\n${run.stdout}\n${run.stderr}`);
  const files = new Map<string, string>();
  for (const entry of readdirSync(dir, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile() || /\.(?:png|ico|woff2?|pmtiles)$/.test(entry.name)) continue;
    const path = join(entry.parentPath, entry.name);
    files.set(path.slice(dir.length + 1), readFileSync(path, 'utf8'));
  }
  return { dir, files };
}

/** The modules a source map names. */
function sources(map: string): string[] {
  return (JSON.parse(map) as { sources: string[] }).sources;
}

let plain: Built;
let preview: Built;

beforeAll(() => {
  plain = built('default');
  preview = built('preview');
}, 240_000);

afterAll(() => {
  rmSync(root, { recursive: true, force: true });
});

describe('a default build', () => {
  it('carries nothing of a theme waiting for approval, source maps included', () => {
    expect(plain.files.size).toBeGreaterThan(20);
    for (const [name, text] of plain.files) {
      expect(text.includes(ID), name).toBe(false);
      expect(text.toLowerCase().includes(MARK), name).toBe(false);
      if (name.endsWith('.map'))
        expect(
          sources(text).filter((source) => source.endsWith('theme/unreleased.ts')),
          name,
        ).toEqual([]);
    }
  });

  it('carries the themes’ palettes only in the shop’s script, which no worker precaches', () => {
    const scripts = [...plain.files].filter(([name]) => name.endsWith('.js'));
    const palettes = scripts
      .filter(([, text]) =>
        [...SNOWBALL_ONLY, ...AURORA_ONLY].some((color) => text.includes(color)),
      )
      .map(([name]) => name);
    // The shop's script alone, in the themes' own folder: never the page's, never the engine's.
    expect(palettes).toEqual([expect.stringMatching(/^assets\/themes\/shop-[\w-]+\.js$/)]);
    expect(scripts.map(([name]) => name)).toContainEqual(
      expect.stringMatching(/^assets\/engine-[\w-]+\.js$/),
    );
    const worker = plain.files.get('sw.js') ?? '';
    expect(worker).toMatch(/assets\/engine-[\w-]+\.js/);
    expect(worker).not.toMatch(/assets\/themes\//);
    // Snowball's rules are in its own style sheet alone, also outside what the worker precaches.
    const sheets = [...plain.files]
      .filter(([name, text]) => !name.endsWith('.map') && text.includes("[data-theme='snowball']"))
      .map(([name]) => name);
    expect(sheets).toEqual([expect.stringMatching(/^assets\/themes\/snowball-[\w-]+\.css$/)]);
  });
});

describe('a build that previews the waiting theme', () => {
  it('carries it: the default build leaves out what is there to leave', () => {
    const carrying = [...preview.files]
      .filter(([name, text]) => name.endsWith('.js') && text.includes(ID))
      .map(([name]) => name);
    expect(carrying.length).toBeGreaterThan(0);
    expect(
      [...preview.files].some(
        ([name, text]) =>
          name.endsWith('.map') &&
          sources(text).some((source) => source.endsWith('theme/unreleased.ts')),
      ),
    ).toBe(true);
  });
});
