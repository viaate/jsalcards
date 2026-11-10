/**
 * A share card drawn: the layout of a card's model (app/share-card.ts) on its
 * Story or Post canvas, and the PNG of it, made in the browser. Dark like the
 * map, the school's status glowing in its own color behind it, its words in
 * the site's own face (Geist, which the page already has), large enough to
 * read on a phone at a story's size. The layout is worked out first, every
 * line measured and wrapped to the card's width (a word too wide for it
 * broken, never clipped; a headline's last word never left alone on its
 * line), the whole sized to fill the room between the card's safe margins:
 * a story keeps its top and bottom 250 pixels free of words, where a
 * story's own bars sit. Where the words cannot fit at a size still easy to
 * read, the card leaves out its least needed lines (the season, then the
 * plain details, then the reason) rather than shrink further, and where even
 * that is not enough it is not made at all: no line ever runs into another.
 * Loaded with the first press of Share, never with the page.
 */

import { CARD_SIZES } from '../app/share-card';
import type { CardKind, CardModel, CardTone } from '../app/share-card';

import { MARK_GRID, drawMark } from './share-card-art';

/** The site's face, as the page's style sheet names it. */
export const CARD_FONT = '"Geist Variable", system-ui, sans-serif';

/** The status colors, as the map's legend draws them (src/styles/global.css). */
export const TONE_COLORS: Readonly<Record<CardTone, string>> = Object.freeze({
  closed: '#7fd4ff',
  delayed: '#ffc46b',
  remote: '#b79cff',
  earlyDismissal: '#6bffb0',
  open: '#a3a3a3',
  chance: '#7fd4ff',
  none: '#6b6b6b',
});

const TEXT_1 = '#f5f5f5';
const TEXT_2 = '#a3a3a3';
const TEXT_3 = '#6b6b6b';
/** The dark: the map's, a breath off black so the glow has something to fall into. */
const BACKGROUND = '#050607';

/** The room kept clear each side of the words, in pixels. */
const SIDE = 96;
/** A story's top and bottom, kept free of words for its own bars. */
export const STORY_SAFE = 250;
/** A post's top and bottom margin. */
const POST_MARGIN = 96;
/** The most the type steps up to fill a card with little to say, as a share of its full size. */
export const MAX_SCALE: Readonly<Record<CardKind, number>> = Object.freeze({
  story: 1.2,
  post: 1.1,
});
/**
 * The least the type steps down to: the smallest words (the site's name, 36 pixels on a
 * story) stay above 25 pixels, easy to read on a phone. Below it the card leaves lines out.
 */
export const MIN_SCALE = 0.7;
/** The lines a card leaves out, in this order, before its type would go below MIN_SCALE. */
export const DROPPED_FIRST = ['season', 'said', 'reason'] as const;
export type Droppable = (typeof DROPPED_FIRST)[number];

/** One run of text, its baseline at `y`, its left at `x`. */
export interface TextRun {
  readonly text: string;
  readonly x: number;
  readonly y: number;
  /** Its size in pixels. */
  readonly size: number;
  readonly weight: number;
  readonly color: string;
  /** Its measured width. */
  readonly width: number;
  /** What part of the card it is, for tests and the drawing's order. */
  readonly role: string;
}

export interface CardLayout {
  readonly kind: CardKind;
  readonly width: number;
  readonly height: number;
  /** The words' box: no run reaches outside it. */
  readonly box: {
    readonly top: number;
    readonly bottom: number;
    readonly left: number;
    readonly right: number;
  };
  readonly runs: readonly TextRun[];
  /** The badge for the school's initial (a school's logo stands here once there are logos). */
  readonly badge: {
    readonly x: number;
    readonly y: number;
    readonly size: number;
    readonly letter: string;
  };
  /** The site's mark beside the wordmark: its top left corner and size. */
  readonly mark: { readonly x: number; readonly y: number; readonly size: number };
  /** The hairline over the wordmark's row. */
  readonly rule: { readonly y: number; readonly left: number; readonly right: number };
  /** The lines left out to fit (DROPPED_FIRST), none for any card with room for all. */
  readonly dropped: readonly Droppable[];
  /** The dot before each status headline, in its status's color. */
  readonly dots: readonly {
    readonly x: number;
    readonly y: number;
    readonly r: number;
    readonly color: string;
  }[];
  /** The glow's center and reach, and its color. */
  readonly glow: {
    readonly x: number;
    readonly y: number;
    readonly r: number;
    readonly color: string;
    readonly strength: number;
  };
  /** How far the type stepped down to fit: 1 is full size. */
  readonly scale: number;
}

/** Measures `text` at `size` pixels and `weight`, in the card's face. */
export type Measure = (text: string, size: number, weight: number) => number;

/** The font shorthand a canvas takes. */
export function fontOf(size: number, weight: number): string {
  return `${String(weight)} ${String(Math.round(size))}px ${CARD_FONT}`;
}

/** A text's letters as a reader sees them (graphemes), so none is ever cut in two. */
function graphemes(text: string): string[] {
  return Array.from(
    new Intl.Segmenter('en-US', { granularity: 'grapheme' }).segment(text),
    (part) => part.segment,
  );
}

/**
 * Wraps `text` into lines no wider than `width`: at spaces, and a word wider
 * than the line on its own broken where it must, so nothing is ever cut off.
 */
export function wrap(text: string, width: number, measure: (text: string) => number): string[] {
  // At spaces only: a no-break space ("6:55 AM", "2-hour delay") holds its words together.
  const words = text.split(/[ \t\n]+/u).filter((word) => word.length > 0);
  const lines: string[] = [];
  let line = '';
  const pushWord = (word: string): void => {
    // A word too wide for a line of its own: as many of its letters as fit, line by line.
    let rest = word;
    while (measure(rest) > width && graphemes(rest).length > 1) {
      const chars = graphemes(rest);
      let fit = 1;
      while (fit < chars.length && measure(chars.slice(0, fit + 1).join('')) <= width) fit++;
      lines.push(chars.slice(0, fit).join(''));
      rest = chars.slice(fit).join('');
    }
    line = rest;
  };
  for (const word of words) {
    if (line === '') {
      pushWord(word);
      continue;
    }
    const joined = `${line} ${word}`;
    if (measure(joined) <= width) line = joined;
    else {
      lines.push(line);
      pushWord(word);
    }
  }
  if (line !== '') lines.push(line);
  return lines;
}

/** A block of the card: its lines at one size and weight, then the room after it. */
interface Block {
  readonly role: string;
  readonly text: string;
  readonly size: number;
  readonly weight: number;
  readonly color: string;
  /** Line height, as a share of the size. */
  readonly leading: number;
  /** Room after the block, in pixels at full scale. */
  readonly after: number;
  /** Indent from the left, in pixels at full scale (a headline after its dot). */
  readonly indent?: number;
  /** Never a last word alone on its line: a headline's or a name's. */
  readonly balance?: boolean;
}

/** The card's blocks top to bottom at full size: its head, its answer, and its foot. */
function blocks(model: CardModel, kind: CardKind): { head: Block[]; body: Block[]; foot: Block[] } {
  const story = kind === 'story';
  const head: Block[] = [];
  head.push({
    role: 'name',
    text: model.name,
    size: story ? 80 : 68,
    weight: 650,
    color: TEXT_1,
    leading: 1.1,
    after: 8,
    balance: true,
  });
  if (model.campus !== null) {
    head.push({
      role: 'campus',
      text: model.campus,
      size: story ? 46 : 40,
      weight: 450,
      color: TEXT_2,
      leading: 1.2,
      after: 6,
    });
  }
  if (model.place !== null) {
    head.push({
      role: 'place',
      text: model.place,
      size: story ? 40 : 36,
      weight: 450,
      color: TEXT_2,
      leading: 1.25,
      after: 0,
    });
  }
  const body: Block[] = [];
  model.lines.forEach((line, n) => {
    // The first line is the card's headline; a second (tomorrow's) a step smaller.
    const lead = n === 0;
    const size = lead ? (story ? 112 : 96) : story ? 72 : 60;
    body.push({
      role: `headline-${String(n)}`,
      text: line.headline,
      size,
      weight: 700,
      color: TEXT_1,
      leading: 1.06,
      after: 14,
      indent: Math.round(size * 0.62),
      balance: true,
    });
    if (line.day !== null) {
      body.push({
        role: `day-${String(n)}`,
        text: line.day,
        size: lead ? (story ? 54 : 48) : story ? 44 : 40,
        weight: 550,
        color: TEXT_1,
        leading: 1.2,
        after: 10,
      });
    }
    if (line.detail !== null) {
      body.push({
        role: `detail-${String(n)}`,
        text: line.detail,
        size: story ? 46 : 40,
        weight: 450,
        color: TEXT_1,
        leading: 1.25,
        after: 8,
      });
    }
    if (line.reason !== null) {
      body.push({
        role: `reason-${String(n)}`,
        text: line.reason,
        size: story ? 44 : 38,
        weight: 450,
        color: TEXT_2,
        leading: 1.25,
        after: 8,
      });
    }
    if (line.said !== null) {
      body.push({
        role: `said-${String(n)}`,
        text: line.said,
        size: story ? 44 : 38,
        weight: 450,
        color: TEXT_2,
        leading: 1.25,
        after: 8,
      });
    }
    body.push({
      role: `gap-${String(n)}`,
      text: '',
      size: 0,
      weight: 400,
      color: TEXT_1,
      leading: 0,
      after: lead ? 44 : 32,
    });
  });
  if (model.chance !== null) {
    const first = model.lines.length === 0;
    body.push({
      role: 'chance-number',
      text: model.chance.number,
      size: first ? (story ? 280 : 220) : story ? 150 : 120,
      weight: 700,
      color: model.chance.fewRecords === null ? TEXT_1 : TEXT_2,
      leading: 1.0,
      after: 18,
    });
    body.push({
      role: 'chance-meaning',
      text: model.chance.meaning,
      size: first ? (story ? 50 : 44) : story ? 46 : 40,
      weight: 550,
      color: TEXT_1,
      leading: 1.2,
      after: 8,
      balance: true,
    });
    body.push({
      role: 'chance-day',
      text: model.chance.day,
      size: first ? (story ? 46 : 40) : story ? 44 : 38,
      weight: 450,
      color: TEXT_2,
      leading: 1.25,
      after: 10,
    });
    if (model.chance.fewRecords !== null) {
      body.push({
        role: 'chance-few',
        text: model.chance.fewRecords,
        size: story ? 40 : 36,
        weight: 450,
        color: TEXT_2,
        leading: 1.25,
        after: 10,
      });
    }
    body.push({
      role: 'gap-chance',
      text: '',
      size: 0,
      weight: 400,
      color: TEXT_1,
      leading: 0,
      after: 28,
    });
  }
  if (model.season !== null) {
    body.push({
      role: 'season',
      text: model.season,
      size: story ? 40 : 36,
      weight: 450,
      color: TEXT_2,
      leading: 1.3,
      after: 0,
    });
  }
  const foot: Block[] = [
    {
      role: 'as-of',
      text: model.asOf,
      size: story ? 40 : 36,
      weight: 500,
      color: TEXT_2,
      leading: 1.25,
      after: 0,
    },
  ];
  return { head, body, foot };
}

interface Placed {
  readonly runs: TextRun[];
  readonly height: number;
  /** How many lines each headline and name took (the blocks that balance their lines). */
  readonly balanced: ReadonlyMap<string, number>;
}

/** Whether a block's last line is one word alone, after a line it could not take from. */
function orphaned(lines: readonly string[]): boolean {
  const last = lines.at(-1);
  return lines.length > 1 && last !== undefined && !/\s/u.test(last);
}

/**
 * A block's size and lines at `scale`: wrapped to `width`; a headline's or a name's with no
 * last word alone on its line, a step smaller where that is what it takes (down to 0.85 of
 * its size), else as wrapped.
 */
function settle(
  block: Block,
  scale: number,
  width: number,
  measure: Measure,
): { size: number; lines: string[] } {
  const at = (size: number): string[] => {
    const fit = (text: string): number => measure(text, size, block.weight);
    const wrapped = wrap(block.text, width, fit);
    return block.balance === true ? unorphan(wrapped, width, fit) : wrapped;
  };
  const size = block.size * scale;
  const lines = at(size);
  if (block.balance !== true || !orphaned(lines)) return { size, lines };
  for (const step of [0.95, 0.9, 0.85]) {
    const smaller = at(size * step);
    if (!orphaned(smaller)) return { size: size * step, lines: smaller };
  }
  return { size, lines };
}

/** Lays blocks out from `top`, each line wrapped to the box, at `scale` of their size. */
function place(
  list: readonly Block[],
  top: number,
  left: number,
  width: number,
  scale: number,
  measure: Measure,
): Placed {
  const runs: TextRun[] = [];
  const balanced = new Map<string, number>();
  let y = top;
  list.forEach((block, i) => {
    const last = i === list.length - 1;
    if (block.text === '') {
      if (!last) y += block.after * scale;
      return;
    }
    const indent = (block.indent ?? 0) * scale;
    const { size, lines } = settle(block, scale, width - indent, measure);
    const lineHeight = size * block.leading;
    if (block.balance === true) balanced.set(block.role, lines.length);
    lines.forEach((text) => {
      // The baseline: the ink (caps about 0.75 of the size above it, descenders 0.22 below)
      // centred in the line's height.
      const baseline = y + lineHeight * 0.5 + size * 0.265;
      runs.push({
        text,
        x: left + indent,
        y: baseline,
        size,
        weight: block.weight,
        color: block.color,
        width: measure(text, size, block.weight),
        role: block.role,
      });
      y += lineHeight;
    });
    if (!last) y += block.after * scale;
  });
  return { runs, height: y - top, balanced };
}

/**
 * Lines with no last word alone on its line where the line before it can give
 * one up and still fit: "Delayed start / today" becomes "Delayed / start
 * today". A word broken to fit is left as it is.
 */
export function unorphan(
  lines: readonly string[],
  width: number,
  measure: (text: string) => number,
): string[] {
  const out = [...lines];
  const last = out.length - 1;
  const before = out[last - 1];
  const alone = out[last];
  if (before === undefined || alone === undefined || /\s/u.test(alone)) return out;
  const cut = before.lastIndexOf(' ');
  if (cut <= 0) return out;
  const moved = `${before.slice(cut + 1)} ${alone}`;
  if (measure(moved) > width) return out;
  out[last - 1] = before.slice(0, cut);
  out[last] = moved;
  return out;
}

/** The room between the head and the answer, and the answer and the foot, at full scale. */
const GAP = { story: 96, post: 64 } as const;
const BADGE = { story: 132, post: 112 } as const;
/** The wordmark's size at full scale; the site's mark beside it a little larger. */
const WORDMARK = { story: 54, post: 48 } as const;
/** The site's name beside it, at the row's right. */
const HOST = { story: 36, post: 36 } as const;

/** Whether a block is one of the lines a card leaves out first, at this many dropped. */
function droppedAt(block: Block, count: number): boolean {
  return DROPPED_FIRST.slice(0, count).some(
    (kind) => block.role === kind || block.role.startsWith(`${kind}-`),
  );
}

/** The scales a card tries, from the largest down, in steps of 0.05. */
function scalesOf(kind: CardKind): number[] {
  const scales: number[] = [];
  for (let step = Math.round(MAX_SCALE[kind] * 20); step >= Math.round(MIN_SCALE * 20); step--) {
    scales.push(step / 20);
  }
  return scales;
}

/**
 * Lays a card out: the badge and the school at the top of its box, the foot
 * (as of when, a hairline, then the site's mark, its wordmark and its name)
 * at its bottom, the answer between them, the type as large as fits between
 * MAX_SCALE and MIN_SCALE. Throws where even the card's needed lines do not
 * fit at MIN_SCALE: a card is never drawn with one line over another.
 */
export function layoutCard(model: CardModel, kind: CardKind, measure: Measure): CardLayout {
  const { width, height } = CARD_SIZES[kind];
  const margin = kind === 'story' ? STORY_SAFE : POST_MARGIN;
  const box = { top: margin, bottom: height - margin, left: SIDE, right: width - SIDE };
  const inner = box.right - box.left;
  const parts = blocks(model, kind);
  for (let count = 0; count <= DROPPED_FIRST.length; count++) {
    const body = parts.body.filter((block) => !droppedAt(block, count));
    // Leaving out a line the card does not have changes nothing: the next one, then.
    if (count > 0 && body.length === parts.body.filter((b) => !droppedAt(b, count - 1)).length) {
      continue;
    }
    // A headline or a name grown past its full size never takes more lines for it: "Closed
    // today" stays one line, however much room the card has.
    const full = new Map([
      ...place(parts.head, 0, box.left, inner, 1, measure).balanced,
      ...place(body, 0, box.left, inner, 1, measure).balanced,
    ]);
    for (const scale of scalesOf(kind)) {
      const laid = tryLayout(model, kind, measure, { ...parts, body }, scale, box, inner, full);
      if (laid !== null) {
        return { ...laid, dropped: DROPPED_FIRST.slice(0, count) };
      }
    }
  }
  throw new Error('share card: the words do not fit');
}

type Box = CardLayout['box'];

/** A card laid out at one scale, or null where its answer does not fit between head and foot. */
function tryLayout(
  model: CardModel,
  kind: CardKind,
  measure: Measure,
  parts: { head: Block[]; body: Block[]; foot: Block[] },
  scale: number,
  box: Box,
  inner: number,
  full: ReadonlyMap<string, number>,
): Omit<CardLayout, 'dropped'> | null {
  const { width, height } = CARD_SIZES[kind];
  const badgeSize = BADGE[kind] * scale;
  const gap = GAP[kind] * scale;
  const headTop = box.top + badgeSize + 40 * scale;
  const head = place(parts.head, headTop, box.left, inner, scale, measure);
  // The foot, from its bottom up: the wordmark's row, a hairline over it, as of when over that;
  // never larger than its full size, however little the card has to say.
  const footScale = Math.min(1, scale);
  const wordSize = WORDMARK[kind] * footScale;
  const markSize = wordSize * 1.4;
  const rowHeight = markSize;
  const asOf = place(parts.foot, 0, box.left, inner, footScale, measure);
  const ruleGap = 36 * footScale;
  const footHeight = asOf.height + ruleGap * 2 + rowHeight;
  const footTop = box.bottom - footHeight;
  const bodyTop = headTop + head.height + gap;
  const body = place(parts.body, bodyTop, box.left, inner, scale, measure);
  if (scale > 1) {
    for (const [role, count] of [...head.balanced, ...body.balanced]) {
      if (count > (full.get(role) ?? count)) return null;
    }
  }
  const room = footTop - gap - bodyTop - body.height;
  if (room < 0 && parts.body.length > 0) return null;
  if (headTop + head.height > footTop) return null;
  // What room is left goes a third above the answer and the rest below it, where the
  // glow falls: the answer stays near the school it is about.
  const shift = Math.max(0, room) / 3;
  const shifted = body.runs.map((run) => ({ ...run, y: run.y + shift }));
  const asOfRuns = asOf.runs.map((run) => ({ ...run, y: run.y + footTop }));
  const ruleY = footTop + asOf.height + ruleGap;
  const rowTop = ruleY + ruleGap;
  const rowBaseline = rowTop + rowHeight / 2 + wordSize * 0.36;
  const wordX = box.left + markSize + 10 * footScale;
  const wordmark: TextRun = {
    text: model.wordmark,
    x: wordX,
    y: rowBaseline,
    size: wordSize,
    weight: 600,
    color: TEXT_1,
    width: measure(model.wordmark, wordSize, 600),
    role: 'wordmark',
  };
  const rowRuns: TextRun[] = [wordmark];
  const hostSize = HOST[kind] * footScale;
  const hostWidth = measure(model.host, hostSize, 450);
  // The site's name at the row's right, where it fits beside the wordmark; under it where not.
  if (model.host !== '' && wordX + wordmark.width + 32 * footScale + hostWidth <= box.right) {
    rowRuns.push({
      text: model.host,
      x: box.right - hostWidth,
      y: rowBaseline,
      size: hostSize,
      weight: 450,
      color: TEXT_3,
      width: hostWidth,
      role: 'host',
    });
  } else if (model.host !== '') return null;
  const runs = [...head.runs, ...shifted, ...asOfRuns, ...rowRuns];
  const dots = shifted
    .filter(
      (run, n, all) =>
        run.role.startsWith('headline-') && all.findIndex((other) => other.role === run.role) === n,
    )
    .map((run) => {
      const index = Number(run.role.slice('headline-'.length));
      const line = model.lines[index];
      const r = run.size * 0.2;
      return {
        x: box.left + r,
        y: run.y - run.size * 0.34,
        r,
        color: TONE_COLORS[line?.tone ?? 'none'],
      };
    });
  return {
    kind,
    width,
    height,
    box,
    runs,
    badge: { x: box.left, y: box.top, size: badgeSize, letter: model.initial },
    mark: { x: box.left, y: rowTop, size: markSize },
    rule: { y: ruleY, left: box.left, right: box.right },
    dots,
    glow: glowOf(model, shifted, dots, width),
    scale,
  };
}

/**
 * The glow: behind the first status's dot, reaching across its headline, or
 * behind the chance's number where it stands alone, in its color.
 */
function glowOf(
  model: CardModel,
  body: readonly TextRun[],
  dots: CardLayout['dots'],
  width: number,
): CardLayout['glow'] {
  const color = TONE_COLORS[model.tone];
  const strength = glowStrength(model);
  const dot = dots[0];
  if (dot !== undefined)
    return { x: dot.x + width * 0.14, y: dot.y, r: width * 0.8, color, strength };
  const number = body.find((run) => run.role === 'chance-number');
  if (number !== undefined) {
    return {
      x: number.x + number.width * 0.5,
      y: number.y - number.size * 0.36,
      r: width * 0.8,
      color,
      strength,
    };
  }
  return { x: width * 0.3, y: width * 0.6, r: width * 0.8, color, strength };
}

/** How bright the glow is: a decided status full, a chance by its number, open and none faint. */
function glowStrength(model: CardModel): number {
  switch (model.tone) {
    case 'open':
    case 'none':
      return 0.18;
    case 'chance': {
      const value = Number.parseFloat(model.chance?.number ?? '');
      const share = Number.isFinite(value) ? value / 100 : 0;
      return 0.25 + 0.5 * Math.min(1, Math.max(0, share));
    }
    default:
      return 0.75;
  }
}

/** A color as rgba with `alpha`, from #rrggbb. */
function rgba(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgba(${String((n >> 16) & 255)}, ${String((n >> 8) & 255)}, ${String(n & 255)}, ${String(alpha)})`;
}

/** How much smaller the backdrop is drawn than the card, then drawn up to its size. */
export const BACKDROP_SCALE = 8;

/**
 * Draws the card's backdrop, `scale` times smaller than the card: the dark,
 * the glow (a wide soft light and a brighter core, as the map's lights glow)
 * and a low light from the foot, so the dark never reads as an empty frame.
 */
export function drawBackdrop(ctx: CanvasRenderingContext2D, layout: CardLayout, scale = 1): void {
  const width = layout.width / scale;
  const height = layout.height / scale;
  const glow = {
    ...layout.glow,
    x: layout.glow.x / scale,
    y: layout.glow.y / scale,
    r: layout.glow.r / scale,
  };
  ctx.fillStyle = BACKGROUND;
  ctx.fillRect(0, 0, width, height);
  // A wide, faint light: the color reaches the frame only as a breath, so the dark stays dark.
  const wide = ctx.createRadialGradient(glow.x, glow.y, 0, glow.x, glow.y, glow.r);
  wide.addColorStop(0, rgba(glow.color, 0.3 * glow.strength));
  wide.addColorStop(0.25, rgba(glow.color, 0.1 * glow.strength));
  wide.addColorStop(0.6, rgba(glow.color, 0.025 * glow.strength));
  wide.addColorStop(1, rgba(glow.color, 0));
  ctx.fillStyle = wide;
  ctx.fillRect(0, 0, width, height);
  // And a tight, bright core behind the dot: the school's light, as the map draws one.
  const core = ctx.createRadialGradient(glow.x, glow.y, 0, glow.x, glow.y, glow.r * 0.3);
  core.addColorStop(0, rgba(glow.color, 0.42 * glow.strength));
  core.addColorStop(0.5, rgba(glow.color, 0.12 * glow.strength));
  core.addColorStop(1, rgba(glow.color, 0));
  ctx.fillStyle = core;
  ctx.fillRect(0, 0, width, height);
}

/**
 * Draws a laid-out card on a 2D context the card's size: its backdrop (drawn
 * small and smoothed up to size where one is given, which keeps the PNG
 * small and quick to make), then the badge, the dots and the words.
 */
export function drawCard(
  ctx: CanvasRenderingContext2D,
  layout: CardLayout,
  backdrop: CanvasImageSource | null = null,
): void {
  const { width, height, glow } = layout;
  if (backdrop === null) drawBackdrop(ctx, layout);
  else {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'low';
    ctx.drawImage(backdrop, 0, 0, width, height);
  }

  // The badge: the school's initial on a disc lit faintly in its status's color, where its
  // logo will stand.
  const { badge } = layout;
  const r = badge.size / 2;
  const bx = badge.x + r;
  const by = badge.y + r;
  const disc = ctx.createLinearGradient(bx, badge.y, bx, badge.y + badge.size);
  disc.addColorStop(0, rgba(glow.color, 0.22));
  disc.addColorStop(1, rgba(glow.color, 0.06));
  ctx.beginPath();
  ctx.arc(bx, by, r, 0, Math.PI * 2);
  ctx.fillStyle = disc;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(bx, by, r - 1, 0, Math.PI * 2);
  ctx.lineWidth = 2;
  ctx.strokeStyle = rgba(glow.color, 0.35);
  ctx.stroke();
  if (badge.letter !== '') {
    ctx.fillStyle = TEXT_1;
    ctx.font = fontOf(badge.size * 0.44, 600);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(badge.letter, badge.x + r, badge.y + r + badge.size * 0.02);
  }

  // Each status's dot, lit like a light on the map.
  for (const dot of layout.dots) {
    const halo = ctx.createRadialGradient(dot.x, dot.y, 0, dot.x, dot.y, dot.r * 3);
    halo.addColorStop(0, rgba(dot.color, 0.55));
    halo.addColorStop(1, rgba(dot.color, 0));
    ctx.fillStyle = halo;
    ctx.fillRect(dot.x - dot.r * 3, dot.y - dot.r * 3, dot.r * 6, dot.r * 6);
    ctx.beginPath();
    ctx.arc(dot.x, dot.y, dot.r, 0, Math.PI * 2);
    ctx.fillStyle = dot.color;
    ctx.fill();
  }

  // The foot: a hairline, and under it the site's mark (the logo in one color) beside its wordmark.
  ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
  ctx.fillRect(
    layout.rule.left,
    Math.round(layout.rule.y),
    layout.rule.right - layout.rule.left,
    2,
  );
  drawMark(ctx, layout.mark.x, layout.mark.y, layout.mark.size / MARK_GRID, TEXT_1);

  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  for (const run of layout.runs) {
    ctx.font = fontOf(run.size, run.weight);
    ctx.fillStyle = run.color;
    ctx.fillText(run.text, run.x, run.y);
  }
}

/** The weights the card draws in, for the face to be ready in each before drawing. */
const WEIGHTS = [450, 500, 550, 600, 650, 700];
/** How long to wait for the face before drawing in the fallback. */
const FONT_WAIT_MS = 1500;

/** Waits for the site's face in every weight the card uses, a moment at most. */
async function fontsReady(text: string): Promise<void> {
  const fonts = typeof document === 'undefined' ? undefined : document.fonts;
  if (fonts === undefined) return;
  const loads = Promise.all(WEIGHTS.map((weight) => fonts.load(fontOf(40, weight), text))).then(
    () => undefined,
    () => undefined,
  );
  await Promise.race([loads, new Promise<void>((resolve) => setTimeout(resolve, FONT_WAIT_MS))]);
}

/** A measure on a canvas context, in the card's face. */
export function canvasMeasure(ctx: CanvasRenderingContext2D): Measure {
  return (text, size, weight) => {
    ctx.font = fontOf(size, weight);
    return ctx.measureText(text).width;
  };
}

/** Renders a card to a PNG. */
export async function renderCard(model: CardModel, kind: CardKind): Promise<Blob> {
  const all = [
    model.name,
    model.campus,
    model.place,
    model.asOf,
    model.wordmark,
    model.host,
    model.season,
    model.initial,
  ]
    .concat(
      model.lines.flatMap((line) => [line.headline, line.day, line.detail, line.reason, line.said]),
    )
    .concat(
      model.chance === null
        ? []
        : [model.chance.number, model.chance.meaning, model.chance.day, model.chance.fewRecords],
    )
    .filter((text): text is string => text !== null)
    .join(' ');
  await fontsReady(all);
  const { width, height } = CARD_SIZES[kind];
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  // Opaque: the card has no see-through part, and its PNG is smaller without an alpha channel.
  const ctx = canvas.getContext('2d', { alpha: false });
  if (ctx === null) throw new Error('share card: no 2D canvas');
  const layout = layoutCard(model, kind, canvasMeasure(ctx));
  // The backdrop small, then smoothed up: a smooth glow, a PNG a quarter the size, made faster.
  const small = document.createElement('canvas');
  small.width = Math.ceil(width / BACKDROP_SCALE);
  small.height = Math.ceil(height / BACKDROP_SCALE);
  const smallCtx = small.getContext('2d', { alpha: false });
  if (smallCtx !== null) drawBackdrop(smallCtx, layout, BACKDROP_SCALE);
  drawCard(ctx, layout, smallCtx === null ? null : small);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob === null) reject(new Error('share card: no PNG'));
      else resolve(blob);
    }, 'image/png');
  });
}
