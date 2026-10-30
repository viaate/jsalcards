/**
 * The whole-app themes: each one is the page's design tokens, the basemap's
 * colors and the map's treatment of the schools' lights, switched together
 * (engine.ts). Midnight is the page as index.html draws it, so it overrides
 * nothing; every other theme is a block of custom properties on
 * :root[data-theme], plus, for a toon theme, rules of its own.
 *
 * The approved looks are the game mockups' (branch wip-game-mockups,
 * web/mockups/game/tools/themes.mjs): Midnight and Daylight free, Aurora,
 * Ember, Glacier and Dusk in the shop, Bronze, Silver and Gold earned at a
 * season's end. A theme still waiting for the owner's yes is in
 * unreleased.ts (THEMES_UNRELEASED). Every theme keeps the four statuses readable on
 * its grounds (tests/contrast.test.ts).
 *
 * This module loads with the engine, after the first paint: the page's first
 * script carries none of it.
 */

import { UNRELEASED_IDS, UNRELEASED_THEMES, type UnreleasedThemeId } from './unreleased.ts';

export type { UnreleasedThemeId } from './unreleased.ts';

/**
 * Whether this build's scripts carry the unreleased themes (unreleased.ts)
 * at all: vite.config.ts says so (__UNRELEASED_THEMES__), true only where
 * VITE_THEMES_PREVIEW names one, so a default build's scripts hold none of
 * them, not even a name: they leave them out as code never run. The build's
 * own tools and the tests, which run with no such word, carry them.
 */
declare const __UNRELEASED_THEMES__: boolean | undefined;
const UNRELEASED_BUILT: boolean =
  typeof __UNRELEASED_THEMES__ === 'boolean' ? __UNRELEASED_THEMES__ : true;

const RELEASED = [
  'midnight',
  'daylight',
  'aurora',
  'ember',
  'glacier',
  'dusk',
  'bronze',
  'silver',
  'gold',
] as const;

/** Every theme's id, whether this build carries it or not. */
export type ThemeId = (typeof RELEASED)[number] | UnreleasedThemeId;

/** The themes this build carries, in the shop's order: an unreleased one last, where built. */
export const THEME_IDS: readonly ThemeId[] = UNRELEASED_BUILT
  ? [...RELEASED, ...UNRELEASED_IDS]
  : RELEASED;

/** The unreleased themes this build carries. */
export const THEMES_UNRELEASED: ReadonlySet<ThemeId> = new Set<ThemeId>(
  UNRELEASED_BUILT ? UNRELEASED_IDS : [],
);

/** The theme a first visit gets, and the one the page's own CSS draws. */
export const DEFAULT_THEME: ThemeId = 'midnight';

/** How a theme is had: free to everyone, bought in the shop, or earned at a season's end. */
export type ThemeAccess = 'free' | 'shop' | 'trophy';

/**
 * How the map draws a lit school: 'glow', today's soft light (screened onto a
 * dark ground); 'flat', the same light cel shaded in flat tones laid over the
 * ground, edged in `outline` (a light ground, where light added would wash
 * out). Up close both draw each school's glyph, ringed in `outline`.
 */
export interface GlowLook {
  readonly mode: 'glow' | 'flat';
  /** The ring around each glyph (and a flat theme's light), and its width in CSS px (0: none). */
  readonly outline: string;
  readonly outlineWidth: number;
  /** A closed school's bold ring around its dot (flat only). */
  readonly burst: boolean;
}

/** One theme's colors. Map colors left out are Midnight's (map/basemap/style.ts). */
export interface ThemeTokens {
  readonly bg: string;
  readonly surface1: string;
  readonly surface2: string;
  readonly border1: string;
  readonly border2: string;
  readonly text1: string;
  readonly text2: string;
  readonly text3: string;
  readonly accent: string;
  readonly closed: string;
  readonly delayed: string;
  readonly remote: string;
  readonly early: string;
  /** An open school's dot, and the chance's number. */
  readonly open: string;
  readonly chance: string;
  /** Text and marks on a closed school's fill. */
  readonly onClosed: string;
  /**
   * The map's names and its dim names (water, parks, neighbourhoods, side
   * streets), where text-2 and text-3 do not read at AA on every ground the
   * map sets them on; text-2 and text-3 where left out.
   */
  readonly mapLabel?: string;
  readonly mapLabelDim?: string;
  /** The national view's land, and the street tiles' ground (the ground beyond it is bg). */
  readonly land: string;
  readonly ground: string;
  readonly water: string;
  readonly park: string;
  /** School grounds up close, and their edge. */
  readonly grounds: string;
  readonly groundsEdge: string;
  /** Lake and river shores. */
  readonly shore: string;
  /** The least road and the greatest: the tiers between step evenly. */
  readonly minorRoad: string;
  readonly majorRoad: string;
  /** Coasts and borders, and state lines; on a phone each a step clearer. */
  readonly lineOutline: string;
  readonly lineState: string;
  readonly lineOutlinePhone: string;
  readonly lineStatePhone: string;
  /** A school's quiet dot before it lights, and its ring. */
  readonly dot: string;
  readonly dotRing: string;
  /** Shades over the map and under cards (RGB triples), and the halo behind words on the map. */
  readonly veil: string;
  readonly shadow: string;
  readonly sheen: string;
  readonly halo: string;
  /** The theme's ambient light over the ground, a CSS background, or 'none'. */
  readonly amb: string;
}

export interface Theme {
  readonly id: ThemeId;
  readonly scheme: 'dark' | 'light';
  readonly access: ThemeAccess;
  readonly tokens: ThemeTokens;
  readonly glow: GlowLook;
  /** Line widths in CSS pixels for the coasts and the state lines, or null for the hairline. */
  readonly lineWidths: { readonly outline: number; readonly state: number } | null;
  /** The road widths' scale. */
  readonly roadScale: number;
  /**
   * The halo behind the street tiles' labels, as CSS color; the ground where
   * left out. A flat theme's is see-through, so a label never cuts a mark.
   */
  readonly labelHalo?: string;
  /** A toon map's own touches (map/basemap/style.ts MapTouches) and its ink edges' width. */
  readonly toon?: {
    readonly edgeWidth: number;
    readonly coastBand: string;
    readonly parkEdge: string;
    readonly parkShade: string;
    readonly roadCasing: string;
    readonly casingWidth: number;
  };
}

const DARK_STATUS = {
  closed: '#7fd4ff',
  delayed: '#ffc46b',
  remote: '#b79cff',
  early: '#6bffb0',
  onClosed: '#000',
} as const;

const GLOW: GlowLook = { mode: 'glow', outline: '#000000', outlineWidth: 0, burst: false };

/** A dark theme from the mockups' tokens: the parts the page draws as Midnight does, recolored. */
function dark(
  id: ThemeId,
  access: ThemeAccess,
  t: Omit<
    ThemeTokens,
    | keyof typeof DARK_STATUS
    | 'ground'
    | 'groundsEdge'
    | 'lineOutline'
    | 'lineState'
    | 'lineOutlinePhone'
    | 'lineStatePhone'
    | 'dot'
    | 'dotRing'
    | 'veil'
    | 'shadow'
    | 'sheen'
    | 'halo'
  >,
): Theme {
  return {
    id,
    scheme: 'dark',
    access,
    tokens: {
      ...DARK_STATUS,
      ...t,
      ground: t.land,
      groundsEdge: t.shore,
      lineOutline: t.text3,
      lineState: t.border2,
      lineOutlinePhone: mix(t.text3, t.text2, 0.45),
      lineStatePhone: mix(t.border2, t.text3, 0.4),
      dot: t.text1,
      dotRing: t.land,
      veil: rgbTriple(t.bg),
      shadow: '0 0 0',
      sheen: '255 255 255',
      halo: t.bg,
    },
    // Each glyph up close keyed out of its ground by a ring of the land's color, so a mark on a
    // bright road still reads (tests/contrast.test.ts); Midnight's glyphs have none.
    glow: { ...GLOW, outline: t.land, outlineWidth: 1 },
    lineWidths: null,
    roadScale: 1,
  };
}

/** Midnight: the page as index.html draws it. Listed for previews and the contrast checks. */
const MIDNIGHT: Theme = {
  id: 'midnight',
  scheme: 'dark',
  access: 'free',
  tokens: {
    ...DARK_STATUS,
    bg: '#000000',
    surface1: '#0a0a0a',
    surface2: '#111111',
    border1: '#1f1f1f',
    border2: '#2a2a2a',
    text1: '#f5f5f5',
    text2: '#a3a3a3',
    text3: '#6b6b6b',
    accent: '#f5f5f5',
    open: '#6b6b6b',
    chance: '#f5f5f5',
    land: '#000000',
    ground: '#000000',
    water: '#0c0c0c',
    park: '#0d0d0d',
    grounds: '#0f0f0f',
    groundsEdge: '#262626',
    shore: '#3a3a3a',
    minorRoad: '#1a1a1a',
    majorRoad: '#454545',
    lineOutline: '#6b6b6b',
    lineState: '#2a2a2a',
    lineOutlinePhone: '#8f8f8f',
    lineStatePhone: '#4d4d4d',
    dot: '#f5f5f5',
    dotRing: '#000000',
    veil: '0 0 0',
    shadow: '0 0 0',
    sheen: '255 255 255',
    halo: '#000000',
    amb: 'none',
  },
  glow: GLOW,
  lineWidths: null,
  roadScale: 1,
};

const DAYLIGHT: Theme = {
  id: 'daylight',
  scheme: 'light',
  access: 'free',
  tokens: {
    bg: '#e9ecef',
    surface1: '#ffffff',
    surface2: '#f2f4f6',
    border1: '#e3e6ea',
    border2: '#d2d6dc',
    text1: '#0d1014',
    text2: '#4a515a',
    text3: '#68707a',
    accent: '#0d1014',
    closed: '#0b6aa6',
    delayed: '#9a5600',
    remote: '#6447c9',
    early: '#08794b',
    open: '#717881',
    chance: '#0d1014',
    onClosed: '#ffffff',
    mapLabel: '#33383f',
    mapLabelDim: '#383e45',
    land: '#eef0f2',
    ground: '#eef0f2',
    water: '#d7e0e9',
    park: '#e4e9e2',
    grounds: '#e2e5e9',
    groundsEdge: '#c3ccd6',
    shore: '#aab1ba',
    minorRoad: '#dfe2e6',
    majorRoad: '#aab1ba',
    lineOutline: '#7d858f',
    lineState: '#c3ccd6',
    lineOutlinePhone: '#68707a',
    lineStatePhone: '#aab1ba',
    dot: '#4a515a',
    dotRing: '#eef0f2',
    veil: '233 236 239',
    shadow: '40 48 58',
    sheen: '255 255 255',
    halo: '#eef0f2',
    amb: 'linear-gradient(180deg, rgb(255 255 255 / 0.7), transparent 40%)',
  },
  glow: { mode: 'flat', outline: '#ffffff', outlineWidth: 1, burst: false },
  lineWidths: null,
  roadScale: 1,
  labelHalo: 'rgb(238 240 242 / 0.6)',
};

/** Every theme this build carries: each released one, and an unreleased one only where built. */
export const THEMES: Readonly<
  Record<Exclude<ThemeId, UnreleasedThemeId>, Theme> & Partial<Record<UnreleasedThemeId, Theme>>
> = Object.freeze({
  midnight: MIDNIGHT,
  daylight: DAYLIGHT,
  aurora: dark('aurora', 'shop', {
    bg: '#02080a',
    surface1: '#08181b',
    surface2: '#0d2226',
    border1: '#163135',
    border2: '#204147',
    text1: '#eefaf6',
    text2: '#a4c4bf',
    text3: '#7a9c97',
    accent: '#9ff5d4',
    open: '#7fa6a0',
    chance: '#eefaf6',
    land: '#02090b',
    water: '#041420',
    park: '#05140f',
    grounds: '#061317',
    shore: '#18404a',
    minorRoad: '#0b1d22',
    majorRoad: '#235a63',
    amb: 'radial-gradient(62% 26% at 26% 13%, rgb(70 240 175 / 0.27), transparent 72%), radial-gradient(58% 24% at 74% 22%, rgb(155 105 255 / 0.32), transparent 74%), linear-gradient(176deg, rgb(70 240 175 / 0.08) 0%, transparent 30%), linear-gradient(176deg, transparent 6%, rgb(155 105 255 / 0.08) 24%, transparent 38%)',
  }),
  ember: dark('ember', 'shop', {
    bg: '#0a0503',
    surface1: '#1a0e09',
    surface2: '#24140d',
    border1: '#3a2117',
    border2: '#4d2d1f',
    text1: '#fff3ec',
    text2: '#d4ae9d',
    text3: '#a88472',
    accent: '#ffc2a3',
    open: '#a08a80',
    chance: '#fff3ec',
    land: '#0a0503',
    water: '#100806',
    park: '#140b06',
    grounds: '#160b07',
    shore: '#43251a',
    minorRoad: '#25130d',
    majorRoad: '#7a3f25',
    amb: 'radial-gradient(95% 40% at 50% 106%, rgb(255 95 30 / 0.3), transparent 76%), linear-gradient(0deg, rgb(255 120 50 / 0.11), transparent 34%)',
  }),
  glacier: dark('glacier', 'shop', {
    bg: '#0a1520',
    surface1: '#112331',
    surface2: '#182e3f',
    border1: '#233a4d',
    border2: '#30495e',
    text1: '#f3f9fe',
    text2: '#adc5d8',
    text3: '#86a2b8',
    accent: '#e2f2ff',
    open: '#8aa2b5',
    chance: '#f3f9fe',
    land: '#0c1823',
    water: '#0e2436',
    park: '#0f1e29',
    grounds: '#112130',
    shore: '#4a6a85',
    minorRoad: '#1b2f40',
    majorRoad: '#8fb1cf',
    amb: 'linear-gradient(180deg, rgb(215 238 255 / 0.15), rgb(215 238 255 / 0.04) 45%, transparent 70%), radial-gradient(70% 45% at 82% 0%, rgb(255 255 255 / 0.09), transparent 70%)',
  }),
  dusk: dark('dusk', 'shop', {
    bg: '#0a0814',
    surface1: '#161129',
    surface2: '#1f1838',
    border1: '#2d2449',
    border2: '#3c305c',
    text1: '#f8f2fc',
    text2: '#c0b3d4',
    text3: '#9586ab',
    accent: '#e2c6ff',
    open: '#9387ab',
    chance: '#f8f2fc',
    land: '#0b0918',
    water: '#0e0b20',
    park: '#110d1d',
    grounds: '#130f22',
    shore: '#3f3160',
    minorRoad: '#1c1731',
    majorRoad: '#5a4785',
    amb: 'linear-gradient(180deg, rgb(170 95 245 / 0.34) 0%, rgb(115 75 215 / 0.14) 34%, rgb(45 55 150 / 0.08) 62%, transparent 80%), linear-gradient(0deg, rgb(25 45 140 / 0.36), transparent 40%)',
  }),
  bronze: dark('bronze', 'trophy', {
    bg: '#0a0705',
    surface1: '#1a120c',
    surface2: '#241911',
    border1: '#3a2a1d',
    border2: '#4b3726',
    text1: '#fbf2ea',
    text2: '#cdb39d',
    text3: '#a08670',
    accent: '#e0a576',
    open: '#a08c7a',
    chance: '#fbf2ea',
    land: '#0a0705',
    water: '#0f0b08',
    park: '#120d08',
    grounds: '#150f0a',
    shore: '#4a3626',
    minorRoad: '#22180f',
    majorRoad: '#6e5036',
    amb: 'radial-gradient(80% 60% at 0% 0%, rgb(220 150 95 / 0.32), transparent 72%), radial-gradient(60% 40% at 100% 100%, rgb(180 110 60 / 0.16), transparent 70%)',
  }),
  silver: dark('silver', 'trophy', {
    bg: '#07080a',
    surface1: '#15181c',
    surface2: '#1d2126',
    border1: '#2c3138',
    border2: '#3a4048',
    text1: '#f6f8fa',
    text2: '#bcc3cb',
    text3: '#8f97a1',
    accent: '#e6ebf1',
    open: '#939ba5',
    chance: '#f6f8fa',
    land: '#08090b',
    water: '#0d1014',
    park: '#0e1013',
    grounds: '#111317',
    shore: '#3b4048',
    minorRoad: '#1b1e23',
    majorRoad: '#5d646e',
    amb: 'linear-gradient(118deg, transparent 18%, rgb(230 236 245 / 0.17) 34%, rgb(230 236 245 / 0.05) 44%, transparent 50%, rgb(230 236 245 / 0.11) 62%, transparent 72%), radial-gradient(70% 50% at 50% 0%, rgb(220 228 240 / 0.1), transparent 70%)',
  }),
  gold: dark('gold', 'trophy', {
    bg: '#090702',
    surface1: '#1a1508',
    surface2: '#241d0c',
    border1: '#3a3014',
    border2: '#4b3e1a',
    text1: '#fff8e8',
    text2: '#d4c294',
    text3: '#a6955f',
    accent: '#ecd283',
    open: '#a29676',
    chance: '#fff8e8',
    land: '#090702',
    water: '#0f0c05',
    park: '#110e05',
    grounds: '#141006',
    shore: '#4a3d1a',
    minorRoad: '#221c0b',
    majorRoad: '#6e5a26',
    amb: 'radial-gradient(58% 50% at 50% -4%, rgb(245 205 100 / 0.28), transparent 76%), radial-gradient(85% 30% at 50% 106%, rgb(245 205 100 / 0.12), transparent 70%)',
  }),
  ...(UNRELEASED_BUILT ? UNRELEASED_THEMES : {}),
});

/** A theme this build carries; for the tools and tests, which carry every one. */
export function themeOf(id: ThemeId): Theme {
  const theme = THEMES[id];
  if (theme === undefined) throw new Error(`This build does not carry the theme ${id}`);
  return theme;
}

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

// Colors --------------------------------------------------------------------------------

function channels(hex: string): [number, number, number] {
  let digits = hex.replace('#', '');
  if (digits.length === 3) digits = digits.replace(/./g, (d) => d + d);
  const value = Number.parseInt(digits, 16);
  if (digits.length !== 6 || Number.isNaN(value)) throw new Error(`Not a hex color: ${hex}`);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** `from` moved `share` of the way to `to`, as #rrggbb. */
export function mix(from: string, to: string, share: number): string {
  const a = channels(from);
  const b = channels(to);
  return `#${a
    .map((c, i) =>
      Math.round(c + ((b[i] ?? c) - c) * share)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')}`;
}

/** A hex color as the "r g b" triple CSS's rgb() takes before its alpha. */
export function rgbTriple(hex: string): string {
  return channels(hex).join(' ');
}

/** WCAG 2 relative luminance of a hex color. */
export function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((c) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio of two hex colors, 1 to 21. */
export function contrast(a: string, b: string): number {
  const x = luminance(a);
  const y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/**
 * The six road tiers' tones, least to greatest, each with its close-up tone:
 * evenly from the least road to the greatest, each a step toward the text up
 * close (map/basemap/style.ts ROAD_TIERS has Midnight's own).
 */
export function roadTiers(t: ThemeTokens): readonly (readonly [string, string])[] {
  const shares = [0, 0.22, 0.4, 0.56, 0.72, 1];
  return shares.map((share) => {
    const tone = mix(t.minorRoad, t.majorRoad, share);
    return [tone, mix(tone, t.text3, 0.12)] as const;
  });
}
