<script lang="ts">
  /**
   * The day line over the map's key: which day the map shows, by its weekday,
   * wherever it is not the visitor's own today, and both days and where while
   * it shows two (copy-format.ts mapDays). Started by the app's services with
   * the first day to name (ui/map-day-host.ts), on the page's stage.
   */
  interface Props {
    /** The page's stage, whose map credits the line keeps clear of. */
    stage: HTMLElement;
  }

  let { stage }: Props = $props();

  let text = $state<string | null>(null);
  /**
   * While the map's credits are open over the key's corner, how far over the
   * stage's foot the line sits, clear above them: the day the lights show is
   * named all the while, as the key steps aside. Null while they are closed.
   */
  let lift = $state<number | null>(null);

  /** Shows these words, or none (null). */
  export function show(next: string | null): void {
    text = next;
  }

  /** The gap between the line and the credits under it. */
  const GAP_PX = 6;

  $effect(() => {
    let credits: Element | null = null;
    const update = (): void => {
      if (credits?.classList.contains('maplibregl-compact-show') !== true) {
        lift = null;
        return;
      }
      lift = stage.getBoundingClientRect().bottom - credits.getBoundingClientRect().top + GAP_PX;
    };
    const opened = new MutationObserver(update);
    // The credits' size, heard as it changes; where the browser has no ResizeObserver, as the
    // window's does (the credits wrap and unwrap with the page's width), so the line is shown
    // all the same.
    const sized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    if (sized === null) window.addEventListener('resize', update);
    // The credits go on the map once its style is in: found then, and heard open or close.
    const find = (): void => {
      if (credits !== null) return;
      credits = stage.querySelector('.maplibregl-ctrl-attrib');
      if (credits === null) return;
      added.disconnect();
      opened.observe(credits, { attributes: true, attributeFilter: ['class'] });
      sized?.observe(credits);
      update();
    };
    const added = new MutationObserver(find);
    added.observe(stage, { childList: true, subtree: true });
    find();
    return () => {
      added.disconnect();
      opened.disconnect();
      sized?.disconnect();
      if (sized === null) window.removeEventListener('resize', update);
    };
  });
</script>

<!--
  Drawn anew for new words, so none is seen to move, and set on the map like
  the key below it, with no chip around it. The map's labels keep clear of it
  (App.svelte CONTROLS).
-->
{#if text !== null}
  {#key text}
    <p class="map-day" style:bottom={lift === null ? null : `${String(lift)}px`}>{text}</p>
  {/key}
{/if}

<style>
  .map-day {
    position: absolute;
    bottom: calc(var(--inset-bottom) + var(--edge) + var(--control-height) + 6px);
    left: calc(var(--inset-left) + var(--edge));
    z-index: 2;
    /* Clear of the phone's locate button across from it. */
    max-width: calc(100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge) - 64px);
    margin: 0;
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text-1);
    text-wrap: balance;
    pointer-events: none;
    text-shadow:
      0 0 2px var(--halo),
      0 0 8px var(--halo);
    animation: appear 320ms ease-out both;
  }

  /* A soft shadow under the words, as under the key, so no light on the map runs through them. */
  .map-day::before {
    position: absolute;
    inset: -2px -8px;
    z-index: -1;
    pointer-events: none;
    content: '';
    background: rgb(var(--veil) / 0.72);
    border-radius: 10px;
    box-shadow: 0 0 16px 8px rgb(var(--veil) / 0.72);
  }

  /*
    A phone sets the key on two lines of two once it has counts, and the
    narrowest phones always: the day line over both (two 16px lines, the gap
    between them and the padding under them, index.html).
  */
  @media (max-width: 719px) {
    :global(.stage:has(.legend .count)) .map-day {
      bottom: calc(
        var(--inset-bottom) + var(--edge) + 40px + (var(--control-height) - 16px) / 2 + 6px
      );
    }
  }

  @media (max-width: 374px) {
    .map-day {
      bottom: calc(
        var(--inset-bottom) + var(--edge) + 40px + (var(--control-height) - 16px) / 2 + 6px
      );
    }
  }

  /*
    The later days' line (ui/LaterKey.svelte) takes the line's place over the
    key: the day line steps up over it, a line and its gap. While the credits
    are open, or a panel, the later days' line steps aside (and the day line
    is lifted clear of the credits as above).
  */
  :global(.stage:has(.later-key):not(:has(.maplibregl-compact-show, .detail))) .map-day {
    transform: translateY(-22px);
  }

  @keyframes appear {
    from {
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .map-day {
      animation: none;
    }
  }
</style>
