/**
 * Where the chance chart's words go (ui/ChanceChart.svelte), once the page has
 * laid them out and their widths are known: the two moments' words above the
 * plot, beside their lines and never meeting, and the words beside the lit
 * hours. In a module of its own, so the panel's chart carries none of the
 * view model's reading of the files (app/chance.ts).
 */

/** A box of words along one row, in pixels from the plot's left edge. */
export interface Placed {
  readonly left: number;
  readonly row: number;
}

/**
 * Where the moments' words go above the plot: beside their line, on the side
 * each prefers, else the other; on a second row only when neither side of
 * the first is clear. Words never leave [min, max], and never meet.
 */
export function placeFlags(
  flags: readonly {
    readonly x: number;
    readonly width: number;
    readonly prefer: 'left' | 'right';
  }[],
  min: number,
  max: number,
  gap = 6,
  space = 10,
): Placed[] {
  const placed: { left: number; right: number; row: number }[] = [];
  const clear = (left: number, right: number, row: number): boolean =>
    left >= min &&
    right <= max &&
    placed.every(
      (box) => box.row !== row || right + space <= box.left || left >= box.right + space,
    );
  return flags.map(({ x, width, prefer }) => {
    const sides = prefer === 'left' ? (['left', 'right'] as const) : (['right', 'left'] as const);
    for (const row of [0, 1]) {
      for (const side of sides) {
        const left = side === 'left' ? x - gap - width : x + gap;
        if (clear(left, left + width, row)) {
          placed.push({ left, right: left + width, row });
          return { left, row };
        }
      }
    }
    // Wider than the room on either side: kept inside as far as it goes, on a row of its own.
    const left = Math.max(
      min,
      Math.min(prefer === 'left' ? x - gap - width : x + gap, max - width),
    );
    const row = placed.some((box) => box.row === 1) ? 2 : 1;
    placed.push({ left, right: left + width, row });
    return { left, row };
  });
}

/**
 * Where the lit hours' words go: to the left of the first lit bar, just above
 * every bar they pass over; else above the lit bars; else nowhere, when
 * neither fits inside the plot. In pixels: the words' left edge from the
 * plot's left, and their foot above the plot's foot.
 */
export function placeLit(input: {
  /** The first lit bar's left edge. */
  readonly runLeft: number;
  readonly width: number;
  readonly height: number;
  /** The tallest bar top at or left of the first lit bar, and the tallest lit bar's. */
  readonly floor: number;
  readonly runTop: number;
  readonly plot: number;
  /** How far left of the plot the words may go (the scale's column), and right. */
  readonly minLeft: number;
  readonly maxRight: number;
  readonly gap?: number;
}): { readonly left: number; readonly bottom: number } | null {
  const { runLeft, width, height, floor, runTop, plot, minLeft, maxRight } = input;
  const gap = input.gap ?? 6;
  const beside = { left: runLeft - 2 - width, bottom: floor + gap };
  if (beside.left >= minLeft && beside.bottom + height <= plot) return beside;
  const above = { left: runLeft, bottom: runTop + gap };
  if (above.left + width <= maxRight && above.bottom + height <= plot) return above;
  return null;
}
