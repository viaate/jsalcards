/**
 * A theme as CSS: its tokens as custom properties on :root[data-theme=…],
 * which outrank the page's own :root and its phone rules, and the rules a
 * theme adds of its own. Midnight is the page's CSS itself and adds nothing.
 *
 * The map reads the same properties (map/basemap/index.ts look, and
 * map/glow-mount.ts glowLook), so the page and the map change together.
 */
import { mix, roadTiers, type Theme } from './themes.ts';

/** The phone rules' media query in index.html, where the lines are a step clearer. */
const PHONE = '(max-width: 719px), (max-height: 519px)';

/** The custom properties a theme sets, in order. */
export function themeProperties(theme: Theme): readonly (readonly [string, string])[] {
  const t = theme.tokens;
  const props: [string, string][] = [
    ['--bg', t.bg],
    ['--surface-1', t.surface1],
    ['--surface-2', t.surface2],
    ['--border-1', t.border1],
    ['--border-2', t.border2],
    ['--text-1', t.text1],
    ['--text-2', t.text2],
    ['--text-3', t.text3],
    ['--accent', t.accent],
    ['--status-closed', t.closed],
    ['--status-delayed', t.delayed],
    ['--status-remote', t.remote],
    ['--status-early-dismissal', t.early],
    ['--status-open', t.open],
    ['--status-chance', t.chance],
    ['--on-closed', t.onClosed],
    ['--veil', t.veil],
    ['--shadow', t.shadow],
    ['--sheen', t.sheen],
    ['--halo', t.halo],
    ['--amb', t.amb],
    ['--land', t.land],
    ['--line-outline', t.lineOutline],
    ['--line-state', t.lineState],
    ['--map-label', t.mapLabel ?? t.text2],
    ['--map-label-dim', t.mapLabelDim ?? t.text3],
    ['--map-ground', t.ground],
    ['--map-water', t.water],
    ['--map-park', t.park],
    ['--map-grounds', t.grounds],
    ['--map-grounds-edge', t.groundsEdge],
    ['--map-shore', t.shore],
    ['--map-building-close', mix(t.surface2, t.text3, 0.06)],
    ['--map-building-edge-close', mix(t.border1, t.text3, 0.1)],
    [
      '--map-roads',
      roadTiers(t)
        .map(([tone, close]) => `${tone} ${close}`)
        .join(','),
    ],
    ['--map-road-scale', String(theme.roadScale)],
    ['--map-dot', t.dot],
    ['--map-dot-ring', t.dotRing],
    // On a light ground the dust is the dim text's color, the darker of speck and map kept.
    ...(theme.scheme === 'light'
      ? ([
          ['--map-dust', t.text2],
          ['--map-dust-blend', 'min'],
        ] as [string, string][])
      : []),
    ['--glow-mode', theme.glow.mode],
    ['--glow-outline', theme.glow.outline],
    ['--glow-outline-width', String(theme.glow.outlineWidth)],
    ['--glow-burst', theme.glow.burst ? 'on' : 'off'],
  ];
  if (theme.labelHalo !== undefined) props.push(['--map-label-halo', theme.labelHalo]);
  if (theme.toon !== undefined) {
    const toon = theme.toon;
    props.push(
      ['--map-edge-width', `${String(toon.edgeWidth)}px`],
      ['--map-coast-band', toon.coastBand],
      ['--map-park-edge', toon.parkEdge],
      ['--map-park-shade', toon.parkShade],
      ['--map-road-casing', toon.roadCasing],
      ['--map-casing-width', `${String(toon.casingWidth)}px`],
    );
  }
  if (theme.lineWidths !== null) {
    props.push(['--map-outline-width', `${String(theme.lineWidths.outline)}px`]);
    props.push(['--map-state-width', `${String(theme.lineWidths.state)}px`]);
  }
  return props;
}

const block = (selector: string, props: readonly (readonly [string, string])[]): string =>
  `${selector}{${props.map(([name, value]) => `${name}:${value}`).join(';')}}`;

/**
 * A theme's CSS as single rules, for a style sheet's insertRule: none for
 * Midnight. `extra` is the theme's own rules (snowball.ts), already scoped to it.
 */
export function themeRules(theme: Theme, extra: readonly string[] = []): readonly string[] {
  if (theme.id === 'midnight') return [];
  const root = `:root[data-theme='${theme.id}']`;
  const t = theme.tokens;
  const rules = [
    block(root, [...themeProperties(theme), ['color-scheme', theme.scheme]]),
    `@media ${PHONE}{${block(root, [
      ['--line-outline', t.lineOutlinePhone],
      ['--line-state', t.lineStatePhone],
    ])}}`,
  ];
  // The theme's ambient light over the ground, under the page's controls.
  if (t.amb !== 'none') {
    rules.push(
      `${root} .map::after{position:absolute;inset:0;z-index:1;pointer-events:none;content:'';background:var(--amb);mix-blend-mode:screen}`,
    );
  }
  // On a light ground the veils at the top and bottom edges are fainter and shorter: a full
  // veil of light would wash the marks under it into paler ones, which read as another status.
  if (theme.scheme === 'light') {
    rules.push(
      `${root} .stage::before{background:linear-gradient(rgb(var(--veil) / 0.3),rgb(var(--veil) / 0.12) 35%,rgb(var(--veil) / 0) 70%)}`,
      `${root} .stage::after{background:linear-gradient(rgb(var(--veil) / 0),rgb(var(--veil) / 0.12) 65%,rgb(var(--veil) / 0.3))}`,
      // With the veil that faint, the words at the top read on a halo of their own, solid enough
      // that a dark line of the map under them never runs into their letters, and the update
      // time on a veil of its own, as the key has.
      `${root} .wordmark,${root} .updated{text-shadow:0 0 1px var(--halo),0 0 2px var(--halo),0 0 3px var(--halo),0 0 4px var(--halo),0 0 12px var(--halo)}`,
      `${root} .updated::before{position:absolute;inset:calc(50% - 12px) -6px;z-index:-1;pointer-events:none;content:'';background:rgb(var(--veil) / 0.85);border-radius:12px;box-shadow:0 0 10px 6px rgb(var(--veil) / 0.85)}`,
    );
  }
  // Flat statuses on a light ground: the key's marks as the map draws them, without the glow.
  if (theme.glow.mode === 'flat') {
    rules.push(
      `${root} .glyph{box-shadow:none}`,
      `${root} .glyph.is-delayed,${root} .glyph.is-early-dismissal{box-shadow:inset 0 0 0 1.5px currentcolor}`,
      `${root} .glyph.is-delayed{color:var(--status-delayed)}`,
      `${root} .glyph.is-early-dismissal{color:var(--status-early-dismissal)}`,
    );
  }
  return [...rules, ...extra];
}

/** The same CSS as one text, as the device keeps it for index.html: '' for Midnight. */
export function themeCss(theme: Theme, extra: readonly string[] = []): string {
  return themeRules(theme, extra).join('');
}
