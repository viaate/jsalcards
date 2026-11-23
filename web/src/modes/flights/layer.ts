/**
 * Flights mode's map layer (flights spec D5, D21 pattern 7), drawn like a calm departures board:
 * the busiest airports and every airport at risk carry a small tag with their code, and no other
 * mark: no dot for an airport with no tag (LR-F18.1). A tag's look is its day: hollow where the
 * day's value is the usual rate, filled light gray on a quiet forecast day, and at risk in the
 * page's status tokens, a thick delayed-amber outline for some risk and solid closed blue for a
 * high risk of cancel, so the two levels never rest on color alone (outline against fill); all
 * hollow and gray once the file is old.
 *
 * Tags never overlap, and each sits on its airport. An airport at risk is placed first, the one
 * in more trouble before the other, then the busier one (LR-F12); one with no room is not drawn
 * until zooming gives it room, and search still finds it. Then the busiest, ranked by metro (New York's three airports count as one
 * city), and more come in as the map zooms in; the smaller fields recede. And the route of an
 * open flight or route as a great-circle arc. Over the same basemap as Schools, every name of
 * it kept (D1): a name gives way where a tag sits, as the map's labels give way to each other,
 * and a tag stays whole inside the view and clear of the page's controls over the map.
 *
 * Every airport is drawn on a 2D canvas over the map, each tag drawn once on a CPU canvas and
 * placed in JS with each of the map's frames: Flights adds no WebGL program to the map, so its
 * start costs the phone's graphics nothing more than Schools' (LR-F13).
 */
import type {
  GeoJSONSource,
  LayerSpecification,
  Map as MapLibreMap,
  MapMouseEvent,
} from 'maplibre-gl';

import type { Basemap } from '../../map/basemap';
import { BASEMAP_IDS } from '../../map/basemap/ids';
import { yieldToMain } from '../../map/basemap/steps';
import type { ScreenBox as Box } from '../../map/basemap/clearance';
import { holdLabels } from './hold';
import { THEME_EVENT } from '../../theme/event';
import { dayViews, todayView } from './chance';
import type { Level } from './chance';
import type { FlightsAirportLive } from '../../types/generated';
import type { Airport, LiveRead } from './data';

/** What the two sources are given: points with their properties, or the one arc. */
interface FeatureCollection {
  readonly type: 'FeatureCollection';
  readonly features: readonly {
    readonly type: 'Feature';
    readonly id?: number;
    readonly properties: Readonly<Record<string, string | number | boolean>>;
    readonly geometry:
      | { readonly type: 'Point'; readonly coordinates: readonly [number, number] }
      | { readonly type: 'LineString'; readonly coordinates: readonly [number, number][] };
  }[];
}

/** The overlay the tags are drawn on, placed in LR-F12's order. */
export const AIRPORT_TAGS = 'flights-airport-tags';
export const ROUTE_SOURCE = 'flights-route';
export const ROUTE_LINE = 'flights-route-line';

/** What a dot shows. */
export interface DotState {
  readonly level: Level | null;
  readonly usual: boolean;
}

export interface FlightsLayer {
  /** Draws the airports with these states; `stale`: the file is old, every tag gray. */
  show(states: ReadonlyMap<string, DotState>, stale: boolean): void;
  /** Draws the arc between two airports, or none. */
  route(from: Airport | null, to: Airport | null): void;
  /** Marks the open airport, or none. */
  select(code: string | null): void;
  remove(): void;
}

/**
 * Each airport's dot for local today at its own clock, as of `now`: its level from forecast
 * values only, or hollow where what is left of the day is the usual rate.
 */
export function dotStates(
  read: LiveRead | null,
  zones: ReadonlyMap<string, string>,
  now: number,
): Map<string, DotState> {
  const states = new Map<string, DotState>();
  for (const entry of read?.file.airports ?? []) setDotState(states, entry, zones, now);
  return states;
}

/** One airport's dot into `states` (dotStates). */
function setDotState(
  states: Map<string, DotState>,
  entry: FlightsAirportLive,
  zones: ReadonlyMap<string, string>,
  now: number,
): void {
  const zone = zones.get(entry.code);
  if (zone === undefined) return;
  const today = todayView(dayViews(entry, zone, now), zone, now);
  if (today !== null)
    states.set(entry.code, { level: today.level, usual: today.answer === 'usual' });
}

/** How long each turn of dotStatesInTurns may run before the page gets the main thread back, ms. */
const STATES_TURN_MS = 4;

/**
 * dotStates in turns, each a task of its own: the first read reckons every airport's day in its
 * own zone, a time format each for the zones it has not met yet, so all at once it would hold
 * the page for one long task.
 */
export async function dotStatesInTurns(
  read: LiveRead | null,
  zones: ReadonlyMap<string, string>,
  now: number,
): Promise<Map<string, DotState>> {
  const states = new Map<string, DotState>();
  let turn = performance.now();
  for (const entry of read?.file.airports ?? []) {
    setDotState(states, entry, zones, now);
    if (performance.now() - turn < STATES_TURN_MS) continue;
    await yieldToMain();
    turn = performance.now();
  }
  return states;
}

/**
 * A tag's look. `none`: nothing known, or the file is old; `usual`: the usual rate, hollow;
 * `low`, `delay`, `cancel`: a forecast's level, filled.
 */
type Look = 'none' | 'usual' | 'low' | 'delay' | 'cancel';
const LOOKS: readonly Look[] = ['none', 'usual', 'low', 'delay', 'cancel'];
/** How far up the board an airport is: risk first, then its metro's departures per day. */
const RISK: Readonly<Record<Look, number>> = { none: 0, usual: 0, low: 0, delay: 1, cancel: 2 };

/**
 * The zoom from which an airport's tag may show, by its place on the board (risk shows at every
 * zoom): the hubs on a phone's whole country, the large airports on a desktop's (about zoom 4),
 * the regional ones across a few states, every airport across one or two. A filter reads these
 * at whole zooms.
 */
const TAG_TIERS: readonly (readonly [rank: number, zoom: number])[] = [
  [25, 0],
  [60, 3],
  [140, 5],
];
const TAG_ALL_FROM = 6;
/** From this place on the board a hollow tag recedes: no hairline, its code in the dimmest gray. */
const RECEDES_FROM = 140;

/**
 * An airport this close to a busier one is in its metro (New York's LGA, EWR and JFK; DC's DCA,
 * IAD and BWI; the Bay Area's SFO, OAK and SJC), km: the metro's busiest airport is placed with
 * the departures of all of them, so the board names New York before Boston.
 */
const METRO_KM = 80;

/** Each airport's place on the board: its metro's departures for the busiest one, its own else. */
export function boardRanks(airports: readonly Airport[]): Map<string, number> {
  // Ties go by code, so the order is the same in every frame and no tag flickers (LR-F12).
  const byCode = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
  const busiest = [...airports].sort((a, b) => b.perDay - a.perDay || byCode(a.code, b.code));
  const leads: { airport: Airport; perDay: number }[] = [];
  const score = new Map<string, number>();
  for (const airport of busiest) {
    // A degree of latitude is 111 km anywhere: most leads are ruled out before the full sum.
    const lead = leads.find(
      (each) =>
        Math.abs(each.airport.lat - airport.lat) * 111 <= METRO_KM &&
        km(each.airport, airport) <= METRO_KM,
    );
    if (lead === undefined) leads.push({ airport, perDay: airport.perDay });
    else {
      lead.perDay += airport.perDay;
      score.set(airport.code, airport.perDay);
    }
  }
  for (const lead of leads) score.set(lead.airport.code, lead.perDay);
  return new Map(
    busiest
      .map((airport) => [airport.code, score.get(airport.code) ?? airport.perDay] as const)
      .sort((a, b) => b[1] - a[1] || byCode(a[0], b[0]))
      .map(([code], rank) => [code, rank] as const),
  );
}

/**
 * Who wins a crowded spot (LR-F12), lowest placed first: the airport in more trouble (high
 * beats some, some beats calm), and between two at the same risk the busier one (its place on
 * the board, `rank`, from boardRanks).
 */
export function tagOrder(risk: number, rank: number): number {
  return (2 - risk) * 1000 + rank;
}

function km(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

export interface Colors {
  readonly low: string;
  /**
   * A low forecast's tag: the quiet gray, set back toward the surface so a board of low days
   * stays calm in both themes and every risk stands out of it.
   */
  readonly lowTag: string;
  readonly delay: string;
  readonly cancel: string;
  readonly label: string;
  /** The search bar's surface and hairline, which a hollow tag is cut from. */
  readonly surface: string;
  readonly hairline: string;
  readonly text1: string;
  readonly text3: string;
  readonly bg: string;
  readonly surfaceHigh: string;
  readonly onClosed: string;
}

function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value === '' ? fallback : value;
}

function colors(): Colors {
  const dark = luminance(token('--bg', '#000')) < 0.2;
  return {
    lowTag: mix(token('--text-3', '#6b6b6b'), token('--surface-2', '#111'), 0.55),
    low: token('--text-2', '#a3a3a3'),
    delay: token('--status-delayed', '#ffc46b'),
    cancel: token('--status-closed', '#7fd4ff'),
    label: token('--text-2', '#a3a3a3'),
    surface: token('--surface-2', '#111'),
    hairline: token('--border-2', '#2a2a2a'),
    text1: token('--text-1', '#f5f5f5'),
    text3: token('--text-3', '#6b6b6b'),
    bg: token('--bg', '#000'),
    surfaceHigh: token('--surface-1', dark ? '#0a0a0a' : '#fff'),
    onClosed: token('--on-closed', dark ? '#000' : '#fff'),
  };
}

/** A color's relative luminance (WCAG), read through a canvas so any CSS color works. */
function luminance(color: string): number {
  const [r, g, b] = rgbOf(color);
  const lin = (v: number): number => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

let probe: CanvasRenderingContext2D | null = null;
/** Each color read once: a tag's ink is weighed against the theme's inks for every look. */
const RGB = new Map<string, [number, number, number]>();
function rgbOf(color: string): [number, number, number] {
  const held = RGB.get(color);
  if (held !== undefined) return held;
  probe ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  if (probe === null) return [0, 0, 0];
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = '#000';
  probe.fillStyle = color;
  probe.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0] = probe.getImageData(0, 0, 1, 1).data;
  RGB.set(color, [r, g, b]);
  return [r, g, b];
}

/** `a` with `share` of it over `b`, as color-mix(in srgb, a share, b) does. */
function mix(a: string, b: string, share: number): string {
  const [x, y] = [rgbOf(a), rgbOf(b)];
  const [r, g, bl] = x.map((v, i) => Math.round(v * share + (y[i] ?? 0) * (1 - share)));
  return `rgb(${String(r)} ${String(g)} ${String(bl)})`;
}

function contrast(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Of the theme's inks, the one that reads best on `fill`. */
function inkOn(fill: string, c: Colors): string {
  let best = c.text1;
  for (const ink of [c.bg, c.onClosed, c.surfaceHigh, c.text1])
    if (contrast(ink, fill) > contrast(best, fill)) best = ink;
  return best;
}

/** A tag's fill, edge, code and ring for each look, and for the open airport's tag. */
interface TagPaint {
  readonly fill: string;
  readonly edge: string | null;
  /** The edge's width, CSS px: a hairline, or some risk's thick outline. */
  readonly edgeWidth?: number;
  readonly code: string;
  /** A crisp ring around the open airport's tag. */
  readonly ring: string | null;
}

/** `recedes`: a smaller field's hollow tag, with no hairline and its code in the dimmest gray. */
function tagPaint(look: Look, picked: boolean, recedes: boolean, c: Colors): TagPaint {
  const ring = picked ? c.text1 : null;
  const filled = (fill: string): TagPaint => ({ fill, edge: null, code: inkOn(fill, c), ring });
  switch (look) {
    case 'cancel':
      return filled(c.cancel);
    case 'delay':
      // Some risk: the light tag with a thick outline in the delayed amber, its code in full ink.
      return { fill: c.surface, edge: c.delay, edgeWidth: DELAY_EDGE, code: c.text1, ring };
    case 'low':
      return filled(c.lowTag);
    case 'usual':
    case 'none':
      // The open airport's hollow tag keeps its look and takes the ring, its code in full ink.
      if (picked) return { fill: c.surface, edge: c.hairline, code: c.text1, ring };
      return {
        fill: c.surface,
        edge: recedes ? null : c.hairline,
        code: look === 'usual' && !recedes ? c.label : c.text3,
        ring: null,
      };
  }
}

/** Each tag's look: a level, the receding hollow looks, and each look open. */
interface TagKind {
  readonly id: string;
  readonly look: Look;
  readonly picked: boolean;
  readonly recedes: boolean;
}

const TAG_KINDS: readonly TagKind[] = [
  ...LOOKS.map((look) => ({ id: look, look, picked: false, recedes: false })),
  ...(['none', 'usual'] as const).map((look) => ({
    id: `${look}-small`,
    look,
    picked: false,
    recedes: true,
  })),
  ...LOOKS.map((look) => ({ id: `${look}-picked`, look, picked: true, recedes: false })),
];
const KIND_BY_ID = new Map(TAG_KINDS.map((kind) => [kind.id, kind]));

/**
 * A tag's shape in CSS px: a pill in the search bar's and the switch's radius family, as tall
 * as a code and its padding, so the board fits as many as it can.
 */
const TAG_RADIUS = 6.5;
/** Room around the open airport's pill for its ring, kept clear with it. */
const PICKED_MARGIN = 3.5;
/** The room between a tag's code and its edge, CSS px: [top, right, bottom, left]. */
const TAG_PADDING: readonly [number, number, number, number] = [1, 5, 0.5, 5];
/** The clear space each tag keeps around it, CSS px. */
const TAG_SPACE = 0.5;
/** The code's size by zoom: [zoom, px] stops. A tag is drawn at the largest and scaled. */
const TEXT_SIZES: readonly (readonly [number, number])[] = [
  [2, 10],
  [6, 11],
  [9, 12],
];
const CODE_PX = 12;
const LETTER_SPACING = 0.04;
/** A code's line in ems, as the map fit a tag to it before. */
const LINE_EM = 1.25;
/** Some risk's outline, CSS px: thick enough to tell from a hollow tag's hairline in gray. */
const DELAY_EDGE = 2;
/** The page's own face of the map's Geist Medium, at the size a tag is drawn. */
const CODE_FONT = `500 ${String(CODE_PX)}px 'Geist Variable', system-ui, sans-serif`;

/**
 * Geist Medium's advance for each capital and digit in ems (measured once in the page): a tag
 * is sized from these, so its box is the same before and after the face loads. A little over,
 * never under.
 */
// prettier-ignore
const ADVANCE: Readonly<Record<string, number>> = {
  A: 0.67, B: 0.68, C: 0.7, D: 0.69, E: 0.6, F: 0.59, G: 0.7, H: 0.71, I: 0.27, J: 0.6,
  K: 0.64, L: 0.58, M: 0.88, N: 0.74, O: 0.74, P: 0.65, Q: 0.73, R: 0.67, S: 0.64, T: 0.55,
  U: 0.69, V: 0.67, W: 0.95, X: 0.61, Y: 0.58, Z: 0.54, '0': 0.66, '1': 0.38, '2': 0.62,
  '3': 0.61, '4': 0.62, '5': 0.63, '6': 0.59, '7': 0.52, '8': 0.6, '9': 0.59,
};

/** The code's size at `zoom`, px. */
export function textSize(zoom: number): number {
  const [first, ...rest] = TEXT_SIZES;
  if (first === undefined) return CODE_PX;
  let [z0, s0] = first;
  if (zoom <= z0) return s0;
  for (const [z1, s1] of rest) {
    if (zoom <= z1) return s0 + ((s1 - s0) * (zoom - z0)) / (z1 - z0);
    [z0, s0] = [z1, s1];
  }
  return s0;
}

/** A tag's pill in CSS px at CODE_PX, the code's room in it, and where that room starts. */
export function tagBox(code: string): {
  width: number;
  height: number;
  text: number;
  start: number;
} {
  let em = 0;
  for (const letter of code) em += (ADVANCE[letter] ?? 0.75) * 1.04;
  const [top, right, bottom, left] = TAG_PADDING;
  const text = em * CODE_PX + code.length * LETTER_SPACING * CODE_PX;
  return {
    width: left + text + right,
    height: LINE_EM * CODE_PX + top + bottom,
    text,
    start: left,
  };
}

/** A tag drawn once at a pixel ratio, and its size in CSS px at CODE_PX (its ring's room in). */
interface Sprite {
  readonly image: HTMLCanvasElement;
  readonly width: number;
  readonly height: number;
}

/**
 * Draws a whole tag once: the pill, its edge (some risk's thick outline), the open airport's ring
 * and the code. The map's overlay then copies it where
 * the tag goes, with no WebGL program of its own (LR-F13).
 */
function tagSprite(kind: TagKind, code: string, c: Colors, ratio: number): Sprite | null {
  const paint = tagPaint(kind.look, kind.picked, kind.recedes, c);
  const box = tagBox(code);
  const margin = kind.picked ? PICKED_MARGIN : 0;
  const image = document.createElement('canvas');
  image.width = Math.ceil((box.width + 2 * margin) * ratio);
  image.height = Math.ceil((box.height + 2 * margin) * ratio);
  const ctx = image.getContext('2d');
  if (ctx === null) return null;
  ctx.scale(ratio, ratio);
  const pill = (inset: number): void => {
    ctx.beginPath();
    ctx.roundRect(
      margin + inset,
      margin + inset,
      box.width - 2 * inset,
      box.height - 2 * inset,
      TAG_RADIUS - inset,
    );
  };
  if (paint.ring !== null) {
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = paint.ring;
    pill(-2.25);
    ctx.stroke();
  }
  ctx.fillStyle = paint.fill;
  pill(0);
  ctx.fill();
  if (paint.edge !== null) {
    const width = paint.edgeWidth ?? 1;
    ctx.lineWidth = width;
    ctx.strokeStyle = paint.edge;
    pill(width / 2);
    ctx.stroke();
  }
  const middle = margin + TAG_PADDING[0] + (LINE_EM * CODE_PX) / 2;
  ctx.font = CODE_FONT;
  ctx.letterSpacing = `${String(LETTER_SPACING * CODE_PX)}px`;
  ctx.fillStyle = paint.code;
  const measured = ctx.measureText(code);
  // Capitals and digits only: centered on their cap height, in the room the box keeps.
  const capital = measured.actualBoundingBoxAscent - measured.actualBoundingBoxDescent;
  const x = margin + box.start + Math.max(0, (box.text - measured.width) / 2);
  ctx.fillText(code, x, middle + capital / 2);
  return { image, width: image.width / ratio, height: image.height / ratio };
}

/** A tag that may go on the map: where its airport is on screen, its size, its place in line. */
export interface TagSpot {
  readonly code: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  /** tagOrder's place: lowest goes first. The open airport goes before every other. */
  readonly order: number;
}

/**
 * The tags that go on, each on its airport, none over another (LR-F11, LR-F12): in `order`,
 * lowest first (the open airport, then risk, then the busier one, then the code), each where it
 * keeps `space` clear of every tag already placed, and inside the view. The same order each
 * frame, so no tag flickers.
 */
export function placeTags(
  spots: readonly TagSpot[],
  view: { readonly width: number; readonly height: number },
  space = TAG_SPACE,
): TagSpot[] {
  const placed: TagSpot[] = [];
  const sorted = [...spots].sort(
    (a, b) => a.order - b.order || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0),
  );
  for (const spot of sorted) {
    const halfW = spot.width / 2;
    const halfH = spot.height / 2;
    if (spot.x + halfW < 0 || spot.y + halfH < 0) continue;
    if (spot.x - halfW > view.width || spot.y - halfH > view.height) continue;
    const clear = placed.every(
      (other) =>
        Math.abs(other.x - spot.x) >= halfW + other.width / 2 + 2 * space ||
        Math.abs(other.y - spot.y) >= halfH + other.height / 2 + 2 * space,
    );
    if (clear) placed.push(spot);
  }
  return placed;
}

/**
 * Where a tag may sit about its airport, in turn: on it, then below, above, right and left of
 * its dot, then at its corners. Each as a step of a tag's half size and the gap, on each axis.
 */
const AROUND: readonly (readonly [number, number])[] = [
  [0, 0],
  [0, 1],
  [0, -1],
  [1, 0],
  [-1, 0],
  [1, 1],
  [-1, 1],
  [1, -1],
  [-1, -1],
];
/** The room between a tag set beside its airport and the airport's point, CSS px. */
const AROUND_GAP = 4;
/** How far inside the view's edges a tag stays, CSS px: a tag is never drawn cut off. */
export const TAG_EDGE = 4;

/** Whether two boxes meet. Boxes that only touch do not. */
export function meets(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/** A tag's box where its centre is `x`, `y`. */
export function spotBox(spot: TagSpot, x = spot.x, y = spot.y): Box {
  return {
    x0: x - spot.width / 2,
    y0: y - spot.height / 2,
    x1: x + spot.width / 2,
    y1: y + spot.height / 2,
  };
}

/**
 * The tags placeTags let on, each moved to the first spot about its airport (AROUND) that is
 * whole inside the view, `edge` in from its edges, and clear of every box `taken` (the map's
 * names, the page's own boxes over the map) and of every tag set before it, in their order. A
 * tag with no such spot hides until the map zooms in; the open airport's alone stays on its
 * airport then, so the open one always shows.
 */
export function settleTags(
  winners: readonly TagSpot[],
  view: { readonly width: number; readonly height: number },
  taken: readonly Box[],
  edge = TAG_EDGE,
  space = TAG_SPACE,
): TagSpot[] {
  const settled: TagSpot[] = [];
  const drawn: Box[] = [];
  for (const spot of winners) {
    let at: TagSpot | null = null;
    for (const [dx, dy] of AROUND) {
      const x = spot.x + dx * (spot.width / 2 + AROUND_GAP);
      const y = spot.y + dy * (spot.height / 2 + AROUND_GAP);
      const box = spotBox(spot, x, y);
      if (box.x0 < edge || box.y0 < edge) continue;
      if (box.x1 > view.width - edge || box.y1 > view.height - edge) continue;
      if (taken.some((other) => meets(box, other))) continue;
      const roomy = {
        x0: box.x0 - space,
        y0: box.y0 - space,
        x1: box.x1 + space,
        y1: box.y1 + space,
      };
      if (drawn.some((other) => meets(roomy, other))) continue;
      at = { ...spot, x, y };
      break;
    }
    if (at === null && spot.order < 0) at = spot;
    if (at === null) continue;
    settled.push(at);
    drawn.push(spotBox(at));
  }
  return settled;
}

/** Points along the great circle from `a` to `b`, for the route's arc. */
export function greatCircle(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
  steps = 64,
): [number, number][] {
  const rad = Math.PI / 180;
  const [la1, lo1, la2, lo2] = [a.lat * rad, a.lon * rad, b.lat * rad, b.lon * rad];
  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((la2 - la1) / 2) ** 2 +
          Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2,
      ),
    );
  if (d === 0) return [[a.lon, a.lat]];
  const points: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const s1 = Math.sin((1 - f) * d) / Math.sin(d);
    const s2 = Math.sin(f * d) / Math.sin(d);
    const x = s1 * Math.cos(la1) * Math.cos(lo1) + s2 * Math.cos(la2) * Math.cos(lo2);
    const y = s1 * Math.cos(la1) * Math.sin(lo1) + s2 * Math.cos(la2) * Math.sin(lo2);
    const z = s1 * Math.sin(la1) + s2 * Math.sin(la2);
    points.push([Math.atan2(y, x) / rad, Math.atan2(z, Math.sqrt(x * x + y * y)) / rad]);
  }
  return points;
}

/** A layer and the layer it goes under (undefined: over every other). */
export interface PlacedLayer {
  readonly layer: LayerSpecification;
  readonly before: string | undefined;
}

/** Flights' map layers from the bottom up: the route's arc, drawn only while it has one. */
export const LAYER_ORDER: readonly string[] = [ROUTE_LINE];

/** Style changes made here go in as built: layer.test.ts checks every layer against the spec. */
const NOT_CHECKED = { validate: false } as const;

/**
 * Flights' map layers in the colors `c`, by id, each under `top`. The airports are not among
 * them: they are drawn on the overlay (mountFlightsLayer), so Flights adds no WebGL program to
 * the map's start (LR-F13). The arc's line is drawn only once a flight or a route is open.
 */
export function airportLayers(c: Colors, top: string | undefined): Map<string, PlacedLayer> {
  return new Map([
    [
      ROUTE_LINE,
      {
        layer: {
          id: ROUTE_LINE,
          type: 'line',
          source: ROUTE_SOURCE,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': c.low, 'line-width': 1.5, 'line-opacity': 0.9 },
        },
        before: top,
      },
    ],
  ]);
}

/** Each airport as the overlay draws it, worked out again only when the data changes. */
interface Point {
  readonly airport: Airport;
  readonly look: Look;
  readonly risk: number;
  readonly kind: TagKind;
  readonly order: number;
  /** The zoom its tag may show from: 0 at risk, else its place on the board's. */
  readonly from: number;
  readonly box: { readonly width: number; readonly height: number };
}

export function mountFlightsLayer(
  basemap: Basemap,
  airports: readonly Airport[],
  onAirport: (code: string) => void,
  signal: AbortSignal,
  first: { readonly states: ReadonlyMap<string, DotState>; readonly stale: boolean } = {
    states: new Map(),
    stale: true,
  },
  covers: () => Iterable<Element> = () => [],
): FlightsLayer {
  const map: MapLibreMap = basemap.map;
  // Each airport's place on the board, and so the zoom its tag may show from.
  const rankOf = boardRanks(airports);
  const tagFrom = (rank: number): number =>
    TAG_TIERS.find(([below]) => rank < below)?.[1] ?? TAG_ALL_FROM;
  // Drawn from the first with what is known.
  let states: ReadonlyMap<string, DotState> = first.states;
  let stale = first.stale;
  let selected: string | null = null;
  let arc: [number, number][] | null = null;
  let c = colors();

  const lookOf = (code: string): Look => {
    const state = states.get(code);
    if (stale || state === undefined) return 'none';
    if (state.level === null) return state.usual ? 'usual' : 'none';
    return state.level;
  };

  const pointsOf = (): Point[] =>
    airports.map((airport) => {
      const look = lookOf(airport.code);
      const rank = rankOf.get(airport.code) ?? airports.length;
      const risk = RISK[look];
      const hollow = look === 'none' || look === 'usual';
      const kind = KIND_BY_ID.get(hollow && rank >= RECEDES_FROM ? `${look}-small` : look);
      return {
        airport,
        look,
        risk,
        kind: kind ?? { id: look, look, picked: false, recedes: false },
        order: tagOrder(risk, rank),
        from: risk > 0 ? 0 : tagFrom(rank),
        box: tagBox(airport.code),
      };
    });
  let points = pointsOf();

  // The overlay: one 2D canvas over the map's, drawn again with each of the map's frames.
  const overlay = document.createElement('canvas');
  overlay.className = AIRPORT_TAGS;
  overlay.setAttribute('aria-hidden', 'true');
  overlay.style.cssText =
    'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none';
  map.getCanvasContainer().appendChild(overlay);
  const ctx = overlay.getContext('2d');

  const ratio = (): number => window.devicePixelRatio || 1;
  /** Each tag as drawn, by its look and code: drawn the first time it goes on. */
  const sprites = new Map<string, Sprite | null>();
  let faceAsked = false;
  const spriteOf = (kind: TagKind, code: string): Sprite | null => {
    const key = `${kind.id} ${code}`;
    let sprite = sprites.get(key);
    if (sprite === undefined) {
      sprite = tagSprite(kind, code, c, Math.max(2, Math.ceil(ratio())));
      sprites.set(key, sprite);
    }
    // Drawn before the page's face is in, every tag is drawn again in it, the same size.
    if (!faceAsked) {
      faceAsked = true;
      if (!document.fonts.check(CODE_FONT))
        void document.fonts.load(CODE_FONT).then(() => {
          sprites.clear();
          map.triggerRepaint();
        });
    }
    return sprite;
  };

  /** The tags on the map now: what a tap reads. */
  let shown: { spot: TagSpot; point: Point }[] = [];
  let said = '';

  /** What the tags show, and where: changed whenever the airports, their looks or the open one do. */
  let version = 0;
  /** A view's layout: where each airport is, the tags that won their spots, and the held ones. */
  interface Laid {
    readonly key: string;
    readonly at: readonly { x: number; y: number }[];
    readonly view: { readonly width: number; readonly height: number };
    readonly taken: readonly Box[];
    readonly byPlace: ReadonlyMap<string, Point>;
    /** The tags the map's names give way to: the open airport's, and those at risk. */
    readonly held: readonly TagSpot[];
    /** The calm ones, which give way to the names in their turn. */
    readonly calm: readonly TagSpot[];
  }
  /** The last layout and what it was made for: the map's names and the overlay read the same. */
  let laid: Laid | null = null;

  /** The page's own boxes over the map (the search, the panel, the key), on the map's canvas. */
  const coverBoxes = (origin: DOMRect): Box[] => {
    const boxes: Box[] = [];
    for (const element of covers()) {
      const r = element.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) continue;
      boxes.push({
        x0: r.left - origin.left,
        y0: r.top - origin.top,
        x1: r.right - origin.left,
        y1: r.bottom - origin.top,
      });
    }
    return boxes;
  };

  /**
   * Where each airport is on the screen now, and the tags that win their spots: the open
   * airport's first, then each in LR-F12's order. The open one's and those at risk are set where
   * they have room, whole inside the view and clear of the page's boxes over the map: the map's
   * names give way to them. Worked out once for each view, as the map places its names (they
   * read the held tags) and again as the overlay draws.
   */
  const layout = (): Laid => {
    const canvas = map.getCanvas();
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const taken = coverBoxes(canvas.getBoundingClientRect());
    const zoom = map.getZoom();
    const center = map.getCenter();
    const key = [
      version,
      zoom,
      center.lng,
      center.lat,
      map.getBearing(),
      map.getPitch(),
      width,
      height,
      ...taken.flatMap((box) => [box.x0, box.y0, box.x1, box.y1]),
    ].join(' ');
    if (laid?.key === key) return laid;
    const scale = textSize(zoom) / CODE_PX;
    const at = points.map((point) => map.project([point.airport.lon, point.airport.lat]));
    const spots: TagSpot[] = [];
    const byPlace = new Map<string, Point>();
    points.forEach((point, i) => {
      const p = at[i];
      const open = point.airport.code === selected;
      if (p === undefined || (!open && zoom < point.from)) return;
      const margin = open ? 2 * PICKED_MARGIN : 0;
      spots.push({
        code: point.airport.code,
        x: p.x,
        y: p.y,
        width: (point.box.width + margin) * scale,
        height: (point.box.height + margin) * scale,
        order: open ? -1 : point.order,
      });
      byPlace.set(point.airport.code, point);
    });
    const view = { width, height };
    const winners = placeTags(spots, view);
    const isHeld = (spot: TagSpot): boolean =>
      spot.order < 0 || (byPlace.get(spot.code)?.risk ?? 0) > 0;
    const held = settleTags(winners.filter(isHeld), view, taken);
    const calm = winners.filter((spot) => !isHeld(spot));
    laid = { key, at, view, taken, byPlace, held, calm };
    return laid;
  };

  // An airport in trouble (LR-F12) or the open one: the map's names give way to its tag, as they
  // would to the map's own labels (hold.ts), and come back once it moves or goes. A calm
  // tag gives way to the names instead: the basemap keeps its names on a calm day (D1).
  const hold = holdLabels(map, () =>
    signal.aborted ? [] : layout().held.map((spot) => spotBox(spot)),
  );

  /**
   * The tags drawn now: the held ones, then each calm one at the first spot about its airport
   * clear of them, of the names the map placed in this frame and of the page's boxes over it.
   */
  const settle = (now: Laid): void => {
    const room = TAG_SPACE + AROUND_GAP / 2;
    const names = hold.placed();
    const taken = [
      ...now.taken,
      ...names,
      ...now.held.map((spot) => {
        const box = spotBox(spot);
        return { x0: box.x0 - room, y0: box.y0 - room, x1: box.x1 + room, y1: box.y1 + room };
      }),
    ];
    shown = [];
    for (const spot of [...now.held, ...settleTags(now.calm, now.view, taken)]) {
      const point = now.byPlace.get(spot.code);
      if (point !== undefined) shown.push({ spot, point });
    }
  };

  const draw = (): void => {
    if (ctx === null || signal.aborted) return;
    const now = layout();
    settle(now);
    const canvas = map.getCanvas();
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const r = ratio();
    const pixelsW = Math.round(width * r);
    const pixelsH = Math.round(height * r);
    if (overlay.width !== pixelsW || overlay.height !== pixelsH) {
      overlay.width = pixelsW;
      overlay.height = pixelsH;
    }
    ctx.setTransform(r, 0, 0, r, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const zoom = map.getZoom();
    const scale = textSize(zoom) / CODE_PX;
    // The tags alone, where the layout put them: no dot for an airport with no tag (LR-F18.1).
    for (const { spot, point } of shown) {
      const kind =
        spot.order < 0 ? (KIND_BY_ID.get(`${point.look}-picked`) ?? point.kind) : point.kind;
      const sprite = spriteOf(kind, spot.code);
      if (sprite === null) continue;
      const w = sprite.width * scale;
      const h = sprite.height * scale;
      ctx.drawImage(sprite.image, spot.x - w / 2, spot.y - h / 2, w, h);
    }
    // What the tags say, for the page's tests: written only when it changes. A change of the
    // tags shown places the map's names again, clear of them.
    const words = shown.map(({ point }) => `${point.airport.code}:${point.look}`).join(' ');
    if (words !== said) {
      said = words;
      overlay.dataset.tags = words;
      map.triggerRepaint();
    }
  };

  /** The route's arc as the map's line source takes it. */
  const arcData = (): FeatureCollection => ({
    type: 'FeatureCollection',
    features:
      arc === null
        ? []
        : [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: arc } }],
  });

  /** The route's source and line on the map's style, once for each style it puts on. */
  const add = (): void => {
    if (map.getSource(ROUTE_SOURCE) !== undefined) return;
    const order = map.getLayersOrder();
    const top = order.includes(BASEMAP_IDS.schools) ? BASEMAP_IDS.schools : undefined;
    map.style.addSource(ROUTE_SOURCE, { type: 'geojson', data: arcData() }, NOT_CHECKED);
    for (const placed of airportLayers(c, top).values())
      map.style.addLayer(placed.layer, placed.before, NOT_CHECKED);
    map._update(true);
  };

  const removeRoute = (): void => {
    for (const id of [...LAYER_ORDER].reverse())
      if (map.getLayer(id) !== undefined) map.removeLayer(id);
    if (map.getSource(ROUTE_SOURCE) !== undefined) map.removeSource(ROUTE_SOURCE);
  };

  const remove = (): void => {
    removeRoute();
    overlay.remove();
    // The names the tags held off come back.
    hold.release();
  };

  /** A tap this close to a tag's edge is on the tag, CSS px. */
  const TAG_SLOP = 4;
  // A tap on a tag opens its airport, wherever the tag sits; just off a tag's edge, that tag's.
  // An airport with no tag shows nothing to tap (LR-F18.1): search finds it.
  const onClick = (event: MapMouseEvent): void => {
    const { x, y } = event.point;
    const nearest = (among: readonly Airport[], reach: number): string | null => {
      let best: { code: string; d: number } | null = null;
      for (const airport of among) {
        const p = map.project([airport.lon, airport.lat]);
        const d = Math.hypot(p.x - x, p.y - y);
        if (d <= reach && (best === null || d < best.d)) best = { code: airport.code, d };
      }
      return best?.code ?? null;
    };
    const onTag = (slop: number): string | null =>
      nearest(
        shown
          .filter(
            ({ spot }) =>
              Math.abs(spot.x - x) <= spot.width / 2 + slop &&
              Math.abs(spot.y - y) <= spot.height / 2 + slop,
          )
          .map(({ point }) => point.airport),
        Infinity,
      );
    const code = onTag(0) ?? onTag(TAG_SLOP);
    if (code !== null) onAirport(code);
  };

  // A theme puts on a new style: the route goes on again, the tags in its colors.
  const onStyle = (): void => {
    if (signal.aborted || map.getSource(ROUTE_SOURCE) !== undefined) return;
    try {
      add();
    } catch {
      // The new style is not in yet: its next event tries again.
    }
  };
  const onTheme = (): void => {
    c = colors();
    sprites.clear();
    removeRoute();
    add();
    map.triggerRepaint();
  };

  /** What changed since the last draw: the points are worked out at most once a frame. */
  let pointsDue = false;
  let arcDue = false;
  let frame: number | null = null;
  const flush = (): void => {
    frame = null;
    if (signal.aborted) return;
    if (pointsDue) points = pointsOf();
    version += 1;
    if (arcDue) void map.getSource<GeoJSONSource>(ROUTE_SOURCE)?.setData(arcData());
    pointsDue = false;
    arcDue = false;
    map.triggerRepaint();
  };
  const redraw = (next: boolean, line: boolean): void => {
    pointsDue ||= next;
    arcDue ||= line;
    frame ??= requestAnimationFrame(flush);
  };

  add();
  // At rest: the tags' boxes, for the page's tests.
  const onIdle = (): void => {
    if (signal.aborted) return;
    const boxes = JSON.stringify(
      shown.map(({ spot }) => {
        const box = spotBox(spot);
        return [spot.code, ...[box.x0, box.y0, box.x1, box.y1].map((n) => Math.round(n * 10) / 10)];
      }),
    );
    if (overlay.dataset.boxes !== boxes) overlay.dataset.boxes = boxes;
  };

  map.on('render', draw);
  map.on('click', onClick);
  map.on('styledata', onStyle);
  map.on('idle', onIdle);
  document.addEventListener(THEME_EVENT, onTheme, { signal });
  signal.addEventListener(
    'abort',
    () => {
      map.off('render', draw);
      map.off('click', onClick);
      map.off('styledata', onStyle);
      map.off('idle', onIdle);
      remove();
    },
    { once: true },
  );
  map.triggerRepaint();

  return {
    show(next, isStale) {
      if (next === states && isStale === stale) return;
      states = next;
      stale = isStale;
      redraw(true, false);
    },
    route(from, to) {
      const next = from === null || to === null ? null : greatCircle(from, to);
      if (next === null && arc === null) return;
      arc = next;
      redraw(false, true);
    },
    select(code) {
      if (code === selected) return;
      selected = code;
      redraw(false, false);
    },
    remove,
  };
}
