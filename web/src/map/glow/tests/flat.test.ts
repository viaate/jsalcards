/**
 * A flat theme's light (GlowLook mode 'flat'): the glow's own field, cel
 * shaded, so the country's closings read by density, and the glyphs up close
 * ringed, a closed school's ring no larger than half again a glyph.
 */
import { describe, expect, it } from 'vitest';

import { litRadius } from '../../glow-mount';
import {
  BURST_HALF_WIDTH,
  BURST_RADIUS,
  FLAT_FIELD_STEPS,
  FLAT_FIELD_TONES,
  glowStyleAtZoom,
} from '../curves';
import { GLOW_LOOK, type GlowLook } from '../GlowLayer';
import { compositeFrag } from '../shaders';

const FLAT: GlowLook = {
  ...GLOW_LOOK,
  mode: 'flat',
  outline: '#12283e',
  outlineWidth: 1.5,
  burst: true,
};

describe('a flat theme’s light', () => {
  it('leaves the glow’s own composite as it was', () => {
    for (const fallback of [false, true]) {
      for (const dense of [false, true]) {
        const glow = compositeFrag(fallback, dense);
        expect(compositeFrag(fallback, dense, false)).toBe(glow);
        expect(glow).toContain('#define GLOW_FLAT 0');
        // Screened light, as before: the cel shading is compiled out.
        expect(glow).toContain('fragColor = vec4(c, 0.0);');
      }
    }
  });

  it('cel shades the same light in flat steps, edged in ink, laid over the map', () => {
    const flat = compositeFrag(false, true, true);
    expect(flat).toContain('#define GLOW_FLAT 1');
    for (const name of [
      'u_flatColors',
      'u_steps',
      'u_tones',
      'u_outline',
      'u_outlineWidth',
      'u_fade',
      'u_under',
      'u_beyond',
      'u_beyondCount',
    ]) {
      expect(flat).toContain(name);
    }
    expect(flat).toContain('fwidth(v)');
  });

  it('lays no light on the map’s grounds beyond the US, read from the map under it', () => {
    const flat = compositeFrag(false, true, true);
    // The map under each pixel, exactly: a ground beyond is left as it is drawn.
    expect(flat).toContain('texelFetch(u_under, ivec2(gl_FragCoord.xy), 0)');
    expect(flat.indexOf('discard')).toBeLessThan(flat.indexOf('float v = max(c.r'));
    // The glow's own composite reads no map: it is compiled out of it.
    expect(compositeFrag(false, true)).toContain('#define GLOW_FLAT 0');
  });

  it('steps up evenly from a lone closing to the thickest crowd', () => {
    const [low, mid, high] = FLAT_FIELD_STEPS;
    expect(low).toBeGreaterThan(0);
    expect(low).toBeLessThan(mid);
    expect(mid).toBeLessThan(high);
    expect(high).toBeLessThan(1);
    const [faint, half, full] = FLAT_FIELD_TONES;
    expect(faint).toBeGreaterThan(0.15);
    expect(faint).toBeLessThan(half);
    expect(half).toBeLessThan(full);
    expect(full).toBeLessThanOrEqual(1);
  });

  it('rings a closed school no more than half again as wide as its glyph', () => {
    expect(BURST_RADIUS + BURST_HALF_WIDTH).toBeLessThanOrEqual(1.55);
    expect(BURST_RADIUS - BURST_HALF_WIDTH).toBeGreaterThan(1);
  });

  it('taps a lit school as far as it is drawn', () => {
    // Up close: the glyph, its ring and the closed school's ring.
    const close = glowStyleAtZoom(14);
    expect(litRadius(14, FLAT)).toBeCloseTo(
      close.glyphRadiusPx * (BURST_RADIUS + BURST_HALF_WIDTH) + FLAT.outlineWidth,
      6,
    );
    expect(litRadius(14, GLOW_LOOK)).toBe(close.glyphRadiusPx);
    // Further out the light reaches as the glow's does.
    for (const zoom of [4, 6, 8, 10])
      expect(litRadius(zoom, FLAT)).toBe(litRadius(zoom, GLOW_LOOK));
  });
});
