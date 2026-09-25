/**
 * Packs a typed-array point set into the interleaved vertex buffer the glow
 * layer uploads, one 24-byte record per point:
 *
 *   offset  0  float32 x2  mercator hi (x, y)
 *   offset  8  float32 x2  mercator lo (x, y)
 *   offset 16  float32     born time, seconds on the layer clock
 *   offset 20  uint8       status code
 *   offset 21  3 bytes     padding
 *
 * Points are reordered so every glowing point comes first, in draw priority
 * (closed last, so it sits on top), and open points trail. The glow pass then
 * draws a prefix of the buffer and the glyph pass draws both ranges without
 * any per-frame sorting. `order` maps each packed record back to its input row.
 */
import { GlowStatus, STATUS_COUNT } from './color';
import { mercatorXFromLng, mercatorYFromLat, splitDouble } from './mercator';

export interface GlowPoints {
  /** Interleaved longitude, latitude pairs in degrees. Give this or `mercator`. */
  readonly lngLat?: Float32Array | Float64Array;
  /** Interleaved Web Mercator x, y pairs in MapLibre's 0..1 world units. */
  readonly mercator?: Float32Array | Float64Array;
  /** One status code per point: 0 closed, 1 delayed, 2 remote, 3 early dismissal, 4 open. */
  readonly status: Uint8Array;
  /**
   * When each point first appeared, as a `performance.now()` timestamp in
   * milliseconds. Points appear with one soft pulse. Omit it, or use NaN for a
   * row, to show points at once. A time later than now (a skewed server clock,
   * or `Date.now()` passed by mistake) counts as now: the point pulses in at
   * once rather than waiting, unseen, for a moment that may never come.
   */
  readonly bornAt?: Float32Array | Float64Array;
}

/**
 * The layer clock a pack is made against, both as `performance.now()`
 * milliseconds: the instant the clock counts from, and the instant of the pack.
 */
export interface PackClock {
  readonly originMs: number;
  readonly nowMs: number;
}

export const STRIDE_BYTES = 24;
export const STRIDE_FLOATS = STRIDE_BYTES / 4;
export const OFFSET_HI = 0;
export const OFFSET_LO = 8;
export const OFFSET_BORN = 16;
export const OFFSET_STATUS = 20;

/** Most points the layer accepts in one set. */
export const MAX_POINTS = 1_000_000;

/** Born time for points that should show without a pulse: far in the past on any clock. */
export const STATIC_BORN_SECONDS = -1e9;

/** Draw priority by status code. Lower ranks are drawn first; open always trails. */
const RANK: readonly number[] = [
  3, // closed on top
  2, // delayed
  1, // remote
  0, // early dismissal
  4, // open, drawn separately and never glowing
];

export interface PackedPoints {
  /** Interleaved records, `count * STRIDE_BYTES` long. A view into the scratch buffer. */
  readonly bytes: Uint8Array;
  /** Points packed. */
  readonly count: number;
  /** Glowing points, packed first. */
  readonly glowCount: number;
  /** Open points, packed after the glowing ones. */
  readonly openCount: number;
  /** Input rows skipped for a bad coordinate or status code. */
  readonly dropped: number;
  /** Packed record index to input row. */
  readonly order: Uint32Array;
  /**
   * Latest born time in layer-clock seconds, or {@link STATIC_BORN_SECONDS} if
   * none pulse. Never later than the pack's own time, so a layer that keeps
   * repainting while points pulse stops at most one pulse after the pack.
   */
  readonly lastBornSeconds: number;
  /** Rows whose bornAt was later than the pack's time and was moved back to it. */
  readonly bornClamped: number;
}

/** Reusable storage so repeated packs of similar size allocate nothing. */
export class PackScratch {
  buffer = new ArrayBuffer(0);
  order = new Uint32Array(0);

  ensure(count: number): void {
    const bytes = count * STRIDE_BYTES;
    if (this.buffer.byteLength < bytes) {
      this.buffer = new ArrayBuffer(Math.max(bytes, this.buffer.byteLength * 2));
    }
    if (this.order.length < count) {
      this.order = new Uint32Array(Math.max(count, this.order.length * 2));
    }
  }
}

function checkLengths(points: GlowPoints): number {
  const count = points.status.length;
  const coords = points.mercator ?? points.lngLat;
  if (coords === undefined) throw new Error('glow: give either lngLat or mercator coordinates');
  if (points.mercator !== undefined && points.lngLat !== undefined) {
    throw new Error('glow: give lngLat or mercator, not both');
  }
  if (coords.length !== count * 2) {
    throw new Error(
      `glow: ${String(coords.length)} coordinates for ${String(count)} statuses; expected ${String(count * 2)}`,
    );
  }
  if (points.bornAt !== undefined && points.bornAt.length !== count) {
    throw new Error(
      `glow: ${String(points.bornAt.length)} bornAt values for ${String(count)} points`,
    );
  }
  if (count > MAX_POINTS) {
    throw new Error(`glow: ${String(count)} points is over the ${String(MAX_POINTS)} limit`);
  }
  return count;
}

/**
 * Packs `points` into `scratch`. Born times are stored in seconds from
 * `clock.originMs`, so they stay small enough for a float32 to time a fade of
 * about a second exactly, and are clamped to `clock.nowMs`.
 */
export function packPoints(
  points: GlowPoints,
  clock: PackClock,
  scratch: PackScratch = new PackScratch(),
): PackedPoints {
  const count = checkLengths(points);
  const { status, bornAt } = points;
  const isMercator = points.mercator !== undefined;
  const coords = points.mercator ?? points.lngLat ?? new Float32Array(0);

  // Pass 1: validate rows and count them per rank for a stable counting sort.
  const rankOf = new Uint8Array(count);
  const perRank = new Uint32Array(STATUS_COUNT + 1);
  let dropped = 0;
  for (let i = 0; i < count; i++) {
    const code = status[i] ?? 255;
    const a = coords[i * 2] ?? Number.NaN;
    const b = coords[i * 2 + 1] ?? Number.NaN;
    const valid =
      code < STATUS_COUNT &&
      Number.isFinite(a) &&
      Number.isFinite(b) &&
      (isMercator || (a >= -180 && a <= 180 && b >= -90 && b <= 90));
    if (!valid) {
      rankOf[i] = STATUS_COUNT; // sentinel: skipped
      dropped++;
      continue;
    }
    const rank = RANK[code] ?? STATUS_COUNT;
    rankOf[i] = rank;
    perRank[rank] = (perRank[rank] ?? 0) + 1;
  }

  const kept = count - dropped;
  const start = new Uint32Array(STATUS_COUNT + 1);
  for (let r = 1; r <= STATUS_COUNT; r++) {
    start[r] = (start[r - 1] ?? 0) + (perRank[r - 1] ?? 0);
  }
  const openCount = perRank[RANK[GlowStatus.Open] ?? 4] ?? 0;

  scratch.ensure(kept);
  const f32 = new Float32Array(scratch.buffer, 0, kept * STRIDE_FLOATS);
  const u8 = new Uint8Array(scratch.buffer, 0, kept * STRIDE_BYTES);
  const order = scratch.order.subarray(0, kept);

  // Pass 2: write each kept row to its slot.
  const nowSeconds = (clock.nowMs - clock.originMs) / 1000;
  let lastBorn = STATIC_BORN_SECONDS;
  let bornClamped = 0;
  for (let i = 0; i < count; i++) {
    const rank = rankOf[i] ?? STATUS_COUNT;
    if (rank >= STATUS_COUNT) continue;
    const slot = start[rank] ?? 0;
    start[rank] = slot + 1;

    const a = coords[i * 2] ?? 0;
    const b = coords[i * 2 + 1] ?? 0;
    const x = isMercator ? a : mercatorXFromLng(a);
    const y = isMercator ? b : mercatorYFromLat(b);
    const [xHi, xLo] = splitDouble(x);
    const [yHi, yLo] = splitDouble(y);
    const born = bornAt?.[i];
    let bornSeconds = STATIC_BORN_SECONDS;
    if (born !== undefined && Number.isFinite(born)) {
      bornSeconds = (born - clock.originMs) / 1000;
      if (bornSeconds > nowSeconds) {
        bornSeconds = nowSeconds;
        bornClamped++;
      }
    }
    if (bornSeconds > lastBorn) lastBorn = bornSeconds;

    const f = slot * STRIDE_FLOATS;
    f32[f] = xHi;
    f32[f + 1] = yHi;
    f32[f + 2] = xLo;
    f32[f + 3] = yLo;
    f32[f + 4] = bornSeconds;
    const s = slot * STRIDE_BYTES + OFFSET_STATUS;
    u8[s] = status[i] ?? 0;
    u8[s + 1] = 0;
    u8[s + 2] = 0;
    u8[s + 3] = 0;
    order[slot] = i;
  }

  return {
    bytes: u8,
    count: kept,
    glowCount: kept - openCount,
    openCount,
    dropped,
    order,
    lastBornSeconds: lastBorn,
    bornClamped,
  };
}
