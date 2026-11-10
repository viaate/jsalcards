/**
 * A share card drawn: the layout of a card's model (app/share-card.ts) on its
 * Story or Post canvas, and the PNG of it, made in the browser. The card is a
 * poster: its status's color from edge to edge, the logo's picture at its
 * foot (a snow crystal, tone on tone, coming up over a white hill), and its
 * words in the site's own face (Geist, which the page already has) on one
 * left edge, the answer as large as the card allows ("Closed today" fills the
 * width). The layout is worked out first, from the face's own measures: every
 * line's ink starts on the left edge and ends by the right one, nothing is set
 * under 40 pixels, and no line is cut while a smaller allowed size or another
 * break would hold it whole. A Story keeps its top 250 and bottom 260 pixels
 * free of words, where a story's own bars sit. Where the words cannot fit
 * with the answer still large, the card leaves out its least needed lines
 * (LEFT_OUT) rather than shrink further, and where even that is not enough it
 * is not made at all: no line ever runs into another. Drawn in flat fills
 * alone: no gradient, shadow, blur or image. Loaded with the first press of
 * Share, never with the page.
 */

import { CARD_SIZES } from '../app/share-card';
import type { CardKind, CardModel } from '../app/share-card';
import { shareCopy, shareFormat } from '../copy-share';

import { ARM_REACH, BREATH, CENTER_LIFT, drawMark, drawSunrise } from './share-card-art';
import type { Sunrise } from './share-card-art';

/** The site's face, as the page's style sheet names it. */
export const CARD_FONT = '"Geist Variable", system-ui, sans-serif';

/** Which poster: a status's, or the chance's. */
export type PosterTone = 'closed' | 'delayed' | 'remote' | 'earlyDismissal' | 'open' | 'chance';

/** A poster's flat colors. */
export interface ToneColors {
  /** The poster itself, edge to edge. */
  readonly field: string;
  /** Its type. */
  readonly type: string;
  /** The big line, or the chance's number. */
  readonly big: string;
  /** Its small type: the place, as of when, the school-year line. */
  readonly small: string;
  /** The crystal: a deeper tone of the field (on the deep chance field, a paler one). */
  readonly flake: string;
  /** The snow. */
  readonly hill: string;
}

/**
 * One card per status, the same in light and dark: a solid color says "this
 * happened", the deep teal "this might". Delayed and early dismissal take dark
 * type, where white would be too faint on amber and on green.
 */
export const CARD_TONES: Readonly<Record<PosterTone, ToneColors>> = Object.freeze({
  closed: tone('#1791dc', '#ffffff', '#ffffff', '#ffffff', '#0d80ca', '#ffffff'),
  delayed: tone('#f0a020', '#241500', '#241500', '#3d2a04', '#e6930d', '#ffffff'),
  remote: tone('#8f72f7', '#ffffff', '#ffffff', '#ffffff', '#7f60ec', '#ffffff'),
  earlyDismissal: tone('#22b46d', '#03200f', '#03200f', '#03200f', '#1aa560', '#ffffff'),
  open: tone('#4b5563', '#ffffff', '#ffffff', '#ffffff', '#414a57', '#ffffff'),
  chance: tone('#143f3c', '#f4f5f7', '#5fe3cc', '#b4d6d1', '#1c524d', '#f4f5f7'),
});

function tone(
  field: string,
  type: string,
  big: string,
  small: string,
  flake: string,
  hill: string,
): ToneColors {
  return Object.freeze({ field, type, big, small, flake, hill });
}

/** The chance's ticks: one per two percent, lit up to the number. */
export const TICK_COLORS = Object.freeze({ lit: '#36c9b3', unlit: '#2c6b64' });

/** The left edge every line's ink starts on, and the right edge none passes. */
export const LEFT = 84;
export const RIGHT = 996;
const MEASURE = RIGHT - LEFT;
/** No line of type is ever set smaller than this. */
export const MIN_TYPE = 40;
/** Geist's cap height and descender, in em. */
export const CAP = 0.71;
export const DESC = 0.17;
/** The big line's smallest and largest size, and the chance number's. */
export const BIG_SIZES = Object.freeze({ words: [150, 330], number: [260, 600] } as const);
/** A Story's first cap-top and the sign-off's bottom line; a Post's. */
export const FRAME: Readonly<Record<CardKind, { readonly top: number; readonly bottom: number }>> =
  Object.freeze({ story: { top: 256, bottom: 1650 }, post: { top: 90, bottom: 1266 } });
/** The top of the hill: the same on every card of a size. */
export const CREST: Readonly<Record<CardKind, number>> = Object.freeze({ story: 1785, post: 1284 });
/** The crystal's largest arm, and the arm under which none is drawn. */
export const ARM = Object.freeze({ most: 550, least: 150 });
/** The tallest the ticks grow. */
export const TICKS_TALLEST: Readonly<Record<CardKind, number>> = Object.freeze({
  story: 240,
  post: 170,
});
/**
 * The largest K: all type but the big line is set at its size times K, which
 * steps down from here to 1 by 0.05. A chance Post stays at 1: its ticks take
 * the spare height.
 */
export const LARGEST_K: Readonly<Record<'status' | 'chance', Readonly<Record<CardKind, number>>>> =
  Object.freeze({ status: { story: 1.5, post: 1.3 }, chance: { story: 1.3, post: 1 } });

/**
 * The lines a card leaves out, in this order, before its big line would go
 * under its smallest size: the school's words, the school-year line, the
 * reason, then the other days (with the chance on a status card).
 */
export const LEFT_OUT = ['said', 'season', 'reason', 'more'] as const;
export type LeftOut = (typeof LEFT_OUT)[number];

/** A text's measures at 100 pixels: its advance, and its ink's reach each side of its origin. */
export interface FaceBox {
  readonly advance: number;
  readonly left: number;
  readonly right: number;
}

/** The card's face: what a text measures at 100 pixels in a weight. Widths scale with size. */
export type Face = (text: string, weight: number) => FaceBox;

/** What part of the card a run is. */
export type Role =
  | 'place'
  | 'name'
  | 'campus'
  | 'big'
  | 'digits'
  | 'sign'
  | 'day'
  | 'fact'
  | 'reason'
  | 'words'
  | 'more'
  | 'chance'
  | 'few'
  | 'meaning'
  | 'chance-day'
  | 'as-of'
  | 'season'
  | 'host';

/** One line of type as drawn. */
export interface TextRun {
  readonly role: Role;
  readonly text: string;
  /** Where its ink starts. */
  readonly x: number;
  /** Its baseline. */
  readonly y: number;
  /** Its size, a whole pixel. */
  readonly size: number;
  readonly weight: number;
  readonly color: string;
  /** Its ink's width. */
  readonly width: number;
  /** Where each of its letters is drawn from, in order. */
  readonly at: readonly number[];
}

export interface CardLayout {
  readonly kind: CardKind;
  readonly width: number;
  readonly height: number;
  readonly tone: PosterTone;
  readonly colors: ToneColors;
  /** What all type but the big line is multiplied by. */
  readonly K: number;
  /** The big line (or the chance's number): its size and how many lines it takes. */
  readonly big: { readonly size: number; readonly lines: number };
  readonly runs: readonly TextRun[];
  /** The chance's ticks, on a chance card. */
  readonly ticks: {
    readonly x: number;
    readonly y: number;
    /** One bar's width, and the room between two. */
    readonly bar: number;
    readonly gap: number;
    readonly height: number;
    readonly count: number;
    readonly lit: number;
  } | null;
  /** The artwork, and what holds the crystal down: 28 pixels under the big line or the ticks. */
  readonly art: Sunrise & { readonly ceiling: number; readonly tip: number };
  /** The sign-off's mark: where its grid's (0, 0) goes, pixels per unit, and its box. */
  readonly mark: {
    readonly x: number;
    readonly y: number;
    readonly u: number;
    readonly left: number;
    readonly width: number;
    readonly height: number;
    readonly bottom: number;
  };
  /** The lines left out to fit (LEFT_OUT), none for any card with room for all. */
  readonly dropped: readonly LeftOut[];
}

/** The font shorthand a canvas takes. */
export function fontOf(size: number, weight: number): string {
  return `${String(weight)} ${String(Math.round(size))}px ${CARD_FONT}`;
}

const SEGMENTER = new Intl.Segmenter('en-US', { granularity: 'grapheme' });

/** A text's letters as a reader sees them (graphemes), so none is ever cut in two. */
function graphemes(text: string): string[] {
  return Array.from(SEGMENTER.segment(text), (part) => part.segment);
}

function isSpace(letter: string | undefined): boolean {
  return letter === ' ' || letter === ' ';
}

/**
 * Where each letter of a line starts, at 100 pixels, from the line's origin:
 * the advance of the text up to and with it, less its own, so the kern before
 * a letter stays before it, then the tracking and word space of the letters
 * before. At no tracking the line is the browser's own. The card draws each
 * letter itself, so every browser makes the same picture.
 */
export function offsets(
  face: Face,
  text: string,
  weight: number,
  tracking: number,
  wordSpace: number,
): number[] {
  const out: number[] = [];
  let spaces = 0;
  let before = '';
  graphemes(text).forEach((letter, i) => {
    before += letter;
    out.push(
      face(before, weight).advance -
        face(letter, weight).advance +
        i * tracking * 100 +
        spaces * wordSpace * 100,
    );
    if (isSpace(letter)) spaces++;
  });
  return out;
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

/** A row of the card's type: its weight, its size at K = 1, its tracking and word space in em. */
interface Row {
  readonly w: number;
  readonly s: number;
  readonly tr: number;
  readonly ws: number;
}

const row = (w: number, s: number, tr: number, ws = 0): Row => ({ w, s, tr, ws });

/** The place, and the campus and as of when, set as it is. */
const PLACE = row(500, 40, -0.012);
const NAME = row(700, 68, -0.022);
const BIG = row(700, 100, -0.038, 0.07);
const NUMBER = row(700, 100, -0.045);
const DAY = row(700, 68, -0.022);
const FACT = row(600, 60, -0.016);
const REASON = row(500, 50, -0.016);
const WORDS = row(500, 44, -0.014);
const MORE = row(600, 46, -0.015);
const MEANING = row(700, 72, -0.022);
const CHANCE_DAY = row(500, 50, -0.016);
const SEASON = row(500, 38, -0.012);
const HOST = row(700, 48, -0.022);

/** A text's measures and its count of letters and spaces, each (text, weight) measured once. */
type Read = (text: string, weight: number) => FaceBox & { n: number; sp: number };

function reader(face: Face): Read {
  const memo = new Map<string, FaceBox & { n: number; sp: number }>();
  return (text, weight) => {
    const key = `${String(weight)}|${text}`;
    let box = memo.get(key);
    if (box === undefined) {
      const letters = graphemes(text);
      box = { ...face(text, weight), n: letters.length, sp: letters.filter(isSpace).length };
      memo.set(key, box);
    }
    return box;
  };
}

/** A line's ink width at 100 pixels: its two ink edges, its tracking and its word space. */
function ink(read: Read, text: string, r: Row): number {
  const box = read(text, r.w);
  return box.left + box.right + (box.n - 1) * r.tr * 100 + box.sp * r.ws * 100;
}

/** The largest whole size up to `most` at which a line is no wider than `room`. */
function fit(read: Read, text: string, r: Row, most: number, room: number): number {
  return Math.min(most, Math.floor((100 * room) / ink(read, text, r)));
}

/** A line cut to its room: whole letters, and a space left at the end, come off until it fits. */
function cut(read: Read, text: string, r: Row, size: number, room: number): string {
  if ((ink(read, text, r) * size) / 100 <= room) return text;
  const letters = graphemes(text);
  do {
    letters.pop();
    while (letters.length > 1 && /\s/u.test(letters.at(-1) ?? '')) letters.pop();
  } while (
    letters.length > 1 &&
    (ink(read, letters.join('') + shareCopy.cut, r) * size) / 100 > room
  );
  return letters.join('') + shareCopy.cut;
}

/**
 * A line that fits: at the largest size up to `most` at which its ink is no wider than its
 * room, never under MIN_TYPE; only there is it cut.
 */
function fits(
  read: Read,
  text: string,
  r: Row,
  most: number,
  room = MEASURE,
): { text: string; size: number } {
  const size = Math.max(MIN_TYPE, fit(read, text, r, most, room));
  return { text: cut(read, text, r, size, room), size };
}

/** A text on the fewest lines up to `most`, then the most even of those; null where it does not fit. */
function even(read: Read, text: string, r: Row, size: number, most: number): string[] | null {
  const words = text.split(' ').filter((word) => word !== '');
  const width = (line: string): number => (ink(read, line, r) * size) / 100;
  for (let count = 1; count <= most; count++) {
    let best: { widest: number; lines: string[] } | null = null;
    const search = (start: number, left: number, lines: string[], widest: number): void => {
      if (left === 1) {
        const line = words.slice(start).join(' ');
        const all = Math.max(widest, width(line));
        if (all <= MEASURE && (best === null || all < best.widest)) {
          best = { widest: all, lines: [...lines, line] };
        }
        return;
      }
      for (let end = start + 1; end <= words.length - (left - 1); end++) {
        const line = words.slice(start, end).join(' ');
        const wide = width(line);
        if (wide > MEASURE) break;
        search(end, left - 1, [...lines, line], Math.max(widest, wide));
      }
    };
    if (words.length >= count) search(0, count, [], 0);
    // TypeScript does not see the closure's write.
    const found = best as { widest: number; lines: string[] } | null;
    if (found !== null) return found.lines;
  }
  return null;
}

/** A text too long even for its last allowed line: the lines filled in order, the last one cut. */
function fill(read: Read, text: string, r: Row, size: number, most: number): string[] {
  const lines = wrap(text, MEASURE, (line) => (ink(read, line, r) * size) / 100);
  if (lines.length <= most) return lines;
  const kept = lines.slice(0, most - 1);
  let used = kept.join('').replace(/\s/gu, '').length;
  let from = 0;
  for (; used > 0; from++) if (!/\s/u.test(text[from] ?? '')) used--;
  return [...kept, cut(read, text.slice(from).trim(), r, size, MEASURE)];
}

/** A text parted in two at a space, never before a middle dot; and whether a sentence or clause ends there. */
function breaks(text: string): [string, string, boolean][] {
  const words = text.split(' ');
  const out: [string, string, boolean][] = [];
  for (let i = 1; i < words.length; i++) {
    if (words[i] === '·') continue;
    out.push([
      words.slice(0, i).join(' '),
      words.slice(i).join(' '),
      /[.!?:;·]$/u.test(words[i - 1] ?? ''),
    ]);
  }
  return out;
}

interface Lines {
  readonly size: number;
  readonly lines: string[];
}

/** The largest whole size from `most` at which both lines of a break fit, or 0 under MIN_TYPE. */
function fitBoth(read: Read, a: string, b: string, r: Row, most: number): number {
  const size = Math.min(fit(read, a, r, most, MEASURE), fit(read, b, r, most, MEASURE));
  return size >= MIN_TYPE ? size : 0;
}

/**
 * A paragraph, never cut: at the largest size from `most` down to MIN_TYPE that holds it on one
 * line or two. One line where it fits; else broken after a word that ends a sentence or a
 * clause (the widest line least); else the break with the widest line least. Null where it does
 * not stand on two lines.
 */
function paragraph(read: Read, text: string, r: Row, most: number): Lines | null {
  // Two lines hold twice the measure of ink at most (and an em, for the space the break takes):
  // a text longer than that at the smallest size is not searched.
  if ((ink(read, text, r) * MIN_TYPE) / 100 > 2 * MEASURE + MIN_TYPE) return null;
  const one = fit(read, text, r, most, MEASURE);
  let best: (Lines & { clause: boolean; widest: number }) | null = null;
  for (const [a, b, clause] of breaks(text)) {
    const size = fitBoth(read, a, b, r, most);
    if (size === 0) continue;
    const widest = Math.max(ink(read, a, r), ink(read, b, r));
    if (
      best === null ||
      size > best.size ||
      (size === best.size &&
        ((clause && !best.clause) || (clause === best.clause && widest < best.widest)))
    ) {
      best = { size, clause, widest, lines: [a, b] };
    }
  }
  if (one >= MIN_TYPE && (best === null || one >= best.size)) return { size: one, lines: [text] };
  return best;
}

/**
 * The school-year line on two lines, never cut: broken after the colon; else after a comma, so
 * no count is parted from its unit; else at any space. Within a kind of break: the largest size
 * up to `most`, then the widest line least. Null where it stands on two lines no way at all.
 */
function seasonLines(read: Read, text: string, most: number): Lines | null {
  const best: ((Lines & { widest: number }) | null)[] = [null, null, null];
  for (const [a, b] of breaks(text)) {
    const size = fitBoth(read, a, b, SEASON, most);
    if (size === 0) continue;
    const widest = Math.max(ink(read, a, SEASON), ink(read, b, SEASON));
    [a.endsWith(':'), a.endsWith(','), true].forEach((kind, n) => {
      const held = best[n];
      if (
        kind &&
        (held === null ||
          held === undefined ||
          size > held.size ||
          (size === held.size && widest < held.widest))
      ) {
        best[n] = { size, widest, lines: [a, b] };
      }
    });
  }
  return best[0] ?? best[1] ?? best[2] ?? null;
}

/** A line placed, before its letters are: its ink starts on `x`, its baseline is `y`. */
interface Draft {
  readonly role: Role;
  readonly text: string;
  readonly r: Row;
  readonly size: number;
  readonly color: string;
  readonly x: number;
  readonly y: number;
}

/** A card laid out at one K. */
interface Plan {
  /** Whether its big line is at its smallest size or over. */
  readonly ok: boolean;
  readonly K: number;
  /** The big line's size before it is rounded down, to compare plans by. */
  readonly raw: number;
  /** The open space left above the bottom group. */
  readonly slack: number;
  /** Whether the school's name ends cut. */
  readonly nameCut: boolean;
  readonly tone: PosterTone;
  readonly big: CardLayout['big'];
  readonly drafts: readonly Draft[];
  readonly ticks: CardLayout['ticks'];
  readonly art: CardLayout['art'];
  readonly mark: CardLayout['mark'];
}

type Want = Record<LeftOut, boolean>;

/** A fact under the big line: `gap` from the baseline above to its cap-top. */
interface Fact {
  readonly role: Role;
  readonly text: string;
  readonly r: Row;
  readonly color: string;
  readonly gap: number;
  readonly size: number;
}

/**
 * The line the card is about: the first that is not open; with none, and no chance, the open
 * line. Undefined on a chance card.
 */
function leadOf(model: CardModel): CardModel['lines'][number] | undefined {
  return (
    model.lines.find((line) => line.tone !== 'open') ??
    (model.chance === null ? model.lines[0] : undefined)
  );
}

/** Measures everything at one K, then places it. Nothing is drawn here. */
function planAt(
  model: CardModel,
  kind: CardKind,
  read: Read,
  K: number,
  want: Want,
  oneLine: boolean,
): Plan {
  const story = kind === 'story';
  const { width, height } = CARD_SIZES[kind];
  const { top, bottom } = FRAME[kind];
  const k = (value: number): number => Math.round(value * K);
  const lead = leadOf(model);
  const chance = model.chance;
  const toneKey: PosterTone = lead === undefined ? 'chance' : lead.tone;
  const colors = CARD_TONES[toneKey];
  const drafts: Draft[] = [];
  const put = (
    role: Role,
    text: string,
    r: Row,
    size: number,
    color: string,
    y: number,
    x = LEFT,
  ): void => {
    drafts.push({ role, text, r, size, color, x, y });
  };

  // The bottom group, built upwards: the sign-off (the mark and the address), and over it the
  // school-year line.
  const address = k(HOST.s);
  const markHeight = Math.round(address * 1.3);
  const u = markHeight / 19;
  const signTop = bottom - markHeight;
  let season: Lines = { size: 0, lines: [] };
  if (model.season !== null && model.season !== '' && want.season) {
    const most = Math.max(MIN_TYPE, k(SEASON.s));
    const one = fit(read, model.season, SEASON, most, MEASURE);
    // One line where that costs at most 6 pixels of size, and never under 40; else two.
    if (one >= (oneLine ? MIN_TYPE : Math.max(MIN_TYPE, most - 6))) {
      season = { size: one, lines: [model.season] };
    } else season = seasonLines(read, model.season, most) ?? season;
  }
  const seasonStep = Math.round(season.size * 1.24);
  const seasonLast = signTop - k(40);
  const groupTop =
    season.lines.length > 0
      ? seasonLast - (season.lines.length - 1) * seasonStep - CAP * season.size
      : signTop;

  // The top group: the place, the school's name, its campus.
  let nameTop = top;
  if (model.place !== null && model.place !== '') {
    const place = fits(read, model.place, PLACE, k(PLACE.s));
    const y = top + CAP * place.size;
    put('place', place.text, PLACE, place.size, colors.small, y);
    nameTop = y + k(30) + 2;
  }
  let nameSize = k(NAME.s);
  let nameLines = even(read, model.name, NAME, nameSize, 2);
  if (nameLines === null) {
    // 60 down to 48 in steps of 2, and 48 itself where the steps pass it by (an odd gap at K).
    const sizes: number[] = [];
    for (let size = k(60); size > k(48); size -= 2) sizes.push(size);
    sizes.push(k(48));
    for (nameSize of sizes) {
      nameLines = even(read, model.name, NAME, nameSize, 3);
      if (nameLines !== null) break;
    }
  }
  if (nameLines === null) {
    nameSize = k(48);
    nameLines = fill(read, model.name, NAME, nameSize, 3);
  }
  const nameCut = nameLines.at(-1)?.endsWith(shareCopy.cut) === true;
  const nameStep = Math.round(nameSize * (nameLines.length > 2 ? 1.13 : 1.08));
  let last = nameTop + CAP * nameSize;
  nameLines.forEach((text, i) => {
    put('name', text, NAME, nameSize, colors.type, last + i * nameStep);
  });
  last += (nameLines.length - 1) * nameStep;
  if (model.campus !== null && model.campus !== '') {
    const campus = fits(read, model.campus, PLACE, k(PLACE.s));
    last += k(22) + CAP * campus.size;
    put('campus', campus.text, PLACE, campus.size, colors.small, last);
  }

  // The facts under the big line.
  const facts: Fact[] = [];
  const add = (
    role: Role,
    line: { text: string; size: number },
    r: Row,
    color: string,
    gap: number,
  ): void => {
    facts.push({
      role,
      text: line.text,
      r,
      color,
      size: line.size,
      gap: facts.length > 0 ? gap : 0,
    });
  };
  const second = (line: CardModel['lines'][number]): void => {
    // Another day's status: one line, without its date where that would not fit at 40.
    const same = line.tone === lead?.tone;
    const text = shareFormat.secondDay(line.headline, same, line.day);
    const size = fit(read, text, MORE, k(MORE.s), MEASURE);
    add(
      'more',
      size >= MIN_TYPE
        ? { text, size }
        : fits(read, shareFormat.secondDay(line.headline, same, null), MORE, k(MORE.s)),
      MORE,
      colors.type,
      k(42),
    );
  };
  if (lead !== undefined) {
    if (lead.day !== null) add('day', fits(read, lead.day, DAY, k(DAY.s)), DAY, colors.type, 0);
    if (lead.detail !== null) {
      // The times run the full measure where they can; under 44 pixels, one fact to a line.
      const size = fit(read, lead.detail, FACT, k(FACT.s), MEASURE);
      if (size >= 44) add('fact', { text: lead.detail, size }, FACT, colors.type, k(34));
      else {
        shareFormat.facts(lead.detail).forEach((part, i) => {
          add('fact', fits(read, part, FACT, k(50)), FACT, colors.type, k(i > 0 ? 22 : 34));
        });
      }
    }
    // The reason, and the school's own words after it, read as one short paragraph, never cut
    // inside a sentence: whole sentences are left out from the end until the rest stands.
    const reason = want.reason ? lead.reason : null;
    let words: Lines | null = null;
    if (want.said && lead.said !== null) {
      const sentences = shareFormat.sentences(lead.said);
      for (let count = sentences.length; count > 0 && words === null; count--) {
        const text = shareFormat.paragraph(reason, sentences.slice(0, count));
        words = paragraph(read, text, WORDS, k(WORDS.s));
      }
    }
    if (words !== null) {
      const { size, lines } = words;
      lines.forEach((text, i) => {
        add(
          'words',
          { text, size },
          WORDS,
          colors.type,
          i > 0 ? Math.round(size * 1.26 - CAP * size) : k(32),
        );
      });
    } else if (reason !== null) {
      add('reason', fits(read, reason, REASON, k(REASON.s)), REASON, colors.type, k(32));
    }
    if (want.more) {
      for (const line of model.lines) if (line !== lead) second(line);
      if (chance !== null) {
        const text = shareFormat.chanceLine(chance.number, chance.meaning);
        add('chance', fits(read, text, MORE, k(MORE.s)), MORE, colors.type, k(42));
        if (chance.fewRecords !== null) {
          add('few', fits(read, chance.fewRecords, PLACE, k(PLACE.s)), PLACE, colors.small, k(22));
        }
      }
    }
  } else if (chance !== null) {
    // "Chance of no school Tuesday" runs the full measure where it can; under 52, two lines.
    const size = fit(read, chance.meaning, MEANING, k(MEANING.s), MEASURE);
    if (size >= 52) add('meaning', { text: chance.meaning, size }, MEANING, colors.type, 0);
    else {
      (
        even(read, chance.meaning, MEANING, 56, 2) ?? fill(read, chance.meaning, MEANING, 56, 2)
      ).forEach((text) => {
        add('meaning', { text, size: 56 }, MEANING, colors.type, 22);
      });
    }
    add(
      'chance-day',
      fits(read, chance.day, CHANCE_DAY, k(CHANCE_DAY.s)),
      CHANCE_DAY,
      colors.small,
      k(34),
    );
    if (chance.fewRecords !== null) {
      add(
        'few',
        fits(read, chance.fewRecords, CHANCE_DAY, k(CHANCE_DAY.s)),
        CHANCE_DAY,
        colors.small,
        k(27),
      );
    }
    if (want.more) model.lines.forEach(second);
  }
  if (model.asOf !== '')
    add('as-of', fits(read, model.asOf, PLACE, k(PLACE.s)), PLACE, colors.small, k(38));
  // From the cap-top of the first to just under the last baseline.
  const factsHeight = facts.reduce((sum, fact) => sum + fact.gap + CAP * fact.size, 0) + k(10);

  const bigTop = last + k(66);
  const room = groupTop - bigTop;
  const keep = story ? 56 : 40;
  let ok = true;
  let raw: number;
  let size: number;
  let bigLines: string[] = [];
  let digits = '';
  let sign = '';
  let tick = 0;
  let tickTop = 0;
  let bigBase: number;
  let factsTop: number;
  if (lead !== undefined) {
    const [least, most] = BIG_SIZES.words;
    const under = k(46);
    // The height a size takes: the first line's caps, the steps to the last, its descender.
    const sizeOf = (lines: readonly string[]): number =>
      Math.min(
        most,
        (100 * MEASURE) / Math.max(...lines.map((line) => ink(read, line, BIG))),
        (room - keep - under - factsHeight) / (CAP + (lines.length - 1) * 0.9 + DESC),
      );
    const words = lead.headline.split(' ').filter((word) => word !== '');
    let best: { size: number; lines: string[] } | null = null;
    if (words.length > 6) {
      // More words than any status has: wrapped at the smallest size, not searched.
      const lines = wrap(lead.headline, MEASURE, (line) => (ink(read, line, BIG) * least) / 100);
      best = { size: sizeOf(lines), lines };
    } else {
      // Every break of its words into one to three lines; another line must earn its height,
      // and wins only where the type grows by more than 15 percent.
      for (let mask = 0; mask < 1 << Math.max(0, words.length - 1); mask++) {
        const lines: string[] = [];
        let line = words[0] ?? '';
        for (let i = 1; i < words.length; i++) {
          if ((mask & (1 << (i - 1))) !== 0) {
            lines.push(line);
            line = words[i] ?? '';
          } else line += ` ${words[i] ?? ''}`;
        }
        lines.push(line);
        if (lines.length > 3) continue;
        const at = sizeOf(lines);
        if (
          best === null ||
          (lines.length > best.lines.length
            ? at > best.size * 1.15
            : lines.length < best.lines.length
              ? at * 1.15 >= best.size
              : at > best.size)
        ) {
          best = { size: at, lines };
        }
      }
    }
    raw = best?.size ?? 0;
    bigLines = best?.lines ?? [];
    size = Math.floor(raw);
    if (size < least) {
      ok = false;
      size = least;
    }
    bigBase = bigTop + CAP * size;
    factsTop = bigBase + (bigLines.length - 1) * 0.9 * size + DESC * size + under;
  } else {
    const [least, most] = BIG_SIZES.number;
    ({ digits, sign } = shareFormat.numberParts(chance?.number ?? ''));
    const bar = k(104);
    const over = k(50);
    const under = k(54);
    const left = room - keep - over - bar - under - factsHeight;
    // The digits, a gap of 0.06 and the sign at 0.42 of the size, across the measure.
    raw = Math.min(
      most,
      (100 * MEASURE) / (ink(read, digits, NUMBER) + 6 + ink(read, sign, NUMBER) * 0.42),
      left / CAP,
    );
    size = Math.floor(raw);
    if (size < least) {
      ok = false;
      size = least;
    }
    // The ticks take the height that is left over: the row becomes a field.
    tick = Math.round(Math.min(TICKS_TALLEST[kind], bar + Math.max(0, left - CAP * size)));
    bigBase = bigTop + CAP * size;
    tickTop = bigBase + over;
    factsTop = tickTop + tick + under;
  }
  let slack = groupTop - (factsTop + factsHeight);
  // A sparse Story breathes: open space beyond 200 pixels is shared, three tenths above the big
  // line and three tenths below it.
  const shift = story ? Math.round(Math.min(64, Math.max(0, slack - 200) * 0.3)) : 0;
  bigBase += shift;
  tickTop += shift;
  factsTop += 2 * shift;
  slack -= 2 * shift;

  let ticks: CardLayout['ticks'] = null;
  let ceiling: number;
  if (lead !== undefined) {
    bigLines.forEach((text, i) => {
      put('big', text, BIG, size, colors.big, bigBase + i * 0.9 * size);
    });
    ceiling = bigBase + (bigLines.length - 1) * 0.9 * size + 28;
  } else {
    // With few local records the number is lighter, as the panel shows it.
    const color = (chance?.fewRecords ?? null) === null ? colors.big : colors.small;
    const signSize = Math.floor(size * 0.42);
    put('digits', digits, NUMBER, size, color, bigBase);
    put(
      'sign',
      sign,
      NUMBER,
      signSize,
      color,
      bigBase - CAP * size + CAP * signSize,
      LEFT + (ink(read, digits, NUMBER) * size) / 100 + size * 0.06,
    );
    const value = Number.parseFloat(digits.replace(/[<>]/gu, ''));
    const gap = 6;
    ticks = {
      x: LEFT,
      y: tickTop,
      bar: (MEASURE - 49 * gap) / 50,
      gap,
      height: tick,
      count: 50,
      lit: digits.startsWith('<') ? 0 : digits.startsWith('>') ? 50 : Math.round(value / 2),
    };
    ceiling = tickTop + tick + 28;
  }
  let base = factsTop;
  for (const fact of facts) {
    base += fact.gap + CAP * fact.size;
    put(fact.role, fact.text, fact.r, fact.size, fact.color, base);
  }
  season.lines.forEach((text, i) => {
    put(
      'season',
      text,
      SEASON,
      season.size,
      colors.small,
      seasonLast - (season.lines.length - 1 - i) * seasonStep,
    );
  });
  // The sign-off: the mark stands on the bottom line, the address beside it.
  const markWidth = 23 * u;
  if (model.host !== '') {
    const from = LEFT + markWidth + address * 0.36;
    const host = fits(read, model.host, HOST, address, RIGHT - from);
    put('host', host.text, HOST, host.size, colors.type, bottom - Math.round(address * 0.35), from);
  }

  // The artwork: the hill is the same on every card of a size; the crystal's top tip stops
  // under the big line or the ticks, and it is drawn smaller where that leaves less room.
  const crest = CREST[kind];
  const r = Math.min(ARM.most, (crest - ceiling) / (1 + CENTER_LIFT / ARM_REACH));
  const s = r / ARM_REACH;
  const cy = crest - CENTER_LIFT * s;
  const curve = (lift: number): [number, number][] => [
    [0, height - lift],
    [width / 2, 2 * crest - height - lift],
    [width, height - lift],
  ];
  return {
    ok,
    K,
    raw,
    slack,
    nameCut,
    tone: toneKey,
    big: { size, lines: Math.max(1, bigLines.length) },
    drafts,
    ticks,
    art: {
      width,
      height,
      crest,
      r,
      crystal: r >= ARM.least,
      cx: width / 2,
      cy,
      breath: curve(BREATH * s),
      hill: curve(0),
      ceiling,
      tip: cy - r,
    },
    mark: {
      x: LEFT - 0.5 * u,
      y: bottom - 21 * u,
      u,
      left: LEFT,
      width: markWidth,
      height: markHeight,
      bottom,
    },
  };
}

/** The Ks a card tries, from its largest down to 1, in steps of 0.05. */
export function stepsOf(model: CardModel, kind: CardKind): number[] {
  const most = LARGEST_K[leadOf(model) === undefined ? 'chance' : 'status'][kind];
  const steps: number[] = [];
  for (let step = Math.round(most * 20); step >= 20; step--) steps.push(step / 20);
  return steps;
}

/**
 * Lays a card out. Of its Ks (a K at which the name would end cut is passed over, 1 excepted)
 * it keeps the one with the largest big line and, among equals, the largest K: the small type
 * grows to fill the frame and gives way before the big line does. Where the big line would
 * still be under its smallest size, lines are left out in LEFT_OUT's order; where that is not
 * enough it throws: a card is never drawn with one line over another. `only` lays out at that
 * K alone (the tests').
 */
export function layoutCard(
  model: CardModel,
  kind: CardKind,
  face: Face,
  only?: number,
): CardLayout {
  const lead = leadOf(model);
  if (lead === undefined && model.chance === null) throw new Error('share card: nothing to say');
  const read = reader(face);
  const steps = only === undefined ? stepsOf(model, kind) : [only];
  const has: Want = {
    said: lead !== undefined && lead.said !== null,
    season: model.season !== null,
    reason: lead !== undefined && lead.reason !== null,
    more:
      model.lines.some((line) => line !== lead) || (lead !== undefined && model.chance !== null),
  };
  const want: Want = { said: true, season: true, reason: true, more: true };
  const dropped: LeftOut[] = [];
  for (;;) {
    const plans = steps
      .map((K) => planAt(model, kind, read, K, want, false))
      .filter((plan) => !plan.nameCut || plan.K === 1 || only !== undefined);
    const top = Math.max(...plans.map((plan) => plan.raw));
    let plan = plans.find((made) => made.raw >= top - 0.5);
    if (plan === undefined) break;
    // More than 120 pixels still open: the larger Ks again, the school-year line held to one line.
    if (plan.slack > 120 && has.season && want.season) {
      const from = plan.K;
      plan =
        steps
          .filter((K) => K > from)
          .map((K) => planAt(model, kind, read, K, want, true))
          .find((made) => !made.nameCut && made.raw >= top - 0.5) ?? plan;
    }
    if (plan.ok) return finish(plan, kind, read, dropped);
    const next = LEFT_OUT.find((part) => has[part] && want[part]);
    if (next === undefined) break;
    want[next] = false;
    dropped.push(next);
  }
  throw new Error('share card: the words do not fit');
}

/** A plan's lines with their letters placed: the layout as drawn. */
function finish(plan: Plan, kind: CardKind, read: Read, dropped: readonly LeftOut[]): CardLayout {
  const { width, height } = CARD_SIZES[kind];
  return {
    kind,
    width,
    height,
    tone: plan.tone,
    colors: CARD_TONES[plan.tone],
    K: plan.K,
    big: plan.big,
    runs: plan.drafts.map(({ role, text, r, size, color, x, y }) => {
      const origin = x + (read(text, r.w).left * size) / 100;
      return {
        role,
        text,
        x,
        y,
        size,
        weight: r.w,
        color,
        width: (ink(read, text, r) * size) / 100,
        at: offsets(read, text, r.w, r.tr, r.ws).map((at) => origin + (at * size) / 100),
      };
    }),
    ticks: plan.ticks,
    art: plan.art,
    mark: plan.mark,
    dropped,
  };
}

/**
 * Draws a laid-out card on a 2D context the card's size, measuring nothing: the field, the
 * artwork, then the type, each line letter by letter at the places the layout worked out.
 */
export function drawCard(ctx: CanvasRenderingContext2D, layout: CardLayout): void {
  const { colors, ticks, mark } = layout;
  ctx.fillStyle = colors.field;
  ctx.fillRect(0, 0, layout.width, layout.height);
  drawSunrise(ctx, layout.art, colors.flake, colors.field, colors.hill);
  if (ticks !== null) {
    for (let i = 0; i < ticks.count; i++) {
      ctx.fillStyle = i < ticks.lit ? TICK_COLORS.lit : TICK_COLORS.unlit;
      ctx.fillRect(ticks.x + i * (ticks.bar + ticks.gap), ticks.y, ticks.bar, ticks.height);
    }
  }
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  for (const run of layout.runs) {
    ctx.font = fontOf(run.size, run.weight);
    ctx.fillStyle = run.color;
    graphemes(run.text).forEach((letter, i) => {
      ctx.fillText(letter, run.at[i] ?? run.x, run.y);
    });
  }
  drawMark(ctx, mark.x, mark.y, mark.u, colors.type);
}

/** The weights the card draws in, for the face to be ready in each before drawing. */
const WEIGHTS = [500, 600, 700];
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

/** The card's face as a canvas measures it. */
export function canvasFace(ctx: CanvasRenderingContext2D): Face {
  return (text, weight) => {
    ctx.font = fontOf(100, weight);
    const box = ctx.measureText(text);
    return {
      advance: box.width,
      left: box.actualBoundingBoxLeft,
      right: box.actualBoundingBoxRight,
    };
  };
}

/** Renders a card to a PNG. */
export async function renderCard(model: CardModel, kind: CardKind): Promise<Blob> {
  const all = [model.name, model.campus, model.place, model.asOf, model.host, model.season]
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
  await fontsReady(all + shareCopy.cut);
  const { width, height } = CARD_SIZES[kind];
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  // Opaque: the card has no see-through part, and its PNG is smaller without an alpha channel.
  const ctx = canvas.getContext('2d', { alpha: false });
  if (ctx === null) throw new Error('share card: no 2D canvas');
  drawCard(ctx, layoutCard(model, kind, canvasFace(ctx)));
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob === null) reject(new Error('share card: no PNG'));
      else resolve(blob);
    }, 'image/png');
  });
}
