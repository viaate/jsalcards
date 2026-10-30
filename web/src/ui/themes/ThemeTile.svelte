<!--
  A theme's tile, as the shop shows it (the approved mockup, page 6): the
  tile drawn in its own theme, a picture of a metro on a snow morning with a
  corner of a school's panel and the four marks over it, and under it the
  theme's name, what the shop says beside it (`badge`) and its button. The
  shop's buying and owning are the game's: it hands the tile its badge and
  its button's job, and the engine puts the theme on (theme/engine.ts).
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  import { themesCopy } from '../../copy-themes';
  import { themeProperties } from '../../theme/css';
  import { themeAvailable } from '../../theme/engine';
  import { readPageThemes } from '../../theme/page';
  import type { Theme } from '../../theme/themes';
  import { SNOWBALL_FONT } from '../../theme/unreleased';
  import {
    PREVIEW_BURST_HALF_WIDTH,
    PREVIEW_BURST_RADIUS,
    PREVIEW_HEIGHT,
    PREVIEW_MARKS,
    PREVIEW_RIVER,
    PREVIEW_ROADS,
    PREVIEW_WIDTH,
    clearMarks,
  } from './preview';

  interface Props {
    theme: Theme;
    /** What the shop says beside the name: a price, Free, Owned. */
    badge?: Snippet;
    /** The button: try the theme, use it, or none while it is in use. */
    action?: 'try' | 'use' | 'in-use' | null;
    onaction?: () => void;
  }

  let { theme, badge, action = 'try', onaction }: Props = $props();

  const FONT_STYLE_ID = 'sl-theme-tile-fonts';
  const toon = $derived(theme.id === 'snowball');
  const flat = $derived(theme.glow.mode === 'flat');
  const t = $derived(theme.tokens);
  const vars = $derived(
    [
      ...themeProperties(theme),
      ...(toon
        ? [['--font-sans', `'${SNOWBALL_FONT}', 'Geist Variable', system-ui, sans-serif`]]
        : []),
    ]
      .map(([name, value]) => `${name}:${value}`)
      .join(';'),
  );
  const colors = $derived([t.closed, t.delayed, t.remote, t.early, t.open] as const);
  const roads = $derived([
    { color: theme.tokens.minorRoad, width: 0.8 * theme.roadScale },
    {
      color: mixHalf(theme.tokens.minorRoad, theme.tokens.majorRoad),
      width: 1.5 * theme.roadScale,
    },
    { color: theme.tokens.majorRoad, width: 2.4 * theme.roadScale },
  ]);
  const ink = $derived(theme.glow.outline);
  const ring = $derived(theme.glow.outlineWidth);
  /** A theme this build may not show draws no tile: the shop never offers it (theme/engine.ts). */
  const shown = $derived(themeAvailable(theme.id));
  /** The picture's width and the corner card's size, as laid out. */
  let pictureWidth = $state(PREVIEW_WIDTH);
  let cardWidth = $state(0);
  let cardHeight = $state(0);
  /** A flat theme's crisp marks, each whole: none cut by the edges or under the corner card. */
  const marks = $derived(
    flat
      ? clearMarks(
          PREVIEW_MARKS,
          {
            width: pictureWidth,
            card: { left: 8, bottom: 8, width: cardWidth, height: cardHeight },
          },
          3 * (theme.glow.burst ? PREVIEW_BURST_RADIUS + PREVIEW_BURST_HALF_WIDTH : 1) + ring + 1,
        )
      : PREVIEW_MARKS,
  );

  function mixHalf(a: string, b: string): string {
    const channel = (hex: string, i: number): number =>
      Number.parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
    return `#${[0, 1, 2]
      .map((i) =>
        Math.round((channel(a, i) + channel(b, i)) / 2)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')}`;
  }

  $effect(() => {
    // The cartoon theme's face, once, for its tile's words.
    if (!toon || !shown || document.getElementById(FONT_STYLE_ID) !== null) return;
    const style = document.createElement('style');
    style.id = FONT_STYLE_ID;
    document.head.append(style);
    // As the page carries Snowball (theme/page.ts): only a build that may show it has its face.
    const rules = readPageThemes(document).snowball?.rules ?? [];
    for (const face of rules.filter((rule) => rule.startsWith('@font-face')))
      style.sheet?.insertRule(face, style.sheet.cssRules.length);
  });

  const filterId = $derived(`tile-glow-${theme.id}`);
</script>

{#if shown}
  <div
    class="tile"
    class:is-toon={toon}
    class:is-flat={flat}
    style={vars}
    data-theme-tile={theme.id}
  >
    <div class="pv" bind:clientWidth={pictureWidth}>
      <svg
        class="map"
        viewBox={`0 0 ${String(PREVIEW_WIDTH)} ${String(PREVIEW_HEIGHT)}`}
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
      >
        <defs>
          <filter id={filterId} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="3.2" />
          </filter>
        </defs>
        <rect width={PREVIEW_WIDTH} height={PREVIEW_HEIGHT} fill={t.ground} />
        <path d={PREVIEW_RIVER} fill={t.water} stroke={t.shore} stroke-width={toon ? 1.6 : 0.6} />
        {#each PREVIEW_ROADS as road, i (i)}
          <path
            d={road.d}
            fill="none"
            stroke={roads[road.tier]?.color}
            stroke-width={roads[road.tier]?.width}
            stroke-linecap="round"
          />
        {/each}
        {#if !flat}
          <g filter={`url(#${filterId})`} opacity="0.7">
            {#each PREVIEW_MARKS as mark, i (i)}
              {#if mark.status !== 4}
                <circle cx={mark.x} cy={mark.y} r="5" fill={colors[mark.status]} />
              {/if}
            {/each}
          </g>
        {/if}
        {#each marks as mark, i (i)}
          {@const color = colors[mark.status]}
          {@const r = flat ? 3 : 2.2}
          {#if mark.status === 4}
            <circle cx={mark.x} cy={mark.y} r="1.6" fill={color} opacity="0.85" />
          {:else if mark.status === 0}
            {#if theme.glow.burst}
              <circle
                cx={mark.x}
                cy={mark.y}
                r={r * PREVIEW_BURST_RADIUS}
                fill="none"
                stroke={ink}
                stroke-width={r * 2 * PREVIEW_BURST_HALF_WIDTH + 2 * ring}
              />
              <circle
                cx={mark.x}
                cy={mark.y}
                r={r * PREVIEW_BURST_RADIUS}
                fill="none"
                stroke={color}
                stroke-width={r * 2 * PREVIEW_BURST_HALF_WIDTH}
              />
            {/if}
            <circle
              cx={mark.x}
              cy={mark.y}
              {r}
              fill={color}
              stroke={ring > 0 ? ink : 'none'}
              stroke-width={ring}
            />
          {:else if mark.status === 1}
            {#if ring > 0}
              <circle
                cx={mark.x}
                cy={mark.y}
                r={r - 0.5}
                fill="none"
                stroke={ink}
                stroke-width={1.4 + 2 * ring}
              />
            {/if}
            <circle
              cx={mark.x}
              cy={mark.y}
              r={r - 0.5}
              fill="none"
              stroke={color}
              stroke-width="1.4"
            />
          {:else if mark.status === 2}
            <rect
              x={mark.x - r * 0.85}
              y={mark.y - r * 0.85}
              width={r * 1.7}
              height={r * 1.7}
              transform={`rotate(45 ${String(mark.x)} ${String(mark.y)})`}
              fill={color}
              stroke={ring > 0 ? ink : 'none'}
              stroke-width={ring}
            />
          {:else}
            <circle
              cx={mark.x}
              cy={mark.y}
              r={r - 0.5}
              fill="none"
              stroke={ring > 0 ? ink : color}
              stroke-width={1.4 + 2 * ring}
            />
            <circle
              cx={mark.x}
              cy={mark.y}
              r={r - 0.5}
              fill="none"
              stroke={color}
              stroke-width="1.4"
            />
            <path
              d={`M${String(mark.x)} ${String(mark.y - r)}A${String(r)} ${String(r)} 0 0 0 ${String(mark.x)} ${String(mark.y + r)}Z`}
              fill={color}
            />
          {/if}
        {/each}
      </svg>
      {#if t.amb !== 'none'}
        <span class="amb"></span>
      {/if}
      <div class="mini" bind:clientWidth={cardWidth} bind:clientHeight={cardHeight}>
        <b>{themesCopy.preview.chance}<small>{themesCopy.preview.percent}</small></b>
        <span>{themesCopy.preview.status}</span>
      </div>
      <div class="sw" role="img" aria-label={themesCopy.preview.marks}>
        <i class="c"></i><i class="d"></i><i class="o"></i><i class="h"></i>
      </div>
    </div>
    <div class="meta">
      <div class="nm">
        <b>{themesCopy.names[theme.id]}</b>
        {@render badge?.()}
      </div>
      {#if action !== null}
        <button
          class="try"
          class:on={action === 'in-use'}
          disabled={action === 'in-use'}
          onclick={() => onaction?.()}
        >
          {action === 'in-use'
            ? themesCopy.action.inUse
            : action === 'use'
              ? themesCopy.action.use
              : themesCopy.action.try}
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .tile {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-family: var(--font-sans);
    color: var(--text-1);
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: 16px;
  }

  .pv {
    position: relative;
    height: 132px;
    overflow: hidden;
    background: var(--land);
    border-bottom: 1px solid var(--border-2);
  }

  .map {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  .amb {
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background: var(--amb);
    mix-blend-mode: screen;
  }

  .mini {
    position: absolute;
    left: 8px;
    bottom: 8px;
    z-index: 2;
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 76px;
    padding: 6px 7px 7px;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 9px;
  }

  .mini b {
    font: 600 17px/18px var(--font-sans);
    letter-spacing: -0.03em;
    color: var(--text-1);
  }

  .mini b small {
    font-size: 9px;
    color: var(--text-2);
    vertical-align: 6px;
  }

  .mini span {
    display: block;
    height: 13px;
    font: 600 8px/13px var(--font-sans);
    text-align: center;
    color: var(--on-closed);
    background: var(--status-closed);
    border-radius: 4px;
  }

  .sw {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 2;
    display: flex;
    gap: 5px;
    padding: 5px 7px;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 999px;
  }

  .sw i {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  .sw .c {
    background: var(--status-closed);
  }

  .sw .d {
    box-shadow: inset 0 0 0 1.5px var(--status-delayed);
  }

  .sw .o {
    background: var(--status-open);
  }

  .sw .h {
    background: var(--status-chance);
  }

  .meta {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
  }

  .nm {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    min-height: 24px;
  }

  .nm b {
    font: 600 15px/22px var(--font-sans);
  }

  .try {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: 100%;
    min-height: 44px;
    font: 500 14px/1 var(--font-sans);
    color: var(--text-1);
    cursor: pointer;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 10px;
  }

  .try.on {
    color: var(--text-2);
    cursor: default;
  }

  /* Snowball: ink outlines, a hard drop offset, round corners and the round face. */
  .is-toon {
    /* The drop's room, inside the tile's own cell. */
    margin: 0 4px 4px 0;
    border-width: 2.5px;
    border-radius: 20px;
    box-shadow: 4px 4px 0 0 var(--border-2);
  }

  .is-toon .pv {
    border-bottom-width: 2.5px;
  }

  .is-toon .mini,
  .is-toon .sw {
    border-width: 2px;
    box-shadow: 2px 2px 0 0 var(--border-2);
  }

  .is-toon .mini {
    border-radius: 11px;
  }

  .is-toon .nm b {
    font-weight: 700;
  }

  .is-toon .try {
    font-weight: 600;
    background: var(--accent);
    border-width: 2.5px;
    border-radius: 999px;
    box-shadow: 0 3px 0 0 var(--border-2);
  }

  .is-toon .try.on {
    background: var(--surface-1);
  }

  .is-toon .sw i {
    box-shadow: 0 0 0 1.5px var(--border-2);
  }

  .is-toon .sw .d {
    box-shadow:
      inset 0 0 0 2px var(--status-delayed),
      0 0 0 1.5px var(--border-2);
  }
</style>
