/**
 * The themes built but not yet offered anywhere, until the owner approves
 * them: a build carries and lists them only where VITE_THEMES_PREVIEW names
 * one (for the owner's screenshots; themes.ts THEMES_UNRELEASED), and a
 * device that has one kept sees Midnight. A default build's scripts carry
 * nothing of this module (vite.config.ts).
 */
import type { Theme } from './themes.ts';

export const UNRELEASED_IDS = ['snowball'] as const;

export type UnreleasedThemeId = (typeof UNRELEASED_IDS)[number];

/**
 * Snowball, the cel-shaded cartoon theme: flat snow and ice in two or three
 * steps, bold ink outlines, chunky round shapes and bright accents. Its own
 * palette and its own name; no game's colors, art or type.
 */
const SNOWBALL: Theme = {
  id: 'snowball',
  scheme: 'light',
  access: 'shop',
  tokens: {
    bg: '#8ccdf2',
    surface1: '#ffffff',
    surface2: '#e8f4fd',
    border1: '#bcd7ec',
    border2: '#16324f',
    text1: '#12283e',
    text2: '#36536f',
    text3: '#566f88',
    accent: '#ffc93c',
    closed: '#0a64c8',
    delayed: '#ac5300',
    remote: '#6a3bd2',
    early: '#08784a',
    open: '#768a9e',
    chance: '#12283e',
    onClosed: '#ffffff',
    mapLabelDim: '#3b536a',
    land: '#f7fbff',
    ground: '#f7fbff',
    water: '#8ccdf2',
    park: '#c9efd6',
    grounds: '#fff0b3',
    groundsEdge: '#16324f',
    shore: '#16324f',
    minorRoad: '#cddff0',
    majorRoad: '#ffffff',
    lineOutline: '#16324f',
    lineState: '#16324f',
    lineOutlinePhone: '#16324f',
    lineStatePhone: '#16324f',
    dot: '#ffffff',
    dotRing: '#16324f',
    veil: '247 251 255',
    shadow: '22 50 79',
    sheen: '255 255 255',
    halo: '#f7fbff',
    amb: 'none',
  },
  glow: { mode: 'flat', outline: '#12283e', outlineWidth: 1.5, burst: true },
  lineWidths: { outline: 3, state: 2 },
  roadScale: 1.6,
  labelHalo: 'rgb(247 251 255 / 0.6)',
  toon: {
    edgeWidth: 1.75,
    // Shallow water: a flat step lighter than the sea, along every coast.
    coastBand: '#bfe5f9',
    parkEdge: '#16324f',
    // A park's shade: a flat step darker than the park.
    parkShade: '#8fd3a8',
    roadCasing: '#16324f',
    casingWidth: 1,
  },
};

/** The family Snowball sets its words in (snowball.ts has its faces). */
export const SNOWBALL_FONT = 'Fredoka Variable';

export const UNRELEASED_THEMES: Readonly<Record<UnreleasedThemeId, Theme>> = {
  snowball: SNOWBALL,
};
