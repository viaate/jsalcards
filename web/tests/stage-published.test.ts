/**
 * Staging's replay branch (scripts/stage-published.mjs, as scripts/stage-data.mjs
 * runs it): each replay day under a content-hashed name once its stamp is the
 * staged directory's, the index under its plain name, and a day stamped for
 * another directory stopping the staging before anything is written. The
 * replay files are SYNTHETIC, made here in a temporary folder.
 */
import { createHash } from 'node:crypto';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { checkStamps, replayStampProblem, stageOthers } from '../scripts/stage-published.mjs';
import { hashedOnStaging, hashedPath } from '../src/data/paths';

/** Every file under `folder`, as sorted paths relative to it. */
function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
    )
    .sort();
}

const STAMP = { generated_on: '2026-09-25', schools: 5, districts: 4 };

function replay(day: string, stamp: object = STAMP): string {
  return JSON.stringify({
    schema_version: 1,
    id: day,
    generated_at: '2026-10-01T12:00:00Z',
    directory: stamp,
    start: `${day}T12:00:00Z`,
    step_minutes: 1440,
    frames: 1,
    rows: [[3, 0, 0, 0, 0]],
  });
}

let root = '';

afterEach(() => {
  if (root !== '') rmSync(root, { recursive: true, force: true });
  root = '';
});

/** A site-data folder with these files, and an empty folder to stage into. */
function site(files: Record<string, string>): { site: string; to: string } {
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-stage-published-'));
  const from = path.join(root, 'site-data');
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(from, name)), { recursive: true });
    writeFileSync(path.join(from, name), text);
  }
  const to = path.join(root, 'data');
  mkdirSync(to);
  return { site: from, to };
}

function stage(folders: { site: string; to: string }) {
  const hashed: string[] = [];
  const staged = stageOthers({
    ...folders,
    skip: (name) => name.startsWith('schools/'),
    stamp: STAMP,
    hashed: hashedOnStaging,
    putHashed: (name, bytes) => {
      const published = hashedPath(name, createHash('sha256').update(bytes).digest('hex'));
      mkdirSync(path.dirname(path.join(folders.to, published)), { recursive: true });
      writeFileSync(path.join(folders.to, published), bytes);
      hashed.push(published);
    },
    fail: (message) => {
      throw new Error(message);
    },
  });
  return { staged, hashed };
}

describe('staging the replays', () => {
  it('hashes each day once its stamp is the directory’s, and keeps the index plain', () => {
    const day = replay('2026-01-05');
    const folders = site({
      'replays/2026-01-05.json': day,
      'replays/index.json': '{"schema_version":1}',
      'replays/2026-01-05.report.internal.json': '{}',
      'live/closings.json': '{}',
      'schools/meta.json': '{}',
    });
    const { staged, hashed } = stage(folders);
    const digest = createHash('sha256').update(day).digest('hex').slice(0, 10);
    expect(hashed).toEqual([`replays/2026-01-05.${digest}.json`]);
    expect(staged.map(([name]) => name)).toEqual(['live/closings.json', 'replays/index.json']);
    expect(filesIn(folders.to)).toEqual([
      'live/closings.json',
      `replays/2026-01-05.${digest}.json`,
      'replays/index.json',
    ]);
    expect(readFileSync(path.join(folders.to, hashed[0] ?? ''), 'utf8')).toBe(day);
  });

  it('stops at a day stamped for another directory, before writing anything', () => {
    const folders = site({
      'live/closings.json': '{}',
      'replays/2024-01-16.json': replay('2024-01-16'),
      'replays/2026-01-05.json': replay('2026-01-05', { ...STAMP, generated_on: '2026-09-01' }),
      'replays/index.json': '{}',
    });
    expect(() => stage(folders)).toThrow(/replays\/2026-01-05\.json: stamped for directory/u);
    expect(filesIn(folders.to)).toEqual([]);
    expect(() => {
      checkStamps({
        site: folders.site,
        skip: () => false,
        stamp: STAMP,
        hashed: hashedOnStaging,
        fail: (message) => {
          throw new Error(message);
        },
      });
    }).toThrow(/2026-01-05/u);
  });

  it('names what is wrong with a day it refuses', () => {
    const name = 'replays/2026-01-05.json';
    expect(replayStampProblem(name, Buffer.from(replay('2026-01-05')), STAMP)).toBeNull();
    expect(replayStampProblem(name, Buffer.from('{'), STAMP)).toBe(`${name}: not JSON`);
    expect(replayStampProblem(name, Buffer.from('{}'), STAMP)).toMatch(
      /stamped for directory null/u,
    );
    expect(
      replayStampProblem(name, Buffer.from(replay('2026-01-05', { ...STAMP, schools: 6 })), STAMP),
    ).toMatch(/not the one staged/u);
  });

  it('stages no replays/ folder when the pipeline published none', () => {
    const folders = site({ 'live/closings.json': '{}' });
    stage(folders);
    expect(existsSync(path.join(folders.to, 'replays'))).toBe(false);
  });
});
