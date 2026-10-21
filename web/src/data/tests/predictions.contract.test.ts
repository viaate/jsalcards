/**
 * The predictions contract, the web half: the golden file the pipeline's
 * serving pass writes from its SYNTHETIC world and storm
 * (pipeline/tests/predict/golden/synthetic_predictions.json, written by
 * pipeline/tests/predict/test_golden.py) reads here as the page reads it:
 * every forecast's parts with forecastDetail, its why adding up to the chance
 * shown, and a school's outlook with schoolOutlook: a public school's by its
 * district, a private school's by its own entry and the file's shared outlooks.
 * The file leaves every default out (a compact file): a missing part reads as
 * its default.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import type { PredictionsFile } from '../../types/generated';
import { forecastDetail } from '../forecast-detail';
import { parsePredictions, schoolEntry, schoolOutlook } from '../school-day';

const GOLDEN = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../pipeline/tests/predict/golden/synthetic_predictions.json',
);

function golden(): PredictionsFile {
  const parsed = parsePredictions(JSON.parse(readFileSync(GOLDEN, 'utf8')) as unknown);
  if (parsed === null) throw new Error('the golden predictions file does not parse');
  return parsed;
}

describe('the golden predictions file', () => {
  it('parses, and every school day has a forecast whose why adds up to its chance', () => {
    const file = golden();
    expect(file.days).toEqual(['2026-01-06', '2026-01-07']);
    let forecasts = 0;
    for (const entry of file.districts) {
      entry.days.forEach((value, at) => {
        expect(value.state).toBe('forecast');
        if (value.state !== 'forecast') return;
        forecasts += 1;
        const detail = forecastDetail(value, {
          day: file.days[at] ?? '',
          districts: file.directory.districts,
          generatedAt: new Date(file.generated_at),
          neighbors: entry.neighbors ?? [],
          timeZone: entry.time_zone,
        });
        expect(detail.why).not.toBeNull();
        const why = detail.why;
        if (why === null) return;
        const total = why.base.points + why.reasons.reduce((sum, item) => sum + item.points, 0);
        expect(total).toBe(Math.round(value.p_no_school * 100));
        expect(value.p_no_school).toBeGreaterThanOrEqual(0.01);
        // No bus times in any data: no chart, no countdown.
        expect(detail.hours).toBeNull();
        expect(detail.busesAt).toBeNull();
        expect(detail.announcesAt).toBeNull();
      });
    }
    expect(forecasts).toBe(file.districts.length * file.days.length);
  });

  it('reads the storm district with its own record and the run before', () => {
    const file = golden();
    const entry = file.districts[1];
    const value = entry?.days[1];
    expect(value?.state).toBe('forecast');
    if (entry === undefined || value?.state !== 'forecast') return;
    const detail = forecastDetail(value, {
      day: '2026-01-07',
      districts: file.directory.districts,
      generatedAt: new Date(file.generated_at),
      neighbors: entry.neighbors ?? [],
      timeZone: entry.time_zone,
    });
    expect(detail.why?.base).toMatchObject({ kind: 'alert', alert: 'winter_storm_warning' });
    expect(detail.record?.proves).toBe('base');
    expect(detail.record?.days.every((day) => day.day < '2026-01-07')).toBe(true);
    expect(detail.previous?.noSchool).toBe(0.01);
    expect(detail.previous?.at.getTime()).toBeLessThan(new Date(file.generated_at).getTime());
    expect(value.reasons).toEqual([0]);
  });

  it('gives a clear school day 1% with no weather named, and a school its outlook', () => {
    const file = golden();
    const clear = file.districts[0]?.days[1];
    // A compact file keeps a clear day's empty reasons: the reader before it refused a
    // forecast without them.
    expect(clear).toMatchObject({ state: 'forecast', p_no_school: 0.01, reasons: [] });
    const now = new Date(new Date(file.generated_at).getTime() + 5 * 60_000);
    const outlook = schoolOutlook({
      district: 1,
      directory: file.directory,
      shipped: true,
      predictions: file,
      now,
    });
    // 8:20 PM in Chicago on the 6th: today is the 6th, tomorrow the storm day.
    expect(outlook?.today).toMatchObject({ state: 'forecast', day: '2026-01-06' });
    expect(outlook?.tomorrow).toMatchObject({ state: 'forecast', day: '2026-01-07' });
    const tomorrow = outlook?.tomorrow;
    if (tomorrow?.state === 'forecast') expect(tomorrow.noSchool).toBeGreaterThan(0.3);
    const stale = new Date(new Date(file.generated_at).getTime() + 91 * 60_000);
    expect(
      schoolOutlook({
        district: 1,
        directory: file.directory,
        shipped: true,
        predictions: file,
        now: stale,
      }),
    ).toBeNull();
  });

  it('gives each private school its own chance, through the shared outlooks', () => {
    const file = golden();
    const schools = file.schools ?? [];
    expect(schools.map((entry) => entry.school)).toEqual([7, 8, 9]);
    expect((file.outlooks ?? []).length).toBeLessThan(schools.length * file.days.length);
    expect(schoolEntry(file, 8)?.school).toBe(8);
    expect(schoolEntry(file, 10)).toBeNull();
    const now = new Date(new Date(file.generated_at).getTime() + 5 * 60_000);
    const outlook = (school: number) =>
      schoolOutlook({
        district: null,
        school,
        directory: file.directory,
        shipped: true,
        predictions: file,
        now,
      });
    // Its own record, under the warning: an own base.
    const own = outlook(7)?.tomorrow;
    expect(own?.state).toBe('forecast');
    if (own?.state === 'forecast') {
      expect(own.noSchool).toBeGreaterThan(0.3);
      expect(own.detail?.why?.base.kind).toBe('alert');
      expect(own.detail?.record?.proves).toBe('base');
    }
    // A school that said school is on: the floor, the private schools around it as the base,
    // and the line that takes the rest away.
    const said = outlook(8)?.tomorrow;
    expect(said?.state).toBe('forecast');
    if (said?.state === 'forecast') {
      expect([said.noSchool, said.delay]).toEqual([0.01, 0]);
      const why = said.detail?.why;
      expect(why?.base).toMatchObject({ kind: 'pooled', of: 'private_schools' });
      expect(why?.reasons.map((reason) => reason.kind)).toEqual(['said_open']);
      const total =
        (why?.base.points ?? 0) + (why?.reasons ?? []).reduce((sum, r) => sum + r.points, 0);
      expect(total).toBe(1);
    }
    // Utah's, in its own zone; Alaska's is not in the file.
    expect(outlook(9)?.timeZone).toBe('America/Denver');
    expect(outlook(10)).toBeNull();
    // A school with neither a district nor its own entry has none.
    expect(
      schoolOutlook({
        district: null,
        directory: file.directory,
        shipped: true,
        predictions: file,
        now,
      }),
    ).toBeNull();
  });
});
