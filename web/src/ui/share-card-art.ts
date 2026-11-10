/**
 * The logo's numbers, for the share card to draw (ui/share-card.ts): a snow
 * crystal coming up over a snowy hill (docs/live.md, "The logo and the
 * icons"). Twice: the one-color mark at the card's foot, as flat shapes on the
 * 24 unit grid of scripts/logo/mark.svg (the file there is the design's own;
 * these are its shapes without its clip, which a canvas card does not use:
 * the three upper arms, the foot, which is what the mound's breath leaves of
 * the three lower arms, and the mound; a test draws both and compares them),
 * and the card's artwork, the same picture large and tone on tone: the
 * crystal's arms in the icon's own units, a breath of the card's color under
 * them, and the white hill.
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

/** A crystal arm's length in the icon's units: every size below is per this much arm. */
export const ARM_REACH = 456;
/** How far the crystal's center stands above the hill's crest. */
export const CENTER_LIFT = 112;
/** The band of plain color kept between the crystal's foot and the snow. */
export const BREATH = 50;

/** A long arm pointing up from the center: 80 wide, one pair of branches, a pointed tip. */
export const LONG_ARM: readonly (readonly [number, number])[] = [
  [-40, 0],
  [-40, -262],
  [-134, -316.3],
  [-134, -396.3],
  [-40, -342],
  [-40, -432.9],
  [0, -456],
  [40, -432.9],
  [40, -342],
  [134, -396.3],
  [134, -316.3],
  [40, -262],
  [40, 0],
];

/** A lower arm, short and bare: the three of them are the foot that goes behind the hill. */
export const SHORT_ARM: readonly (readonly [number, number])[] = [
  [-40, 0],
  [-40, -146.9],
  [0, -170],
  [40, -146.9],
  [40, 0],
];

/** The arms' turns from straight up, in degrees: three long, then the three short. */
export const ARM_TURNS: readonly number[] = [0, 60, -60, 120, -120, 180];

/** Where the card's artwork stands. */
export interface Sunrise {
  /** The card's width and height. */
  readonly width: number;
  readonly height: number;
  /** The top of the hill, under the crystal's center. */
  readonly crest: number;
  /** The crystal's arm in pixels; under 150 no crystal is drawn, the hill alone. */
  readonly r: number;
  /** Whether the crystal is drawn. */
  readonly crystal: boolean;
  /** The crystal's center. */
  readonly cx: number;
  readonly cy: number;
  /** The breath's curve and the hill's: from the left edge, through a control point, to the right. */
  readonly breath: readonly (readonly [number, number])[];
  readonly hill: readonly (readonly [number, number])[];
}

/** Everything under a curve, down to the card's foot. */
function under(
  ctx: CanvasRenderingContext2D,
  curve: readonly (readonly [number, number])[],
  foot: number,
): void {
  const [from, by, to] = curve;
  if (from === undefined || by === undefined || to === undefined) return;
  ctx.beginPath();
  ctx.moveTo(from[0], from[1]);
  ctx.quadraticCurveTo(by[0], by[1], to[0], to[1]);
  ctx.lineTo(to[0], foot);
  ctx.lineTo(from[0], foot);
  ctx.closePath();
  ctx.fill();
}

/**
 * Draws the artwork in three flat fills: the crystal in `flake`, the breath in
 * the card's own color (which trims the crystal's foot to the hill's curve),
 * then the hill.
 */
export function drawSunrise(
  ctx: CanvasRenderingContext2D,
  art: Sunrise,
  flake: string,
  field: string,
  hill: string,
): void {
  if (art.crystal) {
    const s = art.r / ARM_REACH;
    ctx.fillStyle = flake;
    for (const degrees of ARM_TURNS) {
      const turn = (degrees * Math.PI) / 180;
      const cos = Math.cos(turn) * s;
      const sin = Math.sin(turn) * s;
      ctx.beginPath();
      (Math.abs(degrees) > 90 ? SHORT_ARM : LONG_ARM).forEach(([x, y], index) => {
        const px = art.cx + x * cos - y * sin;
        const py = art.cy + x * sin + y * cos;
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fill();
    }
    ctx.fillStyle = field;
    under(ctx, art.breath, art.height + 2);
  }
  ctx.fillStyle = hill;
  under(ctx, art.hill, art.height + 2);
}
