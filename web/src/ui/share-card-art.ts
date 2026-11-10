/**
 * The logo's numbers, for the share card to draw (ui/share-card.ts): the
 * one-color mark, a snow crystal coming up over a snowy hill, as flat shapes
 * on the 24 unit grid of scripts/logo/mark.svg (docs/live.md, "The logo and
 * the icons"). The file there is the design's own; these are its shapes
 * without its clip, which a canvas card does not use: the three upper arms,
 * the foot (what the mound's breath leaves of the three lower arms) and the
 * mound. A test draws both and compares them.
 */

/**
 * One closed shape on the grid, as a run of steps: 'M' and 'L' go to a point,
 * 'Q' curves to its second point through its first.
 */
export type MarkStep =
  readonly ['M' | 'L', number, number] | readonly ['Q', number, number, number, number];

/** The crystal's center, where its arms meet. */
const CENTER = [12, 14.5] as const;

/** The upright arm, from the center up: a shaft with one pair of branches and a pointed tip. */
const ARM: readonly (readonly [number, number])[] = [
  [-1, 0],
  [-1, -7.2],
  [-4, -8.93],
  [-4, -11.33],
  [-1, -9.6],
  [-1, -11.92],
  [0, -12.5],
  [1, -11.92],
  [1, -9.6],
  [4, -11.33],
  [4, -8.93],
  [1, -7.2],
  [1, 0],
];

/** A slanted arm before it is turned: a touch heavier than the upright one, which alone sits on the pixel grid. */
const SIDE_ARM: readonly (readonly [number, number])[] = [
  [-1.15, 0],
  [-1.15, -7.2],
  [-4, -8.85],
  [-4, -11.25],
  [-1.15, -9.6],
  [-1.15, -11.84],
  [0, -12.5],
  [1.15, -11.84],
  [1.15, -9.6],
  [4, -11.25],
  [4, -8.85],
  [1.15, -7.2],
  [1.15, 0],
];

/** An arm's outline about the center, turned `degrees` clockwise. */
function arm(points: readonly (readonly [number, number])[], degrees: number): MarkStep[] {
  const turn = (degrees * Math.PI) / 180;
  const cos = Math.cos(turn);
  const sin = Math.sin(turn);
  return points.map(
    ([x, y], index) =>
      [
        index === 0 ? 'M' : 'L',
        CENTER[0] + x * cos - y * sin,
        CENTER[1] + x * sin + y * cos,
      ] as const,
  );
}

/** The mark's five shapes, each filled in one color: three arms, the foot, the mound. */
export const MARK_SHAPES: readonly (readonly MarkStep[])[] = Object.freeze([
  arm(ARM, 0),
  arm(SIDE_ARM, 60),
  arm(SIDE_ARM, -60),
  // The foot: the roots of the three lower arms, cut along the breath over the mound.
  [
    ['M', 9.7, 14.5],
    ['L', 14.3, 14.5],
    ['L', 16, 15.48],
    ['L', 16, 16.36],
    ['Q', 12, 15.64, 8, 16.36],
    ['L', 8, 15.48],
  ],
  // The mound: a hill that thins to a point at each end.
  [
    ['M', 0.5, 21],
    ['Q', 12, 15, 23.5, 21],
  ],
]);

/** The grid's side: the mark is drawn in a square of 24 units. */
export const MARK_GRID = 24;

/**
 * Draws the mark in one color: grid point (0, 0) at (x, y), `u` pixels to a
 * grid unit. Its ink runs from 2 to 21 down: the mound from 0.5 to 23.5 across,
 * the slanted arms' branches a quarter unit past it each side.
 */
export function drawMark(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  u: number,
  color: string,
): void {
  ctx.fillStyle = color;
  for (const shape of MARK_SHAPES) {
    ctx.beginPath();
    for (const step of shape) {
      if (step[0] === 'Q') {
        ctx.quadraticCurveTo(x + step[1] * u, y + step[2] * u, x + step[3] * u, y + step[4] * u);
      } else if (step[0] === 'M') ctx.moveTo(x + step[1] * u, y + step[2] * u);
      else ctx.lineTo(x + step[1] * u, y + step[2] * u);
    }
    ctx.closePath();
    ctx.fill();
  }
}
