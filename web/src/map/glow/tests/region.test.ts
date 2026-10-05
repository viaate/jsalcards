import { describe, expect, it } from 'vitest';

import { type PackedPoints, PackScratch, packPoints } from '../pack';
import { blurBoxes, glowBounds, isEmpty, levelBox, targetBox, type TexelBox } from '../region';

/** A single-channel level, row 0 at the bottom. */
interface Level {
  readonly width: number;
  readonly height: number;
  readonly data: Float64Array;
}

function level(width: number, height: number): Level {
  return { width, height, data: new Float64Array(width * height) };
}

/** Bilinear sample at (x, y) in texel units, clamped at the edges, as the shaders sample. */
function sample(source: Level, x: number, y: number): number {
  const clamp = (i: number, n: number): number => Math.min(Math.max(i, 0), n - 1);
  const fx = x - 0.5;
  const fy = y - 0.5;
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const tx = fx - x0;
  const ty = fy - y0;
  const at = (i: number, j: number): number =>
    source.data[clamp(j, source.height) * source.width + clamp(i, source.width)] ?? NaN;
  return (
    (1 - ty) * ((1 - tx) * at(x0, y0) + tx * at(x0 + 1, y0)) +
    ty * ((1 - tx) * at(x0, y0 + 1) + tx * at(x0 + 1, y0 + 1))
  );
}

/** DOWNSAMPLE_FRAG: four bilinear taps one source texel off each diagonal. */
function downsample(source: Level): Level {
  const out = level(Math.ceil(source.width / 2), Math.ceil(source.height / 2));
  for (let j = 0; j < out.height; j++) {
    for (let i = 0; i < out.width; i++) {
      const u = ((i + 0.5) / out.width) * source.width;
      const v = ((j + 0.5) / out.height) * source.height;
      out.data[j * out.width + i] =
        0.25 *
        (sample(source, u - 1, v - 1) +
          sample(source, u + 1, v - 1) +
          sample(source, u - 1, v + 1) +
          sample(source, u + 1, v + 1));
    }
  }
  return out;
}

/** BLUR_FRAG along one axis, into `target` within `box` (everywhere without one), adding if `add`. */
function blurPass(
  source: Level,
  target: Level,
  axis: 0 | 1,
  sigma: number,
  radius: number,
  box: TexelBox | null,
  add: boolean,
): void {
  const k = -0.5 / (sigma * sigma);
  for (let j = 0; j < target.height; j++) {
    for (let i = 0; i < target.width; i++) {
      if (box !== null && (i < box[0] || i > box[2] || j < box[1] || j > box[3])) continue;
      let sum = sample(source, i + 0.5, j + 0.5);
      let total = 1;
      for (let t = 1; t <= radius; t += 2) {
        const a = Math.exp(k * t * t);
        const b = t < radius ? Math.exp(k * (t + 1) * (t + 1)) : 0;
        const w = a + b;
        const offset = (t * a + (t + 1) * b) / w;
        const [dx, dy] = axis === 0 ? [offset, 0] : [0, offset];
        sum +=
          w *
          (sample(source, i + 0.5 + dx, j + 0.5 + dy) + sample(source, i + 0.5 - dx, j + 0.5 - dy));
        total += 2 * w;
      }
      const at = j * target.width + i;
      target.data[at] = (add ? (target.data[at] ?? 0) : 0) + sum / total;
    }
  }
}

function within(box: TexelBox, i: number, j: number): boolean {
  return i >= box[0] && i <= box[2] && j >= box[1] && j <= box[3];
}

/** Packs points at mercator (x, y), every one glowing. */
function pack(points: readonly (readonly [number, number])[]): PackedPoints {
  return packPoints(
    {
      mercator: new Float64Array(points.flat()),
      status: new Uint8Array(points.length),
    },
    { originMs: 0, nowMs: 0 },
    new PackScratch(),
  );
}

describe('the lit region', () => {
  it('bounds every glowing point, and none for no points', () => {
    const packed = pack([
      [0.21, 0.37],
      [0.25, 0.31],
      [0.23, 0.4],
    ]);
    const bounds = glowBounds(packed);
    expect(bounds?.[0]).toBeCloseTo(0.21, 7);
    expect(bounds?.[1]).toBeCloseTo(0.31, 7);
    expect(bounds?.[2]).toBeCloseTo(0.25, 7);
    expect(bounds?.[3]).toBeCloseTo(0.4, 7);
    expect(glowBounds(pack([]))).toBeNull();
  });

  it('cannot tell where the light is with a point behind the camera', () => {
    const behind = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1];
    expect(targetBox([0.2, 0.2, 0.3, 0.3], behind, [1, 1], [100, 100], 4)).toBeNull();
  });

  it('blurs a level lit in places the same within its boxes as everywhere, on odd sizes too', () => {
    // Mercator 0..1 onto clip -1..1, so a point at (x, y) lands at (x * width, y * height).
    const matrix = [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1, 0, -1, -1, 0, 1];
    let seed = 7;
    const random = (): number => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    for (const [width, height, count, blurLevel, sigma, smaller] of [
      [101, 67, 3, 1, 1.7, true],
      [192, 128, 1, 2, 2.4, true],
      [77, 120, 6, 2, 1.2, false],
      [64, 63, 2, 3, 0.9, false],
    ] as const) {
      const sprite = 3.5;
      const points = Array.from({ length: count }, (): [number, number] => [
        0.1 + 0.35 * random(),
        0.2 + 0.4 * random(),
      ]);
      const lit = targetBox(
        glowBounds(pack(points)) ?? [0, 0, 0, 0],
        matrix,
        [1, 1],
        [width, height],
        sprite,
      );
      expect(lit).not.toBeNull();
      if (lit === null) return;
      // The light pass: a soft disc of light around each point.
      const base = level(width, height);
      for (const [x, y] of points) {
        for (let j = 0; j < height; j++) {
          for (let i = 0; i < width; i++) {
            const d = Math.hypot(i + 0.5 - x * width, j + 0.5 - y * height);
            if (d < sprite)
              base.data[j * width + i] = (base.data[j * width + i] ?? 0) + 1 - d / sprite;
          }
        }
      }
      let box: TexelBox | null = lit;
      let blurred = base;
      for (let l = 1; l <= blurLevel; l++) {
        const from = blurred;
        const to = downsample(from);
        blurred = to;
        box = box === null ? null : levelBox(box, [from.width, from.height], [to.width, to.height]);
        // Every lit texel of each level is inside its box.
        for (let j = 0; j < to.height; j++) {
          for (let i = 0; i < to.width; i++) {
            if ((to.data[j * to.width + i] ?? 0) !== 0) expect(box && within(box, i, j)).toBe(true);
          }
        }
      }
      const radius = Math.ceil(3 * sigma);
      const boxes = box === null ? null : blurBoxes(box, [blurred.width, blurred.height], radius);
      expect(boxes).not.toBeNull();
      if (boxes === null) return;
      expect(isEmpty(boxes.down)).toBe(false);

      // Everywhere, as before.
      const across = level(blurred.width, blurred.height);
      const full = { ...blurred, data: Float64Array.from(blurred.data, (v) => v + 0.125) };
      blurPass(blurred, across, 0, sigma, radius, null, false);
      blurPass(across, full, 1, sigma, radius, null, true);
      // Within the boxes, over a blur target that holds an older frame's light.
      const stale = { ...across, data: Float64Array.from(across.data, () => 9 * random()) };
      const scissored = { ...blurred, data: Float64Array.from(blurred.data, (v) => v + 0.125) };
      blurPass(blurred, stale, 0, sigma, radius, boxes.across, false);
      blurPass(stale, scissored, 1, sigma, radius, boxes.down, true);
      expect(Array.from(scissored.data)).toEqual(Array.from(full.data));
      // Where the light is small against the level, so is the blur's work.
      const area = (b: TexelBox): number => (b[2] - b[0] + 1) * (b[3] - b[1] + 1);
      if (smaller) expect(area(boxes.across)).toBeLessThan(blurred.width * blurred.height);
    }
  });
});
