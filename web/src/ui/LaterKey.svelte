<script lang="ts">
  /**
   * The key's line for the map's later-day rings (map/later-rings.ts): the
   * dashed ring as the map draws it, "Later days", then each later day by its
   * weekday with how many schools have a status that day ("Thu: 10  Fri: 8"),
   * so no ring is read as one day's. Set over the key, where the day line
   * was, which steps up over it (ui/MapDay.svelte); started with the first
   * later day the live file names (ui/later-host.ts), on the page's stage.
   * While the map's credits are open over the key's corner, or a panel is
   * open over the map's side, it steps aside. Days that do not fit its one
   * line are left off whole, never cut through a count (the screen reader's
   * words keep them all).
   */
  import { laterCopy, laterFormat } from '../copy-later';
  import { NO_LATER, sameDays } from '../data/later-days';
  import type { LaterView } from '../data/later-days';

  let view = $state.raw<LaterView>(NO_LATER);

  /**
   * Shows these days, or none (none in the view); a view with the same days
   * and counts as the one shown changes nothing, so the line is not drawn anew.
   */
  export function show(next: LaterView): void {
    if (!sameDays(next, view)) view = next;
  }

  /** The words, worked out once each time the days change; null where the formatters refuse. */
  const words = $derived.by(() => {
    const { days, from } = view;
    if (days.length === 0 || from === null) return null;
    try {
      return {
        label: laterFormat.label(days, from),
        days: days.map(({ day, count }) => ({
          key: day,
          day: laterFormat.day(day, from),
          count: laterFormat.count(count),
        })),
      };
    } catch {
      // A day the formatters refuse: no line rather than a wrong one.
      return null;
    }
  });
</script>

<!--
  Drawn anew for new words, so none is seen to move, and set on the map like
  the key below it. The map's labels keep clear of it (App.svelte CONTROLS).
-->
{#if words !== null}
  {#key words}
    <p class="later-key">
      <span class="visible" aria-hidden="true">
        <span class="ring"></span>{laterCopy.title}
        {#each words.days as entry (entry.key)}
          <span class="day">{entry.day} <span class="count">{entry.count}</span></span>
        {/each}
      </span>
      <span class="sr-only">{words.label}</span>
    </p>
  {/key}
{/if}

<style>
  .later-key {
    position: absolute;
    bottom: calc(var(--inset-bottom) + var(--edge) + var(--control-height) + 6px);
    left: calc(var(--inset-left) + var(--edge));
    z-index: 2;
    /* Clear of the phone's locate button across from it. */
    max-width: calc(100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge) - 64px);
    margin: 0;
    font-size: var(--legend-font, 12px);
    font-weight: 500;
    line-height: 16px;
    color: var(--text-2);
    white-space: nowrap;
    pointer-events: none;
    text-shadow:
      0 0 2px var(--halo),
      0 0 8px var(--halo);
    animation: appear 320ms ease-out both;
  }

  /*
    One line: a day that does not fit wraps to a second one, set well below
    and cut off with its halo, so a day is shown whole or not at all; the
    first line keeps its halo.
  */
  .visible {
    display: flex;
    flex-wrap: wrap;
    gap: 32px var(--key-gap, 7px);
    align-items: center;
    height: 16px;
    clip-path: inset(-8px);
  }

  /* The ring as the map draws it: thin, dashed, in the second gray, with no glow. */
  .ring {
    flex: none;
    box-sizing: border-box;
    width: 9px;
    height: 9px;
    border: 1px dashed var(--text-2);
    border-radius: 50%;
  }

  .day {
    margin-left: 6px;
    white-space: nowrap;
  }

  .count {
    color: var(--text-1);
  }

  /*
    While the credits are open over the key's corner, the line steps aside
    with the key; and while a panel is open, whose foot can come down to it.
  */
  :global(.stage:has(.maplibregl-compact-show)) .later-key,
  :global(.stage:has(.detail)) .later-key {
    visibility: hidden;
  }

  /*
    A phone sets the key on two lines of two once it has counts, and the
    narrowest phones always: the line over both, where the day line was.
  */
  @media (max-width: 719px) {
    :global(.stage:has(.legend .count)) .later-key {
      bottom: calc(
        var(--inset-bottom) + var(--edge) + 40px + (var(--control-height) - 16px) / 2 + 6px
      );
    }
  }

  @media (max-width: 374px) {
    .later-key {
      bottom: calc(
        var(--inset-bottom) + var(--edge) + 40px + (var(--control-height) - 16px) / 2 + 6px
      );
    }
  }

  @keyframes appear {
    from {
      opacity: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .later-key {
      animation: none;
    }
  }
</style>
