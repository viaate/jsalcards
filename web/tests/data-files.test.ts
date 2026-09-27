import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { dataFilesModule, listDataFiles, removeUnpublished } from '../tools/data-files';

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
});
