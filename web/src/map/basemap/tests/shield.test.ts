// @vitest-environment node
/**
 * The route number badge: drawn in code at the screen's pixel ratio, round
 * corners outside the stretchable middle, a hairline edge around the fill.
 */
import { describe, expect, it } from 'vitest';

import { shieldImage } from '../shield';

const COLORS = { fill: '#111', edge: '#2a2a2a' };

/** The RGBA of one pixel. */
function pixel(shield: ReturnType<typeof shieldImage>, x: number, y: number): number[] {
  const { width, data } = shield.image;
  const at = (y * width + x) * 4;
  return [...data.slice(at, at + 4)];
}

describe('the route badge', () => {
  it('is drawn at the screen pixel ratio, whole and within reason', () => {
    expect(shieldImage(COLORS, 1).image.width).toBe(16);
    expect(shieldImage(COLORS, 2).image).toMatchObject({ width: 32, height: 32 });
    expect(shieldImage(COLORS, 2.625).options.pixelRatio).toBe(3);
    expect(shieldImage(COLORS, 0.5).options.pixelRatio).toBe(1);
    expect(shieldImage(COLORS, 8).options.pixelRatio).toBe(4);
    const { image } = shieldImage(COLORS, 3);
    expect(image.data).toHaveLength(image.width * image.height * 4);
  });

  it('fills its middle, edges it with a hairline, and leaves its corners clear', () => {
    const shield = shieldImage(COLORS, 2);
    const size = shield.image.width;
    const middle = size / 2;
    expect(pixel(shield, middle, middle)).toEqual([0x11, 0x11, 0x11, 255]);
    // The top edge, one device pixel in: the edge tone, fully drawn.
    expect(pixel(shield, middle, 0)).toEqual([0x2a, 0x2a, 0x2a, 255]);
    // Outside the rounded corner.
    expect(pixel(shield, 0, 0)[3]).toBe(0);
    expect(pixel(shield, size - 1, size - 1)[3]).toBe(0);
    // The corner's curve is antialiased: partly covered pixels between clear and drawn.
    const partial = [...Array(size).keys()]
      .map((i) => pixel(shield, i, 1)[3] ?? 0)
      .filter((alpha) => alpha > 0 && alpha < 255);
    expect(partial.length).toBeGreaterThan(0);
  });

  it('stretches only its straight middle, and fits text inside its edge', () => {
    const { options, image } = shieldImage(COLORS, 2);
    const [[fromX, toX] = [0, 0]] = options.stretchX;
    const [[fromY, toY] = [0, 0]] = options.stretchY;
    expect(fromX).toBeGreaterThan(0);
    expect(toX).toBeLessThan(image.width);
    expect(toX).toBeGreaterThan(fromX);
    expect([fromY, toY]).toEqual([fromX, toX]);
    expect(options.content).toEqual([fromX, fromY, toX, toY]);
    // Every pixel along a stretched row is the same, so stretching never shows.
    const row = image.width / 2;
    const first = pixel({ image, options }, fromX, row);
    for (let x = fromX; x < toX; x++) expect(pixel({ image, options }, x, row)).toEqual(first);
  });

  it('reads the colors it is given', () => {
    const shield = shieldImage({ fill: '#0a0a0a', edge: '#333333' }, 1);
    expect(pixel(shield, 8, 8)).toEqual([10, 10, 10, 255]);
    expect(() => shieldImage({ fill: 'red', edge: '#333' })).toThrow();
  });
});
