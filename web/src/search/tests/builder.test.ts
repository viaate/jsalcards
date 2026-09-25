// @vitest-environment node
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';

import { afterAll, describe, expect, it } from 'vitest';

import { loadIndex } from '../decode';
import { SearchEngine } from '../engine';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

const script = resolve(import.meta.dirname, '../../../scripts/build-search-index.mjs');
const dir = mkdtempSync(join(tmpdir(), 'snowlight-search-builder-'));

afterAll(() => {
  rmSync(dir, { recursive: true, force: true });
});

function write(name: string, lines: readonly unknown[]): string {
  const path = join(dir, name);
  writeFileSync(path, lines.map((l) => (typeof l === 'string' ? l : JSON.stringify(l))).join('\n'));
  return path;
}

function build(...args: string[]) {
  const run = spawnSync(process.execPath, [script, ...args], { encoding: 'utf8' });
  return { code: run.status, stdout: run.stdout, stderr: run.stderr };
}

const schools = write(
  'schools.jsonl',
  SYNTHETIC_RECORDS.filter((r) => r.kind === 'school' || r.kind === 'district'),
);
// SYNTHETIC rows in the shapes `snowlight places build` writes.
const cities = write('cities.jsonl', [
  {
    geoid: '4241216',
    kind: 'city',
    lat: 40.04,
    lon: -76.3,
    name: 'Lancaster',
    population: 58000,
    state: 'PA',
  },
  {
    geoid: '0640130',
    kind: 'city',
    lat: 34.69,
    lon: -118.18,
    name: 'Lancaster',
    population: 170000,
    state: 'CA',
  },
  {
    geoid: '4200001',
    kind: 'CDP',
    lat: 40.1,
    lon: -76.1,
    name: 'Synthetic Hollow',
    population: null,
    state: 'PA',
  },
]);
const zips = write('zips.jsonl', [
  { districts: [], lat: 40.07, lon: -76.31, states: ['PA'], zcta: '17601' },
  { districts: [], lat: 41.99, lon: -75.0, states: ['NY', 'PA'], zcta: '18405' },
]);

describe('build-search-index', () => {
  const out = join(dir, 'index.bin');

  it('builds a loadable index from records, cities and ZIP codes', () => {
    const run = build('--out', out, schools, cities, zips);
    expect(run.stderr).toBe('');
    expect(run.code).toBe(0);
    expect(run.stdout).toMatch(/wrote .*index\.bin: 31 records/);
    const index = loadIndex(new Uint8Array(gunzipSync(readFileSync(out))));
    expect(index.recordCount).toBe(31);
    const engine = new SearchEngine(index);
    const r = engine.search('lancaster pa');
    expect(r.cities[0]).toMatchObject({ id: '4241216', sub: 'Pennsylvania', kind: 'city' });
    expect(r.schools[0]?.sub).toBe('Lancaster, PA');
    const zip = engine.search('18405').zips[0];
    expect(zip).toMatchObject({ name: '18405', sub: 'New York, Pennsylvania', state: 'NY' });
    // A place without a population ranks, with weight 0, after those with one.
    expect(engine.search('synthetic hollow').cities[0]?.id).toBe('4200001');
  });

  it('writes the same bytes every time', () => {
    const again = join(dir, 'again.bin');
    build('--out', again, zips, cities, schools);
    expect(readFileSync(again)).toEqual(readFileSync(out));
  });

  it('checks an up-to-date index and flags a stale one', () => {
    expect(build('--check', '--out', out, schools, cities, zips).code).toBe(0);
    const stale = build('--check', '--out', out, schools, cities);
    expect(stale.code).toBe(1);
    expect(stale.stderr).toContain('is stale');
  });

  it('reads every .jsonl file in a directory', () => {
    const run = build('--json', '--out', join(dir, 'dir.bin'), dir);
    expect(run.code).toBe(0);
    const summary = JSON.parse(run.stdout) as { records: number; gzipBytes: number };
    expect(summary.records).toBe(31);
    expect(summary.gzipBytes).toBeGreaterThan(0);
  });

  it.each([
    ['not json', 'not valid JSON'],
    [{ kind: 'school', id: 'x' }, 'name must be a string'],
    [
      { geoid: '12', name: 'A', state: 'PA', lat: 0, lon: 0, population: 1 },
      'geoid must be 7 digits',
    ],
    [{ geoid: '1234567', name: 'A', state: 'PA', lat: 0, lon: 0, population: -1 }, 'population'],
    [{ zcta: '1760', states: ['PA'], lat: 0, lon: 0 }, 'zcta must be 5 digits'],
    [{ zcta: '17601', states: [], lat: 0, lon: 0 }, 'states must be'],
  ])('refuses %j and names the line', (line, message) => {
    const bad = write('bad.jsonl', ['', line]);
    const run = build('--out', join(dir, 'bad.bin'), bad);
    expect(run.code).toBe(1);
    expect(run.stderr).toContain('bad.jsonl:2');
    expect(run.stderr).toContain(message);
  });

  it('refuses duplicate records across files', () => {
    const run = build('--out', join(dir, 'dup.bin'), schools, schools);
    expect(run.code).toBe(1);
    expect(run.stderr).toContain('duplicate id');
  });

  it('refuses unknown options and empty input', () => {
    expect(build('--frobnicate').stderr).toContain('unknown option');
    const empty = write('empty.jsonl', ['']);
    expect(build('--out', join(dir, 'e.bin'), empty).stderr).toContain('no records');
  });
});
