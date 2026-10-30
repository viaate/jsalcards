/**
 * The night chart in the chance section (option (iv), app/chance.ts nightView): hourly bars from
 * Start with no "Now", the times at its foot, the lit span, the range, the title, the summary,
 * the forecast's time under it, the usual announcement's line (critic 2 S6), and the snow reason
 * with no amount while it shows (O6). Every amount is made up.
 */

import { describe, expect, it } from 'vitest';

import { chanceCopy, chanceFormat } from '../../copy-chance';
import type { Zones } from '../../copy-chance';
import type { ForecastDetail, WhyDetail } from '../../data/forecast-detail';
import type { Outlook } from '../../data/school-day';
import { nightOf } from '../../data/night';
import { chanceView, chartView } from '../chance';
import type { ChanceInput, ChartView } from '../chance';
import { A_CLOSINGS, A_DETAIL, NAMES, ZONE, nightOutlook } from './chance-fixtures';

const NBSP = ' ';
const MINUTE = 60_000;
const at = (iso: string): Date => new Date(iso);
const HERE: Zones = { school: ZONE, viewer: ZONE };
/** 9:00 PM Monday in Kansas City: Start 10 PM, End 7 AM Tuesday, 9 hours, from the 7 PM cycle. */
const GENERATED = at('2026-01-13T03:00:00Z');
const CYCLE = at('2026-01-13T01:00:00Z');
const NOW = at('2026-01-13T03:05:00Z');
const RAW = {
  least: [0.1, 0.4, 1.0, 2.0, 3.1, 4.2, 4.9, 5.4, 6.1],
  low: 6,
  high: 9,
  heavy: [3, 6],
};

function night(raw: unknown = RAW, generatedAt = GENERATED, nightAt = CYCLE) {
  return nightOf(raw, { day: '2026-01-13', timeZone: ZONE, generatedAt, nightAt });
}

/** Tuesday's 64%: the base and the snow line (the forecaster's amount, at 7:19 PM). */
const WHY: WhyDetail = {
  base: { kind: 'alert', points: 48, alert: 'winter_storm_warning', borrowed: false, live: false },
  reasons: [
    {
      kind: 'snow_total',
      points: 16,
      low: 6,
      high: 8,
      overnight: false,
      against: 'storms',
      at: at('2026-01-13T01:19:00Z'),
    },
  ],
};

function detail(overrides: Partial<ForecastDetail> = {}): ForecastDetail {
  return {
    ...A_DETAIL,
    announcesAt: null,
    busesAt: null,
    hours: null,
    why: WHY,
    record: null,
    night: night(),
    ...overrides,
  };
}

function input(overrides: Partial<ChanceInput> = {}, forecast = detail()): ChanceInput {
  return {
    outlook: nightOutlook(forecast),
    decided: { today: false, tomorrow: false },
    status: [],
    district: 'Shawnee Mission',
    state: 'KS',
    closings: A_CLOSINGS,
    names: NAMES,
    now: NOW,
    timeZone: ZONE,
    ...overrides,
  };
}

function chart(forecast = detail(), now = NOW, zones = HERE): ChartView {
  const found = chartView(forecast, now, zones);
  if (found === null) throw new Error('no chart');
  return found;
}

describe('the night chart', () => {
  it('draws an empty first bar, then one an hour, each at its least', () => {
    const view = chart();
    expect(view.night).toBe(true);
    expect(view.step).toBe(1);
    expect(view.bars).toHaveLength(10);
    expect(view.bars[0]?.height).toBe(0);
    // Scale 0 to 9 in, in 3 steps of 3 in, 40 px each.
    expect(view.plot).toBe(120);
    expect(view.bars.map((bar) => Math.round(bar.height * 10) / 10)).toEqual([
      0, 1.3, 5.3, 13.3, 26.7, 41.3, 56, 65.3, 72, 81.3,
    ]);
    expect(view.range).toEqual({ bottom: 80, height: 40 });
    expect(view.endTop).toBe(120);
  });

  it('never says "Now", and labels Start, End and the span’s end alone of its hours', () => {
    const view = chart();
    const labels = [view.times, ...view.wider.map((tier) => tier.times)].flat();
    expect(labels.map((time) => time.label)).not.toContain(chanceCopy.now);
    // Heaviest 1 to 4 AM (instants 3 to 6): 4 AM at the span's end, nothing under the gray bar
    // at 1 AM or the lit bars at 2 and 3 AM; 12 AM is the third hour, outside the span.
    expect(view.times.map((time) => [time.at, time.label])).toEqual([
      [0, `10${NBSP}PM`],
      [2, `12${NBSP}AM`],
      [6, `4${NBSP}AM`],
      [9, `7${NBSP}AM`],
    ]);
    expect(view.times.at(-1)?.end).toBe(true);
  });

  it('puts no time under the span’s start or a lit bar but the last, at any width (critic r2 B1)', () => {
    // Every span a 9-hour night can hold, 3 and 4 hours long, on the phone's plot and every wider
    // one, in the school's zone and the viewer's: the key's hours are never contradicted.
    const zonesSeen: Zones[] = [HERE, { school: ZONE, viewer: 'America/New_York' }];
    let checked = 0;
    for (let first = 0; first <= 6; first++) {
      for (const length of [3, 4]) {
        const last = first + length;
        if (last > 9) continue;
        const spanned = night({ ...RAW, heavy: [first, last] });
        if (spanned === null) throw new Error('no night');
        for (const zones of zonesSeen) {
          const view = chart(detail({ night: spanned }), NOW, zones);
          expect(view.bars.map((bar, at) => (bar.lit ? at : -1)).filter((at) => at >= 0)).toEqual(
            Array.from({ length }, (_, k) => first + 1 + k),
          );
          for (const tier of [view.times, ...view.wider.map((more) => more.times)]) {
            const ats = tier.map((time) => time.at);
            for (let at = Math.max(1, first); at < last; at++) expect(ats).not.toContain(at);
            expect(ats).toContain(0);
            expect(ats).toContain(9);
            checked += 1;
          }
          // The key names the span's own hours, from its gray bar's instant to its last lit bar's.
          expect(view.key[0]).toEqual({
            mark: 'heavy',
            text: chanceFormat.heaviestKey(
              spanned.instants[first] ?? new Date(NaN),
              spanned.instants[last] ?? new Date(NaN),
              zones,
            ),
          });
        }
      }
    }
    expect(checked).toBeGreaterThanOrEqual(26);
  });

  it('lights the heaviest span and keys its own hours', () => {
    const view = chart();
    expect(view.bars.map((bar) => bar.lit)).toEqual([
      false, false, false, false, true, true, true, false, false, false,
    ]); // prettier-ignore
    expect(view.key).toEqual([
      { mark: 'heavy', text: `Heaviest snow 1 to 4${NBSP}AM` },
      { mark: 'end', value: `6 to 9${NBSP}in`, rest: ` by 7${NBSP}AM`, glyph: 'range' },
    ]);
  });

  it('keys no span when there is none, and gives tenths under 2 inches', () => {
    const light = night({
      least: [0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 1.0, 1.1, 1.1],
      low: 1.1,
      high: 1.7,
    });
    const view = chart(detail({ night: light }));
    expect(view.bars.some((bar) => bar.lit)).toBe(false);
    expect(view.key).toEqual([
      { mark: 'end', value: `1.1 to 1.7${NBSP}in`, rest: ` by 7${NBSP}AM`, glyph: 'range' },
    ]);
  });

  it('is titled new snow, sums up in a sentence, and says its forecast’s time', () => {
    const view = chart();
    expect(view.title).toBe('New snow, hour by hour');
    expect(view.summary).toBe(
      `From 10${NBSP}PM to 7${NBSP}AM, the weather service’s 7${NBSP}PM hourly forecast has ` +
        '6 to 9 inches of new snow at the district’s public schools.',
    );
    expect(view.note).toBe(`From the 7${NBSP}PM hourly forecast`);
  });

  it('says the zone where the viewer’s clock differs', () => {
    const view = chart(detail(), NOW, { school: ZONE, viewer: 'America/New_York' });
    const end = view.key.at(-1);
    const zones = { school: ZONE, viewer: 'America/New_York' };
    expect(end?.mark === 'end' ? end.rest : '').toBe(
      ` by ${chanceFormat.clock(at('2026-01-13T13:00:00Z'), zones)}`,
    );
    expect(end?.mark === 'end' ? end.rest : '').toContain('CT');
  });

  it('centres each time under its bar where the bar is wider than the words (critic r1 S5)', () => {
    // 3 AM: three bars, 4 to 7 AM, on a 288 px plot: each bar is 43 px, wider than its time.
    const late = night(
      { least: [0.3, 0.7, 1.2], low: 1.2, high: 1.6 },
      at('2026-01-13T09:00:00Z'),
      at('2026-01-13T08:00:00Z'),
    );
    const view = chart(detail({ night: late }), at('2026-01-13T09:05:00Z'));
    expect(view.times.map((time) => [time.label, time.centred])).toEqual([
      [`4${NBSP}AM`, true],
      [`6${NBSP}AM`, true],
      [`7${NBSP}AM`, true],
    ]);
    // 9 PM: ten instants, each bar 17 px: the times start at their bars, the last at the end.
    expect(chart().times.some((time) => time.centred === true)).toBe(false);
    expect(chart().times.at(-1)?.end).toBe(true);
  });

  it('is gone once its forecast is too old or its first hour is past', () => {
    expect(chartView(detail(), new Date(CYCLE.getTime() + 196 * MINUTE), HERE)).toBeNull();
    const fresh = detail({ night: night(RAW, GENERATED, at('2026-01-13T02:00:00Z')) });
    expect(chartView(fresh, at('2026-01-13T05:00:00Z'), HERE)).toBeNull();
    expect(chartView(fresh, at('2026-01-13T04:59:00Z'), HERE)).not.toBeNull();
  });
});

describe('the usual announcement on the night chart', () => {
  // A chart of 4 to 7 AM (made at 3:30 AM), and a usual announcement of 5:30 AM.
  const late = night(
    { least: [1.0, 2.0, 3.0], low: 3, high: 4 },
    at('2026-01-13T09:30:00Z'),
    at('2026-01-13T08:00:00Z'),
  );
  const withAnnouncement = (announcesAt: Date) => detail({ night: late, announcesAt });

  it('is on the chart inside the night and within three hours, at its hour', () => {
    const view = chart(withAnnouncement(at('2026-01-13T11:30:00Z')), at('2026-01-13T09:40:00Z'));
    expect(view.announces).toBe(1.5);
    expect(view.key.map((row) => row.mark)).toEqual(['announces', 'end']);
  });

  it('stays on the chart 2.9 hours past, and is on neither at 3.1 (the timeline’s grace)', () => {
    const announcesAt = at('2026-01-13T10:00:00Z');
    const now29 = new Date(announcesAt.getTime() + 174 * MINUTE);
    const now31 = new Date(announcesAt.getTime() + 186 * MINUTE);
    // A chart made at 4 AM, its first hour 4 to 5 AM CST, kept through the grace for the test.
    const early = night(
      { least: [1.0, 2.0, 3.0], low: 3, high: 4 },
      at('2026-01-13T09:30:00Z'),
      at('2026-01-13T08:00:00Z'),
    );
    if (early === null) throw new Error('no night');
    const held = { ...early, start: new Date(now31.getTime() - 30 * MINUTE), nightAt: now31 };
    const at29 = chartView(
      detail({
        night: { ...held, start: new Date(now29.getTime() - 30 * MINUTE), nightAt: now29 },
        announcesAt,
      }),
      now29,
      HERE,
    );
    expect(at29?.announces).not.toBeNull();
    const at31 = chartView(detail({ night: held, announcesAt }), now31, HERE);
    expect(at31?.announces ?? null).toBeNull();
    // Nor on the timeline (and once the day is under way, there is no chance to show it by).
    const section = chanceView(input({ now: now31 }, detail({ night: held, announcesAt })));
    expect(section?.moments.some((moment) => moment.mark === 'announces') ?? false).toBe(false);
  });

  it('is on the timeline, not the chart, before Start or after End', () => {
    const before = chanceView(input({}, detail({ announcesAt: at('2026-01-13T03:30:00Z') })));
    expect(before?.chart?.announces).toBeNull();
    expect(before?.moments.some((moment) => moment.mark === 'announces')).toBe(true);
    const after = chanceView(input({}, detail({ announcesAt: at('2026-01-13T13:15:00Z') })));
    expect(after?.chart?.announces).toBeNull();
    expect(after?.moments.some((moment) => moment.mark === 'announces')).toBe(true);
  });
});

describe('the snow reason beside a night chart', () => {
  it('states no amount while the night chart shows', () => {
    const view = chanceView(input());
    expect(view?.chart?.night).toBe(true);
    expect(view?.why?.lines.map((line) => line.text)).toEqual([
      `The 7:19${NBSP}PM forecast has more snow by 12${NBSP}PM than most storms.`,
    ]);
  });

  it('states its amount when there is no night chart', () => {
    const view = chanceView(input({}, detail({ night: null })));
    expect(view?.chart).toBeNull();
    expect(view?.why?.lines[0]?.text).toContain(`6 to 8 inches`);
  });

  it('states its amount once the night chart is gone', () => {
    const view = chanceView(input({ now: at('2026-01-13T05:00:00Z') }));
    expect(view?.chart).toBeNull();
    expect(view?.why?.lines[0]?.text).toContain(`6 to 8 inches`);
  });
});

describe('the night chart and the day under way (d04d680, a770f4c)', () => {
  // Made at 4:10 AM Tuesday in Kansas City from the 3 AM cycle: Start 5 AM, End 7 AM.
  const madeAt = at('2026-01-13T10:10:00Z');
  const early = night(
    { least: [0.4, 1.1], low: 1.1, high: 1.6 },
    madeAt,
    at('2026-01-13T09:00:00Z'),
  );
  const tuesday = detail({ night: early });
  const wednesday = detail({ night: null, why: null });
  const outlook: Outlook = {
    neighbors: [1, 2],
    timeZone: ZONE,
    today: {
      state: 'forecast',
      noSchool: 0.64,
      delay: 0.18,
      reasons: [0, 2],
      day: '2026-01-13',
      detail: tuesday,
    },
    tomorrow: {
      state: 'forecast',
      noSchool: 0.22,
      delay: 0.31,
      reasons: [2, 0],
      day: '2026-01-14',
      detail: wednesday,
    },
  };
  const viewAt = (iso: string) =>
    chanceView(input({ now: at(iso), outlook, decided: { today: false, tomorrow: false } }));

  it('shows Tuesday’s night beside Tuesday’s chance, never beside Wednesday’s, minute by minute', () => {
    expect(early).not.toBeNull();
    // 4:10 AM to 9 AM: whatever the hour the day turns (5 AM, then 7:30 AM, on the school's
    // clock), a night chart only ever sits beside its own day's chance.
    let nights = 0;
    for (let t = madeAt.getTime(); t <= at('2026-01-13T15:00:00Z').getTime(); t += MINUTE) {
      const view = viewAt(new Date(t).toISOString());
      if (view?.chart?.night === true) {
        nights += 1;
        expect(view.day).toBe('2026-01-13');
      }
    }
    expect(nights).toBeGreaterThan(0);
    // Shown at 4:59 AM, gone at 6 AM (its first hour past, its window closed), and Wednesday's
    // chance carries none by 9 AM.
    expect(viewAt('2026-01-13T10:59:00Z')?.chart?.night).toBe(true);
    expect(viewAt('2026-01-13T12:00:00Z')?.chart?.night ?? false).toBe(false);
    const later = viewAt('2026-01-13T15:00:00Z');
    expect(later?.day).toBe('2026-01-14');
    expect(later?.chart?.night ?? false).toBe(false);
    expect(later?.chart?.title ?? null).not.toBe(chanceCopy.newSnowTitle);
  });

  it('cannot be read as Wednesday’s night, so no file puts it there', () => {
    const raw = { least: [0.4, 1.1], low: 1.1, high: 1.6 };
    const context = { timeZone: ZONE, generatedAt: madeAt, nightAt: at('2026-01-13T09:00:00Z') };
    expect(nightOf(raw, { ...context, day: '2026-01-13' })).not.toBeNull();
    expect(nightOf(raw, { ...context, day: '2026-01-14' })).toBeNull();
  });
});
