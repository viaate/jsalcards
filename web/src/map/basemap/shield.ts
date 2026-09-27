/**
 * The badge highway route numbers sit on ("I-35", "US 71", "MO 9"): a small
 * rounded rectangle in the page's surface tone with a hairline border, the
 * same as the page's own controls. The style names it by SHIELD_IMAGE and
 * MapLibre stretches it around each number (`icon-text-fit`), keeping the
 * corners.
 *
 * The image is drawn here, pixel by pixel, when the map first asks for it
 * (index.ts), so the style still names no sprite and nothing is fetched.
 */

/** The image id the style's shield layer names. */
export const SHIELD_IMAGE = 'snowlight-route-shield';

export interface ShieldColors {
  /** Inside the badge. */
  readonly fill: string;
  /** Its hairline edge. */
  readonly edge: string;
}

/** An RGBA image MapLibre's addImage takes, with the options that stretch it around text. */
export interface ShieldImage {
  readonly image: { width: number; height: number; data: Uint8Array };
  readonly options: {
    pixelRatio: number;
    stretchX: [number, number][];
    stretchY: [number, number][];
    content: [number, number, number, number];
  };
}

/** Size of the badge before it is stretched, and its corner radius, in CSS pixels. */
const SIZE = 16;
const RADIUS = 4;
/** The edge, in CSS pixels. */
const EDGE = 1;

function channels(hex: string): [number, number, number] {
  let digits = hex.replace('#', '');
  if (digits.length === 3) digits = digits.replace(/./g, (d) => d + d);
  const value = Number.parseInt(digits, 16);
  if (digits.length !== 6 || Number.isNaN(value)) throw new Error(`Not a hex color: ${hex}`);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** Signed distance from a point to a rounded square's outline: negative inside. */
function distance(x: number, y: number, size: number, radius: number): number {
  const half = size / 2;
  const qx = Math.abs(x - half) - (half - radius);
  const qy = Math.abs(y - half) - (half - radius);
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
  return outside + Math.min(Math.max(qx, qy), 0) - radius;
}

/**
 * The badge at a device pixel ratio: `fill` inside a hairline `edge`, each
 * pixel's coverage antialiased. Only the straight middle stretches, so the
 * corners stay round at any size.
 */
export function shieldImage(colors: ShieldColors, pixelRatio = 1): ShieldImage {
  const ratio = Math.max(1, Math.min(4, Math.round(pixelRatio)));
  const size = SIZE * ratio;
  const radius = RADIUS * ratio;
  const edge = EDGE * ratio;
  const fill = channels(colors.fill);
  const line = channels(colors.edge);
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = distance(x + 0.5, y + 0.5, size, radius);
      const cover = Math.min(1, Math.max(0, 0.5 - d));
      if (cover === 0) continue;
      // 1 on the edge, 0 inside it, blended across a pixel.
      const onEdge = Math.min(1, Math.max(0, d + edge + 0.5));
      const at = (y * size + x) * 4;
      for (let c = 0; c < 3; c++) {
        const inner = fill[c] ?? 0;
        data[at + c] = Math.round(inner + ((line[c] ?? 0) - inner) * onEdge);
      }
      data[at + 3] = Math.round(cover * 255);
    }
  }
  const from = radius + edge;
  const to = size - radius - edge;
  return {
    image: { width: size, height: size, data },
    options: {
      pixelRatio: ratio,
      stretchX: [[from, to]],
      stretchY: [[from, to]],
      content: [from, from, to, to],
    },
  };
}
