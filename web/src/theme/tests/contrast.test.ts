/**
 * Every theme keeps the statuses and the words readable on its grounds
 * (WCAG 2): text at 4.5:1 or more (AA), marks on the map at 3:1 or more
 * (non-text contrast), on every ground they are drawn on: the land, the
 * water, the parks, the school grounds and the roads, or, where a theme
 * rings each mark (GlowLook outline), against the ring that parts it from
 * them. An open school's mark is checked as the map draws it, a little
 * faded (OPEN_ALPHA).
 *
 * The dim text (--text-3) is set on the surfaces (the page's cards and
 * fields) at AA. The map's names are text too, set on every ground of the
 * map (theme tokens mapLabel and mapLabelDim, text-2 and text-3 where left
 * out): at AA on each where their halo is see-through (a flat theme's, so a
 * name never cuts a mark), and at AA on their halo where it is solid (a
 * dark theme's, the ground's own color), which parts them from a bright
 * road under them.
 *
 * Midnight is held where it was before themes, so it looks exactly as it
 * did: its dim text at 3:1 on its surfaces, and its names, its open schools'
 * marks and its glow as the map has always drawn them.
 */
import { describe, expect, it } from 'vitest';

import { FLAT_FIELD_TONES } from '../../map/glow/curves';
import { OPEN_ALPHA } from '../../map/glow/shaders';
import { THEME_IDS, contrast, mix, roadTiers, themeOf, type ThemeTokens } from '../themes';

const STATUS = ['closed', 'delayed', 'remote', 'early'] as const;

function worst(color: string, grounds: readonly string[]): number {
  return Math.min(...grounds.map((ground) => contrast(color, ground)));
}

/** A theme's ambient lights at their brightest over the land. */
function litGrounds(t: ThemeTokens): string[] {
  if (t.amb === 'none' || !t.amb.includes('rgb(')) return [];
  const layers = [...t.amb.matchAll(/rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)/g)].map((m) => ({
    hex: `#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, '0')).join('')}`,
    alpha: Number(m[4]),
  }));
  // Screen blending: the layers of one light (one color) stacked at full strength at one spot,
  // the worst case of each light (the mockups' tools/themes.mjs peaks).
  const lights = new Map<string, number[]>();
  for (const { hex, alpha } of layers) lights.set(hex, [...(lights.get(hex) ?? []), alpha]);
  return [...lights].map(([hex, alphas]) =>
    alphas.reduce((ground, alpha) => mix(ground, screen(ground, hex), alpha), t.land),
  );
}

function screen(a: string, b: string): string {
  const ch = (hex: string, i: number): number =>
    Number.parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `#${[0, 1, 2]
    .map((i) =>
      Math.round(255 - ((255 - ch(a, i)) * (255 - ch(b, i))) / 255)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;
}

describe.each(THEME_IDS)('the %s theme', (id) => {
  const theme = themeOf(id);
  const t = theme.tokens;
  const surfaces = [t.surface1, t.surface2];
  /** Every ground a mark sits on, up close too. */
  const map = [t.land, t.ground, t.water, t.park, t.grounds, t.majorRoad, t.minorRoad];
  /** A toon map's own grounds: its park shade and its shallow water. */
  const touchGrounds = theme.toon ? [theme.toon.parkShade, theme.toon.coastBand] : [];
  /** Every road's tone, at a distance and up close (map/basemap/style.ts). */
  const roads = roadTiers(t).flat();

  it.each(STATUS)('sets the %s status as text on its surfaces at AA', (status) => {
    expect(worst(t[status], surfaces)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(STATUS)('draws the %s status on its map at 3:1, under its light too', (status) => {
    expect(worst(t[status], [t.land, t.ground, ...litGrounds(t)])).toBeGreaterThanOrEqual(3);
  });

  it.each(STATUS)('parts the %s status from every ground up close at 3:1', (status) => {
    const ring = theme.glow.outlineWidth > 0 ? theme.glow.outline : null;
    for (const ground of [...map, ...touchGrounds, ...roads]) {
      const parted =
        contrast(t[status], ground) >= 3 || (ring !== null && contrast(t[status], ring) >= 3);
      expect(parted, `${status} on ${ground}`).toBe(true);
    }
  });

  it('draws an open school at 3:1', () => {
    expect(worst(t.open, [t.land, t.ground, t.surface1])).toBeGreaterThanOrEqual(3);
  });

  it.runIf(id !== 'midnight')('parts an open school from every ground up close at 3:1', () => {
    const ring = theme.glow.outlineWidth > 0 ? theme.glow.outline : null;
    for (const ground of [...map, ...touchGrounds, ...roads]) {
      // As drawn: the dot and its ring a little faded over the ground.
      const dot = mix(ground, t.open, OPEN_ALPHA);
      const parted =
        contrast(dot, ground) >= 3 ||
        (ring !== null && contrast(dot, mix(ground, ring, OPEN_ALPHA)) >= 3);
      expect(parted, `open on ${ground}`).toBe(true);
    }
  });

  it.runIf(id !== 'midnight')('sets the map’s names at AA on every ground they are on', () => {
    const names = { label: t.mapLabel ?? t.text2, dim: t.mapLabelDim ?? t.text3 };
    // A flat theme's halo is see-through (Theme.labelHalo); a dark theme's is the ground's color.
    const seeThrough = theme.labelHalo !== undefined;
    const grounds = seeThrough ? [...map, ...touchGrounds, ...roads] : [t.ground];
    for (const [name, color] of Object.entries(names)) {
      for (const ground of grounds) {
        expect(contrast(color, ground), `${name} ${color} on ${ground}`).toBeGreaterThanOrEqual(
          4.5,
        );
      }
      // Water, parks and neighbourhoods are named inside them, past the halo too.
      for (const ground of [t.land, t.water, t.park, t.grounds, ...touchGrounds]) {
        expect(contrast(color, ground), `${name} ${color} on ${ground}`).toBeGreaterThanOrEqual(
          4.5,
        );
      }
    }
  });

  it.runIf(theme.glow.mode === 'flat')(
    'draws a flat light’s fullest tone of each status at 3:1 on the land',
    () => {
      const full = FLAT_FIELD_TONES[2];
      for (const status of STATUS) {
        // Laid over the land at its opacity.
        expect(contrast(mix(t.land, t[status], full), t.land), status).toBeGreaterThanOrEqual(3);
      }
    },
  );

  it('sets the dim text at AA on its surfaces (Midnight as it was)', () => {
    expect(worst(t.text3, surfaces)).toBeGreaterThanOrEqual(id === 'midnight' ? 3 : 4.5);
  });

  it('sets its words, the chance and a closed school’s label at AA', () => {
    expect(worst(t.text1, [t.bg, ...surfaces])).toBeGreaterThanOrEqual(4.5);
    expect(worst(t.text2, [t.bg, ...surfaces])).toBeGreaterThanOrEqual(4.5);
    expect(worst(t.chance, surfaces)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.onClosed, t.closed)).toBeGreaterThanOrEqual(4.5);
  });

  it('draws its coasts and a lit mark’s ring where it can be seen', () => {
    expect(worst(t.lineOutline, [t.land, t.bg])).toBeGreaterThanOrEqual(3);
    if (theme.glow.mode === 'flat' && theme.glow.outlineWidth > 0 && theme.id === 'snowball') {
      // The ink ring parts every mark from the snow.
      expect(contrast(theme.glow.outline, t.land)).toBeGreaterThanOrEqual(3);
    }
  });

  it('keeps dark themes glowing and light ones flat', () => {
    expect(theme.glow.mode).toBe(theme.scheme === 'dark' ? 'glow' : 'flat');
  });
});
