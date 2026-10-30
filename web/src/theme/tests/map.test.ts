/**
 * The map takes a theme from the page's custom properties (theme/css.ts):
 * the basemap's colors and widths (map/basemap/style.ts paletteTokens) and
 * the glow's look (map/glow-mount.ts glowLook). Midnight's map is the one
 * map/basemap/tests/style.test.ts checks; a page with no theme on reads as it.
 */
import type { LayerSpecification } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import { BASEMAP_IDS } from '../../map/basemap/ids';
import { TOUCH_LAYERS, buildBasemapStyle, paletteOf, paletteTokens } from '../../map/basemap/style';
import type { BasemapColors } from '../../map/basemap/style';
import { GLOW_LOOK } from '../../map/glow/GlowLayer';
import { glowLook } from '../../map/glow-mount';
import { BEYOND_MAX } from '../../map/glow/shaders';
import { themeProperties } from '../css';
import { THEMES, THEME_IDS, roadTiers, themeOf } from '../themes';
import type { Theme } from '../themes';

/** The page's tokens with a theme on, as getComputedStyle reads them. */
function reader(theme: Theme | null): (name: string, fallback?: string) => string {
  const props = new Map(theme === null ? [] : themeProperties(theme));
  return (name, fallback = '') => props.get(name) ?? fallback;
}

function colorsOf(theme: Theme): BasemapColors {
  const t = theme.tokens;
  return {
    background: t.bg,
    land: t.land,
    outline: t.lineOutline,
    state: t.lineState,
    label: t.mapLabel ?? t.text2,
    labelDim: t.mapLabelDim ?? t.text3,
    labelBright: t.text1,
    building: t.surface2,
    buildingEdge: t.border1,
    palette: paletteTokens(reader(theme)),
  };
}

function paint(layers: readonly LayerSpecification[], id: string, name: string): unknown {
  const layer = layers.find((candidate) => candidate.id === id) as
    { paint?: Record<string, unknown> } | undefined;
  return layer?.paint?.[name];
}

describe('the map in a theme', () => {
  it('changes its paint at once, in the frame the page does, with no fade', () => {
    const style = buildBasemapStyle({
      usLines: { type: 'FeatureCollection', features: [] },
      hairline: 1,
      colors: colorsOf(THEMES.midnight),
      schools: null,
    });
    expect(style.transition).toEqual({ duration: 0, delay: 0 });
  });

  it('reads nothing from a page with no theme on: Midnight’s own palette', () => {
    expect(paletteTokens(reader(null))).toEqual({});
    expect(glowLook(reader(null))).toEqual({ ...GLOW_LOOK, burst: false });
  });

  it.each(THEME_IDS.filter((id) => id !== 'midnight'))('draws %s in its own colors', (id) => {
    const theme = themeOf(id);
    const t = theme.tokens;
    const colors = colorsOf(theme);
    const palette = paletteOf(colors);
    expect(palette.ground).toBe(t.ground);
    expect(palette.water).toBe(t.water);
    expect(palette.roads).toEqual(roadTiers(t).map(([tone, close]) => [tone, close]));
    const style = buildBasemapStyle({
      usLines: { type: 'FeatureCollection', features: [] },
      hairline: 1,
      colors,
      schools: 'https://example.test/schools.pmtiles',
    });
    const { layers } = style;
    expect(paint(layers, BASEMAP_IDS.ofmWaterFill, 'fill-color')).toBe(t.water);
    expect(paint(layers, BASEMAP_IDS.ofmPark, 'fill-color')).toBe(t.park);
    expect(paint(layers, BASEMAP_IDS.usOutline, 'line-color')).toBe(t.lineOutline);
    expect(paint(layers, BASEMAP_IDS.schoolDots, 'circle-color')).toBe(t.dot);
    expect(paint(layers, BASEMAP_IDS.schoolDots, 'circle-stroke-color')).toBe(t.dotRing);
    // The sea at the national view, the street tiles' ground from the handover.
    const ground = JSON.stringify(paint(layers, BASEMAP_IDS.background, 'background-color'));
    expect(ground).toContain(t.bg);
    expect(ground).toContain(t.ground);
    // No Midnight gray is left in a theme's map, but where the theme uses it itself.
    const midnight = ['#0c0c0c', '#0d0d0d', '#0f0f0f', '#161616', '#191919', '#282828', '#1a1a1a'];
    const all = JSON.stringify(layers);
    for (const gray of midnight) {
      if (!Object.values(t).includes(gray)) expect(all).not.toContain(`"${gray}"`);
    }
  });

  it('draws Snowball’s map as a cartoon: ink lines, edges and casings, and flat steps', () => {
    const colors = colorsOf(themeOf('snowball'));
    const toon = themeOf('snowball').toon;
    if (toon === undefined) throw new Error('Snowball has no touches');
    const { layers } = buildBasemapStyle({
      usLines: { type: 'FeatureCollection', features: [] },
      hairline: 0.75,
      colors,
    });
    const at = (id: string): number => layers.findIndex((layer) => layer.id === id);
    const visibility = (list: readonly LayerSpecification[], id: string): unknown =>
      (list.find((layer) => layer.id === id)?.layout as { visibility?: unknown } | undefined)
        ?.visibility;
    // Ink coasts, and ink state lines at least 2 px.
    expect(paint(layers, BASEMAP_IDS.usOutline, 'line-width')).toBe(3);
    expect(paint(layers, BASEMAP_IDS.usStates, 'line-width')).toBeGreaterThanOrEqual(2);
    expect(paint(layers, BASEMAP_IDS.usStates, 'line-color')).toBe(
      themeOf('snowball').tokens.border2,
    );
    // Ink edges around the water, the parks and the school grounds.
    expect(paint(layers, BASEMAP_IDS.ofmWater, 'line-width')).toBe(toon.edgeWidth);
    expect(paint(layers, BASEMAP_IDS.ofmSchoolGroundsEdge, 'line-width')).toBe(toon.edgeWidth);
    expect(paint(layers, BASEMAP_IDS.ofmParkEdge, 'line-color')).toBe(toon.parkEdge);
    // The through roads cased in ink, under every road.
    expect(paint(layers, BASEMAP_IDS.ofmRoadCasing, 'line-color')).toBe(toon.roadCasing);
    expect(at(BASEMAP_IDS.ofmRoadCasing)).toBeLessThan(at(BASEMAP_IDS.ofmRoad));
    expect(at(BASEMAP_IDS.ofmRoadCasing)).toBeGreaterThan(at(BASEMAP_IDS.ofmRoadTunnel));
    // A flat step of shallow water along the coasts, under the land; one of shade under each park.
    expect(at(BASEMAP_IDS.usCoastBand)).toBe(at(BASEMAP_IDS.usLand) - 1);
    expect(paint(layers, BASEMAP_IDS.usCoastBand, 'line-color')).toBe(toon.coastBand);
    expect(paint(layers, BASEMAP_IDS.ofmParkShade, 'fill-color')).toBe(toon.parkShade);
    expect(at(BASEMAP_IDS.ofmParkShade)).toBe(at(BASEMAP_IDS.ofmPark) - 1);
    expect(at(BASEMAP_IDS.ofmParkEdge)).toBe(at(BASEMAP_IDS.ofmPark) + 1);
    for (const id of TOUCH_LAYERS) expect(visibility(layers, id), id).toBe('visible');
    // Labels' halos let a mark show through.
    expect(paint(layers, BASEMAP_IDS.ofmStreetLabel, 'text-halo-color')).toBe(
      themeOf('snowball').labelHalo,
    );

    // Midnight has none of it: hairlines, and no touch drawn.
    const midnight = buildBasemapStyle({
      usLines: { type: 'FeatureCollection', features: [] },
      hairline: 0.75,
      colors: { ...colors, palette: {} },
    });
    expect(paint(midnight.layers, BASEMAP_IDS.usOutline, 'line-width')).toBe(0.75);
    expect(paint(midnight.layers, BASEMAP_IDS.ofmWater, 'line-width')).toBe(0.75);
    for (const id of TOUCH_LAYERS) expect(visibility(midnight.layers, id), id).toBe('none');
    expect(JSON.stringify(paint(layers, BASEMAP_IDS.ofmRoad, 'line-width'))).not.toBe(
      JSON.stringify(paint(midnight.layers, BASEMAP_IDS.ofmRoad, 'line-width')),
    );
  });

  it('draws a theme’s touches only where it has them all', () => {
    for (const id of THEME_IDS.filter((name) => name !== 'snowball')) {
      expect(paletteTokens(reader(themeOf(id))).touches, id).toBeUndefined();
    }
    const snowball = themeOf('snowball');
    expect(paletteTokens(reader(snowball)).touches).toEqual(
      snowball.toon && {
        coastBand: snowball.toon.coastBand,
        parkEdge: snowball.toon.parkEdge,
        parkShade: snowball.toon.parkShade,
        roadCasing: snowball.toon.roadCasing,
        casingWidth: snowball.toon.casingWidth,
      },
    );
  });

  it('gives the glow each theme’s statuses and treatment', () => {
    for (const id of THEME_IDS.filter((name) => name !== 'midnight')) {
      const theme = themeOf(id);
      const t = theme.tokens;
      const look = glowLook(reader(theme));
      expect(look.status).toEqual([t.closed, t.delayed, t.remote, t.early, t.open]);
      expect(look.mode).toBe(theme.glow.mode);
      expect(look.outlineWidth).toBe(theme.glow.outlineWidth);
      expect(look.burst).toBe(theme.glow.burst);
      // On a light ground the dust is dark, the darker of speck and map kept.
      expect(look.dust?.blend ?? 'max').toBe(theme.scheme === 'light' ? 'min' : 'max');
    }
  });

  it('keeps a flat light off the grounds beyond the US: the sea and a toon map’s coast band', () => {
    for (const id of THEME_IDS.filter((name) => name !== 'midnight')) {
      const theme = themeOf(id);
      const look = glowLook(reader(theme));
      if (theme.glow.mode !== 'flat') {
        expect(look.beyond, id).toBeUndefined();
        continue;
      }
      const beyond = [theme.tokens.bg, ...(theme.toon ? [theme.toon.coastBand] : [])];
      expect(look.beyond, id).toEqual(beyond);
      // Never the land the light is laid on, and no more than the shader reads.
      expect(look.beyond, id).not.toContain(theme.tokens.land);
      expect(beyond.length).toBeLessThanOrEqual(BEYOND_MAX);
    }
  });
});
