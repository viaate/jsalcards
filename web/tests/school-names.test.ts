import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { directoryNames, schoolNamesModule, stagedNameFixes } from '../tools/school-names';

let folder = '';

afterEach(() => {
  if (folder !== '') rmSync(folder, { recursive: true, force: true });
  folder = '';
});

/** points.bin for schools in `districts` (their district positions, -1 for none). */
function points(districts: readonly number[], districtCount: number): Uint8Array {
  const bytes = new Uint8Array(16 + 13 * districts.length);
  const view = new DataView(bytes.buffer);
  bytes.set(new TextEncoder().encode('SLPT'));
  view.setUint16(4, 1, true);
  view.setUint16(6, 13, true);
  view.setUint32(8, districts.length, true);
  view.setUint32(12, districtCount, true);
  districts.forEach((d, i) => {
    view.setUint32(16 + 13 * i + 8, d < 0 ? 0xffffffff : d, true);
  });
  return bytes;
}

const META = {
  ids: ['290061203286', 'A1902690'],
  names: ['ELEMENTARY SCHOOL', 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS'],
  districts: { ids: ['2900612'], names: ['CITIZENS OF THE WORLD CHARTER'] },
};

describe('the school names a build ships', () => {
  it('are read from the staged directory, under its hashed names', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-school-names-'));
    mkdirSync(path.join(folder, 'schools'));
    writeFileSync(path.join(folder, 'schools/meta.0123456789.json'), JSON.stringify(META));
    writeFileSync(path.join(folder, 'schools/points.0123456789.bin'), points([0, -1], 1));
    const fixes = stagedNameFixes(folder);
    expect(fixes.schools).toEqual({
      '290061203286': { district: 'Citizens of the World Charter' },
    });
    const source = schoolNamesModule(fixes);
    expect(source).toContain('export const SCHOOL_NAME_FIXES = Object.freeze(');
    expect(source).toContain('"290061203286":{"district":"Citizens of the World Charter"}');
    expect(source).toContain('export const DISTRICT_NAME_FIXES = Object.freeze({});');
  });

  it('are none with nothing staged, or a directory whose files do not match', () => {
    folder = mkdtempSync(path.join(tmpdir(), 'snowlight-school-names-'));
    expect(stagedNameFixes(folder)).toEqual({ schools: {}, districts: {} });
    expect(directoryNames(META, points([0], 1))).toBeNull();
    expect(directoryNames({ ids: [] }, points([], 0))).toBeNull();
    expect(directoryNames(META, points([0, 5], 1))?.districtOf).toEqual(Int32Array.from([0, -1]));
  });
});
