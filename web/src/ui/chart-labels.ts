/**
 * Where the chance chart's two labels sit over its plot (ChanceChart.svelte):
 * the answer at the bus hour, and when the district usually announces. Kept
 * apart from the chart so its rule can be tested at any width.
 */

/** A label's measured box, in px. */
export interface LabelSize {
  readonly width: number;
  readonly height: number;
}

/** Where a label sits over the plot: its left edge and top, in px from the drawing's corner. */
export interface LabelSpot {
  readonly left: number;
  readonly top: number;
}

export interface LabelPlacement {
  readonly buses: LabelSpot;
  readonly announces: LabelSpot | null;
  /** The labels' height over the plot, both lines. */
  readonly height: number;
  /** Where each dashed line starts, in px from the drawing's top: just under its own label. */
  readonly busesLine: number;
  readonly announcesLine: number | null;
}

/** The least room between a label and the other, or a dashed line not its own. */
export const LABEL_GAP = 8;
/** Between the two lines of labels. */
const LEAD = 8;
/** Between a label's foot and the top of its dashed line. */
const DROP = 2;

/**
 * The rule for the two labels over the plot, the same at any width. The
 * answer ends where the plot ends, on the top line, and its dashed line
 * drops from under it to the bus hour. The announcement starts at its own
 * dashed line, or else ends at it: on the top line when that keeps
 * LABEL_GAP from the answer, else on a second line under it, keeping
 * LABEL_GAP from the answer's dashed line, which passes down through that
 * line (failing both sides, as near its line as that room allows). Each
 * dashed line starts just under its own label; no label runs past the plot.
 */
export function placeLabels(input: {
  /** The plot's width. */
  readonly width: number;
  /** Where each dashed line runs across the plot; the announcement's null without one. */
  readonly busesAt: number;
  readonly announcesAt: number | null;
  /** The labels as measured, the announcement's no wider than announcesRoom(busesAt). */
  readonly buses: LabelSize;
  readonly announces: LabelSize | null;
}): LabelPlacement {
  const { width, busesAt, announcesAt, buses, announces } = input;
  const busesLeft = Math.max(0, width - buses.width);
  const busesSpot = { left: busesLeft, top: 0 };
  const busesLine = buses.height + DROP;
  if (announcesAt === null || announces === null) {
    return {
      buses: busesSpot,
      announces: null,
      height: buses.height,
      busesLine,
      announcesLine: null,
    };
  }
  const w = announces.width;
  const inside = (left: number): boolean => left >= 0 && left + w <= width;
  const sides = [announcesAt, announcesAt - w];
  const on = (spot: LabelSpot): LabelPlacement => ({
    buses: busesSpot,
    announces: spot,
    height: Math.max(buses.height, spot.top + announces.height),
    busesLine,
    announcesLine: spot.top + announces.height + DROP,
  });
  // The top line: clear of the answer.
  for (const left of sides) {
    if (inside(left) && left + w + LABEL_GAP <= busesLeft) return on({ left, top: 0 });
  }
  // The second line: clear of the answer's dashed line, which passes through it.
  const top = buses.height + LEAD;
  for (const left of sides) {
    if (inside(left) && left + w + LABEL_GAP <= busesAt) return on({ left, top });
  }
  return on({ left: Math.max(0, Math.min(announcesAt - w, announcesRoom(busesAt) - w)), top });
}

/**
 * The announcement's widest: the room left of the answer's dashed line, so
 * it always fits on the second line, wrapping on the narrowest night.
 */
export function announcesRoom(busesAt: number): number {
  return busesAt - LABEL_GAP;
}
