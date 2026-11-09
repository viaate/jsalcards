// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { seasonFormat } from '../../copy-season';
import type { SeasonDays } from '../../copy-season';

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../scripts/check-copy.mjs',
);
const { problems } = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string, file?: string) => string[];
};

function days(closed: number, delayed = 0, remote = 0, earlyDismissal = 0): SeasonDays {
  return { closed, delayed, remote, earlyDismissal };
}

describe('the season line', () => {
  it('names each status with a day, the first with its unit', () => {
    expect(seasonFormat.line(days(1), null)).toBe('This school year: closed 1 day.');
    expect(seasonFormat.line(days(2, 1), null)).toBe('This school year: closed 2 days, delayed 1.');
    expect(seasonFormat.line(days(0, 3), null)).toBe('This school year: delayed 3 days.');
    expect(seasonFormat.line(days(0, 0, 1, 2), null)).toBe(
      'This school year: remote 1 day, dismissed early 2.',
    );
    expect(seasonFormat.line(days(0, 0, 0, 1), null)).toBe(
      'This school year: dismissed early 1 day.',
    );
    expect(seasonFormat.line(days(4, 2, 1, 1), null)).toBe(
      'This school year: closed 4 days, delayed 2, remote 1, dismissed early 1.',
    );
    expect(seasonFormat.line(days(1200), null)).toBe('This school year: closed 1,200 days.');
  });

  it('says when counting began, when that is after the school year began', () => {
    expect(seasonFormat.line(days(2, 1), '2026-10-27')).toBe(
      'This school year, since Oct 27: closed 2 days, delayed 1.',
    );
    expect(seasonFormat.line(days(0, 1), '2027-01-04')).toBe(
      'This school year, since Jan 4: delayed 1 day.',
    );
  });

  it('refuses a line with no day, and a count that is not one', () => {
    expect(() => seasonFormat.line(days(0), null)).toThrow(RangeError);
    expect(() => seasonFormat.line(days(-1, 2), null)).toThrow(RangeError);
    expect(() => seasonFormat.line(days(1.5), null)).toThrow(RangeError);
    expect(() => seasonFormat.line(days(1), '2026-02-30')).toThrow(RangeError);
  });

  it('keeps the house style for every mix of statuses and counts', () => {
    const found: string[] = [];
    for (const mix of [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]) {
      const counts = [0, 1, 2, 3].map((bit) => ((mix >> bit) & 1) * (bit + 1));
      if (counts.every((n) => n === 0)) continue;
      const [closed = 0, delayed = 0, remote = 0, early = 0] = counts;
      for (const since of [null, '2026-10-27', '2027-06-30']) {
        const line = seasonFormat.line(days(closed, delayed, remote, early), since);
        for (const problem of problems(line, 'src/copy-season.ts'))
          found.push(`${line}: ${problem}`);
      }
    }
    expect(found).toEqual([]);
  });
});
