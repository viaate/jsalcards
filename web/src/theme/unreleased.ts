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
 * Snowball, the cel-shaded cartoon theme, at night: a deep navy sea and land
 * in flat cel steps, bold moonlit coasts, and the schools' lights glowing on
 * it as they do on Midnight, through Midnight's own glow and in Midnight's
 * status colors (themes.ts DARK_STATUS and GLOW), so a closed school is a
 * soft light-blue light and a storm a soft band of light, never a wall of
 * marks. Cards and buttons keep the cartoon's ink outlines, hard drop
 * offsets, round face and yellow accent (snowball.ts). Its own palette and
 * its own name; no game's colors, art or type.
 */
const SNOWBALL: Theme = {
  id: 'snowball',
  scheme: 'dark',
  access: 'shop',
  tokens: {
    bg: '#0a1834',
    surface1: '#173263',
    surface2: '#1d3c73',
    border1: '#2c5291',
    border2: '#040c1d',
    text1: '#f4f9ff',
    text2: '#c0d6f0',
    text3: '#97b3d6',
    accent: '#ffc93c',
    // Midnight's statuses (themes.ts DARK_STATUS), with ink on a closed school's light blue.
    closed: '#7fd4ff',
    delayed: '#ffc46b',
    remote: '#b79cff',
    early: '#6bffb0',
    onClosed: '#071a33',
    open: '#a3bbd9',
    chance: '#f4f9ff',
    // The dim names, a step lighter than text-3, so a name inside school grounds reads at AA.
    mapLabelDim: '#a6c0e0',
    land: '#12284f',
    ground: '#12284f',
    water: '#0a1834',
    park: '#14405a',
    grounds: '#26457e',
    groundsEdge: '#a9d3f7',
    shore: '#a9d3f7',
    minorRoad: '#1d3a6b',
    majorRoad: '#2a4879',
    lineOutline: '#a9d3f7',
    lineState: '#3f679f',
    lineOutlinePhone: '#bfe0fb',
    lineStatePhone: '#5079b3',
    dot: '#dcebfb',
    dotRing: '#12284f',
    veil: '10 24 52',
    shadow: '4 12 29',
    sheen: '255 255 255',
    halo: '#0f2349',
    amb: 'none',
  },
  // Midnight's own glow (themes.ts GLOW): the lights screened onto the night, with no ring and no
  // burst, so no mark is ever ringed in a dark line. The roads stay dim enough that every glyph
  // reads on them up close without one (tests/contrast.test.ts).
  glow: { mode: 'glow', outline: '#000000', outlineWidth: 0, burst: false },
  lineWidths: { outline: 2.5, state: 1.25 },
  roadScale: 1.2,
};

/** The family Snowball sets its words in (snowball.ts has its faces). */
export const SNOWBALL_FONT = 'Fredoka Variable';

export const UNRELEASED_THEMES: Readonly<Record<UnreleasedThemeId, Theme>> = {
  snowball: SNOWBALL,
};
