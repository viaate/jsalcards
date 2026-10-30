import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { chanceView } from '../../app/chance';
import type { ChanceView } from '../../app/chance';
import type { SchoolView } from '../../app/school';
import {
  A_CLOSINGS,
  A_DETAIL,
  A_NOW,
  A_OUTLOOK,
  B_NOW,
  B_OUTLOOK,
  CLOSED_TODAY,
  NAMES,
  ZONE,
  nightOutlook,
} from '../../app/tests/chance-fixtures';
import { copy } from '../../copy';
import { chanceCopy } from '../../copy-chance';
import { nightOf } from '../../data/night';
import DetailPanel from '../DetailPanel.svelte';

const NBSP = '\u00a0';
const MINUS = '\u2212';

function chance(night: boolean): ChanceView {
  const view = chanceView({
    outlook: night ? A_OUTLOOK : B_OUTLOOK,
    decided: { today: !night, tomorrow: false },
    status: night ? [] : [CLOSED_TODAY],
    district: 'Shawnee Mission',
    state: 'KS',
    closings: night ? A_CLOSINGS : null,
    names: NAMES,
    now: night ? A_NOW : B_NOW,
    timeZone: ZONE,
  });
  if (view === null) throw new Error('no chance');
  return view;
}

/** A public school's view with its chance, made up for these tests. */
function schoolView(section: ChanceView): SchoolView {
  return {
    id: '201164001574',
    name: 'Test Mission East High',
    campus: null,
    kind: `${copy.detail.publicSchool} · 9–12`,
    place: 'Prairie Village, KS · Johnson County',
    status: section.status,
    chance: section,
    facts: [],
    nearby: [],
    loading: false,
  };
}

describe('the chance section', () => {
  let component: ReturnType<typeof mount> | undefined;

  beforeAll(() => {
    // jsdom lays nothing out; the chart measures its words with a ResizeObserver.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
      },
    );
  });

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  function show(section: ChanceView): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(DetailPanel, {
      target,
      props: {
        view: schoolView(section),
        pinned: false,
        copied: false,
        onclose: vi.fn(),
        onpin: vi.fn(),
        onshare: vi.fn(),
      },
    });
    flushSync();
    const panel = target.querySelector<HTMLElement>('aside.detail .chance');
    if (panel === null) throw new Error('no section');
    return panel;
  }

  const text = (root: Element, selector: string): string[] =>
    [...root.querySelectorAll(selector)].map((node) =>
      node.textContent.replace(/[\t\n\r ]+/gu, ' ').trim(),
    );

  it('leads with the chance and the delay, then the evening, the chart and the sum, all open', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show(chance(true));
    // The panel's own status and outlook give way to it.
    expect(document.querySelector('aside.detail .body > .status')).toBeNull();
    expect(document.querySelector('.outlook')).toBeNull();
    expect(section.querySelector('.status')).toBeNull();
    expect(text(section, '.number')).toEqual(['64%']);
    expect(text(section, '.meaning')).toEqual(['64% Chance of no school Tuesday']);
    expect(text(section, '.change')).toEqual([`Up from 41% at 5${NBSP}PM`]);
    expect(section.querySelectorAll('.change svg')).toHaveLength(1);
    expect(text(section, '.delay')).toEqual(['18% chance of a delayed start instead']);
    // The districts next door; when this one announces is the chart's to say.
    expect(text(section, '.moment')).toEqual([
      `8:41${NBSP}PM Blue Valley canceled Tuesday`,
      `8:52${NBSP}PM Olathe canceled Tuesday`,
    ]);
    // Each on the panel's two columns: the time, then the words.
    expect(text(section, '.moment .label')).toEqual([`8:41${NBSP}PM`, `8:52${NBSP}PM`]);

    expect(text(section, 'figcaption')).toEqual([chanceCopy.snowTitle]);
    expect(section.querySelectorAll('.col')).toHaveLength(11);
    // The heaviest snow, 2 to 5 AM, is the 3, 4 and 5 AM bars' growth.
    expect(section.querySelectorAll('.col.is-lit')).toHaveLength(3);
    // The plot carries marks only: the lit bars, the two dashed lines, the range.
    expect(section.querySelectorAll('.line.is-announces')).toHaveLength(1);
    expect(section.querySelectorAll('.line.is-end')).toHaveLength(1);
    expect(section.querySelectorAll('.range')).toHaveLength(1);
    expect(text(section, '.plot')).toEqual(['']);
    expect(text(section, '.time')).toEqual([chanceCopy.now, `11${NBSP}PM`, `7${NBSP}AM`]);
    // Over the plot, the two dashed lines' words, the answer first, its value first; for a
    // screen reader too, after the chart in a sentence.
    expect(text(section, '.chart .sr-only')).toEqual([
      `By 7${NBSP}AM, when the buses run, the forecast has 6 to 9 inches of snow on the ground.`,
    ]);
    expect(text(section, '.words')).toEqual([
      `6 to 9${NBSP}in when buses run at 7${NBSP}AM`,
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}8h${NBSP}25m`,
    ]);
    // Its countdown keeps time.
    vi.advanceTimersByTime(61_000);
    flushSync();
    expect(text(section, '.words.is-announces')).toEqual([
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}8h${NBSP}24m`,
    ]);
    // The words keep the room of the longest countdown the night shows, hidden behind them.
    expect(section.querySelector('.words.is-announces')?.getAttribute('data-room')).toBe(
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}99h${NBSP}59m`,
    );
    // Its dashed line at 5:30 AM: halfway through the 5 AM bar's hour, the 9th of 11.
    const line = section.querySelector<HTMLElement>('.line.is-announces');
    expect(Number.parseFloat(line?.style.left ?? '')).toBeCloseTo((8.5 / 11) * 100, 6);
    expect(text(section, '.words.is-end .value')).toEqual([`6 to 9${NBSP}in`]);
    expect(section.querySelector('.head')?.getAttribute('aria-hidden')).toBeNull();
    // Under it the key, one row on the panel's two columns: the lit bar, drawn small.
    expect(text(section, '.key li')).toEqual([`${chanceCopy.heaviest} 2 to 5${NBSP}AM`]);
    expect([...section.querySelectorAll('.key .sample')].map((sample) => sample.className)).toEqual(
      [expect.stringContaining('is-bar')],
    );
    expect(section.querySelector('.key .sample')?.getAttribute('aria-hidden')).toBe('true');

    expect(text(section, '.why-title')).toEqual(['How we got 64%']);
    expect(text(section, '.sum > li .num')).toEqual(['30', '+16', '+9', '+7', '+5', '−3']);
    // The sum adds up to the headline, which it does not repeat; the record is in its sentence.
    expect(section.querySelector('.is-total')).toBeNull();
    expect(section.querySelector('.record')).toBeNull();
    // Each reason names itself; the chart and the timeline hold their numbers.
    expect(text(section, '.is-reason').slice(0, 3)).toEqual([
      '+16 More snow than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
      '+9 Districts next door canceled.',
      '+7 Heaviest snow just before the buses.',
    ]);
    // Nothing folds away, and no words lead in bold.
    expect(section.querySelectorAll('details, [aria-expanded]')).toHaveLength(0);
    expect(section.querySelectorAll('strong, b')).toHaveLength(0);
  });

  it('draws the night chart: hourly bars from an empty first one, its range and its forecast’s time', () => {
    vi.useFakeTimers({ now: A_NOW });
    const night = nightOf(
      { least: [0.1, 0.4, 1.0, 2.0, 3.1, 4.2, 4.9, 5.4, 6.1], low: 6, high: 9, heavy: [3, 6] },
      {
        day: '2026-01-13',
        timeZone: ZONE,
        generatedAt: new Date('2026-01-13T03:00:00Z'),
        nightAt: new Date('2026-01-13T01:00:00Z'),
      },
    );
    const view = chanceView({
      outlook: nightOutlook({
        ...A_DETAIL,
        announcesAt: null,
        busesAt: null,
        hours: null,
        why: null,
        night,
      }),
      decided: { today: false, tomorrow: false },
      status: [],
      district: 'Shawnee Mission',
      state: 'KS',
      closings: A_CLOSINGS,
      names: NAMES,
      now: A_NOW,
      timeZone: ZONE,
    });
    if (view === null) throw new Error('no chance');
    const section = show(view);
    expect(text(section, 'figcaption')).toEqual(['New snow, hour by hour']);
    expect(section.querySelectorAll('.col')).toHaveLength(10);
    expect(section.querySelectorAll('.col.is-lit')).toHaveLength(3);
    expect(section.querySelectorAll('.range')).toHaveLength(1);
    expect(section.querySelectorAll('.line.is-announces')).toHaveLength(0);
    expect(text(section, '.words')).toEqual([`6 to 9${NBSP}in by 7${NBSP}AM`]);
    // The span's end alone of its hours gets a time: none under the gray bar at 1 AM where the
    // key's hours start, none under the lit bars at 2 and 3 AM (critic r2 B1, as 4300322 rules).
    expect(text(section, '.time')).toEqual([
      `10${NBSP}PM`,
      `12${NBSP}AM`,
      `4${NBSP}AM`,
      `7${NBSP}AM`,
    ]);
    expect(text(section, '.time')).not.toContain(`1${NBSP}AM`);
    expect(text(section, '.key li')).toEqual([`${chanceCopy.heaviest} 1 to 4${NBSP}AM`]);
    expect(text(section, '.chart .note')).toEqual([`From the 7${NBSP}PM hourly forecast`]);
    expect(text(section, '.chart .sr-only')[0]).toContain('6 to 9 inches of new snow');
    expect(section.textContent).not.toContain('Buses');
    expect(section.textContent).not.toContain('buses');
  });

  it('keeps the chance, its meaning and its sum when the chart throws while it draws (critic r1 S2)', () => {
    vi.useFakeTimers({ now: A_NOW });
    const view = chance(true);
    if (view.chart === null) throw new Error('no chart');
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    // Past the panel's own check (its `until` reads), then a bug in every part the chart draws.
    const broken = new Proxy(view.chart, {
      get(target, key): unknown {
        if (key === 'until') return target.until;
        throw new Error('a chart bug');
      },
    });
    const section = show({ ...view, chart: broken });
    expect(section.querySelector('figure')).toBeNull();
    expect(text(section, '.number')[0]).toContain(view.number);
    expect(section.textContent).toContain(view.meaning);
    expect(section.querySelectorAll('.why .row').length).toBeGreaterThan(0);
    // Never a silent loss (critic r2 S5): the console, where the e2e's watch looks, has the bug.
    expect(errors.mock.calls.flat().some((arg) => String(arg).includes('a chart bug'))).toBe(true);
    // A bug in the panel's own check is no chart either, and leaves its trace too.
    errors.mockClear();
    const unreadable = new Proxy(view.chart, {
      get(): never {
        throw new Error('a check bug');
      },
    });
    const again = show({ ...view, chart: unreadable });
    expect(again.querySelector('figure')).toBeNull();
    expect(text(again, '.number')[0]).toContain(view.number);
    expect(errors.mock.calls.flat().some((arg) => String(arg).includes('a check bug'))).toBe(true);
    errors.mockRestore();
  });

  it('hides the night chart on its own clock once its forecast is too old (critic r2 S4)', () => {
    vi.useFakeTimers({ now: A_NOW });
    const night = nightOf(
      { least: [0.1, 0.4, 1.0, 2.0, 3.1, 4.2, 4.9, 5.4, 6.1], low: 6, high: 9, heavy: [3, 6] },
      {
        day: '2026-01-13',
        timeZone: ZONE,
        generatedAt: new Date('2026-01-13T03:00:00Z'),
        nightAt: new Date('2026-01-13T01:00:00Z'),
      },
    );
    const view = chanceView({
      outlook: nightOutlook({
        ...A_DETAIL,
        announcesAt: null,
        busesAt: null,
        hours: null,
        why: null,
        night,
      }),
      decided: { today: false, tomorrow: false },
      status: [],
      district: 'Shawnee Mission',
      state: 'KS',
      closings: A_CLOSINGS,
      names: NAMES,
      now: A_NOW,
      timeZone: ZONE,
    });
    if (view === null) throw new Error('no chance');
    // The 7 PM cycle (01:00Z) is 195 minutes old at 10:15 PM, before Start's hour is past
    // (11 PM): hidden then by the panel's ticking clock alone, with no new reading.
    expect(view.chart?.until?.toISOString()).toBe('2026-01-13T04:15:00.001Z');
    const section = show(view);
    expect(section.querySelectorAll('figure')).toHaveLength(1);
    vi.setSystemTime(new Date('2026-01-13T04:14:30Z'));
    vi.advanceTimersByTime(20_000);
    flushSync();
    expect(section.querySelectorAll('figure')).toHaveLength(1);
    vi.setSystemTime(new Date('2026-01-13T04:15:10Z'));
    vi.advanceTimersByTime(20_000);
    flushSync();
    expect(section.querySelector('figure')).toBeNull();
    expect(text(section, '.number')[0]).toContain(view.number);
  });

  it('the next morning, says the decided status first, then the next day’s chance', () => {
    vi.useFakeTimers({ now: B_NOW });
    const section = show(chance(false));
    const status = section.querySelector('.status');
    expect(status?.getAttribute('aria-label')).toBe(copy.detail.status);
    expect(text(section, '.status .headline')).toEqual([copy.statusLine.closed.today]);
    expect(section.querySelectorAll('.status .glyph.is-closed')).toHaveLength(1);
    // The status comes before the chance.
    const hero = section.querySelector('.hero');
    expect(
      status !== null &&
        hero !== null &&
        (status.compareDocumentPosition(hero) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ).toBe(true);
    expect(text(section, '.number')).toEqual(['22%']);
    expect(text(section, '.change')).toEqual(['Down from 30% last night']);
    expect(text(section, '.moment')).toEqual([`6:00${NBSP}AM Snow stopped, 8 inches in all`]);
    expect(text(section, '.words.is-announces')).toEqual([
      `${chanceCopy.usuallyAnnounces} 5:30${NBSP}AM, in${NBSP}23h${NBSP}10m`,
    ]);
    expect(text(section, 'figcaption')).toEqual([chanceCopy.coldTonight]);
    expect(section.querySelectorAll('.col.is-below')).toHaveLength(11);
    expect(text(section, '.words.is-end .value')).toEqual([`${MINUS}8${NBSP}F`]);
    // No lit hours to name on a cold night: no key.
    expect(section.querySelector('.key')).toBeNull();
    expect(text(section, '.is-start')).toEqual([
      '25% After a recorded snow day, Shawnee Mission stayed closed or went remote the next day 1 time in 4.',
    ]);
  });

  it('without the chart, says when the district usually announces on the timeline, counting down', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show({
      ...chance(true),
      chart: null,
      announces: () => null,
      moments: [
        ...chance(true).moments,
        {
          key: 'announces',
          time: `5:30${NBSP}AM`,
          text: 'Shawnee Mission usually announces',
          mark: 'announces',
          at: new Date('2026-01-13T11:30:00Z'),
        },
      ],
    });
    expect(section.querySelector('.chart')).toBeNull();
    expect(text(section, '.moment').at(-1)).toBe(
      `5:30${NBSP}AM Shawnee Mission usually announces in 8h 25m`,
    );
    vi.advanceTimersByTime(61_000);
    flushSync();
    expect(text(section, '.m-count')).toEqual(['in 8h 24m']);
    // Its marker is a ring, not a dot: when it usually announces, never a post.
    expect(section.querySelector('.moment:last-child .mark')?.className).toMatch(
      /\bis-announces\b/u,
    );
  });

  it('marks each timeline row: a dot in its status color, a ring for the usual announcement, a dotted rail between', () => {
    vi.useFakeTimers({ now: A_NOW });
    const row = (key: string, mark: ChanceView['moments'][number]['mark']) => ({
      key,
      time: `8:41${NBSP}PM`,
      text: key,
      mark,
      at: null,
    });
    const moments = [
      row('a', 'closed'),
      row('b', 'delayed'),
      row('c', 'remote'),
      row('d', 'earlyDismissal'),
      row('e', 'event'),
      row('f', 'announces'),
    ];
    const section = show({ ...chance(true), moments });
    const marks = [...section.querySelectorAll('.moment .mark')].map((mark) =>
      [...mark.classList].filter((name) => name.startsWith('is-')),
    );
    expect(marks).toEqual([
      ['is-closed'],
      ['is-delayed'],
      ['is-remote'],
      ['is-early-dismissal'],
      ['is-event'],
      ['is-announces'],
    ]);
    // Every row's marker, and its rail, is for the eye only: the words say the status.
    const rails = [...section.querySelectorAll('.moment .rail')];
    expect(rails).toHaveLength(6);
    for (const rail of rails) expect(rail.getAttribute('aria-hidden')).toBe('true');
    expect(text(section, '.moment .m-text')).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
    // The words come right after the time for a screen reader; the rail sits between for the eye.
    for (const moment of section.querySelectorAll('.moment')) {
      expect([...moment.children].map((child) => child.className.split(' ')[0])).toEqual([
        'label',
        'm-text',
        'rail',
      ]);
    }
    // The dotted rail joins one row's marker to the next: none after the last.
    const links = [...section.querySelectorAll('.moment')].map(
      (moment) => moment.querySelectorAll('.link').length,
    );
    expect(links).toEqual([1, 1, 1, 1, 1, 0]);
  });

  it('draws no rail for a single row', () => {
    vi.useFakeTimers({ now: A_NOW });
    const [first] = chance(true).moments;
    if (first === undefined) throw new Error('no moment');
    const section = show({ ...chance(true), moments: [first] });
    expect(section.querySelectorAll('.moment .mark.is-closed')).toHaveLength(1);
    expect(section.querySelectorAll('.link')).toHaveLength(0);
  });

  it('paints the dashed lines behind the bars, so a line never crosses one', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show(chance(true));
    const plot = section.querySelector('.plot');
    const lines = [...section.querySelectorAll('.line')];
    expect(lines).toHaveLength(2);
    for (const line of lines) {
      // Earlier in the drawing than the plot, with no stacking of their own: painted first.
      expect(line.parentElement).toBe(plot?.parentElement);
      expect(
        plot !== null &&
          (line.compareDocumentPosition(plot) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
      ).toBe(true);
    }
    const css = readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../ChanceChart.svelte'),
      'utf8',
    );
    expect(css).not.toMatch(/z-index/u);
  });

  it('shows only what is consistent: no sum, no chart, no timeline where the file gives none', () => {
    const bare = { ...chance(true), moved: null, moments: [], chart: null, why: null, delay: null };
    const section = show(bare);
    expect(text(section, '.number')).toEqual(['64%']);
    expect(section.querySelector('.change')).toBeNull();
    expect(section.querySelector('.moments')).toBeNull();
    expect(section.querySelector('.chart')).toBeNull();
    expect(section.querySelector('.why')).toBeNull();
    expect(section.querySelector('.delay')).toBeNull();
  });

  it('with few local records, shows the number lighter and says so on its own line under the meaning', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show({ ...chance(true), fewRecords: chanceCopy.fewRecords });
    expect(text(section, '.number')).toEqual(['64%']);
    expect(section.querySelectorAll('.number.is-thin')).toHaveLength(1);
    expect(text(section, '.few')).toEqual(['Few local records']);
    // Directly under "Chance of no school Tuesday", before what moved it.
    const meaning = section.querySelector('.meaning');
    expect(meaning?.nextElementSibling?.className).toMatch(/\bfew\b/u);
    expect(meaning?.nextElementSibling?.nextElementSibling?.className).toMatch(/\bchange\b/u);
    expect(text(section, '.meaning')).toEqual(['64% Chance of no school Tuesday']);
  });

  it('without the flag, shows the number and its meaning as before', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show(chance(true));
    expect(section.querySelector('.few')).toBeNull();
    expect(section.querySelector('.is-thin')).toBeNull();
    expect(section.textContent).not.toContain(chanceCopy.fewRecords);
  });
});

describe('the timeline markers', () => {
  const read = (file: string): string =>
    readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), file), 'utf8');

  it('fill each status dot with the map’s color for it and draw the announcement as a ring', () => {
    const css = read('../ChanceSection.svelte');
    const rule = (selector: string): string => {
      const found = new RegExp(`\\.mark\\.${selector}\\s*\\{([^}]*)\\}`, 'u').exec(css)?.[1];
      if (found === undefined) throw new Error(`no .mark.${selector}`);
      return found.trim();
    };
    expect(rule('is-closed')).toBe('background: var(--status-closed);');
    expect(rule('is-delayed')).toBe('background: var(--status-delayed);');
    expect(rule('is-remote')).toBe('background: var(--status-remote);');
    expect(rule('is-early-dismissal')).toBe('background: var(--status-early-dismissal);');
    expect(rule('is-event')).toBe('background: var(--text-2);');
    // Hollow: a border, no fill.
    expect(rule('is-announces')).toMatch(/^border: 1\.5px solid var\(--text-1\);$/u);
    // Closed and canceled are the map's blue.
    expect(read('../../styles/global.css')).toMatch(/--status-closed:\s*#7fd4ff;/u);
  });
});

describe('the lighter number', () => {
  /** WCAG relative luminance of a #rrggbb or #rgb color. */
  function luminance(hex: string): number {
    const full = hex.length === 4 ? hex.replace(/[0-9a-f]/giu, (c) => c + c) : hex;
    const [r, g, b] = [1, 3, 5].map((i) => {
      const v = Number.parseInt(full.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
  }

  it('is a theme gray at 4.5:1 or more on every surface a panel sits on', () => {
    const css = readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../styles/global.css'),
      'utf8',
    );
    const token = (name: string): string => {
      const found = new RegExp(`--${name}:\\s*(#[0-9a-f]{3,6});`, 'iu').exec(css)?.[1];
      if (found === undefined) throw new Error(`no --${name}`);
      return found;
    };
    // The site has one theme: these tokens, dark, on :root only.
    expect(css.match(/--text-2:/gu)).toHaveLength(1);
    const gray = luminance(token('text-2'));
    for (const surface of ['bg', 'surface-1', 'surface-2']) {
      const ratio = (gray + 0.05) / (luminance(token(surface)) + 0.05);
      expect(ratio, surface).toBeGreaterThanOrEqual(4.5);
    }
  });
});
