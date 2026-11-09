import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { detailsCopy, detailsFormat } from './copy-details';
import { Detail } from './types/generated';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const { problems } = (await import(
  /* @vite-ignore */ path.join(WEB_ROOT, 'scripts', 'check-copy.mjs')
)) as { problems: (text: string, file?: string) => string[] };

describe('plain details copy (src/copy-details.ts)', () => {
  it('words every detail code once, in the house style, and is frozen', () => {
    expect(Object.isFrozen(detailsCopy)).toBe(true);
    expect(Object.isFrozen(detailsFormat)).toBe(true);
    expect(Object.keys(detailsCopy.said).sort()).toEqual(Object.keys(Detail).sort());
    for (const text of Object.values(detailsCopy.said)) {
      expect(problems(text, 'src/copy-details.ts')).toEqual([]);
      expect(text).toMatch(/^[A-Z].*\.$/);
    }
    expect(new Set(Object.values(detailsCopy.said)).size).toBe(Object.keys(Detail).length);
  });

  it('says them in code order (who, buses, meals, pre-K, after school, offices), each once', () => {
    expect(detailsFormat.said([Detail.no_breakfast, Detail.students_and_staff, 3, 3])).toBe(
      'Students and staff. Buses run snow routes. No breakfast.',
    );
    expect(detailsFormat.said([Detail.offices_closed, Detail.no_am_prek])).toBe(
      'No morning pre-K. Offices closed.',
    );
    expect(detailsFormat.said([])).toBeNull();
    // A code a later file adds that this copy does not know is left out, never shown as a number.
    expect(detailsFormat.said([99, -1, 1.5])).toBeNull();
    expect(detailsFormat.said([99, Detail.no_buses])).toBe('No buses.');
  });

  it('fits whole sentences in the room given, the last ones left out first', () => {
    const codes = [Detail.students_and_staff, Detail.buses_snow_routes, Detail.no_breakfast];
    expect(detailsFormat.within(codes, 200)).toBe(
      'Students and staff. Buses run snow routes. No breakfast.',
    );
    expect(detailsFormat.within(codes, 42)).toBe('Students and staff. Buses run snow routes.');
    expect(detailsFormat.within(codes, 41)).toBe('Students and staff.');
    expect(detailsFormat.within(codes, 18)).toBeNull();
    expect(detailsFormat.within(codes, -5)).toBeNull();
  });

  it('puts the details after a status in the same run of sentences, never cutting the status', () => {
    const status = 'Closed today (Tue, Jan 12)';
    expect(detailsFormat.afterStatus(status, [Detail.no_buses, Detail.no_breakfast])).toBe(
      'Closed today (Tue, Jan 12). No buses. No breakfast.',
    );
    expect(detailsFormat.afterStatus(status, [])).toBe(status);
    // 160 characters in all: a status that leaves no room for a whole detail shows alone.
    const long = 'x'.repeat(150);
    expect(detailsFormat.afterStatus(long, [Detail.no_breakfast])).toBe(long);
    const edge = 'x'.repeat(160 - 2 - 'No buses.'.length);
    expect(detailsFormat.afterStatus(edge, [Detail.no_buses])).toBe(`${edge}. No buses.`);
    expect(detailsFormat.afterStatus(`${edge}x`, [Detail.no_buses])).toBe(`${edge}x`);
  });
});
