import { describe, expect, it } from 'vitest';

import { CARD_SIZES, cardModel } from '../../app/share-card';
import type { CardKind, CardModel } from '../../app/share-card';
import { ZONE } from '../../app/tests/chance-fixtures';
import {
  CLOSED,
  CLOSED_TWO_DAYS,
  DELAYED,
  LONG_SCHOOL,
  MORNING,
  REMOTE,
  SEASON,
  URL_OF,
  samples,
  viewOf,
} from '../../app/tests/share-card-fixtures';
import type { SchoolStatus, StatusRow } from '../../data/school-day';
import { Detail, Reason, Status } from '../../types/generated';
import {
  DROPPED_FIRST,
  MIN_SCALE,
  STORY_SAFE,
  TONE_COLORS,
  layoutCard,
  unorphan,
  wrap,
} from '../share-card';
import type { CardLayout, Measure } from '../share-card';

const KINDS: readonly CardKind[] = ['story', 'post'];

/** A face about as wide as Geist: each letter a little over half its size, bolder a little wider. */
const measure: Measure = (text, size, weight) =>
  [...new Intl.Segmenter('en-US', { granularity: 'grapheme' }).segment(text)].length *
  size *
  (weight >= 650 ? 0.6 : 0.54);

function modelOf(view: ReturnType<typeof viewOf>, now = MORNING): CardModel {
  const model = cardModel({ view, url: URL_OF(view.id), now, timeZone: ZONE });
  if (model === null) throw new Error('no card');
  return model;
}

/** Every run inside the card's box: none wider than the line, none above or below it. */
function expectInside(layout: CardLayout): void {
  const { box } = layout;
  for (const run of layout.runs) {
    expect(run.x, run.text).toBeGreaterThanOrEqual(box.left);
    expect(run.x + run.width, run.text).toBeLessThanOrEqual(box.right + 0.01);
    // A line's ink: its capitals above the baseline, its descenders below (Geist's measures).
    expect(run.y - run.size * 0.75, run.text).toBeGreaterThanOrEqual(box.top - 0.01);
    expect(run.y + run.size * 0.22, run.text).toBeLessThanOrEqual(box.bottom + 0.01);
  }
}

/** The parts of the foot: as of when, the wordmark and the site's name. */
const FOOT = new Set(['as-of', 'wordmark', 'host']);

/**
 * No line runs into another: each line's ink (caps 0.75 of its size above the baseline,
 * descenders 0.22 below) clear of the next line's, top to bottom, and the whole answer
 * clear of the foot and of the hairline over the wordmark.
 */
function expectApart(layout: CardLayout): void {
  const ink = (run: CardLayout['runs'][number]): [number, number] => [
    run.y - run.size * 0.75,
    run.y + run.size * 0.22,
  ];
  const rows = layout.runs.filter((run) => run.role !== 'host');
  for (let n = 1; n < rows.length; n++) {
    const above = rows[n - 1];
    const below = rows[n];
    if (above === undefined || below === undefined) continue;
    expect(ink(below)[0], `${above.text} | ${below.text}`).toBeGreaterThanOrEqual(ink(above)[1]);
  }
  const answer = layout.runs.filter((run) => !FOOT.has(run.role));
  const foot = layout.runs.filter((run) => FOOT.has(run.role));
  const lowest = Math.max(...answer.map((run) => ink(run)[1]));
  expect(lowest).toBeLessThan(Math.min(...foot.map((run) => ink(run)[0])));
  expect(lowest).toBeLessThan(layout.rule.y);
  expect(layout.mark.y).toBeGreaterThan(layout.rule.y);
  expect(layout.mark.y + layout.mark.size).toBeLessThanOrEqual(layout.box.bottom + 0.01);
}

function row(status: Status, extra: Partial<StatusRow> = {}): StatusRow {
  return {
    status,
    reason: Reason.winter_storm,
    announcedAt: new Date('2026-01-12T11:12:00Z'),
    shiftMinutes: 120,
    clockMinute: 600,
    manual: false,
    details: [],
    ...extra,
  };
}

/** The most a real card can say: the longest name, two days, every plain detail on each. */
function heaviest(): CardModel {
  const details = Object.values(Detail);
  const status: SchoolStatus = {
    today: row(Status.delayed, { details }),
    tomorrow: row(Status.early_dismissal, { details }),
  };
  return modelOf(viewOf({ record: LONG_SCHOOL, id: LONG_SCHOOL.id, status, season: SEASON }));
}

/** The words of a part of the card, its wrapped lines joined again. */
function said(layout: CardLayout, role: string): string {
  return layout.runs
    .filter((run) => run.role === role)
    .map((run) => run.text)
    .join(' ');
}

describe('a share card’s layout', () => {
  it('is a story’s 1080 by 1920 and a post’s 1080 by 1350', () => {
    expect(CARD_SIZES.story).toEqual({ width: 1080, height: 1920 });
    expect(CARD_SIZES.post).toEqual({ width: 1080, height: 1350 });
    const model = modelOf(viewOf({ status: CLOSED }));
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, measure);
      expect([layout.width, layout.height]).toEqual([
        CARD_SIZES[kind].width,
        CARD_SIZES[kind].height,
      ]);
    }
  });

  it('keeps a story’s top and bottom 250 pixels free of words', () => {
    for (const { view, now } of samples()) {
      const layout = layoutCard(modelOf(view, now), 'story', measure);
      expect(layout.box.top).toBe(STORY_SAFE);
      expect(layout.box.bottom).toBe(1920 - STORY_SAFE);
      expectInside(layout);
    }
  });

  it('shows every word of the card for each sample, in both sizes, in order', () => {
    for (const { view, now } of samples()) {
      const model = modelOf(view, now);
      for (const kind of KINDS) {
        const layout = layoutCard(model, kind, measure);
        expectInside(layout);
        expect(said(layout, 'name')).toBe(model.name);
        expect(said(layout, 'place')).toBe(model.place ?? '');
        model.lines.forEach((line, n) => {
          expect(said(layout, `headline-${String(n)}`)).toBe(line.headline);
          expect(said(layout, `day-${String(n)}`)).toBe(line.day ?? '');
          expect(said(layout, `detail-${String(n)}`)).toBe(line.detail ?? '');
          expect(said(layout, `reason-${String(n)}`)).toBe(line.reason ?? '');
          expect(said(layout, `said-${String(n)}`)).toBe(line.said ?? '');
        });
        expect(said(layout, 'chance-number')).toBe(model.chance?.number ?? '');
        expect(said(layout, 'chance-meaning')).toBe(model.chance?.meaning ?? '');
        expect(said(layout, 'chance-day')).toBe(model.chance?.day ?? '');
        expect(said(layout, 'season')).toBe(model.season ?? '');
        expect(said(layout, 'as-of')).toBe(model.asOf);
        expect(layout.dropped).toEqual([]);
        expectApart(layout);
        expect(said(layout, 'wordmark')).toBe(model.wordmark);
        expect(said(layout, 'host')).toBe('snowlightmap.com');
        // Top to bottom: the school, its answer, then as of when and the wordmark.
        const at = (role: string): number => layout.runs.find((run) => run.role === role)?.y ?? NaN;
        const answer = model.lines.length > 0 ? 'headline-0' : 'chance-number';
        expect(at('name')).toBeLessThan(at(answer));
        expect(at(answer)).toBeLessThan(at('as-of'));
        expect(at('as-of')).toBeLessThan(at('wordmark'));
      }
    }
  });

  it('glows in the status’s color, with a dot of it before each headline', () => {
    const [closed, delayed, remote, chance] = samples().map(({ view, now }) =>
      layoutCard(modelOf(view, now), 'story', measure),
    );
    expect(closed?.glow.color).toBe('#7fd4ff');
    expect(remote?.glow.color).toBe('#b79cff');
    expect(delayed?.glow.color).toBe(TONE_COLORS.delayed);
    expect(chance?.glow.color).toBe(TONE_COLORS.chance);
    expect(closed?.dots.map((dot) => dot.color)).toEqual(['#7fd4ff']);
    expect(chance?.dots).toEqual([]);
    // A chance glows by its number: 64% less than a school closed.
    expect(chance?.glow.strength).toBeLessThan(closed?.glow.strength ?? 0);
  });

  it('wraps a long name and keeps every word of it, never clipped', () => {
    const view = viewOf({
      record: LONG_SCHOOL,
      id: LONG_SCHOOL.id,
      status: CLOSED_TWO_DAYS,
      season: SEASON,
    });
    const model = modelOf(view);
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, measure);
      expectInside(layout);
      expectApart(layout);
      const lines = layout.runs.filter((run) => run.role === 'name');
      expect(lines.length).toBeGreaterThan(1);
      expect(said(layout, 'name')).toBe(model.name);
    }
  });

  it('breaks a word too wide for a line of its own, and steps the type down to fit', () => {
    const view = viewOf({ status: CLOSED_TWO_DAYS, season: SEASON });
    const base = modelOf(view);
    const model: CardModel = {
      ...base,
      name: `${'Supercalifragilistic'.repeat(4)} ${base.name} ${base.name} ${base.name}`,
    };
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, measure);
      expectInside(layout);
      expectApart(layout);
      expect(layout.scale).toBeLessThan(1);
      expect(said(layout, 'name').replace(/\s/gu, '')).toBe(model.name.replace(/\s/gu, ''));
    }
  });

  it('wraps at spaces, and breaks only a word wider than the line', () => {
    const width = (text: string): number => text.length * 10;
    expect(wrap('one two three', 80, width)).toEqual(['one two', 'three']);
    expect(wrap('abcdefghijkl', 50, width)).toEqual(['abcde', 'fghij', 'kl']);
    expect(wrap('', 50, width)).toEqual([]);
    // A no-break space holds a time to its AM.
    expect(wrap('As of 6:55\u00a0AM', 100, width)).toEqual(['As of', '6:55\u00a0AM']);
  });

  it('fits the most a real card can say at a size easy to read, leaving out the least needed lines first', () => {
    const model = heaviest();
    expect(model.lines).toHaveLength(2);
    expect(model.lines.every((line) => (line.said?.length ?? 0) > 200)).toBe(true);
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, measure);
      expectInside(layout);
      expectApart(layout);
      expect(layout.scale).toBeGreaterThanOrEqual(MIN_SCALE);
      // The smallest words on the card: 25 pixels or more, on a card 1080 wide.
      expect(Math.min(...layout.runs.map((run) => run.size))).toBeGreaterThanOrEqual(25);
      // Lines are left out in their order, and only those: the season, then the plain details,
      // then the reason; the school, its statuses, days, times and as of when stay.
      expect(DROPPED_FIRST.slice(0, layout.dropped.length)).toEqual(layout.dropped);
      for (const kind of DROPPED_FIRST) {
        const gone = layout.dropped.includes(kind);
        const shown = layout.runs.some(
          (run) => run.role === kind || run.role.startsWith(`${kind}-`),
        );
        expect(shown, kind).toBe(!gone);
      }
      expect(said(layout, 'name')).toBe(model.name);
      model.lines.forEach((line, n) => {
        expect(said(layout, `headline-${String(n)}`)).toBe(line.headline);
        expect(said(layout, `day-${String(n)}`)).toBe(line.day ?? '');
        expect(said(layout, `detail-${String(n)}`)).toBe(line.detail ?? '');
      });
      expect(said(layout, 'as-of')).toBe(model.asOf);
    }
  });

  it('leaves out the season first, for a card a little too full', () => {
    const base = modelOf(
      viewOf({ record: LONG_SCHOOL, id: LONG_SCHOOL.id, status: CLOSED_TWO_DAYS, season: SEASON }),
    );
    // A season line long enough that the card cannot keep it at the least size.
    const model: CardModel = { ...base, season: `${base.season ?? ''} `.repeat(14).trim() };
    const layout = layoutCard(model, 'post', measure);
    expect(layout.dropped).toEqual(['season']);
    expect(said(layout, 'season')).toBe('');
    expect(said(layout, 'reason-0')).toBe(base.lines[0]?.reason ?? '');
    expectApart(layout);
  });

  it('is never drawn with one line over another: a card that cannot fit is not made', () => {
    const base = heaviest();
    const model: CardModel = {
      ...base,
      lines: [...base.lines, ...base.lines, ...base.lines, ...base.lines],
    };
    for (const kind of KINDS) {
      expect(() => layoutCard(model, kind, measure)).toThrow();
    }
  });

  it('never leaves a headline’s last word alone on its line, nor grows one onto more lines', () => {
    for (const status of [DELAYED, REMOTE, CLOSED]) {
      const model = modelOf(viewOf({ status }));
      for (const kind of KINDS) {
        const layout = layoutCard(model, kind, measure);
        const lines = layout.runs.filter((run) => run.role === 'headline-0').map((run) => run.text);
        expect(lines.join(' ')).toBe(model.lines[0]?.headline);
        if (lines.length > 1) expect(lines.at(-1), lines.join(' | ')).toMatch(/\s/u);
        // At full size it takes no fewer lines than it shows: room never splits a headline.
        const full = wrap(model.lines[0]?.headline ?? '', 1080 - 192 - 70, (text) =>
          measure(text, kind === 'story' ? 112 : 96, 700),
        );
        expect(lines.length).toBeLessThanOrEqual(Math.max(full.length, 1));
      }
    }
    const width = (text: string): number => text.length * 10;
    expect(unorphan(['Delayed start', 'today'], 140, width)).toEqual(['Delayed', 'start today']);
    // Where the word moved down would not fit, or a line is one word, the lines stay.
    expect(unorphan(['Delayed start', 'today'], 100, width)).toEqual(['Delayed start', 'today']);
    expect(unorphan(['Closed', 'today'], 140, width)).toEqual(['Closed', 'today']);
    expect(unorphan(['one two', 'three four'], 140, width)).toEqual(['one two', 'three four']);
  });

  it('glows behind the status’s dot, or behind the chance where it stands alone', () => {
    const [closed, , , chance] = samples().map(({ view, now }) =>
      layoutCard(modelOf(view, now), 'story', measure),
    );
    const dot = closed?.dots[0];
    expect(dot).toBeDefined();
    expect(closed?.glow.y).toBe(dot?.y);
    expect(closed?.glow.x).toBeGreaterThan(dot?.x ?? Infinity);
    expect(closed?.glow.x).toBeLessThan(1080 / 2);
    const number = chance?.runs.find((run) => run.role === 'chance-number');
    expect(number).toBeDefined();
    expect(chance?.glow.x).toBeCloseTo((number?.x ?? 0) + (number?.width ?? 0) / 2);
    expect(chance?.glow.y).toBeLessThan(number?.y ?? 0);
    expect(chance?.glow.y).toBeGreaterThan((number?.y ?? 0) - (number?.size ?? 0));
  });
});
