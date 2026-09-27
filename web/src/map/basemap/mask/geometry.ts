/**
 * Plane geometry for the US mask, on flat [x0, y0, x1, y1, ...] arrays in
 * tile units (y grows downward): clipping to a box, ring areas, and
 * MaskIndex, which answers "is this point outside the US?" and cuts lines
 * where they cross the border, fast enough to run on every street tile along
 * the border.
 */

/** An axis-aligned box: the same bounds on both axes, as tiles with a buffer have. */
export interface Box {
  readonly lo: number;
  readonly hi: number;
}

/**
 * Signed area of a ring by the shoelace formula. With y growing downward, a
 * ring that looks clockwise on screen is positive: an outer ring in a vector
 * tile; holes are negative.
 */
export function ringArea(ring: readonly number[]): number {
  let sum = 0;
  const n = ring.length;
  for (let i = 0, j = n - 2; i < n; j = i, i += 2) {
    sum += (ring[j] ?? 0) * (ring[i + 1] ?? 0) - (ring[i] ?? 0) * (ring[j + 1] ?? 0);
  }
  return sum / 2;
}

/** The ring reversed, keeping its first point first. */
export function reverseRing(ring: readonly number[]): number[] {
  const out: number[] = [ring[0] ?? 0, ring[1] ?? 0];
  for (let i = ring.length - 2; i >= 2; i -= 2) out.push(ring[i] ?? 0, ring[i + 1] ?? 0);
  return out;
}

/** The box as an outer ring (clockwise on screen). */
export function boxRing({ lo, hi }: Box): number[] {
  return [lo, lo, hi, lo, hi, hi, lo, hi];
}

/**
 * A ring clipped to the box (Sutherland-Hodgman). The part of the ring inside
 * the box keeps its orientation; where the ring leaves the box it runs along
 * the box's edge instead. Empty when nothing is inside.
 */
export function clipRing(ring: readonly number[], { lo, hi }: Box): number[] {
  let points = ring as number[];
  // Each pass clips against one side: axis 0 is x, 1 is y; keep >= lo, then <= hi.
  for (const [axis, bound, keepAbove] of [
    [0, lo, true],
    [0, hi, false],
    [1, lo, true],
    [1, hi, false],
  ] as const) {
    const n = points.length;
    if (n === 0) break;
    const out: number[] = [];
    const inside = (i: number): boolean => {
      const v = points[i + axis] ?? 0;
      return keepAbove ? v >= bound : v <= bound;
    };
    for (let i = 0, j = n - 2; i < n; j = i, i += 2) {
      const currentIn = inside(i);
      const previousIn = inside(j);
      if (currentIn !== previousIn) {
        const pa = points[j + axis] ?? 0;
        const ca = points[i + axis] ?? 0;
        const t = (bound - pa) / (ca - pa);
        const other = 1 - axis;
        const po = points[j + other] ?? 0;
        const co = points[i + other] ?? 0;
        const value = po + (co - po) * t;
        if (axis === 0) out.push(bound, value);
        else out.push(value, bound);
      }
      if (currentIn) out.push(points[i] ?? 0, points[i + 1] ?? 0);
    }
    points = out;
  }
  return points.length >= 6 ? points : [];
}

/** The parts of a line inside the box (Liang-Barsky, segment by segment, joined where they meet). */
export function clipLine(line: readonly number[], { lo, hi }: Box): number[][] {
  const parts: number[][] = [];
  let current: number[] | null = null;
  for (let i = 0; i + 3 < line.length; i += 2) {
    const x0 = line[i] ?? 0;
    const y0 = line[i + 1] ?? 0;
    const x1 = line[i + 2] ?? 0;
    const y1 = line[i + 3] ?? 0;
    const dx = x1 - x0;
    const dy = y1 - y0;
    let t0 = 0;
    let t1 = 1;
    let visible = true;
    for (const [p, q] of [
      [-dx, x0 - lo],
      [dx, hi - x0],
      [-dy, y0 - lo],
      [dy, hi - y0],
    ] as const) {
      if (p === 0) {
        if (q < 0) visible = false;
      } else {
        const r = q / p;
        if (p < 0) {
          if (r > t1) visible = false;
          else if (r > t0) t0 = r;
        } else if (r < t0) visible = false;
        else if (r < t1) t1 = r;
      }
      if (!visible) break;
    }
    if (!visible) {
      current = null;
      continue;
    }
    const ax = x0 + dx * t0;
    const ay = y0 + dy * t0;
    const bx = x0 + dx * t1;
    const by = y0 + dy * t1;
    if (current !== null && t0 === 0) {
      current.push(bx, by);
    } else {
      current = [ax, ay, bx, by];
      parts.push(current);
    }
    if (t1 !== 1) current = null;
  }
  return parts;
}

/** Cell states of MaskIndex's grid. */
const OUTSIDE = 0;
const INSIDE = 1;
const MIXED = 2;

/**
 * The mask of one tile: rings whose inside (even-odd) is outside the US, all
 * within `box`. Answers point and line queries through a grid: a point in a
 * cell no ring edge crosses takes the cell's state at once; one in a cell an
 * edge crosses is tested against the edges in its row of cells.
 *
 * Anywhere outside the box counts as not masked: the box covers the tile and
 * more of its buffer than anything is drawn or queried in.
 */
export class MaskIndex {
  /** Edges as x1, y1, x2, y2. */
  private readonly edges: Float64Array;
  private readonly cells: number;
  private readonly size: number;
  private readonly state: Uint8Array;
  /** Edge indices whose y-range overlaps each row of cells. */
  private readonly rows: number[][];
  /** Edge indices crossing each cell. */
  private readonly cellEdges: (number[] | undefined)[];
  private readonly stamp: Uint32Array;
  private query = 0;
  /** No part of the box is masked. */
  readonly empty: boolean;
  /** All of the box is masked. */
  readonly full: boolean;

  readonly box: Box;

  constructor(rings: readonly (readonly number[])[], box: Box, cells = 64) {
    this.box = box;
    const edges: number[] = [];
    for (const ring of rings) {
      const n = ring.length;
      for (let i = 0, j = n - 2; i < n; j = i, i += 2) {
        const x1 = ring[j] ?? 0;
        const y1 = ring[j + 1] ?? 0;
        const x2 = ring[i] ?? 0;
        const y2 = ring[i + 1] ?? 0;
        if (x1 !== x2 || y1 !== y2) edges.push(x1, y1, x2, y2);
      }
    }
    this.edges = Float64Array.from(edges);
    this.cells = cells;
    this.size = (box.hi - box.lo) / cells;
    this.rows = Array.from({ length: cells }, () => []);
    this.cellEdges = new Array<number[] | undefined>(cells * cells);
    this.state = new Uint8Array(cells * cells);
    this.stamp = new Uint32Array(this.edges.length / 4);

    const edgeCount = this.edges.length / 4;
    for (let e = 0; e < edgeCount; e++) {
      const x1 = this.edges[e * 4] ?? 0;
      const y1 = this.edges[e * 4 + 1] ?? 0;
      const x2 = this.edges[e * 4 + 2] ?? 0;
      const y2 = this.edges[e * 4 + 3] ?? 0;
      const r0 = this.row(Math.min(y1, y2));
      const r1 = this.row(Math.max(y1, y2));
      for (let r = r0; r <= r1; r++) {
        this.rows[r]?.push(e);
        // The edge's x-range within this row of cells.
        const top = box.lo + r * this.size;
        const [xa, xb] = xRangeInBand(x1, y1, x2, y2, top, top + this.size);
        const c0 = this.column(xa);
        const c1 = this.column(xb);
        for (let c = c0; c <= c1; c++) {
          const cell = r * cells + c;
          const list = this.cellEdges[cell];
          if (list === undefined) this.cellEdges[cell] = [e];
          else list.push(e);
          this.state[cell] = MIXED;
        }
      }
    }
    // Cells no edge crosses take the state of their center, found row by row.
    for (let r = 0; r < cells; r++) {
      const y = box.lo + (r + 0.5) * this.size;
      const crossings: number[] = [];
      for (const e of this.rows[r] ?? []) {
        const x = this.crossing(e, y);
        if (x !== null) crossings.push(x);
      }
      crossings.sort((a, b) => a - b);
      let k = crossings.length;
      for (let c = cells - 1; c >= 0; c--) {
        const cell = r * cells + c;
        const x = box.lo + (c + 0.5) * this.size;
        while (k > 0 && (crossings[k - 1] ?? 0) > x) k--;
        if (this.state[cell] === MIXED) continue;
        // Crossings to the right of the center: odd means inside.
        this.state[cell] = (crossings.length - k) % 2 === 1 ? INSIDE : OUTSIDE;
      }
    }
    // Rings wind one way and holes the other, so their areas add up to the area masked.
    const area = rings.reduce((sum, ring) => sum + ringArea(ring), 0);
    const boxArea = (box.hi - box.lo) ** 2;
    this.empty = Math.abs(area) <= boxArea * 1e-9;
    this.full = Math.abs(area - boxArea) <= boxArea * 1e-9;
  }

  private row(y: number): number {
    return Math.min(this.cells - 1, Math.max(0, Math.floor((y - this.box.lo) / this.size)));
  }

  private column(x: number): number {
    return this.row(x);
  }

  /** Where edge e crosses the horizontal line at y (half-open in y), or null. */
  private crossing(e: number, y: number): number | null {
    const x1 = this.edges[e * 4] ?? 0;
    const y1 = this.edges[e * 4 + 1] ?? 0;
    const x2 = this.edges[e * 4 + 2] ?? 0;
    const y2 = this.edges[e * 4 + 3] ?? 0;
    if (y1 > y === y2 > y) return null;
    return x1 + ((y - y1) / (y2 - y1)) * (x2 - x1);
  }

  private inBox(x: number, y: number): boolean {
    const { lo, hi } = this.box;
    return x >= lo && x <= hi && y >= lo && y <= hi;
  }

  /** Whether the point is masked: outside the US. */
  contains(x: number, y: number): boolean {
    if (this.empty || !this.inBox(x, y)) return false;
    if (this.full) return true;
    const cell = this.row(y) * this.cells + this.column(x);
    const state = this.state[cell];
    if (state !== MIXED) return state === INSIDE;
    let count = 0;
    for (const e of this.rows[this.row(y)] ?? []) {
      const cx = this.crossing(e, y);
      if (cx !== null && cx > x) count++;
    }
    return count % 2 === 1;
  }

  /** Whether every point of the rectangle is masked (a quick, conservative answer). */
  covers(x0: number, y0: number, x1: number, y1: number): boolean {
    if (this.empty || !this.inBox(x0, y0) || !this.inBox(x1, y1)) return false;
    if (this.full) return true;
    for (let r = this.row(y0); r <= this.row(y1); r++) {
      for (let c = this.column(x0); c <= this.column(x1); c++) {
        if (this.state[r * this.cells + c] !== INSIDE) return false;
      }
    }
    return true;
  }

  /** Whether no point of the rectangle is masked (a quick, conservative answer). */
  clear(x0: number, y0: number, x1: number, y1: number): boolean {
    if (this.empty) return true;
    const { lo, hi } = this.box;
    if (x1 < lo || y1 < lo || x0 > hi || y0 > hi) return true;
    if (this.full) return false;
    for (let r = this.row(Math.max(lo, y0)); r <= this.row(Math.min(hi, y1)); r++) {
      for (let c = this.column(Math.max(lo, x0)); c <= this.column(Math.min(hi, x1)); c++) {
        if (this.state[r * this.cells + c] !== OUTSIDE) return false;
      }
    }
    return true;
  }

  /** The edges crossing the cells the segment passes through, each once. */
  private candidates(x1: number, y1: number, x2: number, y2: number): number[] {
    this.query++;
    if (this.query === 0xffffffff) {
      this.stamp.fill(0);
      this.query = 1;
    }
    const found: number[] = [];
    const r0 = this.row(Math.min(y1, y2));
    const r1 = this.row(Math.max(y1, y2));
    for (let r = r0; r <= r1; r++) {
      const top = this.box.lo + r * this.size;
      const [xa, xb] = xRangeInBand(x1, y1, x2, y2, top, top + this.size);
      for (let c = this.column(xa); c <= this.column(xb); c++) {
        for (const e of this.cellEdges[r * this.cells + c] ?? []) {
          if (this.stamp[e] !== this.query) {
            this.stamp[e] = this.query;
            found.push(e);
          }
        }
      }
    }
    return found;
  }

  /**
   * The parts of a line that are not masked, cut where it crosses a ring.
   * Coordinates at the cuts are not rounded.
   */
  unmaskedParts(line: readonly number[]): number[][] {
    if (this.empty) return line.length >= 4 ? [line.slice()] : [];
    const parts: number[][] = [];
    let current: number[] | null = null;
    const keep = (ax: number, ay: number, bx: number, by: number): void => {
      const last = current === null ? -1 : current.length;
      if (current !== null && current[last - 2] === ax && current[last - 1] === ay) {
        current.push(bx, by);
      } else {
        current = [ax, ay, bx, by];
        parts.push(current);
      }
    };
    for (let i = 0; i + 3 < line.length; i += 2) {
      const ax = line[i] ?? 0;
      const ay = line[i + 1] ?? 0;
      const bx = line[i + 2] ?? 0;
      const by = line[i + 3] ?? 0;
      const cuts: number[] = [];
      if (!this.full) {
        for (const e of this.candidates(ax, ay, bx, by)) {
          const t = intersect(ax, ay, bx, by, this.edges, e);
          if (t !== null) cuts.push(t);
        }
      }
      cuts.sort((a, b) => a - b);
      let t0 = 0;
      for (const t1 of [...cuts, 1]) {
        if (t1 - t0 <= 1e-12) continue;
        const mid = (t0 + t1) / 2;
        const mx = ax + (bx - ax) * mid;
        const my = ay + (by - ay) * mid;
        if (!this.contains(mx, my)) {
          keep(ax + (bx - ax) * t0, ay + (by - ay) * t0, ax + (bx - ax) * t1, ay + (by - ay) * t1);
        } else {
          current = null;
        }
        t0 = t1;
      }
    }
    return parts;
  }
}

/** The x-range a segment covers between two horizontal lines (clamped to the segment). */
function xRangeInBand(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  top: number,
  bottom: number,
): [number, number] {
  if (y1 === y2) return [Math.min(x1, x2), Math.max(x1, x2)];
  const at = (y: number): number => x1 + ((y - y1) / (y2 - y1)) * (x2 - x1);
  const ya = Math.max(Math.min(y1, y2), top);
  const yb = Math.min(Math.max(y1, y2), bottom);
  const xa = at(ya);
  const xb = at(yb);
  return [Math.min(xa, xb), Math.max(xa, xb)];
}

/** Where segment a-b crosses edge e, as a share of a-b strictly between its ends, or null. */
function intersect(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  edges: Float64Array,
  e: number,
): number | null {
  const cx = edges[e * 4] ?? 0;
  const cy = edges[e * 4 + 1] ?? 0;
  const dx = edges[e * 4 + 2] ?? 0;
  const dy = edges[e * 4 + 3] ?? 0;
  const rx = bx - ax;
  const ry = by - ay;
  const sx = dx - cx;
  const sy = dy - cy;
  const denominator = rx * sy - ry * sx;
  if (denominator === 0) return null;
  const qx = cx - ax;
  const qy = cy - ay;
  const t = (qx * sy - qy * sx) / denominator;
  const u = (qx * ry - qy * rx) / denominator;
  if (t <= 0 || t >= 1 || u < 0 || u > 1) return null;
  return t;
}
