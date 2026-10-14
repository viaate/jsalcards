// @vitest-environment node
/**
 * scripts/stage-data.mjs run whole on a tiny synthetic site-data tree (test data
 * only): the edition checks are called where staging stages, not only tested
 * as functions. `uv` is a stand-in that copies the directory's rows, as
 * scripts/directory-rows.py would write them.
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

const STAGE = path.join(import.meta.dirname, '..', 'scripts', 'stage-data.mjs');
const TIMEOUT = 60_000;

// Written as the pipeline writes meta.json: compact, keys sorted.
const META = {
  count: 2,
  districts: { ids: ['0100005'], names: ['Synthetic District'] },
  generated_on: '2026-10-13',
  ids: ['010000500870', '0000000A'],
  names: ['Synthetic Middle School', 'Synthetic Academy'],
  schema_version: 1,
  school_years: { private: '2023-24', public: '2024-25' },
};
const META_BYTES = Buffer.from(JSON.stringify(META));

/** points.bin (pipeline/snowlight/directory/points.py): a 16-byte header, 13 bytes a school. */
function pointsBytes(): Buffer {
  const bytes = Buffer.alloc(16 + 2 * 13);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(2, 8);
  bytes.writeUInt32LE(1, 12);
  const schools: [number, number, number][] = [
    [-86_100_000, 34_100_000, 0],
    [-86_110_000, 34_110_000, 0xffffffff],
  ];
  schools.forEach(([lon, lat, district], i) => {
    const at = 16 + 13 * i;
    bytes.writeInt32LE(lon, at);
    bytes.writeInt32LE(lat, at + 4);
    bytes.writeUInt32LE(district, at + 8);
    bytes.writeUInt8(0, at + 12);
  });
  return bytes;
}
const POINTS_BYTES = pointsBytes();

function sha256(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex');
}

const EDITION = Buffer.from(
  JSON.stringify({
    content_sha256: sha256(
      Buffer.concat([
        Buffer.from(
          META_BYTES.toString().replace('"generated_on":"2026-10-13"', '"generated_on":""'),
        ),
        POINTS_BYTES,
      ]),
    ),
    districts: 1,
    generated_on: '2026-10-13',
    schema_version: 1,
    schools: 2,
  }),
);

function jsonLines(rows: unknown[]): string {
  return rows.map((row) => JSON.stringify(row)).join('\n') + '\n';
}

let root = '';

function write(file: string, bytes: Buffer | string): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, bytes);
}

/** The pipeline's outputs for the synthetic directory, and a stand-in uv. */
function makeTree(edition: Buffer | null, manifestOutputs?: Record<string, unknown>): void {
  const site = path.join(root, 'site');
  write(path.join(site, 'schools/meta.json'), META_BYTES);
  write(path.join(site, 'schools/points.bin'), POINTS_BYTES);
  const tiles = Buffer.alloc(127);
  tiles.write('PMTiles', 0, 'latin1');
  tiles[7] = 3;
  tiles[99] = 1;
  write(path.join(site, 'schools/schools.pmtiles'), tiles);
  if (edition !== null) write(path.join(site, 'schools/edition.json'), edition);
  if (manifestOutputs !== undefined) {
    write(
      path.join(site, 'schools/manifest.internal.json'),
      JSON.stringify({ outputs: manifestOutputs }),
    );
  }
  write(
    path.join(site, 'search/cities.jsonl'),
    jsonLines([
      {
        geoid: '0100001',
        name: 'Synthville',
        kind: 'city',
        state: 'AL',
        lat: 34.1,
        lon: -86.1,
        population: 100,
      },
    ]),
  );
  write(
    path.join(site, 'search/zips.jsonl'),
    jsonLines([{ zcta: '35000', states: ['AL'], lat: 34.1, lon: -86.1, districts: [] }]),
  );
  const internal = path.join(root, 'internal');
  write(path.join(internal, 'schools.parquet'), '');
  write(path.join(internal, 'districts.parquet'), '');
  const school = (index: number) => ({
    index,
    id: META.ids[index],
    city: 'Synthville',
    state: 'AL',
    enrollment: 100,
    street: '1 Synthetic Road',
    zip: '35000',
    county_name: 'Synthetic County',
    grade_low: null,
    grade_high: null,
    phone: null,
  });
  write(path.join(internal, 'schools.jsonl'), jsonLines([school(0), school(1)]));
  write(
    path.join(internal, 'districts.jsonl'),
    jsonLines([
      { index: 0, id: '0100005', city: 'Synthville', state: 'AL', lat: 34.1, lon: -86.1 },
    ]),
  );
  const uv = path.join(root, 'bin', 'uv');
  write(
    uv,
    '#!/bin/sh\n' +
      'while [ $# -gt 0 ]; do case "$1" in --internal) i=$2;; --out) o=$2;; esac; shift; done\n' +
      'mkdir -p "$o" && cp "$i/schools.jsonl" "$i/districts.jsonl" "$o/"\n',
  );
  chmodSync(uv, 0o755);
}

function stage(): { status: number | null; stdout: string; stderr: string; to: string } {
  const to = path.join(root, 'public-data');
  const run = spawnSync(
    process.execPath,
    [
      STAGE,
      '--site',
      path.join(root, 'site'),
      '--internal',
      path.join(root, 'internal'),
      '--pipeline',
      root,
      '--to',
      to,
    ],
    {
      encoding: 'utf8',
      env: {
        ...process.env,
        PATH: `${path.join(root, 'bin')}${path.delimiter}${process.env.PATH ?? ''}`,
      },
    },
  );
  return { status: run.status, stdout: run.stdout, stderr: run.stderr, to };
}

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-stage-test-'));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe('stage-data with an edition', () => {
  it(
    'stages edition.json under its plain name, byte for byte',
    () => {
      makeTree(EDITION, { 'edition.json': { sha256: sha256(EDITION) } });
      const run = stage();
      expect(run.stderr).toBe('');
      expect(run.status).toBe(0);
      expect(readFileSync(path.join(run.to, 'schools/edition.json'))).toEqual(EDITION);
      const schools = readdirSync(path.join(run.to, 'schools'));
      expect(schools.filter((name) => name.startsWith('edition'))).toEqual(['edition.json']);
      expect(schools.some((name) => /^meta\.[0-9a-f]{10}\.json$/.test(name))).toBe(true);
      expect(run.stdout).not.toContain('no schools/edition.json');
    },
    TIMEOUT,
  );

  it(
    'refuses an edition that does not name the directory beside it',
    () => {
      const tampered = Buffer.from(EDITION.toString().replace('"schools":2', '"schools":3'));
      makeTree(tampered);
      const run = stage();
      expect(run.status).toBe(1);
      expect(run.stderr).toBe(
        'stage-data: schools/edition.json does not name the schools/meta.json and points.bin beside it\n',
      );
      expect(existsSync(run.to)).toBe(false);
    },
    TIMEOUT,
  );

  it(
    'refuses a staging without the edition its build recorded',
    () => {
      makeTree(null, { 'edition.json': { sha256: sha256(EDITION) } });
      const run = stage();
      expect(run.status).toBe(1);
      expect(run.stderr).toContain('schools/edition.json is missing, but the directory build');
      expect(existsSync(run.to)).toBe(false);
    },
    TIMEOUT,
  );

  it(
    'stages a build older than editions without one, and says so',
    () => {
      makeTree(null);
      const run = stage();
      expect(run.stderr).toBe('');
      expect(run.status).toBe(0);
      expect(existsSync(path.join(run.to, 'schools/edition.json'))).toBe(false);
      expect(run.stdout).toContain('no schools/edition.json: the directory build that wrote');
    },
    TIMEOUT,
  );
});
