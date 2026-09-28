import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import type { Plugin } from 'vite';

import {
  clashingFiles,
  dataFiles,
  dataFilesModule,
  listDataFiles,
  listedDataFiles,
  removeUnpublished,
} from '../tools/data-files';

let folder = '';

afterEach(() => {
  if (folder !== '') rmSync(folder, { recursive: true, force: true });
  folder = '';
});

describe('the data files a build ships', () => {
  it('are every staged file, by its path under data/, without the pipeline’s own records', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-data-files-'));
    mkdirSync(path.join(folder, 'schools'));
    mkdirSync(path.join(folder, 'live'));
    for (const file of [
      'schools/meta.json',
      'schools/points.bin',
      'schools/manifest.internal.json',
      'live/closings.json',
      'search-index.bin',
      '.DS_Store',
    ]) {
      writeFileSync(path.join(folder, file), '');
    }
    expect(listDataFiles(folder)).toEqual([
      'live/closings.json',
      'schools/meta.json',
      'schools/points.bin',
      'search-index.bin',
    ]);
  });

  it('are listed for the page by name, all but the school detail shards, which their index names', () => {
    expect(
      listedDataFiles([
        'live/closings.json',
        'schools/details/0.0123456789.json',
        'schools/details/461.abcdefabcd.json',
        'schools/details/index.9876543210.json',
        'schools/meta.b5c6259854.json',
      ]),
    ).toEqual([
      'live/closings.json',
      'schools/details/index.9876543210.json',
      'schools/meta.b5c6259854.json',
    ]);
  });

  it('leave the pipeline’s own records and hidden files out of the build', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-data-files-'));
    mkdirSync(path.join(folder, 'schools'));
    mkdirSync(path.join(folder, '.cache'));
    for (const file of [
      'schools/meta.json',
      'schools/manifest.internal.json',
      '.cache/points.bin',
      '.gitkeep',
      'search-index.bin',
    ]) {
      writeFileSync(path.join(folder, file), '');
    }
    expect(listDataFiles(folder, false)).toEqual([
      '.cache/points.bin',
      '.gitkeep',
      'schools/manifest.internal.json',
    ]);
    expect(removeUnpublished(folder)).toEqual([
      '.cache/points.bin',
      '.gitkeep',
      'schools/manifest.internal.json',
    ]);
    expect(existsSync(path.join(folder, '.cache'))).toBe(false);
    expect(listDataFiles(folder, false)).toEqual([]);
    expect(listDataFiles(folder)).toEqual(['schools/meta.json', 'search-index.bin']);
  });

  it('are none when nothing is staged', () => {
    expect(listDataFiles(path.join(tmpdir(), 'snowlight-no-such-folder'))).toEqual([]);
    expect(dataFilesModule([])).toBe('export const DATA_FILES = Object.freeze([]);\n');
  });

  it('fail the build when a file is staged twice under different hashes', () => {
    expect(
      clashingFiles([
        'schools/meta.0123456789.json',
        'schools/meta.9876543210.json',
        'schools/points.0123456789.bin',
        'live/closings.json',
      ]),
    ).toEqual(['schools/meta.json: schools/meta.0123456789.json, schools/meta.9876543210.json']);
    expect(clashingFiles(['schools/meta.0123456789.json', 'schools/points.bin'])).toEqual([]);
  });
});

describe('a build that ships no data', () => {
  /** The plugin's hooks as Vite calls them for a build rooted at `root`. */
  function build(root: string, ship: boolean) {
    const plugin: Plugin = dataFiles('data/', { ship });
    const call = (hook: unknown, ...args: unknown[]): unknown =>
      (hook as (...rest: unknown[]) => unknown).call(
        {
          error: (message: string) => {
            throw new Error(message);
          },
        },
        ...args,
      );
    call(plugin.configResolved, {
      publicDir: path.join(root, 'public'),
      root,
      base: '/',
      build: { outDir: 'dist', copyPublicDir: true },
    });
    return {
      module: () => call(plugin.load, '\0virtual:snowlight/data-files') as string,
      write: () => call(plugin.writeBundle),
    };
  }

  it('lists nothing and leaves data/ out, whatever is staged', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-data-files-'));
    for (const dir of ['public/data/schools', 'dist/data/schools']) {
      mkdirSync(path.join(folder, dir), { recursive: true });
      writeFileSync(path.join(folder, dir, 'meta.0123456789.json'), '{}');
    }
    const without = build(folder, false);
    expect(without.module()).toBe(dataFilesModule([]));
    without.write();
    expect(existsSync(path.join(folder, 'dist/data'))).toBe(false);

    mkdirSync(path.join(folder, 'dist/data/schools'), { recursive: true });
    const shipped = build(folder, true);
    expect(shipped.module()).toBe(dataFilesModule(['schools/meta.0123456789.json']));
  });

  it('refuses two copies of a file', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-data-files-'));
    mkdirSync(path.join(folder, 'public/data'), { recursive: true });
    writeFileSync(path.join(folder, 'public/data/search-index.0123456789.bin'), '');
    writeFileSync(path.join(folder, 'public/data/search-index.abcdefabcd.bin'), '');
    expect(() => build(folder, true).module()).toThrow(/more than one copy/);
  });
});
