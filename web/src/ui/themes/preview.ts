/**
 * The picture on a theme's tile (ThemeTile.svelte): a crop of a metro on a
 * snow morning, fixed, so every tile shows the same place and only the theme
 * differs. Roads and a river on the ground, and the schools' marks: most
 * closed, some delayed, a few remote, with early dismissals and open schools.
 * Every color is a theme token; the shapes are the map's own glyphs.
 */
/** Wide enough for the widest tile at full size: a narrower one shows its middle. */
export const PREVIEW_WIDTH = 440;
export const PREVIEW_HEIGHT = 132;

/** A mark's status, as the glow codes them (map/glow/color.ts GlowStatus): 4 is open. */
export type MarkStatus = 0 | 1 | 2 | 3 | 4;

/** A school's mark in the picture: where, and its status. */
export interface PreviewMark {
  readonly x: number;
  readonly y: number;
  readonly status: MarkStatus;
}

/** A road: its points and its tier, 0 the least. */
export interface PreviewRoad {
  readonly d: string;
  readonly tier: 0 | 1 | 2;
}

function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const line = (points: readonly (readonly [number, number])[]): string =>
  points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join('');

/** The river across the crop, as a filled band's outline. */
export const PREVIEW_RIVER =
  'M-10 38C30 30 52 46 84 40S140 18 176 26 228 44 260 36 330 20 370 30 420 44 450 38L450 48C420 54 396 40 370 40S300 32 262 46 196 38 176 36 126 54 86 52 32 42 -10 50Z';

/** The roads: a grid of minor ones, two arterials and a highway. */
export const PREVIEW_ROADS: readonly PreviewRoad[] = (() => {
  const roads: PreviewRoad[] = [];
  const r = seeded(7);
  for (let x = 14; x < PREVIEW_WIDTH; x += 26) {
    roads.push({
      d: line([
        [x + (r() - 0.5) * 6, 56],
        [x + (r() - 0.5) * 6, PREVIEW_HEIGHT + 4],
      ]),
      tier: 0,
    });
  }
  for (let y = 70; y < PREVIEW_HEIGHT; y += 22) {
    roads.push({
      d: line([
        [-4, y + (r() - 0.5) * 5],
        [PREVIEW_WIDTH + 4, y + (r() - 0.5) * 5],
      ]),
      tier: 0,
    });
  }
  roads.push({
    d: line([
      [-4, 96],
      [80, 88],
      [160, 98],
      [244, 90],
    ]),
    tier: 1,
  });
  roads.push({
    d: line([
      [118, -4],
      [122, 60],
      [112, 136],
    ]),
    tier: 1,
  });
  roads.push({ d: 'M-4 120C60 108 120 70 170 60S230 20 244 4', tier: 2 });
  return roads;
})();

/** The schools' marks, fixed: a snow morning. */
export const PREVIEW_MARKS: readonly PreviewMark[] = (() => {
  const r = seeded(31);
  const marks: PreviewMark[] = [];
  const statuses: readonly MarkStatus[] = [0, 0, 0, 0, 0, 0, 1, 1, 0, 2, 0, 3, 0, 4, 0, 1, 4, 0];
  for (let i = 0; i < 60; i++) {
    const x = 10 + r() * (PREVIEW_WIDTH - 20);
    const y = 58 + r() * (PREVIEW_HEIGHT - 64);
    marks.push({ x, y, status: statuses[i % statuses.length] ?? 0 });
  }
  return marks;
})();

/**
 * A closed school's ring in a flat theme that draws one, as the map draws it
 * (map/glow/curves.ts BURST_RADIUS and BURST_HALF_WIDTH): out from its dot's
 * radius by this share, this share of the radius wide either way.
 */
export const PREVIEW_BURST_RADIUS = 1.3;
export const PREVIEW_BURST_HALF_WIDTH = 0.2;

/** Where the picture shows on a tile: its width, and the corner card's size over it. */
export interface PreviewFrame {
  readonly width: number;
  readonly card: {
    readonly left: number;
    readonly bottom: number;
    readonly width: number;
    readonly height: number;
  };
}

/**
 * The marks a tile `frame.width` wide shows whole, each `reach` from its
 * middle: none cut by the tile's edges or under its corner card. The picture
 * is cropped to the tile's middle (ThemeTile.svelte, slice), at its own scale.
 */
export function clearMarks(
  marks: readonly PreviewMark[],
  frame: PreviewFrame,
  reach: number,
): readonly PreviewMark[] {
  const shown = Math.min(frame.width, PREVIEW_WIDTH);
  const left = (PREVIEW_WIDTH - shown) / 2;
  const right = left + shown;
  const card = frame.card;
  const cardLeft = left + card.left - reach;
  const cardRight = left + card.left + card.width + reach;
  const cardTop = PREVIEW_HEIGHT - card.bottom - card.height - reach;
  return marks.filter(
    ({ x, y }) =>
      x - reach >= left &&
      x + reach <= right &&
      y - reach >= 0 &&
      y + reach <= PREVIEW_HEIGHT &&
      !(x >= cardLeft && x <= cardRight && y >= cardTop),
  );
}
