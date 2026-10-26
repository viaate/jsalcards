/**
 * The night-before outlook on the web (S7-F F3), on fixtures only: the outlook reason reads as
 * the contract states it and only with the file's forecast time; the pipeline's outlook golden
 * (pipeline/tests/predict/golden/synthetic_outlook.json, a SYNTHETIC pass with the outlook on)
 * reads with every sum adding up and its line worded; and the slot and window the line's words
 * come from are the pipeline's (pipeline/tests/predict/golden/outlook_slots.json).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { whyView } from '../../app/chance';
import { chanceFormat } from '../../copy-chance';
import { parseInstant } from '../../state/instant';
import type { PredictionsFile } from '../../types/generated';
import { forecastDetail } from '../forecast-detail';
import type { DetailContext } from '../forecast-detail';
import { parsePredictions } from '../school-day';

const GOLDEN_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../../pipeline/tests/predict/golden',
);
const NBSP = ' ';

function golden(): PredictionsFile {
  const raw = readFileSync(path.join(GOLDEN_DIR, 'synthetic_outlook.json'), 'utf8');
  const parsed = parsePredictions(JSON.parse(raw) as unknown);
  if (parsed === null) throw new Error('the outlook golden does not parse');
  return parsed;
}

const CONTEXT: DetailContext = {
  day: '2026-01-07',
  districts: 5,
  generatedAt: new Date('2026-01-07T02:07:00Z'),
  forecastAt: new Date('2026-01-07T01:46:00Z'),
  neighbors: [],
  timeZone: 'America/Chicago',
};

const LINE = {
  kind: 'outlook',
  points: 29,
  now: 0,
  f: [0, 6.0, 9.0],
  like: [4, 4, 0],
  to: 5,
  share: 60,
  scope: 0,
};

function forecastWith(reason: object, points = 30): object {
  return {
    state: 'forecast',
    p_no_school: points / 100,
    p_delay: 0.04,
    reasons: [0],
    why: { base: { kind: 'similar_days', points: 1 }, reasons: [reason] },
  };
}

describe('the outlook reason', () => {
  it('reads as the contract states it', () => {
    const detail = forecastDetail(forecastWith(LINE), CONTEXT);
    expect(detail.why?.reasons).toEqual([
      {
        kind: 'outlook',
        points: 29,
        c0: 0,
        heads: 0,
        forecast: { kind: 'snow', low: 6, high: 9 },
        like: { low: 4, high: 4, heads: 0 },
        to: 5,
        share: 60,
        scope: 'state',
        at: new Date('2026-01-07T01:46:00Z'),
        generatedAt: new Date('2026-01-07T02:07:00Z'),
      },
    ]);
    // Every case counted ended so: the contract carries 100, worded "in every case".
    const every = forecastDetail(forecastWith({ ...LINE, share: 100 }), CONTEXT);
    expect(every.why?.reasons[0]).toMatchObject({ share: 100 });
    const quiet = forecastDetail(forecastWith({ ...LINE, f: undefined, now: 7, to: 0 }), CONTEXT);
    expect(quiet.why?.reasons[0]).toMatchObject({ c0: 1, heads: 1, forecast: null, to: 0 });
    const ice = forecastDetail(forecastWith({ ...LINE, f: [1, 0.1, 0.23] }), CONTEXT);
    expect(ice.why?.reasons[0]).toMatchObject({ forecast: { kind: 'ice', low: 0.1, high: 0.23 } });
  });

  it('does not read without the file forecast time, or with anything the contract refuses', () => {
    expect(forecastDetail(forecastWith(LINE), { ...CONTEXT, forecastAt: null }).why).toBeNull();
    expect(
      forecastDetail(forecastWith(LINE), {
        ...CONTEXT,
        forecastAt: new Date('2026-01-07T03:00:00Z'),
      }).why,
    ).toBeNull();
    for (const bad of [
      { now: 12 },
      { now: 13 },
      { to: 0 },
      { to: 8 },
      { share: 0 },
      { share: 101 },
      { share: 99.5 },
      { scope: 3 },
      { like: [5, 4, 0] },
      { like: [4, 4, 7] },
      { like: [4, 4] },
      { f: [3, 1, 2] },
      { f: [0, 6.5, 9] },
      { f: [0, 9, 6] },
      { f: [1, 0.125, 0.3] },
      { f: [2, -90, 4] },
      { f: 'snow' },
    ]) {
      const found = forecastDetail(forecastWith({ ...LINE, ...bad }), CONTEXT);
      expect(found.why, JSON.stringify(bad)).toBeNull();
    }
  });
});

describe('the outlook golden', () => {
  it('reads with every sum adding up and its lines worded', () => {
    const file = golden();
    expect(file.forecast_at).toBe('2026-01-07T01:46:00Z');
    let lines = 0;
    for (const entry of file.districts) {
      entry.days.forEach((value, at) => {
        if (value.state !== 'forecast') return;
        const day = file.days[at] ?? '';
        const detail = forecastDetail(value, {
          day,
          districts: file.directory.districts,
          generatedAt: new Date(file.generated_at),
          forecastAt: parseInstant(file.forecast_at),
          neighbors: entry.neighbors ?? [],
          timeZone: entry.time_zone,
        });
        const why = detail.why;
        expect(why).not.toBeNull();
        if (why === null) return;
        const total = why.base.points + why.reasons.reduce((sum, item) => sum + item.points, 0);
        expect(total).toBe(Math.round(value.p_no_school * 100));
        if (why.reasons.some((reason) => reason.kind === 'outlook')) {
          lines += 1;
          const view = whyView({
            detail,
            chance: value.p_no_school,
            day,
            district: 'Olathe',
            nameOf: () => null,
            now: new Date(file.generated_at),
            zones: { school: entry.time_zone, viewer: entry.time_zone },
            state: entry.district === 0 ? 'KS' : 'MO',
          });
          expect(view).not.toBeNull();
          const line = view?.lines[0];
          expect(line?.text).toMatch(
            new RegExp(
              `^No winter storm warning, winter advisory or winter storm watch covers half of Olathe’s schools yet, but the weather service’s 7:46${NBSP}PM forecast has 6 to [89] inches of snow at Olathe’s schools between then and 12${NBSP}PM [A-Z][a-z]+day\\. Across (Kansas|Missouri) districts, in [34] of 5 cases like this, a winter (storm warning|advisory) was out by 5${NBSP}AM\\.$`,
              'u',
            ),
          );
          expect(line?.help).toMatch(
            /^A case is one district at one hour between 7:30 and 10:30 PM/,
          );
        }
      });
    }
    expect(lines).toBe(2);
  });
});

interface SlotRow {
  readonly zone: string;
  readonly day: string;
  readonly at: string;
  readonly slot: number;
  readonly window_from: string;
  readonly window_until: string;
}

function hourMinute(at: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(at);
  const part = (type: string): string => parts.find((item) => item.type === type)?.value ?? '';
  return `${part('hour')}:${part('minute')}`;
}

describe('the slot and window golden', () => {
  it('gives the pipeline slot and window at every row', () => {
    const rows = JSON.parse(
      readFileSync(path.join(GOLDEN_DIR, 'outlook_slots.json'), 'utf8'),
    ) as SlotRow[];
    expect(rows.length).toBeGreaterThan(1000);
    for (const row of rows) {
      const at = new Date(row.at);
      expect(chanceFormat.outlookSlot(at, row.day, row.zone), JSON.stringify(row)).toBe(row.slot);
      const { from, until } = chanceFormat.outlookWindow(row.day);
      expect(hourMinute(from, row.zone)).toBe(row.window_from);
      expect(hourMinute(until, row.zone)).toBe(row.window_until);
    }
  });
});

describe('the 50% rule the words say', () => {
  it('is the pipeline config’s covered share: "covers half of" is said of exactly a half', () => {
    // copy-chance.ts NOT_YET and HALF_ITS say "half"; the pipeline's class is the strongest
    // covering weather.covered_share of a district's schools. Changing one alone would make
    // every such sentence false, so the two are held together here and in the pipeline
    // (tests/predict/test_outlook_serve.py, the worded share).
    const config = readFileSync(path.join(GOLDEN_DIR, '../../../config/predict.yaml'), 'utf8');
    const found = /^\s*covered_share:\s*([0-9.]+)/mu.exec(config)?.[1];
    expect(Number(found)).toBe(0.5);
    const zones = { school: 'America/Chicago', viewer: 'America/Chicago' };
    const line = chanceFormat.reason(
      {
        kind: 'outlook',
        points: 5,
        c0: 0,
        heads: 0,
        forecast: null,
        like: { low: 0, high: 0, heads: 0 },
        to: 1,
        share: 30,
        scope: 'nation',
        state: 'KS',
        at: new Date('2026-01-13T01:46:00Z'),
        generatedAt: new Date('2026-01-13T02:05:00Z'),
        day: '2026-01-13',
        record: new Date('2026-01-13T11:00:00Z'),
        busTime: new Date('2026-01-13T13:00:00Z'),
      },
      'Olathe',
      new Date('2026-01-13T02:05:00Z'),
      zones,
    );
    expect(line).toContain('covers half of Olathe’s schools yet');
  });
});

describe('the heads-ups', () => {
  it('are worded in the contract’s order (pipeline situations.HeadsUp)', () => {
    const schema = JSON.parse(
      readFileSync(path.join(GOLDEN_DIR, '../../../../schemas/predictions.schema.json'), 'utf8'),
    ) as { $defs: Record<string, { description?: string }> };
    const description = (schema.$defs.OutlookReason?.description ?? '').replace(/\s+/gu, ' ');
    const listed = description.split('heads-up 0 none, ')[1]?.split(')')[0] ?? '';
    const names = listed.split(', ').map((item) => item.replace(/^\d+ /u, ''));
    expect(names).toEqual([
      'winter storm watch',
      'extreme cold watch',
      'cold weather advisory',
      'hurricane watch',
      'tropical storm watch',
    ]);
    const zones = { school: 'America/Chicago', viewer: 'America/Chicago' };
    names.forEach((name, i) => {
      const words = chanceFormat.reason(
        {
          kind: 'outlook',
          points: 20,
          c0: 0,
          heads: i + 1,
          forecast: { kind: 'snow', low: 6, high: 9 },
          like: { low: 4, high: 4, heads: 0 },
          to: 5,
          share: 60,
          scope: 'nation',
          state: null,
          at: new Date('2026-01-12T22:46:00Z'),
          generatedAt: new Date('2026-01-13T02:05:00Z'),
          day: '2026-01-13',
          record: new Date('2026-01-13T11:00:00Z'),
          busTime: new Date('2026-01-13T13:00:00Z'),
        },
        'Olathe',
        new Date('2026-01-13T02:05:00Z'),
        zones,
      );
      expect(words.toLowerCase()).toMatch(new RegExp(`^an? ${name} is out, and `, 'u'));
    });
  });
});
