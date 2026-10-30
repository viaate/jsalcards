/**
 * The night chart's day and window, the web half: the cases the pipeline's one definition
 * writes (pipeline/tests/predict/golden/night_day.json, from test_night_day.py) read here the
 * same, through nightDay, nightOpen and nightWindow (data/night.ts).
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { chartView } from '../../app/chance';
import { chanceCopy, chanceFormat } from '../../copy-chance';
import { NO_DETAIL } from '../forecast-detail';
import { nightDay, nightOf, nightOpen, nightWindow } from '../night';

const GOLDEN_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../pipeline/tests/predict/golden',
);
const GOLDEN = path.join(GOLDEN_DIR, 'night_day.json');

interface Case {
  readonly zone: string;
  readonly at: string;
  readonly day: string;
  readonly open: boolean;
  readonly start: string;
  readonly end: string;
  readonly hours: number;
}

const iso = (instant: Date): string => instant.toISOString().replace('.000Z', 'Z');

describe('the night chart’s day and window', () => {
  const cases = JSON.parse(readFileSync(GOLDEN, 'utf8')) as Case[];

  it('holds every case of the pipeline’s golden file', () => {
    expect(cases.length).toBeGreaterThan(300);
    for (const item of cases) {
      const at = new Date(item.at);
      const what = `${item.zone} ${item.at}`;
      expect(nightDay(at, item.zone), what).toBe(item.day);
      expect(nightOpen(at, item.zone), what).toBe(item.open);
      const window = nightWindow(at, item.zone);
      expect(iso(window.start), what).toBe(item.start);
      expect(iso(window.end), what).toBe(item.end);
      expect(window.hours, what).toBe(item.hours);
    }
  });

  it('covers both clock changes, every zone and the morning edge', () => {
    const zones = new Set(cases.map((item) => item.zone));
    expect([...zones].sort()).toEqual([
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'America/New_York',
      'America/Phoenix',
    ]);
    const days = new Set(cases.map((item) => item.at.slice(0, 10)));
    for (const day of ['2026-03-08', '2026-11-01', '2026-07-13']) expect(days.has(day)).toBe(true);
    expect(cases.some((item) => item.open)).toBe(true);
    expect(cases.some((item) => !item.open)).toBe(true);
  });
});

interface NightCase {
  readonly zone: string;
  readonly day: string;
  readonly generated_at: string;
  readonly night_at: string;
  readonly night: unknown;
  readonly start: string;
  readonly end: string;
  readonly instants: number;
  readonly lit: readonly number[];
  readonly heavy_from: string | null;
  readonly heavy_to: string | null;
  readonly tenths: boolean;
}

describe('the golden nights the pipeline’s rule wrote', () => {
  const cases = JSON.parse(
    readFileSync(path.join(GOLDEN_DIR, 'night_chart.json'), 'utf8'),
  ) as NightCase[];

  it('read as the contract says, and draw the same window, bars, lit hours and answer', () => {
    expect(cases.length).toBeGreaterThanOrEqual(25);
    for (const item of cases) {
      const what = `${item.zone} ${item.generated_at}`;
      const generatedAt = new Date(item.generated_at);
      const night = nightOf(item.night, {
        day: item.day,
        timeZone: item.zone,
        generatedAt,
        nightAt: new Date(item.night_at),
      });
      expect(night, what).not.toBeNull();
      if (night === null) continue;
      expect(iso(night.start), what).toBe(item.start);
      expect(iso(night.end), what).toBe(item.end);
      expect(night.instants, what).toHaveLength(item.instants);
      expect(night.range.tenths, what).toBe(item.tenths);
      expect(night.heavy === null ? null : iso(night.heavy.from), what).toBe(item.heavy_from);
      expect(night.heavy === null ? null : iso(night.heavy.to), what).toBe(item.heavy_to);
      const zones = { school: item.zone, viewer: item.zone };
      const chart = chartView({ ...NO_DETAIL, night }, generatedAt, zones);
      expect(chart, what).not.toBeNull();
      if (chart === null) continue;
      expect(chart.title, what).toBe(chanceCopy.newSnowTitle);
      expect(chart.bars, what).toHaveLength(item.instants);
      expect(
        chart.bars.flatMap((bar, at) => (bar.lit ? [at] : [])),
        what,
      ).toEqual(item.lit);
      const end = chart.key.at(-1);
      expect(end?.mark, what).toBe('end');
      if (end?.mark === 'end') {
        expect(end.rest, what).toBe(` by ${chanceFormat.clock(night.end, zones)}`);
        expect(end.value, what).toBe(chanceFormat.inches(night.range.low, night.range.high));
      }
      expect(chart.times.map((time) => time.at).at(0), what).toBe(0);
      expect(chart.times.at(-1)?.at, what).toBe(item.instants - 1);
      expect(
        chart.times.map((time) => time.label),
        what,
      ).not.toContain(chanceCopy.now);
    }
  });
});
