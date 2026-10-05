/** Where the light is, so the blend's blur runs only there: elsewhere it reads only zeros and adds nothing. */
import { type PackedPoints, STRIDE_FLOATS } from './pack';

/** Inclusive texel ranges [x0, y0, x1, y1], row 0 at the bottom as the scissor counts them. */
export type TexelBox = readonly [x0: number, y0: number, x1: number, y1: number];

/** Mercator bounds [minX, minY, maxX, maxY] of the glowing points, or null for none or a bad one. */
export function glowBounds(packed: PackedPoints): readonly [number, number, number, number] | null {
  if (packed.glowCount === 0) return null;
  const floats = new Float32Array(
    packed.bytes.buffer,
    packed.bytes.byteOffset,
    packed.glowCount * STRIDE_FLOATS,
  );
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < packed.glowCount; i++) {
    const at = i * STRIDE_FLOATS;
    const x = (floats[at] ?? NaN) + (floats[at + 2] ?? NaN);
    const y = (floats[at + 1] ?? NaN) + (floats[at + 3] ?? NaN);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [minX, minY, maxX, maxY];
}

/** The light target's texels within `reachPx` of `bounds` through `matrix` and `ndcScale`, or null when a corner is behind the camera. */
export function targetBox(
  bounds: readonly [number, number, number, number],
  matrix: ArrayLike<number>,
  ndcScale: readonly [number, number],
  [width, height]: readonly [number, number],
  reachPx: number,
): TexelBox | null {
  const m = (i: number): number => matrix[i] ?? NaN;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const x of [bounds[0], bounds[2]]) {
    for (const y of [bounds[1], bounds[3]]) {
      const w = m(3) * x + m(7) * y + m(15);
      if (!(w > 0)) return null;
      const px = (((m(0) * x + m(4) * y + m(12)) / w) * ndcScale[0] * 0.5 + 0.5) * width;
      const py = (((m(1) * x + m(5) * y + m(13)) / w) * ndcScale[1] * 0.5 + 0.5) * height;
      x0 = Math.min(x0, px);
      y0 = Math.min(y0, py);
      x1 = Math.max(x1, px);
      y1 = Math.max(y1, py);
    }
  }
  // Two texels more, for float32 on the GPU against float64 here.
  const reach = reachPx + 2;
  return clampBox(
    [Math.floor(x0 - reach), Math.floor(y0 - reach), Math.ceil(x1 + reach), Math.ceil(y1 + reach)],
    width,
    height,
  );
}

/** The texels the downsample can light from `box`: each reads source texels 2i - 1 to 2i + 2, with room for an odd size. */
export function levelBox(
  box: TexelBox,
  from: readonly [number, number],
  to: readonly [number, number],
): TexelBox | null {
  if (isEmpty(box)) return box;
  const rx = from[0] / to[0];
  const ry = from[1] / to[1];
  return clampBox(
    [
      Math.floor(box[0] / rx) - 2,
      Math.floor(box[1] / ry) - 2,
      Math.ceil(box[2] / rx) + 2,
      Math.ceil(box[3] / ry) + 2,
    ],
    to[0],
    to[1],
  );
}

/** Where the blur's second pass adds light, and where its first must run for the second to read it, with a texel's slack for each read. */
export function blurBoxes(
  box: TexelBox,
  [width, height]: readonly [number, number],
  radius: number,
): { readonly across: TexelBox; readonly down: TexelBox } | null {
  if (isEmpty(box)) return { across: box, down: box };
  const r = radius + 2;
  const down = clampBox([box[0] - r - 1, box[1] - r, box[2] + r + 1, box[3] + r], width, height);
  const across = clampBox(
    [box[0] - r - 2, box[1] - 2 * r, box[2] + r + 2, box[3] + 2 * r],
    width,
    height,
  );
  return across === null || down === null ? null : { across, down };
}

export function isEmpty(box: TexelBox): boolean {
  return box[0] > box[2] || box[1] > box[3];
}

function clampBox(box: TexelBox, width: number, height: number): TexelBox | null {
  const x0 = Math.max(box[0], 0);
  const y0 = Math.max(box[1], 0);
  const x1 = Math.min(box[2], width - 1);
  const y1 = Math.min(box[3], height - 1);
  if (![x0, y0, x1, y1].every(Number.isFinite)) return null;
  return x0 > x1 || y0 > y1 ? [0, 0, -1, -1] : [x0, y0, x1, y1];
}
