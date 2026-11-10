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
  SEASON,
  URL_OF,
  samples,
  viewOf,
} from '../../app/tests/share-card-fixtures';
import { copy } from '../../copy';
import { shareCopy, shareFormat } from '../../copy-share';
import type { SchoolStatus, StatusRow } from '../../data/school-day';
import { Detail, Reason, Status } from '../../types/generated';
import {
  ARM,
  BIG_SIZES,
  CAP,
  CARD_TONES,
  CREST,
  DESC,
  FRAME,
  LARGEST_K,
  LEFT,
  LEFT_OUT,
  MIN_TYPE,
  RIGHT,
  TICKS_TALLEST,
  TICK_COLORS,
  drawCard,
  layoutCard,
  offsets,
  stepsOf,
  wrap,
} from '../share-card';
import type { CardLayout, Face, LeftOut, PosterTone, Role, TextRun } from '../share-card';
import { LONG_NAME, NAME_100, NAME_ONE_WORD, PLACE_60, SAMPLES } from './share-card-samples';

const KINDS: readonly CardKind[] = ['story', 'post'];

const SEGMENTER = new Intl.Segmenter('en-US', { granularity: 'grapheme' });

function letters(text: string): string[] {
  return Array.from(SEGMENTER.segment(text), (part) => part.segment);
}

/**
 * A made-up face, near Geist's own widths, the same on any machine: each letter 60 wide at 100
 * pixels in the bold weights and 46 below, less 8 for each "Tu" in the text (its one kern
 * pair); the ink starts on the origin and ends at the advance.
 */
const face: Face = (text, weight) => {
  const advance =
    letters(text).length * (weight >= 650 ? 60 : 46) - 8 * (text.split('Tu').length - 1);
  return { advance, left: 0, right: advance };
};

/** The made-up face, `times` as wide. */
const wider =
  (times: number): Face =>
  (text, weight) => {
    const advance = face(text, weight).advance * times;
    return { advance, left: 0, right: advance };
  };

function modelOf(view: ReturnType<typeof viewOf>, now = MORNING): CardModel {
  const model = cardModel({ view, url: URL_OF(view.id), now, timeZone: ZONE });
  if (model === null) throw new Error('no card');
  return model;
}

function sample(name: string): CardModel {
  const found = SAMPLES.find((each) => each.name === name);
  if (found === undefined) throw new Error(`no sample ${name}`);
  return found.model;
}

interface Card {
  readonly name: string;
  readonly kind: CardKind;
  readonly model: CardModel;
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

/**
 * Every card the tests look at: the design's samples and the cards it did not sample, the cards
 * of the panel's own views (closed, delayed, remote, a chance alone, sent home early, open) and
 * the heaviest real card, in both formats.
 */
const CARDS: readonly Card[] = [
  ...SAMPLES.map(({ name, kind, model }) => ({ name, kind, model })),
  ...samples().flatMap(({ name, view, now }) =>
    KINDS.map((kind) => ({ name: `view-${name}-${kind}`, kind, model: modelOf(view, now) })),
  ),
  ...KINDS.map((kind) => ({ name: `view-heaviest-${kind}`, kind, model: heaviest() })),
  // A school-year line short enough to stand on one line at 40, on a Story with room to spare.
  {
    name: 'short-school-year-story',
    kind: 'story',
    model: {
      ...sample('closed-story-light'),
      season: 'This school year, since Aug 1: closed 2 days.',
    },
  },
];

const LAID: readonly (Card & { layout: CardLayout })[] = CARDS.map((card) => ({
  ...card,
  layout: layoutCard(card.model, card.kind, face),
}));

function runsOf(layout: CardLayout, ...roles: Role[]): TextRun[] {
  return layout.runs.filter((run) => roles.includes(run.role));
}

/** The words of a part of the card, its lines joined again. */
function said(layout: CardLayout, role: Role): string {
  return runsOf(layout, role)
    .map((run) => run.text)
    .join(' ');
}

/** The line the card is about: the first that is not open, else (with no chance) the open one. */
function leadOf(model: CardModel): CardModel['lines'][number] | undefined {
  return (
    model.lines.find((line) => line.tone !== 'open') ??
    (model.chance === null ? model.lines[0] : undefined)
  );
}

/** The lines of LEFT_OUT a card has to leave out, in their order. */
function leavable(model: CardModel): LeftOut[] {
  const lead = leadOf(model);
  const has: Record<LeftOut, boolean> = {
    said: (lead?.said ?? null) !== null,
    season: model.season !== null,
    reason: (lead?.reason ?? null) !== null,
    more:
      model.lines.some((line) => line !== lead) || (lead !== undefined && model.chance !== null),
  };
  return LEFT_OUT.filter((part) => has[part]);
}

/** A color's relative luminance, and the contrast of two (WCAG 2). */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const part = Number.parseInt(hex.slice(at, at + 2), 16) / 255;
    return part <= 0.03928 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}
function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}

/** The order of a card's lines, top to bottom. */
const STATUS_ORDER: readonly Role[] = [
  'place',
  'name',
  'campus',
  'big',
  'day',
  'fact',
  'reason',
  'words',
  'more',
  'chance',
  'few',
  'as-of',
  'season',
  'host',
];
const CHANCE_ORDER: readonly Role[] = [
  'place',
  'name',
  'campus',
  'digits',
  'meaning',
  'chance-day',
  'few',
  'more',
  'as-of',
  'season',
  'host',
];

/** One thing a card did to its canvas. */
interface Call {
  name: string;
  args: readonly unknown[];
  fillStyle: unknown;
  font: unknown;
  path: readonly (readonly [number, number])[];
}

/** A canvas context that draws nothing and keeps what it was asked to do, and what was set on it. */
function recorder(): { ctx: CanvasRenderingContext2D; calls: Call[]; set: Set<string> } {
  const calls: Call[] = [];
  const set = new Set<string>();
  const state: Record<string, unknown> = {};
  let path: (readonly [number, number])[] = [];
  const ctx = new Proxy(state, {
    get(target, key) {
      if (typeof key !== 'string') return undefined;
      if (key in target) return target[key];
      return (...args: number[]) => {
        if (key === 'beginPath') path = [];
        if (key === 'moveTo' || key === 'lineTo') path.push([args[0] ?? NaN, args[1] ?? NaN]);
        if (key === 'quadraticCurveTo') {
          path.push([args[0] ?? NaN, args[1] ?? NaN], [args[2] ?? NaN, args[3] ?? NaN]);
        }
        calls.push({
          name: key,
          args,
          fillStyle: target.fillStyle,
          font: target.font,
          path: [...path],
        });
        return undefined;
      };
    },
    set(target, key, value) {
      if (typeof key === 'string') {
        target[key] = value;
        set.add(key);
      }
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls, set };
}

describe('a share card’s layout', () => {
  it('is a story’s 1080 by 1920 and a post’s 1080 by 1350', () => {
    expect(CARD_SIZES.story).toEqual({ width: 1080, height: 1920 });
    expect(CARD_SIZES.post).toEqual({ width: 1080, height: 1350 });
    for (const { kind, layout } of LAID) {
      expect([layout.width, layout.height]).toEqual([
        CARD_SIZES[kind].width,
        CARD_SIZES[kind].height,
      ]);
    }
    // The design's seven, the cards it did not sample and the panel's own, in both formats.
    expect(LAID.length).toBeGreaterThanOrEqual(7 + 39 + 14);
  });

  it('is a poster in its status’s colors, with dark type on amber and on green', () => {
    expect(CARD_TONES).toEqual({
      closed: {
        field: '#1791dc',
        type: '#ffffff',
        big: '#ffffff',
        small: '#ffffff',
        flake: '#0d80ca',
        hill: '#ffffff',
      },
      delayed: {
        field: '#f0a020',
        type: '#241500',
        big: '#241500',
        small: '#3d2a04',
        flake: '#e6930d',
        hill: '#ffffff',
      },
      remote: {
        field: '#8f72f7',
        type: '#ffffff',
        big: '#ffffff',
        small: '#ffffff',
        flake: '#7f60ec',
        hill: '#ffffff',
      },
      earlyDismissal: {
        field: '#22b46d',
        type: '#03200f',
        big: '#03200f',
        small: '#03200f',
        flake: '#1aa560',
        hill: '#ffffff',
      },
      open: {
        field: '#4b5563',
        type: '#ffffff',
        big: '#ffffff',
        small: '#ffffff',
        flake: '#414a57',
        hill: '#ffffff',
      },
      chance: {
        field: '#143f3c',
        type: '#f4f5f7',
        big: '#5fe3cc',
        small: '#b4d6d1',
        flake: '#1c524d',
        hill: '#f4f5f7',
      },
    });
    expect(TICK_COLORS).toEqual({ lit: '#36c9b3', unlit: '#2c6b64' });
    // Early dismissal is dark on its green, as delayed is on amber: white there is too faint.
    const early = CARD_TONES.earlyDismissal;
    expect(contrast('#ffffff', early.field)).toBeLessThan(3);
    for (const ink of [early.type, early.big, early.small]) {
      expect(ink).not.toBe('#ffffff');
      expect(contrast(ink, early.field)).toBeGreaterThanOrEqual(6.4);
      expect(contrast(ink, early.flake)).toBeGreaterThanOrEqual(5.4);
    }
    for (const colors of Object.values(CARD_TONES)) {
      expect(contrast(colors.type, colors.field)).toBeGreaterThanOrEqual(3.4);
      expect(contrast(colors.small, colors.field)).toBeGreaterThanOrEqual(3.4);
    }
    // Each card takes the colors of the line it is about, or the chance's.
    const seen = new Set<PosterTone>();
    for (const { model, layout } of LAID) {
      const lead = leadOf(model);
      expect(layout.tone).toBe(lead === undefined ? 'chance' : lead.tone);
      expect(layout.colors).toBe(CARD_TONES[layout.tone]);
      seen.add(layout.tone);
    }
    expect([...seen].sort()).toEqual(Object.keys(CARD_TONES).sort());
  });

  it('keeps a story’s top 250 and bottom 260 pixels free of words, and a post inside its margins', () => {
    for (const { name, kind, layout } of LAID) {
      const { top, bottom } = FRAME[kind];
      expect([kind, top, bottom]).toEqual(kind === 'story' ? [kind, 256, 1650] : [kind, 90, 1266]);
      const first = layout.runs[0];
      expect(first, name).toBeDefined();
      // The first line's cap-top, and the mark's underside on the sign-off's bottom line.
      expect((first?.y ?? 0) - CAP * (first?.size ?? 0), name).toBeCloseTo(top, 6);
      expect(layout.mark.bottom).toBe(bottom);
      for (const run of layout.runs) {
        // A line's ink: its ascenders 0.76 of its size above the baseline, its descenders 0.2 below.
        const up = run.y - 0.76 * run.size;
        const down = run.y + 0.2 * run.size;
        if (kind === 'story') {
          expect(up, `${name}: ${run.text}`).toBeGreaterThanOrEqual(250);
          expect(down, `${name}: ${run.text}`).toBeLessThanOrEqual(1920 - 260);
        } else {
          expect(up, `${name}: ${run.text}`).toBeGreaterThanOrEqual(top - 6);
          expect(down, `${name}: ${run.text}`).toBeLessThanOrEqual(bottom);
        }
      }
    }
  });

  it('starts every line’s ink on the one left edge and ends it by the right one', () => {
    expect([LEFT, RIGHT]).toEqual([84, 996]);
    for (const { name, layout } of LAID) {
      for (const run of layout.runs) {
        if (run.role !== 'sign' && run.role !== 'host') {
          expect(run.x, `${name}: ${run.text}`).toBe(LEFT);
        }
        expect(run.x + run.width, `${name}: ${run.text}`).toBeLessThanOrEqual(RIGHT + 1e-6);
        // Its first letter is drawn from where its ink starts (this face has no side bearing).
        expect(run.at[0], `${name}: ${run.text}`).toBeCloseTo(run.x, 9);
        expect(run.at).toHaveLength(letters(run.text).length);
      }
    }
    // A face whose ink starts 5 per 100 right of its origin: the ink is still on the edge.
    const inset: Face = (text, weight) => {
      const { advance } = face(text, weight);
      return { advance, left: -5, right: advance };
    };
    const layout = layoutCard(sample('closed-story-light'), 'story', inset);
    for (const run of layout.runs) {
      if (run.role !== 'host') expect(run.x).toBe(LEFT);
      expect(run.at[0]).toBeCloseTo(run.x - (5 * run.size) / 100, 9);
    }
  });

  it('sets no line under 40 pixels, and every size a whole pixel', () => {
    expect(MIN_TYPE).toBe(40);
    for (const { name, layout } of LAID) {
      for (const run of layout.runs) {
        expect(run.size, `${name}: ${run.text}`).toBeGreaterThanOrEqual(40);
        expect(Number.isInteger(run.size), `${name}: ${run.text}`).toBe(true);
        expect([500, 600, 700]).toContain(run.weight);
      }
    }
  });

  it('says the card top to bottom in its order, no line over another, a campus under its name', () => {
    for (const { name, model, layout } of LAID) {
      const order = layout.tone === 'chance' ? CHANCE_ORDER : STATUS_ORDER;
      const lines = layout.runs.filter((run) => run.role !== 'sign');
      const ranks = lines.map((run) => order.indexOf(run.role));
      expect(ranks, name).not.toContain(-1);
      expect(ranks, name).toEqual([...ranks].sort((a, b) => a - b));
      lines.forEach((run, n) => {
        const above = lines[n - 1];
        if (above === undefined) return;
        // Each line's capitals start under the baseline of the line above it.
        expect(run.y - CAP * run.size, `${name}: ${above.text} | ${run.text}`).toBeGreaterThan(
          above.y,
        );
      });
      expect(said(layout, 'place'), name).toBe(
        name.startsWith('place-60') ? said(layout, 'place') : (model.place ?? ''),
      );
      expect(said(layout, 'as-of'), name).toBe(model.asOf);
      expect(said(layout, 'host'), name).toBe(model.host);
      if (model.campus !== null) {
        const [campus] = runsOf(layout, 'campus');
        const school = runsOf(layout, 'name').at(-1);
        expect(campus?.text).toBe(model.campus);
        expect(campus?.color).toBe(layout.colors.small);
        // 22 times K from the name's last baseline to the campus's cap-top.
        expect((campus?.y ?? 0) - CAP * (campus?.size ?? 0) - (school?.y ?? 0)).toBeCloseTo(
          Math.round(22 * layout.K),
          6,
        );
      } else expect(runsOf(layout, 'campus')).toEqual([]);
    }
    expect(LAID.some(({ model }) => model.campus !== null)).toBe(true);
    // A card with no place starts with the name, where the place's capitals would be.
    const bare = layoutCard({ ...sample('closed-story-light'), place: null }, 'story', face);
    expect(bare.runs[0]?.role).toBe('name');
    expect((bare.runs[0]?.y ?? 0) - CAP * (bare.runs[0]?.size ?? 0)).toBeCloseTo(256, 6);
  });

  it('sets the answer whole and as large as the card allows, another line only where it earns it', () => {
    expect(BIG_SIZES).toEqual({ words: [150, 330], number: [260, 600] });
    for (const { name, model, layout } of LAID) {
      const lead = leadOf(model);
      if (lead !== undefined) {
        const big = runsOf(layout, 'big');
        expect(said(layout, 'big'), name).toBe(lead.headline);
        expect(big.length).toBe(layout.big.lines);
        for (const run of big) {
          expect(run.size, name).toBe(layout.big.size);
          expect(run.color).toBe(layout.colors.big);
          expect(run.width, name).toBeLessThanOrEqual(912 + 1e-6);
        }
        expect(layout.big.size, name).toBeGreaterThanOrEqual(150);
        expect(layout.big.size, name).toBeLessThanOrEqual(330);
        expect(layout.ticks).toBeNull();
      } else {
        const [digits] = runsOf(layout, 'digits');
        const [sign] = runsOf(layout, 'sign');
        expect(`${digits?.text ?? ''}${sign?.text ?? ''}`, name).toBe(model.chance?.number);
        expect(digits?.size, name).toBe(layout.big.size);
        expect(layout.big.size, name).toBeGreaterThanOrEqual(260);
        expect(layout.big.size, name).toBeLessThanOrEqual(600);
        expect((sign?.x ?? 0) + (sign?.width ?? 0), name).toBeLessThanOrEqual(RIGHT + 1e-6);
        expect(runsOf(layout, 'big')).toEqual([]);
      }
    }
    // "Delayed start today": never "Delayed start" over "today" alone, in either format.
    for (const kind of KINDS) {
      const layout = layoutCard(modelOf(viewOf({ status: DELAYED })), kind, face);
      const lines = runsOf(layout, 'big').map((run) => run.text);
      expect(lines.join(' ')).toBe(copy.statusLine.delayed.today);
      expect(lines).not.toEqual(['Delayed start', 'today']);
    }
    // Another line only where the type grows by more than 15 percent for it. A crowded Post
    // leaves "Open today" two lines 16 percent larger than one: two lines. A step more crowded
    // and two lines would be no larger than one: one line.
    const crowded: CardModel = {
      ...sample('open-post'),
      name: LONG_NAME,
      campus: 'Wornall Campus',
      season: sample('nearby-four-counts-post').season,
    };
    const answer = (K: number): [number, string[]] => {
      const layout = layoutCard(crowded, 'post', face, K);
      return [layout.big.size, runsOf(layout, 'big').map((run) => run.text)];
    };
    expect(answer(1.2)).toEqual([189, ['Open', 'today']]);
    expect(answer(1.3)).toEqual([159, ['Open today']]);
    expect(189 / 159).toBeGreaterThan(1.15);
    // One word as wide as the card sets the size: "Closed" over "today".
    const closed = layoutCard(modelOf(viewOf({ status: CLOSED })), 'post', face);
    expect(runsOf(closed, 'big').map((run) => run.text)).toEqual(['Closed', 'today']);
  });

  it('steps its small type up to fill the frame, and never cuts a name a smaller step holds whole', () => {
    expect(LARGEST_K).toEqual({
      status: { story: 1.5, post: 1.3 },
      chance: { story: 1.3, post: 1 },
    });
    expect(stepsOf(sample('closed-story-light'), 'story')).toEqual([
      1.5, 1.45, 1.4, 1.35, 1.3, 1.25, 1.2, 1.15, 1.1, 1.05, 1,
    ]);
    expect(stepsOf(sample('chance-story-dark'), 'story')[0]).toBe(1.3);
    expect(stepsOf(sample('chance-story-dark'), 'post')).toEqual([1]);
    let heldToOneLine = 0;
    for (const { name, kind, model, layout } of LAID) {
      const steps = stepsOf(model, kind);
      expect(steps, name).toContain(layout.K);
      // Each step on its own; null where the card is not made at it with the lines it kept.
      const alone = steps.map((K) => {
        try {
          const made = layoutCard(model, kind, face, K);
          return made.dropped.length > layout.dropped.length ? null : made;
        } catch {
          return null;
        }
      });
      const whole = (made: CardLayout | null): made is CardLayout =>
        made !== null && !said(made, 'name').endsWith(shareCopy.cut);
      // A name that stands whole at some step is whole on the card.
      if (alone.some(whole)) expect(said(layout, 'name'), name).not.toContain(shareCopy.cut);
      // Of the steps: the largest big line, and among equals the largest step. A larger step
      // than that only with the school-year line held to one line, where that keeps the big line.
      const made = alone.filter(whole);
      if (made.length === 0) continue;
      const most = Math.max(...made.map((each) => each.big.size));
      expect(layout.big.size, name).toBe(most);
      const plain = made.find((each) => each.big.size === most);
      if (plain !== undefined && layout.K > plain.K) {
        heldToOneLine++;
        expect(runsOf(layout, 'season'), name).toHaveLength(1);
      } else expect(layout.K, name).toBe(plain?.K);
    }
    // With room to spare the school-year line is tried on one line: a step larger for it.
    expect(heldToOneLine).toBeGreaterThan(0);
    const short = LAID.find(({ name }) => name === 'short-school-year-story')?.layout;
    expect(short?.K).toBe(1.4);
    expect(runsOf(layoutCard(sample('closed-story-light'), 'story', face), 'season')).toHaveLength(
      2,
    );
    if (short !== undefined) expect(runsOf(short, 'season')).toHaveLength(1);
    // A name of 91 letters: cut at the largest step, whole at a smaller one, so whole on the
    // card (in Geist, narrower than this face, the same holds for a hundred letters).
    const long = { ...sample('closed-story-light'), name: LONG_NAME, season: null };
    expect(said(layoutCard(long, 'story', face, 1.5), 'name')).toContain(shareCopy.cut);
    const kept = layoutCard(long, 'story', face);
    expect(said(kept, 'name')).toBe(LONG_NAME);
    expect(runsOf(kept, 'name')).toHaveLength(3);
    expect(kept.K).toBeLessThan(1.5);
    expect(NAME_100).toHaveLength(100);
  });

  it('says the school-year line whole on one line or two, or not at all', () => {
    for (const { name, model, layout } of LAID) {
      const lines = runsOf(layout, 'season');
      if (lines.length === 0) continue;
      expect(said(layout, 'season'), name).toBe(model.season);
      expect(lines.length, name).toBeLessThanOrEqual(2);
      for (const run of lines) {
        expect(run.size, name).toBeGreaterThanOrEqual(40);
        expect(run.size, name).toBeLessThanOrEqual(Math.max(40, Math.round(38 * layout.K)));
        expect(run.color).toBe(layout.colors.small);
      }
    }
    const base = sample('nearby-four-counts-story');
    const season = base.season ?? '';
    // Two lines break after the colon where both fit at 40 or more.
    const colon = layoutCard(sample('closed-story-light'), 'post', face, 1);
    expect(runsOf(colon, 'season').map((run) => run.text)).toEqual([
      'This school year, since Aug 1:',
      'closed 2 days, delayed 1.',
    ]);
    // Four counts: too long after the colon, so after a comma, no count parted from its unit;
    // whole at every step a Closed Story may take.
    expect(season).toBe(
      'This school year, since Oct 27: closed 4 days, delayed 3, remote 1, dismissed early 2.',
    );
    for (const K of stepsOf(base, 'story')) {
      const layout = layoutCard(base, 'story', face, K);
      expect(layout.dropped, String(K)).toEqual([]);
      expect(
        runsOf(layout, 'season').map((run) => run.text),
        String(K),
      ).toEqual([
        'This school year, since Oct 27: closed 4 days,',
        'delayed 3, remote 1, dismissed early 2.',
      ]);
    }
    // Neither a colon nor a comma: at a space, the two lines as even as they go.
    const plain =
      'one two three four five six seven eight nine ten eleven twelve thirteen fourteen';
    const spaced = layoutCard({ ...base, season: plain }, 'post', face, 1);
    expect(runsOf(spaced, 'season').map((run) => run.text)).toEqual([
      'one two three four five six seven eight',
      'nine ten eleven twelve thirteen fourteen',
    ]);
    // Too long for two lines at 40: left out whole, never cut, and nothing else goes for it.
    const endless = layoutCard({ ...base, season: `${season} ${season} ${season}` }, 'story', face);
    expect(runsOf(endless, 'season')).toEqual([]);
    expect(endless.dropped).toEqual([]);
    expect(said(endless, 'reason')).toBe(base.lines[0]?.reason);
  });

  it('says another day, or a chance under a status, as one line each', () => {
    // Closed today and tomorrow: the second day is one line under the first's facts.
    const two = modelOf(viewOf({ status: CLOSED_TWO_DAYS, season: SEASON }));
    for (const kind of KINDS) {
      const layout = layoutCard(two, kind, face);
      const more = runsOf(layout, 'more');
      expect(more.map((run) => run.text)).toEqual([
        shareFormat.secondDay(copy.statusLine.closed.tomorrow, true, 'Tuesday, Jan 13'),
      ]);
      expect(more[0]?.text).toBe('Closed tomorrow too · Tuesday, Jan 13');
      expect(more[0]?.size).toBeLessThanOrEqual(Math.round(46 * layout.K));
      expect(more[0]?.color).toBe(layout.colors.type);
      expect(said(layout, 'big')).toBe(copy.statusLine.closed.today);
    }
    // 46 down to 40; then without its date; then cut.
    const base = sample('remote-story');
    const second = (headline: string): CardModel => ({
      ...base,
      lines: [
        ...base.lines,
        {
          tone: 'remote',
          headline,
          day: 'Wednesday, Sep 30',
          detail: null,
          reason: null,
          said: null,
        },
      ],
    });
    const tomorrow = copy.statusLine.remote.tomorrow;
    const fitted = layoutCard(second(tomorrow), 'post', wider(1.05), 1);
    expect(said(fitted, 'more')).toBe(`${tomorrow} too · Wednesday, Sep 30`);
    expect(runsOf(fitted, 'more')[0]?.size).toBeLessThan(46);
    expect(runsOf(fitted, 'more')[0]?.size).toBeGreaterThanOrEqual(40);
    const undated = layoutCard(second(tomorrow), 'post', wider(1.15), 1);
    expect(said(undated, 'more')).toBe(`${tomorrow} too`);
    expect(runsOf(undated, 'more')[0]?.size).toBe(46);
    const cut = layoutCard(second(`${tomorrow} ${tomorrow} ${tomorrow}`), 'post', face, 1);
    expect(said(cut, 'more')).toMatch(/^Remote learning tomorrow Remote.*[^ ]…$/u);
    expect(runsOf(cut, 'more')[0]?.size).toBe(40);

    // The card is about its first line that is not open: an open today reads as the other day.
    const openFirst = layoutCard(sample('open-then-closed-story'), 'story', face);
    expect(openFirst.tone).toBe('closed');
    expect(said(openFirst, 'big')).toBe(copy.statusLine.closed.tomorrow);
    expect(said(openFirst, 'day')).toBe('Tuesday, Jan 13');
    expect(said(openFirst, 'more')).toBe('Open today · Monday, Jan 12');
    // Open with a chance is the chance's card, the open line under it.
    const openChance = layoutCard(sample('open-with-chance-post'), 'post', face);
    expect(openChance.tone).toBe('chance');
    expect(openChance.ticks).not.toBeNull();
    expect(said(openChance, 'more')).toBe('Open today · Monday, Jan 12');
    // Open alone is a status card in open's own colors.
    const open = layoutCard(sample('open-story'), 'story', face);
    expect(open.tone).toBe('open');
    expect(said(open, 'big')).toBe(copy.open.today);
    // Closed with a chance is a status card: the chance one line, no big number and no ticks.
    for (const kind of KINDS) {
      const layout = layoutCard(sample(`closed-with-chance-${kind}`), kind, face);
      expect(layout.tone).toBe('closed');
      expect(layout.ticks).toBeNull();
      expect(runsOf(layout, 'digits', 'sign', 'meaning', 'chance-day')).toEqual([]);
      expect(runsOf(layout, 'chance').map((run) => run.text)).toEqual([
        '64% · Chance of no school Tuesday',
      ]);
    }
    // And under it the few-records line, where the chance has one, set as the place is.
    const withChance = sample('closed-with-chance-story');
    const few = layoutCard(
      {
        ...withChance,
        chance:
          withChance.chance === null
            ? null
            : { ...withChance.chance, fewRecords: 'Few local records' },
      },
      'story',
      face,
    );
    const [line] = runsOf(few, 'chance');
    const [under] = runsOf(few, 'few');
    expect(under?.text).toBe('Few local records');
    expect(under?.color).toBe(few.colors.small);
    expect(under?.weight).toBe(500);
    expect((under?.y ?? 0) - CAP * (under?.size ?? 0) - (line?.y ?? 0)).toBeCloseTo(
      Math.round(22 * few.K),
      6,
    );
  });

  it('leaves out its least needed lines first, in one order, and is not made where that is not enough', () => {
    expect(LEFT_OUT).toEqual(['said', 'season', 'reason', 'more']);
    const gone: Record<LeftOut, readonly Role[]> = {
      said: ['words'],
      season: ['season'],
      reason: ['reason', 'words'],
      more: ['more', 'chance', 'few'],
    };
    const model = heaviest();
    expect(model.lines).toHaveLength(2);
    expect(model.lines.every((line) => (line.said?.length ?? 0) > 200)).toBe(true);
    let left = 0;
    for (const card of LAID) {
      const { layout } = card;
      left += layout.dropped.length;
      // In the order, and only lines the card has.
      expect(leavable(card.model).slice(0, layout.dropped.length), card.name).toEqual(
        layout.dropped,
      );
      for (const part of layout.dropped) {
        expect(runsOf(layout, ...gone[part]), `${card.name}: ${part}`).toEqual([]);
      }
      // The school, its answer, its day and times and as of when always stay.
      const lead = leadOf(card.model);
      if (lead !== undefined) {
        expect(said(layout, 'big')).toBe(lead.headline);
        expect(said(layout, 'day')).toBe(lead.day ?? '');
        expect(
          runsOf(layout, 'fact')
            .map((run) => run.text)
            .join(' · '),
        ).toBe(lead.detail ?? '');
      }
      expect(said(layout, 'as-of')).toBe(card.model.asOf);
      expect(layout.K).toBeGreaterThanOrEqual(1);
    }
    // The heaviest real card is made in both formats: its name on three lines, its second day
    // one line, and on a Post the school's words and the school-year line left out for it.
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, face);
      expect(runsOf(layout, 'name')).toHaveLength(3);
      expect(said(layout, 'name')).toBe(model.name);
      expect(said(layout, 'more')).toBe('Early dismissal tomorrow · Tuesday, Jan 13');
      expect(Math.min(...layout.runs.map((run) => run.size))).toBeGreaterThanOrEqual(40);
    }
    expect(left).toBeGreaterThan(0);
    expect(layoutCard(model, 'post', face).dropped[0]).toBe('said');
    // A face ten times as wide: no card, rather than one line over another.
    for (const kind of KINDS) {
      expect(() => layoutCard(sample('closed-story-light'), kind, wider(10))).toThrow(
        'the words do not fit',
      );
      expect(() => layoutCard(model, kind, wider(10))).toThrow();
    }
    // A card with nothing to say is not a card.
    expect(() =>
      layoutCard({ ...sample('closed-story-light'), lines: [], chance: null }, 'story', face),
    ).toThrow();
  });

  it('never cuts a line that a smaller size or another break holds whole', () => {
    // A reason alone shrinks to stay whole, at every step a card may take.
    const nearby = sample('nearby-school-words-story');
    const reason = nearby.lines[0]?.reason ?? '';
    expect(reason).toBe('A district nearby said severe storms');
    const alone: CardModel = {
      ...nearby,
      lines: nearby.lines.map((line) => ({ ...line, said: null })),
    };
    for (const K of stepsOf(alone, 'story')) {
      const layout = layoutCard(alone, 'story', face, K);
      expect(said(layout, 'reason'), String(K)).toBe(reason);
      expect(runsOf(layout, 'reason')[0]?.size).toBeLessThanOrEqual(Math.round(50 * K));
    }
    // The reason and the school's words: one paragraph on one line or two, whole sentences only,
    // the last left out first; no line begins with the middle dot.
    const sentences = shareFormat.sentences(nearby.lines[0]?.said ?? '');
    expect(sentences).toHaveLength(2);
    const allowed = sentences.map((_, n) =>
      shareFormat.paragraph(reason, sentences.slice(0, n + 1)),
    );
    let paragraphs = 0;
    for (const kind of KINDS) {
      for (const K of stepsOf(nearby, kind)) {
        const layout = layoutCard(nearby, kind, face, K);
        const words = runsOf(layout, 'words');
        if (words.length === 0) {
          expect(said(layout, 'reason')).toBe(layout.dropped.includes('reason') ? '' : reason);
          continue;
        }
        paragraphs++;
        expect(words.length).toBeLessThanOrEqual(2);
        expect(allowed).toContain(said(layout, 'words'));
        expect(runsOf(layout, 'reason')).toEqual([]);
        for (const run of words) {
          expect(run.text.startsWith('·')).toBe(false);
          expect(run.size).toBeGreaterThanOrEqual(40);
          expect(run.size).toBeLessThanOrEqual(Math.round(44 * K));
        }
      }
    }
    expect(paragraphs).toBeGreaterThan(0);
    // Every plain detail at once: what stands is whole sentences from the first on.
    const model = heaviest();
    const every = shareFormat.sentences(model.lines[0]?.said ?? '');
    for (const kind of KINDS) {
      const shown = said(layoutCard(model, kind, face), 'words');
      if (shown === '') continue;
      const kept = every.findIndex(
        (_, n) =>
          shareFormat.paragraph(model.lines[0]?.reason ?? null, every.slice(0, n + 1)) === shown,
      );
      expect(kept, shown).toBeGreaterThan(-1);
    }
    // Of the samples, only the 60-character place and the two over-long names may end cut.
    for (const { name, layout } of LAID) {
      for (const run of layout.runs) {
        expect(run.text.startsWith('·'), `${name}: ${run.text}`).toBe(false);
        if (!run.text.endsWith(shareCopy.cut)) continue;
        expect(name, run.text).toMatch(/^(place-60|name-one-word|name-100)-/u);
        expect(run.role, run.text).toBe(name.startsWith('place') ? 'place' : 'name');
        expect(run.size, run.text).toBe(run.role === 'place' ? 40 : Math.round(48 * layout.K));
      }
    }
    // The long place is cut at 40, whole letters, no space before the mark.
    const place = runsOf(layoutCard(sample('place-60-story'), 'story', face), 'place')[0];
    expect(PLACE_60).toHaveLength(60);
    expect(place?.size).toBe(40);
    expect(place?.text).toMatch(/[^ ]…$/u);
    expect(PLACE_60.startsWith(place?.text.slice(0, -1) ?? 'none')).toBe(true);
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
      const layout = layoutCard(model, kind, face);
      const lines = runsOf(layout, 'name');
      expect(lines.length).toBeGreaterThan(1);
      expect(said(layout, 'name')).toBe(model.name);
    }
  });

  it('tries a name on three lines at 48 x K itself where the steps of 2 from 60 x K pass it by', () => {
    // At K 1.1 the sizes run 66, 64 ... 54 and then 53 (48 x 1.1). In a face 0.98 as wide, a
    // word of 30 letters stands alone on a line at 53 and not at 54, so the name breaks three
    // ways only at 53, and there by the row's own rule: fewest lines, then the narrowest
    // widest line, the first such break taken.
    const long = 'A'.padEnd(30, 'a');
    const name = `Bbbbbb Cccccc Dddddd Eeeeee Ffffff Gggggg ${long}`;
    const model = { ...sample('closed-story-light'), name, season: null };
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, wider(0.98), 1.1);
      const lines = runsOf(layout, 'name');
      expect(lines.map((run) => run.size)).toEqual([53, 53, 53]);
      expect(lines.map((run) => run.text)).toEqual([
        'Bbbbbb Cccccc',
        'Dddddd Eeeeee Ffffff Gggggg',
        long,
      ]);
      expect((lines[1]?.y ?? 0) - (lines[0]?.y ?? 0)).toBe(Math.round(53 * 1.13));
    }
  });

  it('breaks a word too wide for a line of its own, and ends a name too long for three lines cut', () => {
    const view = viewOf({ status: CLOSED_TWO_DAYS, season: SEASON });
    const base = modelOf(view);
    const model: CardModel = {
      ...base,
      name: `${'Supercalifragilistic'.repeat(4)} ${base.name} ${base.name} ${base.name}`,
    };
    for (const kind of KINDS) {
      const layout = layoutCard(model, kind, face);
      const lines = runsOf(layout, 'name');
      expect(lines).toHaveLength(3);
      for (const run of lines) expect(run.x + run.width).toBeLessThanOrEqual(RIGHT + 1e-6);
      expect(lines.at(-1)?.text.endsWith(shareCopy.cut)).toBe(true);
      expect(layout.K).toBeGreaterThanOrEqual(1);
      // What is shown is the name's own letters, in order, up to the cut.
      const shown = lines
        .map((run) => run.text)
        .join('')
        .replace(/\s|…/gu, '');
      expect(model.name.replace(/\s/gu, '').startsWith(shown)).toBe(true);
    }
    // One word of 80 letters: broken across lines, never clipped, never past the right edge.
    const word = layoutCard(sample('name-one-word-story'), 'story', face);
    const broken = runsOf(word, 'name');
    expect(broken.length).toBeGreaterThan(1);
    expect(broken.length).toBeLessThanOrEqual(3);
    expect(
      NAME_ONE_WORD.startsWith(
        broken
          .map((run) => run.text)
          .join('')
          .replace('…', ''),
      ),
    ).toBe(true);
  });

  it('wraps at spaces, and breaks only a word wider than the line', () => {
    const width = (text: string): number => text.length * 10;
    expect(wrap('one two three', 80, width)).toEqual(['one two', 'three']);
    expect(wrap('abcdefghijkl', 50, width)).toEqual(['abcde', 'fghij', 'kl']);
    expect(wrap('', 50, width)).toEqual([]);
    // A no-break space holds a time to its AM.
    expect(wrap('As of 6:55 AM', 100, width)).toEqual(['As of', '6:55 AM']);
  });

  it('sets a chance as its number over fifty ticks, lit by twos', () => {
    const lit = (name: string): number | undefined =>
      layoutCard(sample(name), 'story', face).ticks?.lit;
    expect(lit('chance-story-dark')).toBe(32);
    expect(lit('chance-7-story')).toBe(4);
    expect(lit('chance-under-1-story')).toBe(0);
    expect(lit('chance-over-99-story')).toBe(50);
    expect(TICKS_TALLEST).toEqual({ story: 240, post: 170 });
    let seen = 0;
    let lighter = 0;
    for (const { name, kind, model, layout } of LAID) {
      const { ticks } = layout;
      if (ticks === null) continue;
      seen++;
      const [digits] = runsOf(layout, 'digits');
      const [sign] = runsOf(layout, 'sign');
      if (digits === undefined || sign === undefined) throw new Error('no number');
      // Fifty bars across the measure, 6 apart.
      expect([ticks.count, ticks.x, ticks.gap]).toEqual([50, 84, 6]);
      expect(ticks.bar).toBeCloseTo(12.36, 6);
      expect(ticks.x + 49 * (ticks.bar + ticks.gap) + ticks.bar).toBeCloseTo(996, 6);
      // Their top 50 times K under the number's baseline; 104 times K tall or more, up to the cap.
      expect(ticks.y - digits.y, name).toBeCloseTo(Math.round(50 * layout.K), 6);
      expect(ticks.height, name).toBeGreaterThanOrEqual(Math.round(104 * layout.K));
      expect(ticks.height, name).toBeLessThanOrEqual(TICKS_TALLEST[kind]);
      // The sign at 0.42 of the size, its top level with the digits', 0.06 of the size after them.
      expect(sign.size).toBe(Math.floor(digits.size * 0.42));
      expect(sign.y - CAP * sign.size).toBeCloseTo(digits.y - CAP * digits.size, 6);
      expect(sign.x).toBeCloseTo(LEFT + digits.width + 0.06 * digits.size, 6);
      // With few local records the number is lighter, as the panel shows it.
      const few = (model.chance?.fewRecords ?? null) !== null;
      if (few) lighter++;
      const color = few ? layout.colors.small : layout.colors.big;
      expect([digits.color, sign.color], name).toEqual([color, color]);
      expect(runsOf(layout, 'chance-day')[0]?.color).toBe(layout.colors.small);
      expect(said(layout, 'few')).toBe(model.chance?.fewRecords ?? '');
    }
    expect(seen).toBeGreaterThanOrEqual(12);
    expect(lighter).toBeGreaterThan(0);
  });

  it('stands the crystal on the hill, under the answer, and never moves the hill', () => {
    expect(CREST).toEqual({ story: 1785, post: 1284 });
    expect(ARM).toEqual({ most: 550, least: 150 });
    for (const { name, kind, layout } of LAID) {
      const { art } = layout;
      const { height } = CARD_SIZES[kind];
      const crest = CREST[kind];
      expect([art.width, art.height, art.crest]).toEqual([1080, height, crest]);
      // The hill: from the bottom left corner, over its crest, to the bottom right corner.
      expect(art.hill).toEqual([
        [0, height],
        [540, 2 * crest - height],
        [1080, height],
      ]);
      expect(art.hill[1]?.[1]).toBe(kind === 'story' ? 1650 : 1218);
      // The crystal stops 28 pixels under the answer's last baseline, or under the ticks.
      const big = runsOf(layout, 'big').at(-1);
      const under = layout.ticks === null ? (big?.y ?? NaN) : layout.ticks.y + layout.ticks.height;
      expect(art.ceiling, name).toBeCloseTo(under + 28, 6);
      expect(art.r, name).toBeCloseTo(Math.min(550, (crest - art.ceiling) / (1 + 112 / 456)), 6);
      expect(1 + 112 / 456).toBeCloseTo(1.2456, 4);
      const s = art.r / 456;
      expect([art.cx, art.cy]).toEqual([540, crest - 112 * s]);
      expect(art.tip, name).toBeCloseTo(art.cy - art.r, 6);
      expect(art.tip, name).toBeGreaterThanOrEqual(art.ceiling - 1e-6);
      // The breath: the hill's curve, 50 per 456 of arm higher.
      expect(art.breath).toEqual([
        [0, height - 50 * s],
        [540, 2 * crest - height - 50 * s],
        [1080, height - 50 * s],
      ]);
      expect(art.crystal, name).toBe(art.r >= 150);
    }
    // The design's samples, in this face: a full arm on the status Stories, smaller on the rest.
    const arm = (name: string, kind: CardKind): number =>
      Math.round(layoutCard(sample(name), kind, face).art.r);
    expect(arm('closed-story-light', 'story')).toBe(550);
    expect(arm('delayed-story-light', 'story')).toBe(550);
    expect(arm('chance-story-dark', 'story')).toBeLessThan(550);
    expect(arm('closed-post-light', 'post')).toBeLessThan(550);
    expect(arm('chance-post-dark', 'post')).toBeLessThan(arm('chance-story-dark', 'story'));
  });

  it('signs off with the logo on the bottom line and the address beside it', () => {
    for (const { name, kind, model, layout } of LAID) {
      const { mark } = layout;
      const address = Math.round(48 * layout.K);
      expect(mark.height, name).toBe(Math.round(1.3 * address));
      expect(mark.u).toBeCloseTo(mark.height / 19, 9);
      expect(mark.width).toBeCloseTo(23 * mark.u, 9);
      expect([mark.left, mark.bottom]).toEqual([84, FRAME[kind].bottom]);
      // Grid point (0.5, 21) on the left edge and the bottom line.
      expect(mark.x + 0.5 * mark.u).toBeCloseTo(84, 9);
      expect(mark.y + 21 * mark.u).toBeCloseTo(mark.bottom, 9);
      const [host] = runsOf(layout, 'host');
      expect(host?.text, name).toBe(model.host);
      expect(host?.x).toBeCloseTo(84 + mark.width + 0.36 * address, 9);
      expect(host?.y).toBe(mark.bottom - Math.round(0.35 * address));
      expect(host?.size).toBe(address);
      expect(host?.color).toBe(layout.colors.type);
      // The school-year line's last baseline 40 times K over the top of the mark.
      const season = runsOf(layout, 'season').at(-1);
      if (season !== undefined) {
        expect(mark.bottom - mark.height - season.y, name).toBeCloseTo(
          Math.round(40 * layout.K),
          6,
        );
      }
    }
    // An address too wide for its room shrinks to it, never under 40, never past the right edge.
    const base = sample('closed-story-light');
    const long = layoutCard(
      { ...base, host: 'a-long-preview-name.snowlightmap.example' },
      'story',
      face,
    );
    const [host] = runsOf(long, 'host');
    expect(host?.size).toBeLessThan(Math.round(48 * long.K));
    expect(host?.size).toBeGreaterThanOrEqual(40);
    expect((host?.x ?? 0) + (host?.width ?? 0)).toBeLessThanOrEqual(RIGHT + 1e-6);
    expect(host?.y).toBe(1650 - Math.round(0.35 * Math.round(48 * long.K)));
    // No host: the mark alone.
    const bare = layoutCard({ ...base, host: '' }, 'story', face);
    expect(runsOf(bare, 'host')).toEqual([]);
    expect(bare.mark.bottom).toBe(1650);
  });

  it('draws in flat fills alone, each line letter by letter where the layout put it', () => {
    const allowed = new Set([
      'fillRect',
      'beginPath',
      'moveTo',
      'lineTo',
      'quadraticCurveTo',
      'closePath',
      'fill',
      'fillText',
      'save',
      'restore',
      'translate',
      'rotate',
      'scale',
    ]);
    for (const { name, kind, layout } of LAID) {
      const { ctx, calls, set } = recorder();
      drawCard(ctx, layout);
      // No gradient, shadow, blur, filter, blend, clip, stroke, arc or image; nothing measured.
      expect(
        [...new Set(calls.map((call) => call.name))].filter((call) => !allowed.has(call)),
        name,
      ).toEqual([]);
      expect(
        [...set].filter((key) => !['font', 'fillStyle', 'textAlign', 'textBaseline'].includes(key)),
        name,
      ).toEqual([]);
      expect(set.has('letterSpacing') || set.has('wordSpacing')).toBe(false);
      // The field first, edge to edge; the hill before any word.
      expect(calls[0]).toMatchObject({
        name: 'fillRect',
        args: [0, 0, 1080, CARD_SIZES[kind].height],
        fillStyle: layout.colors.field,
      });
      const firstWord = calls.findIndex((call) => call.name === 'fillText');
      const hill = calls.findIndex(
        (call) =>
          call.name === 'fill' &&
          call.fillStyle === layout.colors.hill &&
          call.path[1]?.[1] === layout.art.hill[1]?.[1],
      );
      expect(hill, name).toBeGreaterThan(0);
      expect(hill, name).toBeLessThan(firstWord);
      // The crystal, where it is drawn: six arms in the flake's tone, then the breath in the field's.
      const before = calls.slice(1, hill).filter((call) => call.name === 'fill');
      expect(
        before.map((call) => call.fillStyle),
        name,
      ).toEqual(
        layout.art.crystal
          ? [...Array<string>(6).fill(layout.colors.flake), layout.colors.field]
          : [],
      );
      // One fillText a letter, at the layout's places, in the run's color.
      const texts = calls.filter((call) => call.name === 'fillText');
      const expected = layout.runs.flatMap((run) =>
        letters(run.text).map((letter, i) => [letter, run.at[i], run.y, run.color]),
      );
      expect(
        texts.map((call) => [...call.args, call.fillStyle]),
        name,
      ).toEqual(expected);
      for (const call of texts) expect(call.font).toMatch(/^(500|600|700) \d+px "Geist Variable"/u);
      // The ticks: fifty bars, the lit ones first.
      const bars = calls.filter((call) => call.name === 'fillRect').slice(1);
      expect(bars.length, name).toBe(layout.ticks === null ? 0 : 50);
      if (layout.ticks !== null) {
        expect(bars.map((call) => call.fillStyle)).toEqual([
          ...Array<string>(layout.ticks.lit).fill(TICK_COLORS.lit),
          ...Array<string>(50 - layout.ticks.lit).fill(TICK_COLORS.unlit),
        ]);
        expect(bars[49]?.args).toEqual([
          84 + 49 * (layout.ticks.bar + 6),
          layout.ticks.y,
          layout.ticks.bar,
          layout.ticks.height,
        ]);
      }
    }
    // Under an arm of 150 no crystal is drawn: the hill alone.
    const small = LAID[0]?.layout;
    if (small === undefined) throw new Error('no card');
    const { ctx, calls } = recorder();
    drawCard(ctx, { ...small, art: { ...small.art, r: 149, crystal: false } });
    const fills = calls.filter((call) => call.name === 'fill');
    expect(fills.map((call) => call.fillStyle)).toEqual([
      small.colors.hill,
      ...Array<string>(5).fill(small.colors.type),
    ]);
  });

  it('keeps each kern before its own letter, and tracks every letter after it', () => {
    // "Tuesday, Jan 13" as a day line: the "u" starts 8 per 100 of size nearer the "T" than
    // the face's plain advances put it, and so does every letter after it.
    const layout = layoutCard(sample('closed-tomorrow-story'), 'story', face);
    const [day] = runsOf(layout, 'day');
    if (day === undefined) throw new Error('no day');
    expect(day.text).toBe('Tuesday, Jan 13');
    expect(day.weight).toBe(700);
    const tracking = -0.022;
    letters(day.text).forEach((_, i) => {
      const plain = i * 60 + i * tracking * 100;
      expect(day.at[i]).toBeCloseTo(day.x + ((plain - (i > 0 ? 8 : 0)) * day.size) / 100, 6);
    });
    expect(day.width).toBeCloseTo(((15 * 60 - 8 + 14 * tracking * 100) * day.size) / 100, 6);
    // The offsets themselves, at 100 pixels: untracked they are the face's own advances.
    expect(offsets(face, 'Tue', 700, 0, 0)).toEqual([0, 52, 112]);
    expect(offsets(face, 'aTu', 700, 0, 0)).toEqual([0, 60, 112]);
    expect(offsets(face, 'a b c', 500, -0.01, 0.07)).toEqual([0, 45, 97, 142, 194]);
    // A no-break space is a word space too.
    expect(offsets(face, 'a b', 500, 0, 0.1)).toEqual([0, 46, 102]);
    // The big line's word space comes before the word after it.
    const one = offsets(face, 'Closed tomorrow', 700, -0.038, 0.07);
    expect(one[6]).toBeCloseTo(6 * 60 + 6 * -3.8, 9);
    expect(one[7]).toBeCloseTo(7 * 60 + 7 * -3.8 + 7, 9);
  });

  it('measures each text once in each weight for a card', () => {
    for (const { name, kind, model } of CARDS) {
      const seen = new Map<string, number>();
      layoutCard(model, kind, (text, weight) => {
        const key = `${String(weight)}|${text}`;
        seen.set(key, (seen.get(key) ?? 0) + 1);
        return face(text, weight);
      });
      const twice = [...seen].filter(([, count]) => count > 1);
      expect(twice, name).toEqual([]);
      expect(seen.size, name).toBeGreaterThan(20);
    }
  });

  it('holds the gaps and the metrics of the design, at K and at 1', () => {
    expect([CAP, DESC]).toEqual([0.71, 0.17]);
    for (const { name, kind, layout } of LAID) {
      const k = (value: number): number => Math.round(value * layout.K);
      const at = (role: Role): TextRun | undefined => runsOf(layout, role)[0];
      const capTop = (run: TextRun | undefined): number =>
        (run?.y ?? NaN) - CAP * (run?.size ?? NaN);
      const place = at('place');
      const school = at('name');
      // Place to name: 30 times K, and 2 pixels more at any K.
      if (place !== undefined) expect(capTop(school) - place.y, name).toBeCloseTo(k(30) + 2, 6);
      // Name, or campus, to the answer: 66 times K, plus what a sparse Story shares out.
      const head = at('big') ?? at('digits');
      const above = at('campus') ?? runsOf(layout, 'name').at(-1);
      const shift = capTop(head) - (above?.y ?? NaN) - k(66);
      expect(shift, name).toBeGreaterThanOrEqual(-1e-6);
      expect(shift, name).toBeLessThanOrEqual(kind === 'story' ? 64 : 1e-6);
      const day = at('day');
      const big = runsOf(layout, 'big').at(-1);
      if (day !== undefined && big !== undefined) {
        // The answer's descender to the day: 46 times K (and the Story's share again).
        expect(capTop(day) - (big.y + DESC * big.size), name).toBeCloseTo(k(46) + shift, 6);
      }
      const asOf = at('as-of');
      const before = layout.runs[layout.runs.findIndex((run) => run.role === 'as-of') - 1];
      if (asOf !== undefined && before !== undefined && before.role !== 'sign') {
        expect(capTop(asOf) - before.y, name).toBeCloseTo(k(38), 6);
      }
      // Open space is kept over the bottom group: 56 on a Story, 40 on a Post.
      const below = at('season');
      const groupTop =
        below === undefined ? layout.mark.bottom - layout.mark.height : capTop(below);
      expect(groupTop - (asOf?.y ?? NaN), name).toBeGreaterThanOrEqual(
        (kind === 'story' ? 56 : 40) - 1,
      );
    }
  });
});
