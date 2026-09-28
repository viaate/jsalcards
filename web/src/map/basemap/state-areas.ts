/**
 * The states in view, named where a phone's map comes to rest closer in.
 *
 * The bundled state names (state-names.ts) each sit at one place in their
 * state, set for the view that shows the whole of it. Closer in a state runs
 * off the screen, its one place often with it, and from the street tiles'
 * zoom on there are no bundled names at all. So on a phone, once the map
 * comes to rest at a view from the bundled names' first zoom up to
 * STATE_AREAS_UNTIL (a metro), every state whose part in the frame has room
 * for its name is named there: at the point of that part farthest from its
 * edges and from the frame's (its pole of inaccessibility), moved off the
 * city names shown there where the part has room enough, and only when the
 * name, with STATE_AREA_MARGIN around it, fits inside that part, clear of
 * the page's controls (where the map would not draw it). A state
 * whose bundled name the map sets whole in the frame keeps it where it is,
 * at its size (keptNames). From then on one layer draws every state's name
 * the map shows and the bundled layer none (index.ts), so no state is ever
 * named twice.
 *
 * The shapes (public/geo/us-states.<hash>.json, scripts/build-geo.mjs) are
 * the states' own, 1 km coarse, and load only when a phone first needs them.
 * Everything here is plain math on Web Mercator world units and the screen's
 * CSS pixels, so it is tested without a map.
 */
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';
import type { MapView } from './bounds';

/** The zoom the states in view are named up to: a metro's, and the whole of it. */
export const STATE_AREAS_UNTIL = 11;

/** Clear space kept between a state's name and its state's edge or the frame's, in CSS pixels. */
export const STATE_AREA_MARGIN = 6;

/** A state's shape: its name, its bounds in degrees and its rings, longitude and latitude in turn. */
export interface StateArea {
  readonly name: string;
  readonly west: number;
  readonly south: number;
  readonly east: number;
  readonly north: number;
  readonly rings: readonly Float64Array[];
}

/** A box on the screen, in CSS pixels from its top left corner. */
export interface ScreenRect {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

/** A state's name, where it goes on the screen. */
export interface StateSpot {
  readonly name: string;
  readonly x: number;
  readonly y: number;
}

/** A state's name set at a spot: its middle on the screen and its size there, in CSS pixels. */
export interface SetName {
  readonly name: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/**
 * Of the bundled names as the map sets them, in their order, the ones the
 * states in view keep: each whole inside the frame, out of the `blocked`
 * boxes and clear by `gap` of every one kept before it (MapLibre would drop
 * it for that one). The rest of the states in view are named where they
 * have room (stateSpots).
 */
export function keptNames(
  names: readonly SetName[],
  frame: ScreenRect,
  gap: number,
  blocked: readonly ScreenRect[] = [],
): SetName[] {
  const kept: SetName[] = [];
  for (const name of names) {
    const box = nameBox(name);
    if (box.x0 < frame.x0 || box.x1 > frame.x1 || box.y0 < frame.y0 || box.y1 > frame.y1) {
      continue;
    }
    if (blocked.some((other) => overlaps(box, other))) continue;
    const clear = kept.every((other) => {
      const them = nameBox(other);
      return (
        box.x1 + gap <= them.x0 ||
        them.x1 + gap <= box.x0 ||
        box.y1 + gap <= them.y0 ||
        them.y1 + gap <= box.y0
      );
    });
    if (clear) kept.push(name);
  }
  return kept;
}

/** Whether two boxes share any area. */
function overlaps(a: ScreenRect, b: ScreenRect): boolean {
  return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
}

/** The box a name set at a spot covers. */
export function nameBox(name: SetName): ScreenRect {
  return {
    x0: name.x - name.width / 2,
    y0: name.y - name.height / 2,
    x1: name.x + name.width / 2,
    y1: name.y + name.height / 2,
  };
}

/** The screen the map is drawn on, in CSS pixels. */
export interface Screen {
  readonly width: number;
  readonly height: number;
}

/** The shapes in the file build-geo.mjs writes; null when it is not that file. */
export function parseStateAreas(data: unknown): StateArea[] | null {
  const states = (data as { states?: unknown } | null)?.states;
  if (!Array.isArray(states)) return null;
  const areas: StateArea[] = [];
  for (const state of states as unknown[]) {
    const { name, rings } = (state ?? {}) as { name?: unknown; rings?: unknown };
    if (typeof name !== 'string' || !Array.isArray(rings)) return null;
    let west = Infinity;
    let south = Infinity;
    let east = -Infinity;
    let north = -Infinity;
    const parsed: Float64Array[] = [];
    for (const ring of rings as unknown[]) {
      if (!Array.isArray(ring) || ring.length < 6 || ring.length % 2 !== 0) return null;
      const flat = Float64Array.from(ring as unknown[], (value) =>
        typeof value === 'number' ? value : Number.NaN,
      );
      for (let i = 0; i < flat.length; i += 2) {
        const lon = flat[i] ?? Number.NaN;
        const lat = flat[i + 1] ?? Number.NaN;
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
        west = Math.min(west, lon);
        east = Math.max(east, lon);
        south = Math.min(south, lat);
        north = Math.max(north, lat);
      }
      parsed.push(flat);
    }
    if (parsed.length > 0) areas.push({ name, west, south, east, north, rings: parsed });
  }
  return areas;
}

/** MapLibre's tiles are 512 px: the world is 512 * 2^zoom px wide. */
const TILE_SIZE = 512;

/** Where to put the name of each state in `areas` that has room for it in `frame` at `view`. */
export interface SpotsOptions {
  readonly view: MapView;
  readonly screen: Screen;
  /** The part of the screen the page's own bars leave to the map, which a name stays inside. */
  readonly frame: ScreenRect;
  /** The size of a state's name on the screen, or null for a state the map does not name. */
  readonly nameSize: (name: string) => { readonly width: number; readonly height: number } | null;
  /** Names already on the screen a state's name keeps off, where its part has room. */
  readonly avoid?: readonly ScreenRect[];
  /** States to leave out: their bundled name is drawn whole. */
  readonly skip?: ReadonlySet<string>;
  /**
   * Boxes a name keeps out of, wherever its part of the frame is: the page's
   * controls and the screen's edges, each with the clear space the map keeps
   * its labels from them (clearance.ts), where the map would not draw it.
   */
  readonly blocked?: readonly ScreenRect[];
}

/** The spot for each state that has room for its name in the frame. */
export function stateSpots(areas: readonly StateArea[], options: SpotsOptions): StateSpot[] {
  const { view, screen, frame } = options;
  if (!(frame.x1 > frame.x0 && frame.y1 > frame.y0)) return [];
  const scale = TILE_SIZE * 2 ** view.zoom;
  const cx = mercatorXFromLng(view.lon);
  const cy = mercatorYFromLat(view.lat);
  const toX = (lon: number): number => screen.width / 2 + (mercatorXFromLng(lon) - cx) * scale;
  const toY = (lat: number): number => screen.height / 2 + (mercatorYFromLat(lat) - cy) * scale;
  const spots: StateSpot[] = [];
  for (const area of areas) {
    if (options.skip?.has(area.name) === true) continue;
    // Its bounds on the screen: a state wholly outside the frame is not in view.
    if (toX(area.east) <= frame.x0 || toX(area.west) >= frame.x1) continue;
    if (toY(area.south) <= frame.y0 || toY(area.north) >= frame.y1) continue;
    const size = options.nameSize(area.name);
    if (size === null) continue;
    const shape = screenShape(area, toX, toY, frame);
    if (shape.edges.length === 0) continue;
    const blocked = options.blocked ?? [];
    // Off the city names where the part has room for that, else where it has the most room.
    const spot =
      fitting(shape, frame, size, blocked, pole(shape, frame, options.avoid ?? [], blocked)) ??
      fitting(shape, frame, size, blocked, pole(shape, frame, [], blocked));
    if (spot !== null) spots.push({ name: area.name, x: spot.x, y: spot.y });
  }
  return spots;
}

/**
 * A state on the screen: its edges as x0, y0, x1, y1 in turn, only those
 * that can bear on the frame (the ones level with it, for inside tests, and
 * of those, the ones near it for distances).
 */
interface ScreenShape {
  readonly edges: Float64Array;
}

function screenShape(
  area: StateArea,
  toX: (lon: number) => number,
  toY: (lat: number) => number,
  frame: ScreenRect,
): ScreenShape {
  const edges: number[] = [];
  for (const ring of area.rings) {
    let px = toX(ring[ring.length - 2] ?? 0);
    let py = toY(ring[ring.length - 1] ?? 0);
    for (let i = 0; i < ring.length; i += 2) {
      const x = toX(ring[i] ?? 0);
      const y = toY(ring[i + 1] ?? 0);
      // An edge wholly above or below the frame never crosses a ray from a point in it, and
      // is farther from any such point than the frame's own edge.
      if (!((py < frame.y0 && y < frame.y0) || (py > frame.y1 && y > frame.y1))) {
        edges.push(px, py, x, y);
      }
      px = x;
      py = y;
    }
  }
  return { edges: Float64Array.from(edges) };
}

/** Whether a point is inside the shape: an even-odd ray cast to the right. */
function inside(shape: ScreenShape, x: number, y: number): boolean {
  const { edges } = shape;
  let odd = false;
  for (let i = 0; i < edges.length; i += 4) {
    const ax = edges[i] ?? 0;
    const ay = edges[i + 1] ?? 0;
    const bx = edges[i + 2] ?? 0;
    const by = edges[i + 3] ?? 0;
    if (ay > y !== by > y && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) odd = !odd;
  }
  return odd;
}

/** Squared distance from a point to a segment. */
function segmentDistance2(
  x: number,
  y: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const length2 = dx * dx + dy * dy;
  const t = length2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / length2));
  const ex = ax + t * dx - x;
  const ey = ay + t * dy - y;
  return ex * ex + ey * ey;
}

/** Distance from a point to a box, 0 inside it. */
function boxDistance(x: number, y: number, box: ScreenRect): number {
  const dx = Math.max(box.x0 - x, 0, x - box.x1);
  const dy = Math.max(box.y0 - y, 0, y - box.y1);
  return Math.hypot(dx, dy);
}

/**
 * How much room a point has: its distance to the shape's edge and the
 * frame's, and to the names to avoid and the boxes blocked; negative outside
 * the shape or the frame. It changes by at most as much as the point moves,
 * which the search in `pole` relies on.
 */
function room(
  shape: ScreenShape,
  frame: ScreenRect,
  avoid: readonly ScreenRect[],
  blocked: readonly ScreenRect[],
  x: number,
  y: number,
): number {
  const { edges } = shape;
  let nearest2 = Infinity;
  for (let i = 0; i < edges.length; i += 4) {
    const d2 = segmentDistance2(
      x,
      y,
      edges[i] ?? 0,
      edges[i + 1] ?? 0,
      edges[i + 2] ?? 0,
      edges[i + 3] ?? 0,
    );
    if (d2 < nearest2) nearest2 = d2;
  }
  const edge = Math.sqrt(nearest2);
  const inFrame = Math.min(x - frame.x0, frame.x1 - x, y - frame.y0, frame.y1 - y);
  if (!inside(shape, x, y)) return -edge;
  let best = Math.min(edge, inFrame);
  for (const box of avoid) best = Math.min(best, boxDistance(x, y, box));
  for (const box of blocked) best = Math.min(best, boxDistance(x, y, box));
  return best;
}

/** A square of the search: its middle, half its side, its room and the most any point in it can have. */
interface Cell {
  readonly x: number;
  readonly y: number;
  readonly half: number;
  readonly room: number;
  readonly most: number;
}

/** How precisely the search finds the point with the most room, in CSS pixels. */
const POLE_PRECISION = 2;

/** A heap of cells, the one that can hold the most room on top. */
class CellHeap {
  private readonly cells: Cell[] = [];

  get size(): number {
    return this.cells.length;
  }

  push(cell: Cell): void {
    const { cells } = this;
    cells.push(cell);
    let i = cells.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      const above = cells[parent];
      if (above === undefined || above.most >= cell.most) break;
      cells[i] = above;
      i = parent;
    }
    cells[i] = cell;
  }

  pop(): Cell | undefined {
    const { cells } = this;
    const top = cells[0];
    const last = cells.pop();
    if (top === undefined || last === undefined || cells.length === 0) return top;
    let i = 0;
    for (;;) {
      const left = 2 * i + 1;
      const right = left + 1;
      const leftCell = cells[left];
      const rightCell = cells[right];
      if (leftCell === undefined) break;
      const [child, larger] =
        rightCell !== undefined && rightCell.most > leftCell.most
          ? [right, rightCell]
          : [left, leftCell];
      if (larger.most <= last.most) break;
      cells[i] = larger;
      i = child;
    }
    cells[i] = last;
    return top;
  }
}

/**
 * The point of the shape's part in the frame with the most room (its pole
 * of inaccessibility, the names to avoid counted as edges), found by
 * splitting squares and dropping the ones that cannot hold more room than
 * the best point found so far.
 */
function pole(
  shape: ScreenShape,
  frame: ScreenRect,
  avoid: readonly ScreenRect[],
  blocked: readonly ScreenRect[],
): { x: number; y: number } {
  const width = frame.x1 - frame.x0;
  const height = frame.y1 - frame.y0;
  const side = Math.min(width, height);
  const cell = (x: number, y: number, half: number): Cell => {
    const value = room(shape, frame, avoid, blocked, x, y);
    return { x, y, half, room: value, most: value + half * Math.SQRT2 };
  };
  const queue = new CellHeap();
  let best = cell((frame.x0 + frame.x1) / 2, (frame.y0 + frame.y1) / 2, 0);
  for (let x = frame.x0; x < frame.x1; x += side) {
    for (let y = frame.y0; y < frame.y1; y += side) {
      queue.push(cell(x + side / 2, y + side / 2, side / 2));
    }
  }
  while (queue.size > 0) {
    const next = queue.pop();
    if (next === undefined) break;
    if (next.room > best.room) best = next;
    if (next.most - best.room <= POLE_PRECISION) continue;
    const half = next.half / 2;
    queue.push(cell(next.x - half, next.y - half, half));
    queue.push(cell(next.x + half, next.y - half, half));
    queue.push(cell(next.x - half, next.y + half, half));
    queue.push(cell(next.x + half, next.y + half, half));
  }
  return { x: best.x, y: best.y };
}

/**
 * The spot, when a name of `size` fits there: with STATE_AREA_MARGIN around
 * it, inside the frame, the spot inside the shape and no edge of the shape
 * crossing it; and the name itself out of the boxes blocked. Null when it
 * does not.
 */
function fitting(
  shape: ScreenShape,
  frame: ScreenRect,
  size: { readonly width: number; readonly height: number },
  blocked: readonly ScreenRect[],
  spot: { x: number; y: number },
): { x: number; y: number } | null {
  const name = nameBox({ name: '', x: spot.x, y: spot.y, ...size });
  if (blocked.some((other) => overlaps(name, other))) return null;
  const box = {
    x0: name.x0 - STATE_AREA_MARGIN,
    y0: name.y0 - STATE_AREA_MARGIN,
    x1: name.x1 + STATE_AREA_MARGIN,
    y1: name.y1 + STATE_AREA_MARGIN,
  };
  if (box.x0 < frame.x0 || box.x1 > frame.x1 || box.y0 < frame.y0 || box.y1 > frame.y1) {
    return null;
  }
  if (!inside(shape, spot.x, spot.y)) return null;
  const { edges } = shape;
  for (let i = 0; i < edges.length; i += 4) {
    if (
      segmentMeetsBox(edges[i] ?? 0, edges[i + 1] ?? 0, edges[i + 2] ?? 0, edges[i + 3] ?? 0, box)
    ) {
      return null;
    }
  }
  return spot;
}

/** Whether a segment runs through a box or into it. */
function segmentMeetsBox(ax: number, ay: number, bx: number, by: number, box: ScreenRect): boolean {
  if (Math.max(ax, bx) < box.x0 || Math.min(ax, bx) > box.x1) return false;
  if (Math.max(ay, by) < box.y0 || Math.min(ay, by) > box.y1) return false;
  const within = (x: number, y: number): boolean =>
    x >= box.x0 && x <= box.x1 && y >= box.y0 && y <= box.y1;
  if (within(ax, ay) || within(bx, by)) return true;
  // Which side of the segment each corner is on: all on one side, the segment misses the box.
  const side = (x: number, y: number): number =>
    Math.sign((bx - ax) * (y - ay) - (by - ay) * (x - ax));
  const sides = [
    side(box.x0, box.y0),
    side(box.x1, box.y0),
    side(box.x0, box.y1),
    side(box.x1, box.y1),
  ];
  return !(sides.every((s) => s > 0) || sides.every((s) => s < 0));
}
