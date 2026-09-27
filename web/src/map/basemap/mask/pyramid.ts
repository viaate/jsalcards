/**
 * The US mask cut into vector tiles, zoom by zoom, for the build script
 * (scripts/build-us-mask.mjs). Pure geometry: the rings come in as longitude
 * and latitude, with a flag on each vertex that sits on the border with
 * Canada or Mexico, and tiles come out ready for the archive (format.ts).
 *
 * Tiles are cut from the full-resolution rings, each tile's children from its
 * own cut, and simplified only as they are written: the border barely (it is
 * drawn and cut against up to street zoom from the deepest tiles), the edge
 * out at sea a lot (nothing is drawn on either side of it).
 */
import { BORDER_LAYER, MASK_BUFFER, MASK_LAYER } from './format';
import { boxRing, reverseRing } from './geometry';
import { EXTENT, LINE, POLYGON, encodeTile, newLayer } from './mvt';
import type { ArchiveTile } from './pmtiles';

/** The flag on a vertex that sits on the border with Canada or Mexico. */
export const BORDER_FLAG = 1;

/** A ring of the US: flat longitude, latitude pairs, and a flag per vertex. */
export interface SourceRing {
  readonly coords: readonly number[];
  /** BORDER_FLAG on vertices on the border with Canada or Mexico, else 0. */
  readonly flags: Uint8Array;
  /** A hole in the US, rather than an outer ring. */
  readonly hole: boolean;
}

export interface PyramidOptions {
  readonly minZoom: number;
  /** The deepest zoom of tiles the border crosses. */
  readonly borderMaxZoom: number;
  /** The deepest zoom of tiles only the edge at sea crosses. */
  readonly seaMaxZoom: number;
  /** Douglas-Peucker tolerance along the border, in tile units at zoom z. */
  readonly borderTolerance: (z: number) => number;
  /** The same out at sea. */
  readonly seaTolerance: (z: number) => number;
}

/** Vertex flags: on the border (from the source), and pinned where a cut made it. */
const BORDER = BORDER_FLAG;
const PINNED = 2;

/** A ring as flat x, y, flags triples in tile units. */
type Ring = number[];

const LO = -MASK_BUFFER;
const HI = EXTENT + MASK_BUFFER;
const BOX_AREA = (HI - LO) ** 2;

function mercatorX(lon: number): number {
  return (lon + 180) / 360;
}

function mercatorY(lat: number): number {
  const sin = Math.sin((lat * Math.PI) / 180);
  return 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI);
}

/** Area of a ring of triples, positive when clockwise on screen. */
function area3(ring: Ring): number {
  let sum = 0;
  const n = ring.length;
  for (let i = 0, j = n - 3; i < n; j = i, i += 3) {
    sum += (ring[j] ?? 0) * (ring[i + 1] ?? 0) - (ring[i] ?? 0) * (ring[j + 1] ?? 0);
  }
  return sum / 2;
}

/** Sutherland-Hodgman against the tile box, on triples; cut points take the border flag of both ends, pinned. */
function clip3(ring: Ring): Ring {
  let points = ring;
  for (const [axis, bound, keepAbove] of [
    [0, LO, true],
    [0, HI, false],
    [1, LO, true],
    [1, HI, false],
  ] as const) {
    const n = points.length;
    if (n === 0) break;
    const out: number[] = [];
    const inside = (i: number): boolean => {
      const v = points[i + axis] ?? 0;
      return keepAbove ? v >= bound : v <= bound;
    };
    for (let i = 0, j = n - 3; i < n; j = i, i += 3) {
      const currentIn = inside(i);
      if (currentIn !== inside(j)) {
        const pa = points[j + axis] ?? 0;
        const t = (bound - pa) / ((points[i + axis] ?? 0) - pa);
        const other = 1 - axis;
        const po = points[j + other] ?? 0;
        const value = po + ((points[i + other] ?? 0) - po) * t;
        const flags = ((points[j + 2] ?? 0) & (points[i + 2] ?? 0) & BORDER) | PINNED;
        if (axis === 0) out.push(bound, value, flags);
        else out.push(value, bound, flags);
      }
      if (currentIn) out.push(points[i] ?? 0, points[i + 1] ?? 0, points[i + 2] ?? 0);
    }
    points = out;
  }
  return points.length >= 9 ? points : [];
}

/** Douglas-Peucker on points i0..i1 of a ring (indices of triples), marking those to keep. */
function simplifyRun(ring: Ring, indices: number[], tolerance: number, keep: Uint8Array): void {
  if (indices.length <= 2) return;
  const squared = tolerance * tolerance;
  const stack: [number, number][] = [[0, indices.length - 1]];
  while (stack.length > 0) {
    const [first, last] = stack.pop() ?? [0, 0];
    const a = (indices[first] ?? 0) * 3;
    const b = (indices[last] ?? 0) * 3;
    const ax = ring[a] ?? 0;
    const ay = ring[a + 1] ?? 0;
    const dx = (ring[b] ?? 0) - ax;
    const dy = (ring[b + 1] ?? 0) - ay;
    const length = dx * dx + dy * dy;
    let worst = -1;
    let worstDistance = squared;
    for (let k = first + 1; k < last; k++) {
      const p = (indices[k] ?? 0) * 3;
      const px = (ring[p] ?? 0) - ax;
      const py = (ring[p + 1] ?? 0) - ay;
      let t = length === 0 ? 0 : (px * dx + py * dy) / length;
      t = Math.max(0, Math.min(1, t));
      const ex = t * dx - px;
      const ey = t * dy - py;
      const distance = ex * ex + ey * ey;
      if (distance > worstDistance) {
        worst = k;
        worstDistance = distance;
      }
    }
    if (worst >= 0) {
      keep[indices[worst] ?? 0] = 1;
      stack.push([first, worst], [worst, last]);
    }
  }
}

/**
 * A ring simplified and rounded to whole tile units. Border runs and sea runs
 * are simplified apart, each with its own tolerance; where one meets the
 * other, and where a cut was made, the vertex stays.
 */
function simplifyRing(ring: Ring, borderTolerance: number, seaTolerance: number): Ring {
  const count = ring.length / 3;
  const keep = new Uint8Array(count);
  const kind = (i: number): number => (ring[i * 3 + 2] ?? 0) & BORDER;
  const breaks: number[] = [];
  for (let i = 0; i < count; i++) {
    const flags = ring[i * 3 + 2] ?? 0;
    if ((flags & PINNED) !== 0 || kind(i) !== kind((i - 1 + count) % count)) breaks.push(i);
  }
  if (breaks.length === 0) {
    // One kind all round: split at the first point and the one farthest from it.
    let far = 0;
    let farDistance = -1;
    for (let i = 1; i < count; i++) {
      const d =
        ((ring[i * 3] ?? 0) - (ring[0] ?? 0)) ** 2 + ((ring[i * 3 + 1] ?? 0) - (ring[1] ?? 0)) ** 2;
      if (d > farDistance) {
        far = i;
        farDistance = d;
      }
    }
    breaks.push(0, far);
  }
  for (const b of breaks) keep[b] = 1;
  for (let k = 0; k < breaks.length; k++) {
    const start = breaks[k] ?? 0;
    const end = breaks[(k + 1) % breaks.length] ?? 0;
    const indices: number[] = [];
    for (let i = start; ; i = (i + 1) % count) {
      indices.push(i);
      if (indices.length > 1 && i === end) break;
      if (indices.length > count + 1) break;
    }
    // A run is border when its inner points are (or, with none, both ends are).
    const inner = indices.length > 2 ? (indices[1] ?? start) : start;
    const border = kind(inner) !== 0 && (indices.length > 2 || kind(end) !== 0);
    simplifyRun(ring, indices, border ? borderTolerance : seaTolerance, keep);
  }
  const out: number[] = [];
  for (let i = 0; i < count; i++) {
    if (keep[i] !== 1) continue;
    const x = Math.round(ring[i * 3] ?? 0);
    const y = Math.round(ring[i * 3 + 1] ?? 0);
    const flags = ring[i * 3 + 2] ?? 0;
    const n = out.length;
    if (n >= 3 && out[n - 3] === x && out[n - 2] === y) {
      out[n - 1] = (out[n - 1] ?? 0) & flags;
      continue;
    }
    out.push(x, y, flags);
  }
  while (out.length >= 6 && out[0] === out[out.length - 3] && out[1] === out[out.length - 2]) {
    out.length -= 3;
  }
  return out;
}

function onBoxEdge(ax: number, ay: number, bx: number, by: number): boolean {
  return (ax === bx && (ax === LO || ax === HI)) || (ay === by && (ay === LO || ay === HI));
}

/** The border drawn along a simplified ring: runs of edges whose both ends are on it, off the box edge. */
function borderLines(ring: Ring): number[][] {
  const count = ring.length / 3;
  const isBorderEdge = (i: number): boolean => {
    const j = (i + 1) % count;
    const a = i * 3;
    const b = j * 3;
    return (
      ((ring[a + 2] ?? 0) & (ring[b + 2] ?? 0) & BORDER) !== 0 &&
      !onBoxEdge(ring[a] ?? 0, ring[a + 1] ?? 0, ring[b] ?? 0, ring[b + 1] ?? 0)
    );
  };
  // Start after an edge that is not border, so no run is split at the start.
  let start = -1;
  for (let i = 0; i < count; i++) {
    if (!isBorderEdge(i)) {
      start = (i + 1) % count;
      break;
    }
  }
  const lines: number[][] = [];
  if (start < 0) {
    // The whole ring is border: draw it closed.
    const line: number[] = [];
    for (let i = 0; i <= count; i++)
      line.push(ring[(i % count) * 3] ?? 0, ring[(i % count) * 3 + 1] ?? 0);
    return [line];
  }
  let current: number[] | null = null;
  for (let k = 0; k < count; k++) {
    const i = (start + k) % count;
    if (isBorderEdge(i)) {
      const j = (i + 1) % count;
      if (current === null) {
        current = [ring[i * 3] ?? 0, ring[i * 3 + 1] ?? 0];
        lines.push(current);
      }
      current.push(ring[j * 3] ?? 0, ring[j * 3 + 1] ?? 0);
    } else {
      current = null;
    }
  }
  return lines;
}

function toPairs(ring: Ring): number[] {
  const out: number[] = [];
  for (let i = 0; i < ring.length; i += 3) out.push(ring[i] ?? 0, ring[i + 1] ?? 0);
  return out;
}

/** A mask tile wholly inside the US, and one wholly outside. */
export const INSIDE_TILE = encodeTile([newLayer(MASK_LAYER, [])]);
export const OUTSIDE_TILE = encodeTile([
  newLayer(MASK_LAYER, [{ type: POLYGON, parts: [boxRing({ lo: LO, hi: HI })] }]),
]);

/** Which of the three a tile is. */
export type TileKind = 'inside' | 'outside' | 'mixed';

export interface PyramidStats {
  /** Tiles written, by zoom and kind. */
  readonly tiles: Record<string, number>;
}

/**
 * Every tile of the mask. Tiles at the first zoom that are wholly outside the
 * US are left out; below that, every child of a tile that was cut further.
 */
export function buildPyramid(
  rings: readonly SourceRing[],
  options: PyramidOptions,
): { tiles: ArchiveTile[]; stats: PyramidStats } {
  const tiles: ArchiveTile[] = [];
  const counts: Record<string, number> = {};
  const count = (z: number, kind: TileKind): void => {
    const name = `${String(z)} ${kind}`;
    counts[name] = (counts[name] ?? 0) + 1;
  };

  const visit = (z: number, x: number, y: number, local: Ring[]): void => {
    const clipped = local.map(clip3).filter((ring) => ring.length > 0);
    const usArea = clipped.reduce((sum, ring) => sum + area3(ring), 0);
    let kind: TileKind = 'mixed';
    if (usArea <= BOX_AREA * 1e-12) kind = 'outside';
    else if (usArea >= BOX_AREA * (1 - 1e-12)) kind = 'inside';
    count(z, kind);
    if (kind === 'outside') {
      if (z > options.minZoom) tiles.push({ z, x, y, bytes: OUTSIDE_TILE });
      return;
    }
    if (kind === 'inside') {
      tiles.push({ z, x, y, bytes: INSIDE_TILE });
      return;
    }
    const hasBorder = clipped.some((ring) => {
      for (let i = 2; i < ring.length; i += 3) if (((ring[i] ?? 0) & BORDER) !== 0) return true;
      return false;
    });
    const deepest = hasBorder ? options.borderMaxZoom : options.seaMaxZoom;
    const simplified = clipped
      .map((ring) => simplifyRing(ring, options.borderTolerance(z), options.seaTolerance(z)))
      .filter((ring) => ring.length >= 9 && Math.abs(area3(ring)) >= 0.5);
    const mask = [
      boxRing({ lo: LO, hi: HI }),
      // The US parts are holes in the mask: wound the other way.
      ...simplified.map((ring) => reverseRing(toPairs(ring))),
    ];
    const border = simplified.flatMap(borderLines);
    tiles.push({
      z,
      x,
      y,
      bytes: encodeTile([
        newLayer(MASK_LAYER, [{ type: POLYGON, parts: mask }]),
        newLayer(BORDER_LAYER, border.length > 0 ? [{ type: LINE, parts: border }] : []),
      ]),
    });
    if (z >= deepest) return;
    for (let cy = 0; cy < 2; cy++) {
      for (let cx = 0; cx < 2; cx++) {
        const child = clipped.map((ring) => {
          const out: number[] = [];
          for (let i = 0; i < ring.length; i += 3) {
            out.push(
              (ring[i] ?? 0) * 2 - cx * EXTENT,
              (ring[i + 1] ?? 0) * 2 - cy * EXTENT,
              (ring[i + 2] ?? 0) & BORDER,
            );
          }
          return out;
        });
        visit(z + 1, x * 2 + cx, y * 2 + cy, child);
      }
    }
  };

  // Rings in world units at the first zoom: x, y, flags.
  const z0 = options.minZoom;
  const scale = 2 ** z0 * EXTENT;
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  const world: Ring[] = rings.map((ring) => {
    const out: number[] = [];
    for (let i = 0; i + 1 < ring.coords.length; i += 2) {
      const x = mercatorX(ring.coords[i] ?? 0) * scale;
      const y = mercatorY(ring.coords[i + 1] ?? 0) * scale;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      out.push(x, y, (ring.flags[i / 2] ?? 0) & BORDER);
    }
    // Outer rings of the US wind clockwise on screen, holes the other way.
    const area = area3(out);
    if (area === 0) throw new Error('pyramid: a ring with no area');
    return area > 0 === !ring.hole ? out : reverse3(out);
  });
  const tileRange = (value: number): number => Math.floor(value / EXTENT);
  for (let ty = tileRange(minY - MASK_BUFFER); ty <= tileRange(maxY + MASK_BUFFER); ty++) {
    for (let tx = tileRange(minX - MASK_BUFFER); tx <= tileRange(maxX + MASK_BUFFER); tx++) {
      const local = world.map((ring) => {
        const out: number[] = [];
        for (let i = 0; i < ring.length; i += 3) {
          out.push(
            (ring[i] ?? 0) - tx * EXTENT,
            (ring[i + 1] ?? 0) - ty * EXTENT,
            ring[i + 2] ?? 0,
          );
        }
        return out;
      });
      visit(z0, tx, ty, local);
    }
  }
  return { tiles, stats: { tiles: counts } };
}

function reverse3(ring: Ring): Ring {
  const out: number[] = [];
  for (let i = ring.length - 3; i >= 0; i -= 3)
    out.push(ring[i] ?? 0, ring[i + 1] ?? 0, ring[i + 2] ?? 0);
  return out;
}
