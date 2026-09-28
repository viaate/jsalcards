import { describe, expect, it } from 'vitest';

import { copy, format } from '../../copy';
import type { ForecastDetail, WhyDetail } from '../../data/forecast-detail';
import type { Outlook } from '../../data/school-day';
import {
  MAX_NEIGHBOR_MOMENTS,
  chanceView,
  chartScale,
  chartTimes,
  chartView,
  headlineDay,
  neighborPosts,
  placeFlags,
  placeLit,
  shortDistrictName,
  timeGap,
  whyView,
} from '../chance';
import type { ClosingsFile } from '../../types/generated';
import type { ChanceInput, WhyView } from '../chance';
import {
  A_CLOSINGS,
  A_DETAIL,
  A_NOW,
  A_OUTLOOK,
  A_RECORD,
  A_WHY,
  B_DETAIL,
  B_NOW,
  B_OUTLOOK,
  CLOSED_TODAY,
  NAMES,
  STAMP,
  ZONE,
  nightOutlook,
} from './chance-fixtures';

const NBSP = ' ';
const MINUS = '−';
const at = (iso: string): Date => new Date(iso);

function nightBefore(overrides: Partial<ChanceInput> = {}): ChanceInput {
  return {
    outlook: A_OUTLOOK,
    decided: { today: false, tomorrow: false },
    status: [],
    district: 'Shawnee Mission',
    closings: A_CLOSINGS,
    names: NAMES,
    now: A_NOW,
    timeZone: ZONE,
    ...overrides,
  };
}

function nextMorning(overrides: Partial<ChanceInput> = {}): ChanceInput {
  return nightBefore({
    outlook: B_OUTLOOK,
    decided: { today: true, tomorrow: false },
    status: [CLOSED_TODAY],
    closings: null,
    now: B_NOW,
    ...overrides,
  });
}

/** A line of the sum as it reads: its points, then its sentence. */
function lines(why: WhyView | null): string[] {
  if (why === null) return [];
  return [
    `${why.base.number}% ${why.base.lead}${why.base.rest}`,
    ...why.lines.map((line) => `${line.points} ${line.lead}${line.rest}`),
    `${why.total.number}% ${why.total.text}`,
  ];
}

describe('the chance section, the night before', () => {
  const view = chanceView(nightBefore());

  it('leads with the chance, for the day it is for, and what moved it', () => {
    expect(view).toMatchObject({
      status: [],
      day: '2026-01-13',
      number: '64',
      meaning: 'Chance of no school Tuesday',
      moved: { direction: 'up', text: `Up from 41% at 5${NBSP}PM` },
      delay: '18% chance of a delayed start instead',
      timeZone: ZONE,
    });
  });

  it('lists the districts next door that already canceled, then when this one usually announces', () => {
    expect(
      view?.moments.map((moment) => [moment.time, moment.mark, moment.text, moment.at]),
    ).toEqual([
      [`8:41${NBSP}PM`, 'closed', 'Blue Valley canceled Tuesday', null],
      [`8:52${NBSP}PM`, 'closed', 'Olathe canceled Tuesday', null],
      [`5:30${NBSP}AM`, 'next', 'Shawnee Mission usually announces', at('2026-01-13T11:30:00Z')],
    ]);
    expect(format.countdown(at('2026-01-13T11:30:00Z'), A_NOW, ZONE)).toBe('in 8h 25m');
  });

  it('adds up to the headline, a sentence a reason, with the record under the reason it proves', () => {
    expect(lines(view?.why ?? null)).toEqual([
      '30% Where we start: Shawnee Mission cancels for about 3 in 10 winter storm warnings.',
      '+16 A bigger storm than most, 6 to 9 inches overnight. It closed 4 of the last 5 times it got 6 inches or more.',
      '+9 Blue Valley and Olathe, next door, have already canceled.',
      `+7 The heaviest snow falls from 2 to 5${NBSP}AM, just before the buses go out.`,
      `+5 The wind will make it feel like -4${NBSP}F at the bus stop.`,
      `${MINUS}3 The snow should stop by 7${NBSP}AM, which gives the plows a head start.`,
      '64% Chance of no school Tuesday',
    ]);
    expect(view?.why?.title).toBe('How we got 64%');
    expect(view?.why?.key).toBe(copy.chance.key);
    const storms = view?.why?.lines[0]?.record;
    expect(storms?.map((day) => [day.tone, day.label])).toEqual([
      ['closed', `8${NBSP}in`],
      ['closed', `10${NBSP}in`],
      ['closed', `6${NBSP}in`],
      ['delayed', `6${NBSP}in`],
      ['closed', `7${NBSP}in`],
    ]);
    expect(storms?.[3]?.spoken).toBe('Delayed, Feb 5, 2025, 6 inches');
    expect(view?.why?.base.record).toBeNull();
    expect(view?.why?.lines.slice(1).every((line) => line.record === null)).toBe(true);
  });

  it('draws the snow on the ground to 9 inches, with the times, the two moments and the range', () => {
    const chart = view?.chart;
    expect(chart?.title).toBe(copy.chance.snowTitle);
    expect(chart?.ticks.map((tick) => [tick.label, tick.bottom])).toEqual([
      ['0', 0],
      [`3${NBSP}in`, 40],
      [`6${NBSP}in`, 80],
      [`9${NBSP}in`, 120],
    ]);
    expect(chart?.plot).toBe(120);
    expect(chart?.bars.map((bar) => bar.lit)).toEqual([
      ...Array<boolean>(6).fill(false),
      true,
      true,
      true,
      false,
      false,
    ]);
    expect(chart?.bars[10]?.height).toBeCloseTo(100, 6);
    // A trace of snow shows; no snow is no bar.
    expect(chart?.bars[2]?.height).toBeCloseTo(2.667, 3);
    expect(chart?.bars[0]?.height).toBe(0);
    expect(chart?.times.map((time) => [time.at, time.label, time.sub])).toEqual([
      [0, `9${NBSP}PM`, copy.chance.now],
      [2, `11${NBSP}PM`, null],
      [5, `2${NBSP}AM`, null],
      [8, `5${NBSP}AM`, null],
      [10, `7${NBSP}AM`, null],
    ]);
    expect(chart?.flags).toEqual([
      {
        key: 'announces',
        at: 8.5,
        label: `${copy.chance.usuallyAnnounces} 5:30${NBSP}AM`,
        prefer: 'left',
        downTo: 0,
      },
      {
        key: 'buses',
        at: 10,
        label: `${copy.chance.buses} 7${NBSP}AM`,
        prefer: 'right',
        downTo: 123,
      },
    ]);
    expect(chart?.range).toEqual({ bottom: 80, height: 40 });
    expect(chart?.end).toEqual({ label: `6 to 9${NBSP}in`, bottom: 100 });
    expect(chart?.lit).toMatchObject({
      label: `${copy.chance.heaviest} 2 to 5${NBSP}AM`,
      first: 6,
      last: 8,
    });
    expect(chart?.summary).toBe(
      `By 7${NBSP}AM, when the buses run, 6 to 9 inches of snow should be on the ground.`,
    );
  });
});

describe('the chance section, the next morning', () => {
  const view = chanceView(nextMorning());

  it('says the decided status first, then the next day’s chance and what moved it', () => {
    expect(view).toMatchObject({
      status: [CLOSED_TODAY],
      day: '2026-01-14',
      number: '22',
      meaning: 'Chance of no school Wednesday',
      moved: { direction: 'down', text: 'Down from 30% last night' },
      delay: '31% chance of a delayed start instead',
    });
    expect(view?.moments.map((moment) => [moment.time, moment.mark, moment.text])).toEqual([
      [`6:00${NBSP}AM`, 'event', 'Snow stopped, 8 inches in all'],
      [`5:30${NBSP}AM`, 'next', 'Shawnee Mission usually announces'],
    ]);
    expect(format.countdown(at('2026-01-14T11:30:00Z'), B_NOW, ZONE)).toBe('Wednesday, in 23h 10m');
  });

  it('adds up from the day after a snow day, with the record under the base', () => {
    expect(lines(view?.why ?? null)).toEqual([
      '25% Where we start: after a snow day, Shawnee Mission stays closed the next day about 1 time in 4.',
      `${MINUS}8 The snow stopped around 6${NBSP}AM, so the plows have all day to clear the roads.`,
      `+6 It will feel like -8${NBSP}F at the bus stop on Wednesday morning.`,
      `${MINUS}5 Sun this afternoon will help the salt melt the ice.`,
      '+4 Some side streets could stay icy after 8 inches of snow.',
      '22% Chance of no school Wednesday',
    ]);
    expect(view?.why?.base.record?.map((day) => [day.tone, day.label])).toEqual([
      ['open', copy.chance.open],
      ['closed', copy.chance.closed],
      ['open', copy.chance.open],
      ['open', copy.chance.open],
    ]);
  });

  it('draws how cold it will feel tonight, hanging below 0 F, the bus hour lit', () => {
    const chart = view?.chart;
    expect(chart?.title).toBe(copy.chance.coldTonight);
    expect(chart?.ticks.map((tick) => [tick.label, tick.bottom])).toEqual([
      [`-10${NBSP}F`, 0],
      [`-5${NBSP}F`, 40],
      [`0${NBSP}F`, 80],
    ]);
    expect(chart?.bars.map((bar) => bar.below)).toEqual(Array<boolean>(11).fill(true));
    expect(chart?.bars.map((bar) => bar.lit)).toEqual([...Array<boolean>(10).fill(false), true]);
    // The last bar hangs from the zero rule down to -8 F.
    expect(chart?.bars[10]).toMatchObject({ bottom: 16, height: 64 });
    expect(chart?.end).toEqual({ label: `-8${NBSP}F`, bottom: 16 });
    expect(chart?.range).toBeNull();
    expect(chart?.lit).toBeNull();
    // The night is still to come: no "Now" under its first hour.
    expect(chart?.times.map((time) => [time.label, time.sub])).toEqual([
      [`9${NBSP}PM`, null],
      [`12${NBSP}AM`, null],
      [`3${NBSP}AM`, null],
      [`7${NBSP}AM`, null],
    ]);
    expect(chart?.flags.find((flag) => flag.key === 'buses')?.downTo).toBe(83);
  });
});

describe('what the section leaves out', () => {
  it('has no section without a forecast for a day that is not decided', () => {
    expect(chanceView(nightBefore({ outlook: null }))).toBeNull();
    expect(chanceView(nightBefore({ outlook: 'not_enough_data' }))).toBeNull();
    expect(chanceView(nightBefore({ decided: { today: false, tomorrow: true } }))).toBeNull();
    const quiet: Outlook = { today: { state: 'no_threat' }, tomorrow: { state: 'no_threat' } };
    expect(chanceView(nightBefore({ outlook: quiet }))).toBeNull();
    // Both days decided the next morning: nothing left to give a chance for.
    expect(chanceView(nextMorning({ decided: { today: true, tomorrow: true } }))).toBeNull();
  });

  it('takes today’s chance before tomorrow’s, but not once its buses have long run', () => {
    expect(headlineDay(B_OUTLOOK, { today: false, tomorrow: false }, B_NOW)?.day).toBe(
      '2026-01-13',
    );
    const underWay: Outlook = {
      today: {
        state: 'forecast',
        noSchool: 0.5,
        delay: 0.1,
        reasons: [0],
        day: '2026-01-13',
        detail: { ...A_DETAIL, busesAt: at('2026-01-13T13:00:00Z') },
      },
      tomorrow: null,
    };
    expect(
      headlineDay(underWay, { today: false, tomorrow: false }, at('2026-01-13T14:59:00Z')),
    ).not.toBeNull();
    expect(
      headlineDay(underWay, { today: false, tomorrow: false }, at('2026-01-13T15:01:00Z')),
    ).toBeNull();
  });

  it('shows the headline alone when the forecast gives nothing else', () => {
    const bare: Outlook = {
      today: { state: 'forecast', noSchool: 0.5, delay: 0, reasons: [0], day: '2026-01-12' },
      tomorrow: null,
    };
    expect(chanceView(nightBefore({ outlook: bare, now: at('2026-01-12T12:00:00Z') }))).toEqual({
      status: [],
      day: '2026-01-12',
      number: '50',
      meaning: 'Chance of no school Monday',
      moved: null,
      moments: [],
      chart: null,
      why: null,
      delay: null,
      timeZone: ZONE,
    });
  });

  it('never shows a sum that does not add up to the headline, and shows the rest', () => {
    const off = { ...A_DETAIL, why: { ...A_WHY, base: { ...A_WHY.base, points: 31 } } };
    const view = chanceView(nightBefore({ outlook: nightOutlook(off) }));
    expect(view?.why).toBeNull();
    expect(view?.number).toBe('64');
    expect(view?.chart).not.toBeNull();
    expect(view?.moments).toHaveLength(3);
    const args = { day: '2026-01-13', district: 'Shawnee Mission', names: NAMES, now: A_NOW };
    const why = (detail: ForecastDetail, chance = 0.64): WhyView | null =>
      whyView({ detail, chance, timeZone: ZONE, ...args });
    expect(why(A_DETAIL)).not.toBeNull();
    // One point off either way.
    expect(why(A_DETAIL, 0.63)).toBeNull();
    expect(why(A_DETAIL, 0.65)).toBeNull();
    // A reason left out would leave the sum short.
    expect(why({ ...A_DETAIL, why: { ...A_WHY, reasons: A_WHY.reasons.slice(1) } })).toBeNull();
    // Points that are not whole numbers, even when they add up.
    const halves: WhyDetail = {
      base: { kind: 'similar_days', points: 29.5 },
      reasons: [{ kind: 'sun', points: 34.5 }],
    };
    expect(why({ ...A_DETAIL, why: halves })).toBeNull();
    // Nothing to explain.
    expect(why({ ...A_DETAIL, why: null })).toBeNull();
    // A sum to 0 or 100 would claim a certainty the headline does not ("<1%", ">99%").
    const none: WhyDetail = { base: { kind: 'similar_days', points: 0 }, reasons: [] };
    expect(why({ ...A_DETAIL, why: none }, 0)).toBeNull();
    const all: WhyDetail = { base: { kind: 'similar_days', points: 100 }, reasons: [] };
    expect(why({ ...A_DETAIL, why: all }, 1)).toBeNull();
    // A base alone, when it is the chance.
    const alone: WhyDetail = { base: { kind: 'similar_days', points: 20 }, reasons: [] };
    expect(lines(why({ ...A_DETAIL, why: alone }, 0.2))).toEqual([
      '20% Where we start: on days like this, Shawnee Mission closes about 1 time in 5.',
      '20% Chance of no school Tuesday',
    ]);
  });

  it('leaves the sum out when a reason cannot be said, and says what it can', () => {
    const args = { day: '2026-01-13', district: 'Shawnee Mission', now: A_NOW, timeZone: ZONE };
    // A record reason with no record to count.
    const counting: WhyDetail = {
      base: A_WHY.base,
      reasons: [
        { kind: 'snow_total', points: 12, low: 6, high: 9, overnight: true },
        { kind: 'record', points: 4 },
        ...A_WHY.reasons.slice(1),
      ],
    };
    const record = { ...A_DETAIL, why: counting };
    expect(whyView({ detail: record, chance: 0.64, names: NAMES, ...args })).toBeNull();
    const counted = whyView({
      detail: { ...record, record: { ...A_RECORD, proves: 'record' } },
      chance: 0.64,
      names: NAMES,
      ...args,
    });
    expect(lines(counted).slice(1, 3)).toEqual([
      '+12 A bigger storm than most, 6 to 9 inches overnight.',
      '+4 Shawnee Mission’s record: it closed 4 of the last 5 times it got 6 inches or more.',
    ]);
    expect(counted?.lines[1]?.record).toHaveLength(5);
    // The directory not read (yet): the districts next door by how many.
    const unnamed = whyView({ detail: A_DETAIL, chance: 0.64, names: null, ...args });
    expect(unnamed?.lines[1]).toMatchObject({
      lead: '2 districts next door',
      rest: ' have already canceled.',
    });
  });
});

describe('the timeline', () => {
  it('takes each district next door once, at its first post, earliest first', () => {
    expect(
      neighborPosts(A_CLOSINGS, '2026-01-13', [1, 2], NAMES, A_NOW).map((post) => [
        post.district,
        post.status,
        post.at.toISOString(),
      ]),
    ).toEqual([
      [1, 'closed', '2026-01-13T02:41:00.000Z'],
      [2, 'closed', '2026-01-13T02:52:00.000Z'],
    ]);
    // De Soto posted too, but is not next door.
    expect(neighborPosts(A_CLOSINGS, '2026-01-13', [3], NAMES, A_NOW)).toHaveLength(1);
    expect(neighborPosts(A_CLOSINGS, '2026-01-13', [], NAMES, A_NOW)).toEqual([]);
  });

  it('reads nothing from another directory, another day, or without names or times', () => {
    const other = { ...A_CLOSINGS, directory: { ...STAMP, schools: 7 } };
    expect(neighborPosts(other, '2026-01-13', [1, 2], NAMES, A_NOW)).toEqual([]);
    expect(neighborPosts(A_CLOSINGS, '2026-01-14', [1, 2], NAMES, A_NOW)).toEqual([]);
    expect(neighborPosts(A_CLOSINGS, '2026-01-13', [1, 2], null, A_NOW)).toEqual([]);
    expect(neighborPosts(null, '2026-01-13', [1, 2], NAMES, A_NOW)).toEqual([]);
    const untimed: ClosingsFile = {
      ...A_CLOSINGS,
      days: A_CLOSINGS.days.map((group) => ({ ...group, announced: [null, null, 8, null] })),
    };
    expect(
      neighborPosts(untimed, '2026-01-13', [1, 2], NAMES, A_NOW).map((p) => p.district),
    ).toEqual([2]);
    // A post after now is not on the timeline yet.
    expect(
      neighborPosts(A_CLOSINGS, '2026-01-13', [1, 2], NAMES, at('2026-01-13T02:45:00Z')),
    ).toHaveLength(1);
  });

  it('keeps the timeline short: the first districts to post', () => {
    const many: ClosingsFile = {
      ...A_CLOSINGS,
      directory: { ...STAMP, schools: 8 },
      days: [
        {
          day: '2026-01-13',
          gaps: [0, 0, 0, 0, 0, 0],
          statuses: [0, 1, 2, 3, 0, 0],
          announced: [60, 50, 40, 30, 20, 10],
          reasons: [0, 0, 0, 0, 0, 0],
          shifts: [null, null],
          clocks: [null, null],
        },
      ],
    };
    const names = { ...NAMES, stamp: many.directory, districtOf: (school: number) => school + 1 };
    const posts = neighborPosts(many, '2026-01-13', [1, 2, 3, 4, 5, 6], names, A_NOW);
    expect(posts.map((post) => [post.district, post.status])).toEqual([
      [1, 'closed'],
      [2, 'delayed'],
      [3, 'remote'],
      [4, 'earlyDismissal'],
    ]);
    expect(posts).toHaveLength(MAX_NEIGHBOR_MOMENTS);
  });

  it('drops the usual announcement once it is long past', () => {
    const late = chanceView(nightBefore({ now: at('2026-01-13T14:31:00Z') }));
    expect(late?.moments.map((moment) => moment.mark)).toEqual(['closed', 'closed']);
    const soon = chanceView(nightBefore({ now: at('2026-01-13T14:29:00Z') }));
    expect(soon?.moments.at(-1)?.mark).toBe('next');
  });
});

describe('the countdown', () => {
  const ny = 'America/New_York';

  it('counts hours and minutes, and says the day when it is half a day or more away', () => {
    const announce = at('2026-01-13T11:30:00Z');
    expect(format.countdown(announce, at('2026-01-13T11:29:30Z'), ZONE)).toBe('in 1m');
    expect(format.countdown(announce, at('2026-01-13T11:15:00Z'), ZONE)).toBe('in 15m');
    expect(format.countdown(announce, at('2026-01-13T09:30:00Z'), ZONE)).toBe('in 2h');
    expect(format.countdown(announce, at('2026-01-12T23:31:00Z'), ZONE)).toBe('in 11h 59m');
    expect(format.countdown(announce, at('2026-01-12T23:30:00Z'), ZONE)).toBe('Tuesday, in 12h');
    expect(format.countdown(announce, announce, ZONE)).toBeNull();
    expect(format.countdown(announce, at('2026-01-13T12:00:00Z'), ZONE)).toBeNull();
  });

  it('runs across midnight, and names the day where the viewer is', () => {
    // 11:50 PM to 12:10 AM, Central.
    expect(format.countdown(at('2026-01-13T06:10:00Z'), at('2026-01-13T05:50:00Z'), ZONE)).toBe(
      'in 20m',
    );
    // 11:30 PM Tuesday in Kansas City is 12:30 AM Wednesday in New York.
    const late = at('2026-01-14T05:30:00Z');
    const morning = at('2026-01-13T12:00:00Z');
    expect(format.countdown(late, morning, ZONE)).toBe('Tuesday, in 17h 30m');
    expect(format.countdown(late, morning, ny)).toBe('Wednesday, in 17h 30m');
    // Across a change of clocks: real hours, not wall-clock ones.
    expect(format.countdown(at('2026-03-08T12:00:00Z'), at('2026-03-08T06:00:00Z'), ZONE)).toBe(
      'in 6h',
    );
  });
});

describe('the chart', () => {
  it('scales snow to 2 or 3 round steps, the range’s high end included', () => {
    expect(chartScale('snow_total', [0, 3, 7.5], 9)).toMatchObject({ max: 9, step: 3 });
    expect(chartScale('snow_total', [0, 3, 7.5], null)).toMatchObject({ max: 9, step: 3 });
    expect(chartScale('snow_total', [0, 1, 2], 3).ticks).toEqual([0, 1, 2, 3]);
    expect(chartScale('snow_total', [0, 0.4], null).ticks).toEqual([0, 0.5, 1]);
    expect(chartScale('snow_total', [0, 0], null).ticks).toEqual([0, 0.5, 1]);
    expect(chartScale('snow_total', [0, 14], 16).ticks).toEqual([0, 6, 12, 18]);
    expect(chartScale('snow_total', [0, 30], 40).ticks).toEqual([0, 15, 30, 45]);
    expect(chartScale('snow_total', [0, 3.1], 4.4).ticks).toEqual([0, 2, 4, 6]);
  });

  it('scales how cold it feels around 0 F, on the side the values are', () => {
    expect(chartScale('wind_chill', [-1, -8], null).ticks).toEqual([-10, -5, 0]);
    expect(chartScale('wind_chill', [-1, -2], null).ticks).toEqual([-10, -5, 0]);
    expect(chartScale('wind_chill', [4, 12], null).ticks).toEqual([0, 5, 10, 15]);
    expect(chartScale('wind_chill', [8, -8], null).ticks).toEqual([-10, 0, 10]);
    expect(chartScale('wind_chill', [-25, -31], null).ticks).toEqual([-40, -20, 0]);
    expect(chartScale('wind_chill', [-80, 60], null).ticks).toEqual([-100, 0, 100]);
  });

  it('keeps the times at its foot apart, however many hours it has', () => {
    expect(timeGap(11)).toBe(2);
    expect(timeGap(6)).toBe(1);
    expect(timeGap(24)).toBe(4);
    expect(timeGap(36)).toBe(6);
    for (const count of [2, 5, 11, 17, 24, 36]) {
      const times = chartTimes({
        count,
        start: at('2026-01-13T03:00:00Z'),
        values: Array.from({ length: count }, (_, i) => i / 2),
        kind: 'snow_total',
        heavy: count > 4 ? { first: 3, last: 4 } : null,
        now: at('2026-01-13T03:10:00Z'),
        timeZone: ZONE,
      });
      expect(times[0]?.at).toBe(0);
      expect(times.at(-1)?.at).toBe(count - 1);
      for (let i = 1; i < times.length; i++) {
        expect((times[i]?.at ?? 0) - (times[i - 1]?.at ?? 0)).toBeGreaterThanOrEqual(
          timeGap(count),
        );
      }
    }
  });

  it('starts from this hour: the hours gone by are not the night ahead', () => {
    const later = chartView(A_DETAIL, at('2026-01-13T05:30:00Z'), ZONE);
    expect(later?.bars).toHaveLength(9);
    expect(later?.times[0]).toEqual({ at: 0, label: `11${NBSP}PM`, sub: copy.chance.now });
    expect(later?.flags.map((flag) => flag.at)).toEqual([6.5, 8]);
    expect(later?.lit).toMatchObject({
      first: 4,
      last: 6,
      label: `${copy.chance.heaviest} 2 to 5${NBSP}AM`,
    });
    // Two hours left draw two bars; the bus hour alone is no chart.
    expect(chartView(A_DETAIL, at('2026-01-13T12:30:00Z'), ZONE)?.bars).toHaveLength(2);
    expect(chartView(A_DETAIL, at('2026-01-13T13:30:00Z'), ZONE)).toBeNull();
    expect(chartView({ ...A_DETAIL, hours: null }, A_NOW, ZONE)).toBeNull();
    // An announcement outside the night drawn has no line.
    const evening = chartView(
      { ...A_DETAIL, announcesAt: at('2026-01-13T01:30:00Z') },
      A_NOW,
      ZONE,
    );
    expect(evening?.flags.map((flag) => flag.key)).toEqual(['buses']);
    expect(chartView(B_DETAIL, B_NOW, 'America/Los_Angeles')?.title).toBe(copy.chance.coldTonight);
    expect(chartView(B_DETAIL, B_NOW, 'Europe/Berlin')?.title).toBe(copy.chance.coldTitle);
  });

  it('puts the moments’ words on their own sides, else the other, else a second row', () => {
    // The mock's night: the announcement's words left of its line, the buses' right of theirs.
    expect(
      placeFlags(
        [
          { x: 250, width: 150, prefer: 'left' },
          { x: 290, width: 66, prefer: 'right' },
        ],
        -34,
        386,
      ),
    ).toEqual([
      { left: 94, row: 0 },
      { left: 296, row: 0 },
    ]);
    // No room on the left early in the night: its words go right of the line.
    expect(placeFlags([{ x: 20, width: 150, prefer: 'left' }], -34, 386)).toEqual([
      { left: 26, row: 0 },
    ]);
    // Two lines close together, with room on neither side of the first for both: a second row.
    const crowded = placeFlags(
      [
        { x: 300, width: 150, prefer: 'left' },
        { x: 250, width: 120, prefer: 'right' },
      ],
      -34,
      386,
    );
    expect(crowded).toEqual([
      { left: 144, row: 0 },
      { left: 256, row: 1 },
    ]);
    // Words wider than any room stay inside the chart.
    const wide = placeFlags([{ x: 100, width: 500, prefer: 'left' }], -34, 386);
    expect(wide[0]?.left).toBe(-34);
    // Whatever the widths, nothing meets and nothing leaves the chart.
    for (let a = 0; a < 320; a += 16) {
      for (let b = a; b < 320; b += 16) {
        const boxes = placeFlags(
          [
            { x: a, width: 150, prefer: 'left' },
            { x: b, width: 70, prefer: 'right' },
          ],
          -34,
          386,
        );
        const [first, second] = boxes;
        if (first === undefined || second === undefined) throw new Error('unplaced');
        expect(first.left).toBeGreaterThanOrEqual(-34);
        expect(second.left + 70).toBeLessThanOrEqual(386);
        if (first.row === second.row) {
          expect(first.left + 150 <= second.left || second.left + 70 <= first.left).toBe(true);
        }
      }
    }
  });

  it('puts the lit hours’ words beside them, else above them, else nowhere', () => {
    const base = {
      width: 140,
      height: 14,
      floor: 44,
      runTop: 84,
      plot: 120,
      minLeft: 0,
      maxRight: 386,
    };
    expect(placeLit({ ...base, runLeft: 180 })).toEqual({ left: 38, bottom: 50 });
    // The heaviest hours early in the night: above them.
    expect(placeLit({ ...base, runLeft: 40 })).toEqual({ left: 40, bottom: 90 });
    // Nowhere they fit: left out, and the bars stay lit.
    expect(placeLit({ ...base, runLeft: 40, runTop: 110 })).toBeNull();
    expect(placeLit({ ...base, runLeft: 300, floor: 110 })).toBeNull();
  });
});

describe('district names', () => {
  it('says a district as a family does', () => {
    expect(shortDistrictName('Shawnee Mission Public Schools')).toBe('Shawnee Mission');
    expect(shortDistrictName('Blue Valley')).toBe('Blue Valley');
    expect(shortDistrictName('Lee County Schools')).toBe('Lee County');
    expect(shortDistrictName('Kansas City 33 School District')).toBe('Kansas City 33');
    expect(shortDistrictName('Center Joint Unified School District')).toBe('Center');
    expect(shortDistrictName('Hickman Mills C-1')).toBe('Hickman Mills C-1');
    expect(shortDistrictName('Independence School District')).toBe('Independence');
    expect(shortDistrictName('Katy ISD')).toBe('Katy');
    expect(shortDistrictName('Public Schools')).toBe('Public Schools');
    expect(shortDistrictName('Gardner CCSD 72C')).toBe('Gardner CCSD 72C');
  });
});
