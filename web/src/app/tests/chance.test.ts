import { describe, expect, it } from 'vitest';

import { chanceCopy, chanceFormat } from '../../copy-chance';
import type { Zones } from '../../copy-chance';
import type { ForecastDetail, WhyDetail } from '../../data/forecast-detail';
import type { Outlook } from '../../data/school-day';
import {
  MAX_BARS,
  MAX_NEIGHBOR_MOMENTS,
  NARROWEST_PLOT_PX,
  TIME_LABEL_PX,
  WIDER_PLOTS_PX,
  ZONE_LABEL_PX,
  atLocalHour,
  chanceView,
  chartScale,
  chartTimes,
  chartView,
  headlineDay,
  hoursPerBar,
  neighborPosts,
  shortDistrictName,
  standings,
  toldApart,
  whyView,
} from '../chance';
import type { ClosingsFile, Status } from '../../types/generated';
import type { ChanceInput, DistrictNaming, Names, WhyView } from '../chance';
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
  NAME_OF,
  STAMP,
  ZONE,
  nightOutlook,
} from './chance-fixtures';

const NBSP = '\u00a0';
const MINUS = '\u2212';
const at = (iso: string): Date => new Date(iso);
/** The districts next door on the timeline, from the live file. */
const postsOf = (
  closings: ClosingsFile | null,
  day: string,
  neighbors: readonly number[],
  names: Names | null,
  now: Date,
) => neighborPosts(standings(closings, day, neighbors, names, now), neighbors);
/** The school's clock, read where the school is. */
const HERE: Zones = { school: ZONE, viewer: ZONE };

function nightBefore(overrides: Partial<ChanceInput> = {}): ChanceInput {
  return {
    outlook: A_OUTLOOK,
    decided: { today: false, tomorrow: false },
    status: [],
    district: 'Shawnee Mission',
    state: 'KS',
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
    `${why.base.number}% ${why.base.text}`,
    ...why.lines.map((line) => `${line.points} ${line.text}`),
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
    });
    // The countdown in the school's own time zone, the weekday its own once half a day away.
    expect(view?.countdown(at('2026-01-13T11:30:00Z'), A_NOW)).toBe('in 8h 25m');
    expect(view?.countdown(at('2026-01-14T11:30:00Z'), A_NOW)).toBe('Wednesday, in 32h 25m');
    expect(view?.countdown(at('2026-01-13T11:30:00Z'), at('2026-01-13T11:30:00Z'))).toBeNull();
  });

  it('lists the districts next door that already canceled; the chart says when this one announces', () => {
    expect(
      view?.moments.map((moment) => [moment.time, moment.mark, moment.text, moment.at]),
    ).toEqual([
      [`8:41${NBSP}PM`, 'closed', 'Blue Valley canceled Tuesday', null],
      [`8:52${NBSP}PM`, 'closed', 'Olathe canceled Tuesday', null],
    ]);
    // On the chart, at its line, counting down; once it has come, its time alone.
    expect(view?.announces(A_NOW)).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}8h${NBSP}25m`,
    );
    expect(view?.announces(at('2026-01-13T11:29:30Z'))).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}1m`,
    );
    expect(view?.announces(at('2026-01-13T11:30:00Z'))).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM`,
    );
  });

  it('adds up to the headline, naming what the chart and the timeline already say', () => {
    expect(lines(view?.why ?? null)).toEqual([
      '30% Shawnee Mission cancels for 3 in 10 winter storm warnings.',
      // "6 to 9 in" is the chart's answer; the record is said only here.
      '+16 More snow than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
      // Who canceled, and when, is the timeline's.
      '+9 Districts next door canceled.',
      // The hours are the chart's key.
      '+7 Heaviest snow just before the buses.',
      `+5 The forecast has a wind chill of ${MINUS}4${NBSP}F at the bus stop.`,
      // The snow ends as the buses go out, whose hour is the chart's: no head start.
      `${MINUS}3 The forecast has the snow ending as the buses go out.`,
    ]);
    expect(view?.why?.title).toBe('How we got 64%');
  });

  it('says each fact once in the whole section', () => {
    const said = [
      ...(view?.moments.map((moment) => `${moment.time} ${moment.text}`) ?? []),
      ...(view?.chart?.key.map((row) => (row.mark === 'buses' ? row.value + row.rest : row.text)) ??
        []),
      ...lines(view?.why ?? null),
    ].join(' | ');
    for (const fact of [
      `5:30${NBSP}AM`,
      `2 to 5${NBSP}AM`,
      `7${NBSP}AM`,
      '6 to 9',
      'Blue Valley',
      'Olathe',
    ]) {
      expect(said.split(fact).length - 1, fact).toBe(1);
    }
  });

  it('draws the snow on the ground to 9 inches, its marks, and the key to them', () => {
    const chart = view?.chart;
    expect(chart?.title).toBe(chanceCopy.snowTitle);
    // A scale to 9 inches in three steps; its one rule is the zero at the foot.
    expect(chart?.plot).toBe(120);
    expect(chart?.zero).toBe(0);
    expect(chart?.step).toBe(1);
    // The heaviest snow, 2 to 5 AM, is the 3, 4 and 5 AM bars' growth: those three are lit, and
    // the 2 AM bar, the snow on the ground as it starts, is not.
    expect(chart?.bars.map((bar) => bar.lit)).toEqual([
      ...Array<boolean>(6).fill(false),
      true,
      true,
      true,
      false,
      false,
    ]);
    expect(chart?.bars[10]?.height).toBeCloseTo(100, 6);
    // Each bar exactly its value: a trace of snow is a sliver, no snow is no bar.
    expect(chart?.bars[2]?.height).toBeCloseTo(2.667, 3);
    expect(chart?.bars[0]?.height).toBe(0);
    // No time under the gray 2 AM bar or the first lit ones, which the key's "2 to 5 AM" would
    // seem to contradict; the 5 AM end would meet the bus hour's 7 AM on the narrowest plot.
    expect(chart?.times).toEqual([
      { at: 0, label: chanceCopy.now, end: false },
      { at: 2, label: `11${NBSP}PM`, end: false },
      { at: 10, label: `7${NBSP}AM`, end: true },
    ]);
    // From a 390 px phone's plot up, the 5 AM end has room, under the last lit bar.
    expect(chart?.wider).toEqual([
      {
        plot: WIDER_PLOTS_PX[0],
        times: [
          { at: 0, label: chanceCopy.now, end: false },
          { at: 2, label: `11${NBSP}PM`, end: false },
          { at: 8, label: `5${NBSP}AM`, end: false },
          { at: 10, label: `7${NBSP}AM`, end: true },
        ],
      },
    ]);
    // The announcement at 5:30 AM, halfway between the 5 and 6 AM bars.
    expect(chart?.announces).toBe(8.5);
    expect(chart?.range).toEqual({ bottom: 80, height: 40 });
    expect(chart?.busTop).toBe(120);
    expect(chart?.key).toEqual([
      { mark: 'heavy', text: `${chanceCopy.heaviest} 2 to 5${NBSP}AM` },
      {
        mark: 'announces',
        text: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM`,
        at: at('2026-01-13T11:30:00Z'),
        // The room the words keep: as wide as any countdown makes them.
        widest: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}99h${NBSP}59m`,
      },
      {
        mark: 'buses',
        value: `6 to 9${NBSP}in`,
        rest: ` when buses run at 7${NBSP}AM`,
        glyph: 'range',
      },
    ]);
    expect(chart?.summary).toBe(
      `By 7${NBSP}AM, when the buses run, the forecast has 6 to 9 inches of snow on the ground.`,
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
    ]);
    // A day away: the chart's night is one night, so no weekday.
    expect(view?.announces(B_NOW)).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}23h${NBSP}10m`,
    );
  });

  it('adds up from the day after a snow day, naming the cold and the snow stopping', () => {
    expect(lines(view?.why ?? null)).toEqual([
      '25% After a snow day, Shawnee Mission stays closed the next day 1 time in 4.',
      // When it stopped is the timeline's; how cold, the chart's.
      `${MINUS}8 The snow stopped, a full day for the plows.`,
      '+6 Cold at the bus stop Wednesday morning.',
      `${MINUS}5 The forecast has sun this afternoon to help melt the ice.`,
      '+4 Side streets stay icy after 8 inches of snow.',
    ]);
  });

  it('draws how cold it will feel tonight, hanging below 0 F, the bus hour lit', () => {
    const chart = view?.chart;
    expect(chart?.title).toBe(chanceCopy.coldTonight);
    // From -10 F up to 0 F: the zero rule is at the top, and the bars hang from it.
    expect(chart?.plot).toBe(80);
    expect(chart?.zero).toBe(80);
    expect(chart?.bars.map((bar) => bar.below)).toEqual(Array<boolean>(11).fill(true));
    expect(chart?.bars.map((bar) => bar.lit)).toEqual([...Array<boolean>(10).fill(false), true]);
    // The last bar hangs from the zero rule down to -8 F.
    expect(chart?.bars[10]).toMatchObject({ bottom: 16, height: 64 });
    expect(chart?.range).toBeNull();
    expect(chart?.busTop).toBe(80);
    // The night is still to come: no "Now" for its first hour.
    expect(chart?.times.map((time) => time.label)).toEqual([
      `9${NBSP}PM`,
      `12${NBSP}AM`,
      `3${NBSP}AM`,
      `7${NBSP}AM`,
    ]);
    expect(chart?.key).toEqual([
      {
        mark: 'announces',
        text: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM`,
        at: at('2026-01-14T11:30:00Z'),
        widest: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}99h${NBSP}59m`,
      },
      {
        mark: 'buses',
        value: `${MINUS}8${NBSP}F`,
        rest: ` when buses run at 7${NBSP}AM`,
        glyph: 'bar',
      },
    ]);
  });
});

describe('the school’s own clock', () => {
  const east = chanceView(nightBefore({ timeZone: 'America/New_York' }));

  it('says every time where the school is, with its zone where the viewer’s clock differs', () => {
    expect(east?.moved?.text).toBe(`Up from 41% at 5${NBSP}PM${NBSP}CT`);
    expect(east?.moments.map((moment) => moment.time)).toEqual([
      `8:41${NBSP}PM CT`,
      `8:52${NBSP}PM CT`,
    ]);
    expect(east?.announces(A_NOW)).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM${NBSP}CT, in${NBSP}8h${NBSP}25m`,
    );
    expect(east?.chart?.key).toEqual([
      { mark: 'heavy', text: `${chanceCopy.heaviest} 2 to 5${NBSP}AM${NBSP}CT` },
      {
        mark: 'announces',
        text: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM${NBSP}CT`,
        at: at('2026-01-13T11:30:00Z'),
        widest: `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM${NBSP}CT, in${NBSP}99h${NBSP}59m`,
      },
      {
        mark: 'buses',
        value: `6 to 9${NBSP}in`,
        rest: ` when buses run at 7${NBSP}AM${NBSP}CT`,
        glyph: 'range',
      },
    ]);
    // The hours under the chart are the school's too, with its zone, as the chart's words.
    expect(east?.chart?.times.map((time) => time.label)).toEqual([
      chanceCopy.now,
      `11${NBSP}PM${NBSP}CT`,
      `7${NBSP}AM${NBSP}CT`,
    ]);
    // With no chart to say the bus hour, the sum says it, in the school's time.
    const bare = chanceView(
      nightBefore({
        timeZone: 'America/New_York',
        outlook: nightOutlook({ ...A_DETAIL, hours: null }),
      }),
    );
    expect(bare?.chart).toBeNull();
    expect(lines(bare?.why ?? null)[5]).toBe(
      `${MINUS}3 The forecast has the snow ending at 7${NBSP}AM${NBSP}CT, as the buses go out.`,
    );
    // A viewer on the school's clock, in another zone of the same offset, sees no zone.
    const same = chanceView(nightBefore({ timeZone: 'America/Menominee' }));
    expect(same?.moved?.text).toBe(`Up from 41% at 5${NBSP}PM`);
  });

  it('finds an hour of a day on the school’s own clock, across a change of clocks too', () => {
    expect(atLocalHour('2026-01-13', 9, ZONE).toISOString()).toBe('2026-01-13T15:00:00.000Z');
    expect(atLocalHour('2026-07-13', 9, ZONE).toISOString()).toBe('2026-07-13T14:00:00.000Z');
    expect(atLocalHour('2026-03-08', 9, ZONE).toISOString()).toBe('2026-03-08T14:00:00.000Z');
    expect(atLocalHour('2026-01-13', 9, 'America/Los_Angeles').toISOString()).toBe(
      '2026-01-13T17:00:00.000Z',
    );
  });
});

describe('what the section leaves out', () => {
  it('has no section without a forecast for a day that is not decided', () => {
    expect(chanceView(nightBefore({ outlook: null }))).toBeNull();
    expect(chanceView(nightBefore({ decided: { today: false, tomorrow: true } }))).toBeNull();
    const quiet: Outlook = {
      today: { state: 'no_threat' },
      tomorrow: { state: 'no_threat' },
      timeZone: ZONE,
    };
    expect(chanceView(nightBefore({ outlook: quiet }))).toBeNull();
    // Both days decided the next morning: nothing left to give a chance for.
    expect(chanceView(nextMorning({ decided: { today: true, tomorrow: true } }))).toBeNull();
  });

  it('takes today’s chance before tomorrow’s, but not once its buses have run', () => {
    expect(headlineDay(B_OUTLOOK, { today: false, tomorrow: false }, B_NOW)?.day).toBe(
      '2026-01-13',
    );
    const today = {
      state: 'forecast',
      noSchool: 0.5,
      delay: 0.1,
      reasons: [0],
      day: '2026-01-13',
      detail: { ...A_DETAIL, busesAt: at('2026-01-13T13:00:00Z') },
    } as const;
    const open = { today: false, tomorrow: false };
    const alone: Outlook = { today, tomorrow: null, timeZone: ZONE };
    // 6:59 AM in Kansas City, buses at 7: still the morning's chance.
    expect(headlineDay(alone, open, at('2026-01-13T12:59:00Z'))?.day).toBe('2026-01-13');
    // 7 AM with no closing posted: the children are at school; no chance for today.
    expect(headlineDay(alone, open, at('2026-01-13T13:00:00Z'))).toBeNull();
    expect(chanceView(nightBefore({ outlook: alone, now: at('2026-01-13T13:30:00Z') }))).toBeNull();
    // The next school day's, where the file gives one.
    if (B_OUTLOOK === null) throw new Error('no outlook');
    const next: Outlook = { ...B_OUTLOOK, today };
    expect(headlineDay(next, open, at('2026-01-13T13:00:00Z'))?.day).toBe('2026-01-14');
    expect(
      chanceView(nightBefore({ outlook: next, now: at('2026-01-13T14:30:00Z') }))?.meaning,
    ).toBe('Chance of no school Wednesday');
  });

  it('without its bus time, takes a day as under way from 9 AM on the school’s clock', () => {
    const bare: Outlook = {
      today: { state: 'forecast', noSchool: 0.5, delay: 0, reasons: [0], day: '2026-01-12' },
      tomorrow: null,
      timeZone: ZONE,
    };
    const decided = { today: false, tomorrow: false };
    // 8:59 and 9:00 AM in Kansas City.
    expect(headlineDay(bare, decided, at('2026-01-12T14:59:00Z'))).not.toBeNull();
    expect(headlineDay(bare, decided, at('2026-01-12T15:00:00Z'))).toBeNull();
    // The same moment is 7 AM in Los Angeles: a school there is not under way yet.
    expect(
      headlineDay(
        { ...bare, timeZone: 'America/Los_Angeles' },
        decided,
        at('2026-01-12T15:00:00Z'),
      ),
    ).not.toBeNull();
  });

  it('shows the headline alone when the forecast gives nothing else', () => {
    const bare: Outlook = {
      today: { state: 'forecast', noSchool: 0.5, delay: 0, reasons: [0], day: '2026-01-12' },
      tomorrow: null,
      timeZone: ZONE,
    };
    const view = chanceView(nightBefore({ outlook: bare, now: at('2026-01-12T12:00:00Z') }));
    expect(view?.countdown).toBeTypeOf('function');
    expect(view?.announces(at('2026-01-12T12:00:00Z'))).toBeNull();
    expect(view).toEqual({
      status: [],
      day: '2026-01-12',
      number: '50',
      meaning: 'Chance of no school Monday',
      moved: null,
      moments: [],
      chart: null,
      why: null,
      delay: null,
      countdown: view?.countdown,
      announces: view?.announces,
    });
  });

  it('never shows a sum that does not add up to the headline, and shows the rest', () => {
    const off = { ...A_DETAIL, why: { ...A_WHY, base: { ...A_WHY.base, points: 31 } } };
    const view = chanceView(nightBefore({ outlook: nightOutlook(off) }));
    expect(view?.why).toBeNull();
    expect(view?.number).toBe('64');
    expect(view?.chart).not.toBeNull();
    expect(view?.moments).toHaveLength(2);
    const args = { day: '2026-01-13', district: 'Shawnee Mission', nameOf: NAME_OF, now: A_NOW };
    const why = (detail: ForecastDetail, chance = 0.64): WhyView | null =>
      whyView({ detail, chance, zones: HERE, ...args });
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
    // The file never gives a certainty; a sum to 0 or 100 would claim one.
    const none: WhyDetail = { base: { kind: 'similar_days', points: 0 }, reasons: [] };
    expect(why({ ...A_DETAIL, why: none }, 0)).toBeNull();
    const all: WhyDetail = { base: { kind: 'similar_days', points: 100 }, reasons: [] };
    expect(why({ ...A_DETAIL, why: all }, 1)).toBeNull();
    // At 1% and 99% the sum still shows.
    const low: WhyDetail = { base: { kind: 'similar_days', points: 1 }, reasons: [] };
    expect(lines(why({ ...A_DETAIL, why: low }, 0.01))).toEqual([
      '1% On days like this, Shawnee Mission closes 1 time in 100.',
    ]);
    const high: WhyDetail = { base: { kind: 'similar_days', points: 99 }, reasons: [] };
    expect(lines(why({ ...A_DETAIL, why: high }, 0.99))).toEqual([
      '99% On days like this, Shawnee Mission closes 99 times in 100.',
    ]);
    // A base alone, when it is the chance.
    const alone: WhyDetail = { base: { kind: 'similar_days', points: 20 }, reasons: [] };
    expect(lines(why({ ...A_DETAIL, why: alone }, 0.2))).toEqual([
      '20% On days like this, Shawnee Mission closes 1 time in 5.',
    ]);
    // A district with too short a history of its own: the districts around it.
    const pooled: WhyDetail = {
      base: { kind: 'pooled', points: 33, scope: 'nearby', alert: null },
      reasons: [],
    };
    expect(lines(why({ ...A_DETAIL, why: pooled }, 0.33))).toEqual([
      '33% Districts near Shawnee Mission close 1 time in 3 on days like this.',
    ]);
  });

  it('leaves the sum out when a reason cannot be said, and says what it can', () => {
    const args = { day: '2026-01-13', district: 'Shawnee Mission', now: A_NOW, zones: HERE };
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
    expect(whyView({ detail: record, chance: 0.64, nameOf: NAME_OF, ...args })).toBeNull();
    const counted = whyView({
      detail: { ...record, record: { ...A_RECORD, proves: 'record' } },
      chance: 0.64,
      nameOf: NAME_OF,
      ...args,
    });
    expect(lines(counted).slice(1, 3)).toEqual([
      '+12 The forecast has 6 to 9 inches overnight, more than most storms.',
      '+4 Shawnee Mission closed 4 of the last 5 times it got 6 inches or more.',
    ]);
    // The directory not read (yet): the districts next door by how many.
    const unnamed = whyView({ detail: A_DETAIL, chance: 0.64, nameOf: () => null, ...args });
    expect(unnamed?.lines[1]?.text).toBe('2 districts next door canceled.');
  });
});

describe('the timeline', () => {
  it('takes each district next door once, at its first post, earliest first', () => {
    expect(
      postsOf(A_CLOSINGS, '2026-01-13', [1, 2], NAMES, A_NOW).map((post) => [
        post.district,
        post.status,
        post.at.toISOString(),
      ]),
    ).toEqual([
      [1, 'closed', '2026-01-13T02:41:00.000Z'],
      [2, 'closed', '2026-01-13T02:52:00.000Z'],
    ]);
    // De Soto posted too, but is not next door.
    expect(postsOf(A_CLOSINGS, '2026-01-13', [3], NAMES, A_NOW)).toHaveLength(1);
    expect(postsOf(A_CLOSINGS, '2026-01-13', [], NAMES, A_NOW)).toEqual([]);
  });

  it('reads nothing from another directory, another day, or without names or times', () => {
    const other = { ...A_CLOSINGS, directory: { ...STAMP, schools: 7 } };
    expect(postsOf(other, '2026-01-13', [1, 2], NAMES, A_NOW)).toEqual([]);
    expect(postsOf(A_CLOSINGS, '2026-01-14', [1, 2], NAMES, A_NOW)).toEqual([]);
    expect(postsOf(A_CLOSINGS, '2026-01-13', [1, 2], null, A_NOW)).toEqual([]);
    expect(postsOf(null, '2026-01-13', [1, 2], NAMES, A_NOW)).toEqual([]);
    const untimed: ClosingsFile = {
      ...A_CLOSINGS,
      days: A_CLOSINGS.days.map((group) => ({ ...group, announced: [null, null, 8, null] })),
    };
    expect(postsOf(untimed, '2026-01-13', [1, 2], NAMES, A_NOW).map((p) => p.district)).toEqual([
      2,
    ]);
    // A post after now is not on the timeline yet.
    expect(
      postsOf(A_CLOSINGS, '2026-01-13', [1, 2], NAMES, at('2026-01-13T02:45:00Z')),
    ).toHaveLength(1);
  });

  it('names a district only with the status every one of its schools holds', () => {
    /** Blue Valley's two schools (8:41 and 8:55 PM) as given, Olathe closed at 8:52 PM. */
    const blueValley = (statuses: Status[], announced: (number | null)[]): ClosingsFile => {
      const shifted = statuses.filter((status) => status === 1 || status === 3).length;
      return {
        ...A_CLOSINGS,
        days: [
          {
            day: '2026-01-13',
            gaps: [2, 0, 0],
            statuses: [...statuses, 0],
            announced: [...announced, 8],
            reasons: [0, 0, 0],
            shifts: Array<null>(shifted).fill(null),
            clocks: Array<null>(shifted).fill(null),
          },
        ],
      };
    };
    const timeline = (closings: ClosingsFile): string[] =>
      chanceView(nightBefore({ closings }))?.moments.map((moment) => moment.text) ?? [];
    // Delayed, then closed: neither is Blue Valley's, so it is left out.
    const delayedThenClosed = blueValley([1, 0], [19, 5]);
    expect(standings(delayedThenClosed, '2026-01-13', [1, 2], NAMES, A_NOW)).toEqual([
      { district: 1, status: null, at: at('2026-01-13T02:41:00Z') },
      { district: 2, status: 'closed', at: at('2026-01-13T02:52:00Z') },
    ]);
    expect(timeline(delayedThenClosed)).toEqual(['Olathe canceled Tuesday']);
    // Closed, then delayed.
    expect(timeline(blueValley([0, 1], [19, 5]))).toEqual(['Olathe canceled Tuesday']);
    // Both at the same minute.
    expect(timeline(blueValley([1, 0], [19, 19]))).toEqual(['Olathe canceled Tuesday']);
    // One of them listed without a time: its status still counts.
    expect(timeline(blueValley([0, 1], [19, null]))).toEqual(['Olathe canceled Tuesday']);
    // Both delayed: the district starts late, at its first post.
    expect(timeline(blueValley([1, 1], [5, 19]))).toEqual([
      'Blue Valley starts late Tuesday',
      'Olathe canceled Tuesday',
    ]);
    // Only one of Blue Valley's schools listed: not the district's status either.
    const one: ClosingsFile = {
      ...A_CLOSINGS,
      days: [
        {
          day: '2026-01-13',
          gaps: [2, 1],
          statuses: [0, 0],
          announced: [19, 8],
          reasons: [0, 0],
          shifts: [],
          clocks: [],
        },
      ],
    };
    expect(standings(one, '2026-01-13', [1, 2], NAMES, A_NOW).map((s) => s.status)).toEqual([
      null,
      'closed',
    ]);
    expect(timeline(one)).toEqual(['Olathe canceled Tuesday']);
    // The sum's reason has Blue Valley canceled: with its schools apart, what it did goes unsaid.
    expect(chanceView(nightBefore({ closings: delayedThenClosed }))?.why?.lines[1]?.text).toBe(
      'Districts next door posted.',
    );
    expect(chanceView(nightBefore({ closings: one }))?.why?.lines[1]?.text).toBe(
      'Districts next door posted.',
    );
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
    const names = {
      ...NAMES,
      stamp: many.directory,
      districtOf: (school: number) => school + 1,
      schools: () => 1,
    };
    const posts = postsOf(many, '2026-01-13', [1, 2, 3, 4, 5, 6], names, A_NOW);
    expect(posts.map((post) => [post.district, post.status])).toEqual([
      [1, 'closed'],
      [2, 'delayed'],
      [3, 'remote'],
      [4, 'earlyDismissal'],
    ]);
    expect(posts).toHaveLength(MAX_NEIGHBOR_MOMENTS);
  });

  it('says when this district usually announces where the chart does not, in time order', () => {
    // No chart: the timeline says it, counting down while it is to come.
    const flat = nightOutlook({ ...A_DETAIL, hours: null });
    const bare = chanceView(nightBefore({ outlook: flat }));
    expect(bare?.chart).toBeNull();
    expect(bare?.announces(A_NOW)).toBeNull();
    expect(
      bare?.moments.map((moment) => [moment.time, moment.mark, moment.text, moment.at]),
    ).toEqual([
      [`8:41${NBSP}PM`, 'closed', 'Blue Valley canceled Tuesday', null],
      [`8:52${NBSP}PM`, 'closed', 'Olathe canceled Tuesday', null],
      [`5:30${NBSP}AM`, 'next', 'Shawnee Mission usually announces', at('2026-01-13T11:30:00Z')],
    ]);
    expect(bare?.countdown(at('2026-01-13T11:30:00Z'), A_NOW)).toBe('in 8h 25m');
    // Without the chart, the sum says the numbers it would have said.
    expect(lines(bare?.why ?? null).slice(1, 4)).toEqual([
      '+16 The forecast has 6 to 9 inches overnight, more than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
      '+9 Districts next door canceled.',
      `+7 The forecast has the heaviest snow 2 to 5${NBSP}AM, just before the buses.`,
    ]);
    // Passed within the chart's first hour: still on the chart, its time alone.
    const just = chanceView(nightBefore({ now: at('2026-01-13T11:45:00Z') }));
    expect(just?.chart?.announces).toBe(0.5);
    expect(just?.announces(at('2026-01-13T11:45:00Z'))).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM`,
    );
    expect(just?.moments).toHaveLength(2);
    // Before the chart's first hour: back on the timeline, no longer "next".
    const past = chanceView(nightBefore({ now: at('2026-01-13T12:05:00Z') }));
    expect(past?.chart?.announces).toBeNull();
    expect(past?.moments.map((moment) => [moment.mark, moment.at])).toEqual([
      ['closed', null],
      ['closed', null],
      ['event', null],
    ]);
    // An announcement the evening before, before the districts next door posted.
    const early = chanceView(
      nightBefore({
        outlook: nightOutlook({ ...A_DETAIL, announcesAt: at('2026-01-13T02:30:00Z') }),
      }),
    );
    expect(early?.moments.map((moment) => moment.text)).toEqual([
      'Shawnee Mission usually announces',
      'Blue Valley canceled Tuesday',
      'Olathe canceled Tuesday',
    ]);
    expect(early?.moments[0]?.mark).toBe('event');
    // Long past: off the timeline.
    const late = chanceView(
      nightBefore({
        outlook: nightOutlook({ ...A_DETAIL, announcesAt: at('2026-01-12T23:30:00Z') }),
      }),
    );
    expect(late?.moments.map((moment) => moment.mark)).toEqual(['closed', 'closed']);
  });

  it('names a reason without its numbers only where the chart or the timeline gives them', () => {
    // The storm's total is not the chart's answer at the bus hour: both are said.
    const more = {
      ...A_DETAIL,
      why: {
        ...A_WHY,
        reasons: A_WHY.reasons.map((reason) =>
          reason.kind === 'snow_total' ? { ...reason, low: 8, high: 12 } : reason,
        ),
      },
    };
    expect(lines(chanceView(nightBefore({ outlook: nightOutlook(more) }))?.why ?? null)[1]).toBe(
      '+16 The forecast has 8 to 12 inches overnight, more than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
    );
    // The districts next door not on the timeline (no live file): named in the sum.
    const unlisted = chanceView(nightBefore({ closings: null }));
    expect(unlisted?.moments).toEqual([]);
    expect(unlisted?.why?.lines[1]?.text).toBe('Blue Valley and Olathe, next door, canceled.');
    // Only one of them on the timeline: the sum still names both, or Blue Valley would go unsaid.
    const one: ClosingsFile = {
      ...A_CLOSINGS,
      days: A_CLOSINGS.days.map((group) => ({ ...group, announced: [null, null, 8, null] })),
    };
    const partly = chanceView(nightBefore({ closings: one }));
    expect(partly?.moments.map((moment) => moment.text)).toEqual(['Olathe canceled Tuesday']);
    expect(partly?.why?.lines[1]?.text).toBe('Blue Valley and Olathe, next door, canceled.');
    // Both on it, but having gone remote rather than canceled: the sum leaves out what they
    // did, rather than say it two ways.
    const remote: ClosingsFile = {
      ...A_CLOSINGS,
      days: A_CLOSINGS.days.map((group) => ({ ...group, statuses: [2, 2, 2, 2] })),
    };
    const other = chanceView(nightBefore({ closings: remote }));
    expect(other?.moments.map((moment) => moment.text)).toEqual([
      'Blue Valley is remote Tuesday',
      'Olathe is remote Tuesday',
    ]);
    expect(other?.why?.lines[1]?.text).toBe('Districts next door posted.');
    // One of them gone remote, the other not listed: still not said two ways.
    const mixed: ClosingsFile = {
      ...A_CLOSINGS,
      days: A_CLOSINGS.days.map((group) => ({
        ...group,
        statuses: [2, 2, 2, 2],
        announced: [null, null, 8, null],
      })),
    };
    expect(chanceView(nightBefore({ closings: mixed }))?.why?.lines[1]?.text).toBe(
      'Districts next door posted.',
    );
    // Both on it, canceled: the timeline names them, the sum only the reason.
    expect(chanceView(nightBefore())?.why?.lines[1]?.text).toBe('Districts next door canceled.');
    // How cold it feels at the bus hour is not the reason's: both are said.
    const colder: ForecastDetail = {
      ...B_DETAIL,
      why: {
        base: { kind: 'day_after', points: 25 },
        reasons: [
          { kind: 'snow_stops', points: -8, at: at('2026-01-13T12:00:00Z') },
          { kind: 'cold', points: 6, feelsLike: -12 },
          { kind: 'sun', points: -5 },
          { kind: 'icy_roads', points: 4, inches: 8 },
        ],
      },
    };
    const tomorrow = B_OUTLOOK?.tomorrow;
    if (tomorrow?.state !== 'forecast' || B_OUTLOOK === null) throw new Error('no forecast');
    const outlook: Outlook = { ...B_OUTLOOK, tomorrow: { ...tomorrow, detail: colder } };
    expect(lines(chanceView(nextMorning({ outlook }))?.why ?? null)[2]).toBe(
      `+6 The forecast has it feeling like ${MINUS}12${NBSP}F at the bus stop Wednesday morning.`,
    );
  });
});

describe('the countdown', () => {
  const ny = 'America/New_York';

  it('counts hours and minutes, and says the day when it is half a day or more away', () => {
    const announce = at('2026-01-13T11:30:00Z');
    expect(chanceFormat.countdown(announce, at('2026-01-13T11:29:30Z'), ZONE)).toBe('in 1m');
    expect(chanceFormat.countdown(announce, at('2026-01-13T11:15:00Z'), ZONE)).toBe('in 15m');
    expect(chanceFormat.countdown(announce, at('2026-01-13T09:30:00Z'), ZONE)).toBe('in 2h');
    expect(chanceFormat.countdown(announce, at('2026-01-12T23:31:00Z'), ZONE)).toBe('in 11h 59m');
    expect(chanceFormat.countdown(announce, at('2026-01-12T23:30:00Z'), ZONE)).toBe(
      'Tuesday, in 12h',
    );
    expect(chanceFormat.countdown(announce, announce, ZONE)).toBeNull();
    expect(chanceFormat.countdown(announce, at('2026-01-13T12:00:00Z'), ZONE)).toBeNull();
  });

  it('runs across midnight, and names the day where the school is', () => {
    // 11:50 PM to 12:10 AM, Central.
    expect(
      chanceFormat.countdown(at('2026-01-13T06:10:00Z'), at('2026-01-13T05:50:00Z'), ZONE),
    ).toBe('in 20m');
    // 11:30 PM Tuesday in Kansas City is 12:30 AM Wednesday in New York.
    const late = at('2026-01-14T05:30:00Z');
    const morning = at('2026-01-13T12:00:00Z');
    expect(chanceFormat.countdown(late, morning, ZONE)).toBe('Tuesday, in 17h 30m');
    expect(chanceFormat.countdown(late, morning, ny)).toBe('Wednesday, in 17h 30m');
    // Across a change of clocks: real hours, not wall-clock ones.
    expect(
      chanceFormat.countdown(at('2026-03-08T12:00:00Z'), at('2026-03-08T06:00:00Z'), ZONE),
    ).toBe('in 6h');
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

  it('keeps the times at its foot apart on each plot, however many bars it has', () => {
    const viewers = [ZONE, 'America/New_York'];
    for (const [count, viewer, plot] of [2, 5, 11, 17, MAX_BARS].flatMap((n) =>
      viewers.flatMap((zone) =>
        [NARROWEST_PLOT_PX, ...WIDER_PLOTS_PX].map((px) => [n, zone, px] as const),
      ),
    )) {
      const instants = Array.from(
        { length: count },
        (_, i) => new Date(Date.parse('2026-01-13T03:00:00Z') + i * 3_600_000),
      );
      const times = chartTimes({
        instants,
        step: 1,
        marks: count > 4 ? [3, 4, 1] : [1],
        isNow: true,
        zones: { school: ZONE, viewer },
        plot,
      });
      expect(times[0]).toMatchObject({ at: 0, label: chanceCopy.now });
      expect(times.at(-1)).toMatchObject({ at: count - 1, end: true });
      // A viewer elsewhere reads the school's zone after every time, as on the chart's words.
      const zoned = viewer !== ZONE;
      for (const time of times.slice(1)) expect(time.label.endsWith(`${NBSP}CT`)).toBe(zoned);
      // Each time's words, 40 px at most (70 with the zone), from its bar's left edge; the last
      // ends at the plot's.
      const slot = plot / count;
      const width = (time: { at: number }) =>
        time.at === 0 || !zoned ? TIME_LABEL_PX : TIME_LABEL_PX + ZONE_LABEL_PX;
      const boxes = times.map((time) =>
        time.end ? [plot - width(time), plot] : [time.at * slot, time.at * slot + width(time)],
      );
      for (let i = 1; i < boxes.length; i++) {
        expect((boxes[i]?.[0] ?? 0) - (boxes[i - 1]?.[1] ?? 0)).toBeGreaterThanOrEqual(8);
      }
    }
  });

  it('keeps the room of the announcement’s longest countdown, so its words never rewrap', () => {
    for (let minutes = 0; minutes < 8 * 60 + 25; minutes += 7) {
      const now = new Date(A_NOW.getTime() + minutes * 60_000);
      const view = chanceView(nightBefore({ now }));
      const row = view?.chart?.key.find((item) => item.mark === 'announces');
      if (row?.mark !== 'announces') throw new Error('no announcement on the chart');
      // Until the next view, five minutes on, and past it: never longer than the room kept.
      for (const later of [0, 5, 59]) {
        const words = view?.announces(new Date(now.getTime() + later * 60_000)) ?? '';
        expect(words.length).toBeLessThanOrEqual(row.widest.length);
      }
    }
  });

  it('lights only the heaviest snow’s own hours, and puts its end, never its start, under them', () => {
    // Heaviest 11 PM to 2 AM: the 12, 1 and 2 AM bars grew in those hours; the 11 PM bar did not.
    const early: ForecastDetail = {
      ...A_DETAIL,
      hours: A_DETAIL.hours === null ? null : { ...A_DETAIL.hours, heavy: { first: 3, last: 5 } },
    };
    const chart = chartView(early, A_NOW, HERE);
    expect(chart?.bars.flatMap((bar, i) => (bar.lit ? [i] : []))).toEqual([3, 4, 5]);
    expect(chart?.key[0]).toEqual({
      mark: 'heavy',
      text: `${chanceCopy.heaviest} 11${NBSP}PM to 2${NBSP}AM`,
    });
    // 2 AM under the last lit bar; nothing under the gray 11 PM bar where it starts, though the
    // snow starts there too, and nothing under the 12 AM bar, though it is a third hour.
    expect(chart?.times).toEqual([
      { at: 0, label: chanceCopy.now, end: false },
      { at: 5, label: `2${NBSP}AM`, end: false },
      { at: 10, label: `7${NBSP}AM`, end: true },
    ]);
    // A quiet bar never takes a time, but the first and the last always do.
    const instants = Array.from(
      { length: 11 },
      (_, i) => new Date(Date.parse('2026-01-13T03:00:00Z') + i * 3_600_000),
    );
    const times = chartTimes({
      instants,
      step: 1,
      marks: [3],
      quiet: [0, 3, 10],
      isNow: true,
      zones: HERE,
    });
    expect(times.map((time) => time.at)).toEqual([0, 6, 10]);
    const loud = chartTimes({ instants, step: 1, marks: [3], isNow: true, zones: HERE });
    expect(loud.map((time) => time.at)).toEqual([0, 3, 6, 10]);
  });

  it('draws a long night with a bar for every 2 or 3 hours, each a readable width', () => {
    expect([1, 18, 19, 36].map(hoursPerBar)).toEqual([1, 1, 2, 2]);
    // A storm across 30 hours, from 3 PM Monday to 9 PM Tuesday, heaviest 2 to 5 AM.
    const values = Array.from({ length: 30 }, (_, i) => Math.round(i * 3) / 10);
    const detail: ForecastDetail = {
      ...A_DETAIL,
      announcesAt: at('2026-01-13T11:30:00Z'),
      busesAt: at('2026-01-14T02:00:00Z'),
      hours: {
        kind: 'snow_total',
        start: at('2026-01-12T21:00:00Z'),
        values,
        range: { low: 8, high: 10 },
        heavy: { first: 12, last: 14 },
      },
    };
    const chart = chartView(detail, at('2026-01-12T21:10:00Z'), HERE);
    expect(chart?.step).toBe(2);
    expect(chart?.bars).toHaveLength(15);
    // Each bar at least 16 px of the narrowest plot, its bar 60% of that.
    expect((NARROWEST_PLOT_PX / (chart?.bars.length ?? 1)) * 0.6).toBeGreaterThanOrEqual(3);
    // Back from the bus hour, every second hour: the last bar is the bus hour's value.
    // On a scale to 12 inches, three steps of 4.
    expect(chart?.bars.at(-1)?.height).toBeCloseTo((8.7 / 12) * 120, 6);
    // Lit where a bar's own two hours of snowfall meet the heaviest, 2 to 5 AM: the 4 AM bar
    // (2 to 4 AM) and the 6 AM bar (4 to 6 AM); not the 2 AM bar, whose snow fell before.
    expect(chart?.bars.map((bar) => bar.lit)).toEqual(
      Array.from({ length: 15 }, (_, bar) => bar === 6 || bar === 7),
    );
    expect(chart?.key[0]).toEqual({
      mark: 'heavy',
      text: `${chanceCopy.heaviest} 2 to 5${NBSP}AM`,
    });
    // No time at the gray 2 AM bar; the last lit bar is not the key's 5 AM, so no mark there.
    expect(chart?.times.find((time) => time.at === 5)).toBeUndefined();
    expect(chart?.times.find((time) => time.label.startsWith('5'))).toBeUndefined();
    // The first hour drawn is 4 PM, an hour after the series starts: no "Now" there.
    expect(chart?.times[0]).toEqual({ at: 0, label: `4${NBSP}PM`, end: false });
    // The announcement at 5:30 AM: 14.5 hours into the series, 13.5 past the first bar's hour.
    expect(chart?.announces).toBe(6.75);
  });

  it('starts from this hour: the hours gone by are not the night ahead', () => {
    const later = chartView(A_DETAIL, at('2026-01-13T05:30:00Z'), HERE);
    expect(later?.bars).toHaveLength(9);
    expect(later?.times[0]).toEqual({ at: 0, label: chanceCopy.now, end: false });
    expect(later?.bars.map((bar) => bar.lit)).toEqual([
      false,
      false,
      false,
      false,
      true,
      true,
      true,
      false,
      false,
    ]);
    // In the heaviest hours already: lit from now, the key still the whole of them.
    const during = chartView(A_DETAIL, at('2026-01-13T09:10:00Z'), HERE);
    expect(during?.bars.map((bar) => bar.lit)).toEqual([true, true, true, false, false]);
    expect(during?.key[0]).toEqual({
      mark: 'heavy',
      text: `${chanceCopy.heaviest} 2 to 5${NBSP}AM`,
    });
    // After them: no lit bars, and no key row.
    const after = chartView(A_DETAIL, at('2026-01-13T12:10:00Z'), HERE);
    expect(after?.bars.some((bar) => bar.lit)).toBe(false);
    expect(after?.key.map((row) => row.mark)).toEqual(['buses']);
    // Two hours left draw two bars; the bus hour alone is no chart.
    expect(chartView(A_DETAIL, at('2026-01-13T12:30:00Z'), HERE)?.bars).toHaveLength(2);
    expect(chartView(A_DETAIL, at('2026-01-13T13:30:00Z'), HERE)).toBeNull();
    expect(chartView({ ...A_DETAIL, hours: null }, A_NOW, HERE)).toBeNull();
    // An announcement outside the night drawn has no line, and no row in the key.
    const before = chartView({ ...A_DETAIL, announcesAt: at('2026-01-13T01:30:00Z') }, A_NOW, HERE);
    expect(before?.announces).toBeNull();
    expect(before?.key.map((row) => row.mark)).toEqual(['heavy', 'buses']);
    const west = { school: 'America/Los_Angeles', viewer: 'America/Los_Angeles' };
    expect(chartView(B_DETAIL, B_NOW, west)?.title).toBe(chanceCopy.coldTonight);
    const berlin = { school: 'Europe/Berlin', viewer: 'Europe/Berlin' };
    expect(chartView(B_DETAIL, B_NOW, berlin)?.title).toBe(chanceCopy.coldTitle);
  });
});

describe('district names', () => {
  it('says a district as a family does', () => {
    expect(shortDistrictName('Shawnee Mission Public Schools')).toBe('Shawnee Mission');
    expect(shortDistrictName('Blue Valley')).toBe('Blue Valley');
    expect(shortDistrictName('Lee County Schools')).toBe('Lee County');
    expect(shortDistrictName('Kansas City 33 School District')).toBe('Kansas City 33');
    expect(shortDistrictName('Center Joint Unified School District')).toBe('Center');
    expect(shortDistrictName('Independence School District')).toBe('Independence');
    expect(shortDistrictName('Katy ISD')).toBe('Katy');
    expect(shortDistrictName('Public Schools')).toBe('Public Schools');
    // Missouri's numbers, kept only where another district of the state reads the same.
    expect(shortDistrictName('Hickman Mills C-1')).toBe('Hickman Mills');
    expect(shortDistrictName('Wheaton R-III')).toBe('Wheaton');
    expect(shortDistrictName('Blue Springs R-IV', false, 'MO')).toBe('Blue Springs');
    expect(shortDistrictName("Lee's Summit R-VII", false, 'MO')).toBe("Lee's Summit");
    expect(shortDistrictName('North Kansas City 74', false, 'MO')).toBe('North Kansas City');
    expect(shortDistrictName('Kansas City 33', false, 'MO')).toBe('Kansas City');
    expect(shortDistrictName('Grandview C-4', true, 'MO')).toBe('Grandview C-4');
    // New York's central school districts, and Montana's K-12 schools.
    expect(shortDistrictName('Dolgeville Central School District', false, 'NY')).toBe('Dolgeville');
    expect(shortDistrictName('Baker K-12 Schools', false, 'MT')).toBe('Baker');
    expect(shortDistrictName('Rocklin Unified')).toBe('Rocklin');
    expect(shortDistrictName('Flagstaff Unified District (4192)')).toBe('Flagstaff');
    expect(shortDistrictName('School District No. 1 in the county of Denver and State')).toBe(
      'Denver',
    );
  });

  it('never leaves a kind of district for its name, and gives its number only where needed', () => {
    // The whole of the kind goes, not its last words: never "Indian Prairie Community Unit".
    expect(shortDistrictName('Indian Prairie Community Unit School District 204')).toBe(
      'Indian Prairie',
    );
    expect(shortDistrictName('Indian Prairie CUSD 204')).toBe('Indian Prairie');
    expect(shortDistrictName('Joliet PSD 86')).toBe('Joliet');
    expect(shortDistrictName('Woodlawn Unit School District 209')).toBe('Woodlawn');
    expect(shortDistrictName('Acalanes Union High')).toBe('Acalanes');
    expect(shortDistrictName('Amityville Union Free School District')).toBe('Amityville');
    expect(shortDistrictName('Ada Exempted Village')).toBe('Ada');
    expect(shortDistrictName('Harwood Unified Union School District #60')).toBe('Harwood');
    expect(shortDistrictName('Anderson Community School Corp')).toBe('Anderson');
    // Where another district of the state says the same words: its number, or its whole name.
    expect(shortDistrictName('Hinsdale Township HSD 86', true)).toBe('Hinsdale 86');
    expect(shortDistrictName('Hinsdale CCSD 181', true)).toBe('Hinsdale 181');
    expect(shortDistrictName('Weld County School District No. Re-4', true)).toBe(
      'Weld County Re-4',
    );
    expect(shortDistrictName('Corning Union High', true)).toBe('Corning Union High');
    expect(shortDistrictName('Yuma Union High School District (4507)', true)).toBe(
      'Yuma Union High',
    );
    expect(shortDistrictName('Franklin Regional School District', true, 'PA')).toBe(
      'Franklin Regional',
    );
    expect(shortDistrictName('Midway ISD', true, 'TX')).toBe('Midway ISD');
    // A name that is nothing but its kind and its number: the number's district.
    expect(shortDistrictName('Community Unit School District 300')).toBe('District 300');
    expect(shortDistrictName('Cusd 300')).toBe('District 300');
    expect(shortDistrictName('Township High School District 211')).toBe('District 211');
    expect(shortDistrictName('Township HSD 214')).toBe('District 214');
    expect(shortDistrictName('Community Unit School District No 196')).toBe('District 196');
    // Without a number, a name that is nothing but its kind stays whole.
    expect(shortDistrictName('Community Unit School District')).toBe(
      'Community Unit School District',
    );
    for (const name of [
      'Indian Prairie Community Unit School District 204',
      'Township High School District 211',
      'Community Unit School District 300',
      'Rich Township HSD 227',
      'Bluford Unit School District 318',
      'Lake Region Union High School District #24',
    ]) {
      for (const alike of [false, true]) {
        expect(shortDistrictName(name, alike)).not.toMatch(
          /(?:Community|Unit|Union High|Township High|High|CUSD|HSD|PSD)(?: \S+)?$/,
        );
      }
    }
    // Where no other district of the state reads the same, nothing of its kind.
    for (const [name, state] of [
      ['Beaver River Central School District', 'NY'],
      ['Bellmore-Merrick Central High School District', 'NY'],
      ['Ennis K-12 Schools', 'MT'],
      ['Monomoy Regional School District', 'MA'],
      ['Gila County Regional School District (87600)', 'AZ'],
      ['Springboro Community City', 'OH'],
    ] as const) {
      expect(shortDistrictName(name, false, state)).not.toMatch(
        /(?:Community|Central|High|K-12|Regional|City)$/,
      );
    }
  });
});

describe('districts next door, told apart', () => {
  const naming = (shown: string, state: string, alike = false): DistrictNaming => ({
    shown,
    state,
    alike,
  });
  /** The names said for `next`, the districts next door, where the school's own is `own`. */
  function told(own: DistrictNaming, next: readonly DistrictNaming[]): (string | null)[] {
    const names: Names = { ...NAMES, naming: (district) => next[district] ?? null };
    const mine = shortDistrictName(own.shown, own.alike, own.state);
    const nameOf = toldApart(names, mine, own.state, [...next.keys()]);
    return [...next.keys()].map(nameOf);
  }

  it('says the state of one in another state that reads as the school’s own district or as another', () => {
    // Driggs, Idaho, and Jackson, Wyoming, 3 miles apart across the state line.
    const idaho = naming('Teton County District', 'ID');
    const wyoming = naming('Teton County School District #1', 'WY');
    expect(told(idaho, [wyoming, naming('Fremont County Joint District', 'ID')])).toEqual([
      'Teton County in Wyoming',
      'Fremont County',
    ]);
    expect(told(wyoming, [idaho])).toEqual(['Teton County in Idaho']);
    // Texarkana, Texas and Arkansas, next door to a third district: only the one away says it.
    expect(
      told(naming('Liberty-Eylau ISD', 'TX'), [
        naming('Texarkana ISD', 'TX'),
        naming('Texarkana School District', 'AR'),
      ]),
    ).toEqual(['Texarkana', 'Texarkana in Arkansas']);
    expect(told(naming('Texhoma', 'OK'), [naming('Texhoma ISD', 'TX')])).toEqual([
      'Texhoma in Texas',
    ]);
    // Kansas City, Kansas, next door to Kansas City, Missouri.
    expect(told(naming('Kansas City', 'KS'), [naming('Kansas City 33', 'MO')])).toEqual([
      'Kansas City in Missouri',
    ]);
  });

  it('says more of the name of one in the same state, its state’s id last', () => {
    // Arizona's charter districts, whose names differ only by the state's id.
    const basis = (id: string): DistrictNaming =>
      naming(`BASIS Charter Schools Inc. (${id})`, 'AZ', true);
    expect(told(basis('6361'), [basis('81078'), basis('90508')])).toEqual([
      'BASIS Charter Schools Inc. (81078)',
      'BASIS Charter Schools Inc. (90508)',
    ]);
    expect(
      told(naming('Mesa Unified District (4235)', 'AZ'), [basis('81078'), basis('90508')]),
    ).toEqual(['BASIS Charter Schools Inc. (81078)', 'BASIS Charter Schools Inc. (90508)']);
    // Its number, where the build did not find the two alike.
    expect(
      told(naming('Hinsdale Township HSD 86', 'IL'), [naming('Hinsdale CCSD 181', 'IL')]),
    ).toEqual(['Hinsdale 181']);
    // Already told apart: as they are.
    expect(
      told(naming('Hinsdale Township HSD 86', 'IL', true), [
        naming('Hinsdale CCSD 181', 'IL', true),
      ]),
    ).toEqual(['Hinsdale 181']);
    // A name nothing tells from the school's own district: not said.
    expect(told(naming('Midway ISD', 'TX', true), [naming('Midway ISD', 'TX', true)])).toEqual([
      null,
    ]);
  });

  it('never names one as the school’s own district or another, in the timeline or the sum', () => {
    // A Driggs family: Teton County, Wyoming, canceled; so did Olathe.
    const names: Names = {
      ...NAMES,
      naming: (district) =>
        [
          naming('Teton County District', 'ID'),
          naming('Teton County School District #1', 'WY'),
          naming('Olathe', 'KS'),
        ][district] ?? null,
    };
    const view = chanceView(
      nightBefore({ district: 'Teton County', state: 'ID', names, closings: null }),
    );
    expect(view?.why?.base.text).toMatch(/^Teton County /);
    expect(view?.why?.lines[1]?.text).toBe(
      'Teton County in Wyoming and Olathe, next door, canceled.',
    );
    const listed = chanceView(nightBefore({ district: 'Teton County', state: 'ID', names }));
    expect(listed?.moments.map((moment) => moment.text)).toEqual([
      'Teton County in Wyoming canceled Tuesday',
      'Olathe canceled Tuesday',
    ]);
  });
});
