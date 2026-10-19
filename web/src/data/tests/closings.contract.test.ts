/**
 * T17, the web half: the closings files the pipeline writes read here to the
 * same rows the pipeline wrote them from.
 *
 * - The pipeline's schema example (pipeline/tests/schemas/examples), which the
 *   pipeline's own model reads back byte for byte; its rows are written out
 *   below as ClosingsFile.closings() gives them.
 * - The live ingest's golden files (pipeline/tests/live/golden), each
 *   synthetic_*.json written by the pipeline from its synthetic rows, which it
 *   writes beside it as synthetic_*.rows.json: one object per row, with the
 *   school's position, the local day, the status and reason codes,
 *   announced_at (an instant, or null), shift_minutes and clock_minute (Row
 *   below). Every golden file there is read, and each must have its rows
 *   file. Once S8-D's publisher is in, a case fails, naming the file, while
 *   synthetic_closings.json or its rows file is missing.
 *
 * Every row is read the two ways the page reads it: the map's (decodeDay) and
 * the school panel's (schoolStatus), at noon of its day in the US.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import type { ClosingsFile, LocalDate } from '../../types/generated';
import { decodeDay, parseClosings } from '../closings';
import { nextDay, schoolStatus } from '../school-day';

const PIPELINE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../pipeline');
const EXAMPLE = path.join(PIPELINE, 'tests/schemas/examples/synthetic-closings.json');
const GOLDEN_DIR = path.join(PIPELINE, 'tests/live/golden');
const ROWS_SUFFIX = '.rows.json';
/** The golden file's agreed name (S8 spec T17). */
const GOLDEN = path.join(GOLDEN_DIR, 'synthetic_closings.json');
/** S8-D's publisher, which writes the golden file. */
const PUBLISHER = path.join(PIPELINE, 'snowlight/live/publish.py');
/** The golden folder's files, or null while there is no folder. */
const GOLDEN_FILES: readonly string[] | null = existsSync(GOLDEN_DIR)
  ? readdirSync(GOLDEN_DIR)
      .filter((name) => /^synthetic_.*\.json$/.test(name))
      .sort()
  : null;

/** A row as the pipeline's Closing holds it. */
interface Row {
  readonly school: number;
  readonly day: LocalDate;
  readonly status: number;
  readonly announced_at: string | null;
  readonly reason: number | null;
  readonly shift_minutes: number | null;
  readonly clock_minute: number | null;
}

/** The example's rows, as the pipeline's ClosingsFile.closings() decodes them. */
const EXAMPLE_ROWS: readonly Row[] = [
  row(0, '2027-01-12', 0, '2027-01-12T11:42:00Z', 0),
  row(1, '2027-01-12', 1, '2027-01-12T11:03:00Z', 1, 120, 600),
  row(2, '2027-01-12', 1, null, null),
  row(3, '2027-01-12', 2, '2027-01-12T01:15:00Z', 2),
  row(5, '2027-01-12', 3, '2027-01-12T13:00:00Z', 5, 180, 750),
  row(0, '2027-01-13', 0, '2027-01-12T12:50:00Z', 0),
  row(4, '2027-01-13', 0, '2027-01-12T12:58:00Z', null),
];

function row(
  school: number,
  day: LocalDate,
  status: number,
  announced: string | null,
  reason: number | null,
  shift: number | null = null,
  clock: number | null = null,
): Row {
  return {
    school,
    day,
    status,
    announced_at: announced,
    reason,
    shift_minutes: shift,
    clock_minute: clock,
  };
}

function readJson(file: string): unknown {
  return JSON.parse(readFileSync(file, 'utf8')) as unknown;
}

/** Every row of the file as the map decodes it: school and status, by day. */
function mapRows(file: ClosingsFile): [LocalDate, number, number][] {
  return file.days.flatMap((group) => {
    const { schools, statuses } = decodeDay(group);
    return [...schools].map((school, i): [LocalDate, number, number] => [
      group.day,
      school,
      statuses[i] ?? -1,
    ]);
  });
}

/** Every row of the file as the school panel reads it, school by school. */
function panelRows(file: ClosingsFile): Row[] {
  const found: Row[] = [];
  for (const { day } of file.days) {
    const now = new Date(`${day}T18:00:00Z`);
    for (let school = 0; school < file.directory.schools; school++) {
      const { today } = schoolStatus({
        school,
        directory: file.directory,
        closings: file,
        covered: null,
        now,
      });
      if (today === null || today === 'open') continue;
      found.push(
        row(
          school,
          day,
          today.status,
          today.announcedAt === null ? null : today.announcedAt.toISOString().replace('.000Z', 'Z'),
          today.reason,
          today.shiftMinutes,
          today.clockMinute,
        ),
      );
    }
  }
  return found;
}

function expectSameRows(raw: unknown, rows: readonly Row[]): void {
  const file = parseClosings(raw);
  expect(file).not.toBeNull();
  if (file === null) return;
  const sorted = [...rows].sort((a, b) => a.day.localeCompare(b.day) || a.school - b.school);
  expect(mapRows(file)).toEqual(sorted.map((item) => [item.day, item.school, item.status]));
  expect(panelRows(file)).toEqual(sorted);
  // Each day's rows are also the next-day rows the panel shows the evening before.
  for (const { day } of file.days) {
    const before = new Date(`${day}T00:00:00Z`);
    before.setUTCHours(-6);
    const evening = sorted.filter((item) => item.day === day);
    for (const item of evening) {
      const { tomorrow } = schoolStatus({
        school: item.school,
        directory: file.directory,
        closings: file,
        covered: null,
        now: before,
      });
      expect([item.school, nextDay(before.toISOString().slice(0, 10)), tomorrow?.status]).toEqual([
        item.school,
        day,
        item.status,
      ]);
    }
  }
}

describe('the pipeline’s closings files, read here', () => {
  it('reads the schema example to the rows the pipeline decodes from it', () => {
    expectSameRows(readJson(EXAMPLE), EXAMPLE_ROWS);
  });

  it('has the live ingest\u2019s golden file under its agreed name once its publisher is in', () => {
    // S8-D brings the publisher (pipeline/snowlight/live/publish.py) and its golden file
    // together. Neither yet: nothing to read. Either one alone: this fails, by name, rather than
    // reading nothing quietly.
    const landed = existsSync(PUBLISHER) || GOLDEN_FILES !== null;
    if (!landed) return;
    expect(
      existsSync(GOLDEN) && existsSync(GOLDEN.replace(/\.json$/, ROWS_SUFFIX)),
      `S8-D must write ${path.relative(path.dirname(PIPELINE), GOLDEN)} and its rows file beside it`,
    ).toBe(true);
  });

  if (GOLDEN_FILES !== null) {
    const golden = GOLDEN_FILES.filter((name) => !name.endsWith(ROWS_SUFFIX));
    const rows = GOLDEN_FILES.filter((name) => name.endsWith(ROWS_SUFFIX));

    it('finds a golden closings file, and a rows file for each and no other', () => {
      expect(golden).toContain('synthetic_closings.json');
      expect(rows.sort()).toEqual(
        golden.map((name) => name.replace(/\.json$/, ROWS_SUFFIX)).sort(),
      );
    });

    it.each(golden)(
      'reads the live ingest\u2019s %s to the rows the pipeline wrote it from',
      (name) => {
        const rowsFile = path.join(GOLDEN_DIR, name.replace(/\.json$/, ROWS_SUFFIX));
        expectSameRows(readJson(path.join(GOLDEN_DIR, name)), readJson(rowsFile) as Row[]);
      },
    );
  }
});
