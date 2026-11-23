<script lang="ts">
  import { onMount } from 'svelte';

  import { modesCopy } from '../copy-modes';
  import { THEME_EVENT } from '../theme/event';
  import type { Cell } from './host';
  import type { ModeEntry } from './registry';

  interface Props {
    modes: readonly ModeEntry[];
    /** The mode shown, which the host sets. */
    current: Cell<string>;
    onpick: (key: string) => void;
  }

  let { modes, current, onpick }: Props = $props();

  let shown = $state('');
  let list = $state<HTMLElement>();

  /**
   * Bumped as a theme goes on in another face (Snowball's, or back from it): each button's glyph
   * and word are drawn anew in it, as App draws the key and the update time anew, so no word
   * moves in view (a layout shift, e2e/app.spec.ts). The buttons themselves stay, and keep focus.
   */
  let drawn = $state(0);

  onMount(() => {
    const stop = current.subscribe((key) => (shown = key));
    const faceOf = (): string =>
      getComputedStyle(document.documentElement).getPropertyValue('--font-sans');
    let face = faceOf();
    const onTheme = (): void => {
      const next = faceOf();
      if (next === face) return;
      face = next;
      drawn += 1;
    };
    document.addEventListener(THEME_EVENT, onTheme);
    return () => {
      stop();
      document.removeEventListener(THEME_EVENT, onTheme);
    };
  });

  /** Arrow keys move between the modes, as in any group of radio buttons. */
  function onKeydown(event: KeyboardEvent): void {
    const at = modes.findIndex((mode) => mode.key === shown);
    let next = -1;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (at + 1) % modes.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp')
      next = (at - 1 + modes.length) % modes.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = modes.length - 1;
    if (next < 0) return;
    event.preventDefault();
    const mode = modes[next];
    if (mode === undefined) return;
    onpick(mode.key);
    list?.querySelector<HTMLElement>(`[data-mode-key="${mode.key}"]`)?.focus();
  }
</script>

<!--
  The switch between the modes: a row of radio buttons drawn as one pill, in the strip's own
  surface and border, beside the menu's button. Only the mode shown takes a Tab stop; the arrow
  keys move between them.
-->
<div
  class="mode-switch"
  role="radiogroup"
  aria-label={modesCopy.label}
  tabindex="-1"
  style:--modes={modes.length}
  bind:this={list}
  onkeydown={onKeydown}
>
  {#each modes as mode (mode.key)}
    <button
      type="button"
      role="radio"
      class="mode"
      class:is-on={mode.key === shown}
      aria-checked={mode.key === shown}
      tabindex={mode.key === shown ? 0 : -1}
      data-mode-key={mode.key}
      onclick={() => {
        onpick(mode.key);
      }}
    >
      {#key drawn}
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d={mode.glyph} /></svg>
        <span class="word">{mode.label}</span>
      {/key}
    </button>
  {/each}
</div>

<style>
  /*
    Row 1 beside the menu's button on a wide screen: in the strip's third column after it. On a
    phone, across from the wordmark, just before the menu's button (and the account's, when
    there is one). Placed in a slot nothing else uses, so it moves nothing as it comes in.
  */
  .mode-switch {
    grid-row: 1;
    grid-column: 3;
    justify-self: start;
    display: flex;
    gap: 2px;
    align-items: center;
    /*
      One width under every theme and its face, set from the modes and not from their words: a
      theme's face (Snowball's Fredoka) is narrower than Geist, and its outline wider, so a width
      from the words would move the buttons when a theme goes on, a layout shift
      (e2e/app.spec.ts). The outline is drawn inside this width (border-box), and the buttons
      share what is left; the words inside them are drawn anew in a new face (drawn). Each mode's word fits in --mode-width in either face
      (e2e/flights.spec.ts holds every registered label to it).
    */
    --mode-width: 89px;
    width: calc(var(--modes) * var(--mode-width) + (var(--modes) - 1) * 2px + 2 * 3px + 2px);
    height: var(--menu-size);
    margin-left: calc(var(--menu-gap) + var(--menu-size) + var(--menu-gap) - var(--brand-gap));
    padding: 3px;
    background: var(--surface-2);
    border: 1px solid var(--border-2);
    border-radius: calc(var(--menu-size) / 2);
    /* The menu's button's own lift (index.html .menu-button), so the two read as one strip. */
    box-shadow:
      inset 0 1px 0 rgb(var(--sheen) / 0.07),
      0 0 0 1px var(--bg),
      0 8px 24px rgb(var(--shadow) / 0.6);
    box-sizing: border-box;
  }

  @media (max-width: 719px) {
    .mode-switch {
      grid-column: 1;
      justify-self: end;
      margin: 0 calc(var(--menu-size) + var(--menu-gap)) 0 0;
    }

    :global(.bar:has(.account)) .mode-switch {
      margin-right: calc(var(--menu-size) + var(--menu-gap) + var(--account-room, 0px));
    }
  }

  .mode {
    display: flex;
    flex: 1 1 0;
    gap: 6px;
    align-items: center;
    justify-content: center;
    min-width: 0;
    height: 100%;
    padding: 0 6px;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text-2);
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: calc(var(--menu-size) / 2 - 3px);
    transition:
      background-color 150ms ease-out,
      color 150ms ease-out;
  }

  .mode:hover {
    color: var(--text-1);
  }

  .mode.is-on {
    color: var(--text-1);
    background: var(--border-2);
  }

  .mode:focus-visible {
    outline: 2px solid var(--text-1);
    outline-offset: 1px;
  }

  svg {
    flex: none;
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.25;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  /* A narrow phone: the glyphs alone, their words for a screen reader. */
  @media (max-width: 359px) {
    .word {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }

    .mode {
      padding: 0;
    }

    .mode-switch {
      --mode-width: 32px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .mode {
      transition: none;
    }
  }
</style>
