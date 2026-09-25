import { describe, expect, it } from 'vitest';

import { GlowLayer, GlowStatus } from '..';

describe('GlowLayer', () => {
  it('is a 2D MapLibre custom layer', () => {
    const layer = new GlowLayer({ id: 'glow' });
    expect(layer.id).toBe('glow');
    expect(layer.type).toBe('custom');
    expect(layer.renderingMode).toBe('2d');
    expect(typeof layer.prerender).toBe('function');
    expect(typeof layer.render).toBe('function');
  });

  it('takes data before it is on a map and reports what it holds', () => {
    const layer = new GlowLayer();
    layer.setData({
      lngLat: new Float32Array([-93, 45, -88, 42, -71, 42, 0, 95]),
      status: new Uint8Array([
        GlowStatus.Closed,
        GlowStatus.Open,
        GlowStatus.Remote,
        GlowStatus.Delayed,
      ]),
    });
    expect(layer.stats).toMatchObject({
      mode: 'none',
      frames: 0,
      count: 3,
      glowCount: 2,
      dropped: 1,
      bornClamped: 0,
    });
  });

  it('counts born times later than now, as from a skewed clock or epoch milliseconds', () => {
    const layer = new GlowLayer();
    const now = layer.now();
    layer.setData({
      lngLat: new Float32Array([-93, 45, -88, 42, -71, 42]),
      status: new Uint8Array([GlowStatus.Closed, GlowStatus.Delayed, GlowStatus.Remote]),
      bornAt: new Float64Array([now + 5_000, Date.now(), now - 100]),
    });
    expect(layer.stats.bornClamped).toBe(2);
  });
});
