// @vitest-environment node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';
import { describe, expect, it } from 'vitest';

import { cardModel } from '../../app/share-card';
import type { CardKind } from '../../app/share-card';
import { ZONE } from '../../app/tests/chance-fixtures';
import { URL_OF, samples } from '../../app/tests/share-card-fixtures';
import { drawCard, layoutCard } from '../share-card';
import type { Measure } from '../share-card';
import { MARK_GRID, MARK_SHAPES, drawMark } from '../share-card-art';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
/** The design's own one-color mark (scripts/build-icons.mjs names the folder). */
const MARK_FILE = path.join(WEB, 'scripts', 'logo', 'mark.svg');

/** The side both marks are drawn at to be compared. */
const SIDE = 240;

/** A drawing's ink on white, one byte a pixel: 0 is full ink. */
async function ink(svg: string): Promise<Buffer> {
  const { data, info } = await sharp(Buffer.from(svg))
    .flatten({ background: '#ffffff' })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  expect([info.width, info.height, info.channels]).toEqual([SIDE, SIDE, 1]);
  return data;
}

/** The card's shapes written out as one SVG path. */
function shapesSvg(): string {
  const d = MARK_SHAPES.map(
    (shape) => `${shape.map(([step, ...at]) => `${step}${at.join(' ')}`).join('')}Z`,
  ).join('');
  const side = String(SIDE);
  const grid = String(MARK_GRID);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${side}" height="${side}" viewBox="0 0 ${grid} ${grid}"><path d="${d}"/></svg>`;
}

/** One thing a card did to its canvas. */
interface Call {
  name: string;
  args: readonly unknown[];
  /** The fill color as the call was made, where it was a plain color. */
  fillStyle: unknown;
  /** The points of the path a fill filled. */
  path: readonly (readonly [number, number])[];
}

/** A canvas context that draws nothing and keeps what it was asked to do, in order. */
function recorder(): { ctx: CanvasRenderingContext2D; calls: Call[] } {
  const calls: Call[] = [];
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
        calls.push({ name: key, args, fillStyle: target.fillStyle, path: [...path] });
        if (key.startsWith('create')) return { addColorStop: () => undefined };
        return undefined;
      };
    },
    set(target, key, value) {
      if (typeof key === 'string') target[key] = value;
      return true;
    },
  });
  return { ctx: ctx as unknown as CanvasRenderingContext2D, calls };
}

/** A face about as wide as Geist: each letter a little over half its size, bolder a little wider. */
const measure: Measure = (text, size, weight) =>
  [...new Intl.Segmenter('en-US', { granularity: 'grapheme' }).segment(text)].length *
  size *
  (weight >= 650 ? 0.6 : 0.54);

/** The foot's ink, as the site's first text color. */
const MARK_COLOR = '#f5f5f5';

describe('the logo in one color', () => {
  it("draws the design's mark: its shapes and scripts/logo/mark.svg are one picture", async () => {
    const [drawn, design] = await Promise.all([
      ink(shapesSvg()),
      ink(
        readFileSync(MARK_FILE, 'utf8').replace(
          '<svg ',
          `<svg width="${String(SIDE)}" height="${String(SIDE)}" `,
        ),
      ),
    ]);
    let inked = 0;
    let differ = 0;
    for (let at = 0; at < design.length; at++) {
      if ((design[at] ?? 255) < 128) inked++;
      if (Math.abs((drawn[at] ?? 0) - (design[at] ?? 0)) > 8) differ++;
    }
    // A crystal and a mound, about three tenths of the square; no more than an edge's breath apart.
    expect(inked).toBeGreaterThan(0.2 * SIDE * SIDE);
    expect(differ / (SIDE * SIDE)).toBeLessThan(0.005);
  });

  it('is five flat shapes: three arms, the foot and the mound, inside the grid', () => {
    expect(MARK_SHAPES).toHaveLength(5);
    const spans = MARK_SHAPES.flat().flatMap(([, ...at]) => at);
    expect(Math.min(...spans)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...spans)).toBeLessThanOrEqual(MARK_GRID);
    // The upright arm stands on whole units, so it is sharp at 24 and 48 pixels.
    const upright = MARK_SHAPES[0] ?? [];
    expect(upright[0]).toEqual(['M', 11, 14.5]);
    expect(upright[6]).toEqual(['L', 12, 2]);
    expect(upright.at(-1)).toEqual(['L', 13, 14.5]);
    // The mound runs the grid's width, half a unit in from each side, on the underside at 21.
    expect(MARK_SHAPES[4]).toEqual([
      ['M', 0.5, 21],
      ['Q', 12, 15, 23.5, 21],
    ]);
  });

  it('draws each shape at the place and size asked, in the one color', () => {
    const { ctx, calls } = recorder();
    drawMark(ctx, 100, 200, 3, '#123456');
    const fills = calls.filter((call) => call.name === 'fill');
    expect(fills.map((call) => call.fillStyle)).toEqual(Array(5).fill('#123456'));
    expect(fills[0]?.path[0]).toEqual([100 + 11 * 3, 200 + 14.5 * 3]);
    expect(fills[4]?.path).toEqual([
      [100 + 0.5 * 3, 200 + 21 * 3],
      [100 + 12 * 3, 200 + 15 * 3],
      [100 + 23.5 * 3, 200 + 21 * 3],
    ]);
    expect(new Set(calls.map((call) => call.name))).toEqual(
      new Set(['beginPath', 'moveTo', 'lineTo', 'quadraticCurveTo', 'closePath', 'fill']),
    );
  });
});

describe("the mark at the card's foot", () => {
  const cards = samples().flatMap(({ name, view, now }) =>
    (['story', 'post'] as const).map((kind): [string, CardKind, typeof view, Date] => [
      name,
      kind,
      view,
      now,
    ]),
  );

  it.each(cards)('is the logo, flat, on the %s %s card', (_, kind, view, now) => {
    const model = cardModel({ view, url: URL_OF(view.id), now: now, timeZone: ZONE });
    if (model === null) throw new Error('no card');
    const layout = layoutCard(model, kind, measure);
    const { ctx, calls } = recorder();
    drawCard(ctx, layout);

    // After the hairline over the foot, nothing glows: the bloom is gone.
    const hairline = calls.findIndex(
      (call) => call.name === 'fillRect' && call.args[1] === Math.round(layout.rule.y),
    );
    expect(hairline).toBeGreaterThan(-1);
    const foot = calls.slice(hairline + 1);
    expect(foot.filter((call) => /^create|^arc$|^stroke$|^drawImage$/.test(call.name))).toEqual([]);

    // The logo's five shapes, in the foot's ink, inside the mark's square.
    const fills = foot.filter((call) => call.name === 'fill');
    expect(fills.map((call) => call.fillStyle)).toEqual(Array(5).fill(MARK_COLOR));
    const { x, y, size } = layout.mark;
    for (const [px, py] of fills.flatMap((call) => call.path)) {
      expect(px).toBeGreaterThanOrEqual(x);
      expect(px).toBeLessThanOrEqual(x + size);
      expect(py).toBeGreaterThanOrEqual(y);
      expect(py).toBeLessThanOrEqual(y + size);
    }
    // Its mound runs the square's width, half a unit in from each side, on the row's underside.
    const u = size / MARK_GRID;
    expect(fills[4]?.path).toEqual([
      [x + 0.5 * u, y + 21 * u],
      [x + 12 * u, y + 15 * u],
      [x + 23.5 * u, y + 21 * u],
    ]);
  });

  it('is checked on every sample card, in both formats', () => {
    expect(cards.length).toBeGreaterThanOrEqual(8);
  });
});
