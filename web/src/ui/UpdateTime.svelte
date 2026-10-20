<script lang="ts">
  import { onMount } from 'svelte';

  import {
    LIVE_FRESH_MS,
    createConnectivity,
    heldFor,
    heldSince,
    liveUntil,
    updateState,
  } from '../state/freshness';
  import type { HeldSince, UpdateState } from '../state/freshness';
  import { watchWake } from '../state/wake';
  import type { UtcInstant } from '../types/generated';

  interface Props {
    /** The generated_at of the live file the map shows. */
    generatedAt: UtcInstant;
  }

  let { generatedAt }: Props = $props();

  /** How often the line is worked out again as the file ages. */
  const TICK_MS = 30_000;

  let online = $state(true);
  /** The clock at the last tick, so the line is worked out again as time passes. */
  let ticked = $state(Date.now());

  const clocks = (): HeldSince => ({ wall: Date.now(), monotonic: performance.now() });
  /**
   * When the page first took the file it shows, by both its clocks, kept for
   * the page's life (heldSince), so a line that comes back after a replay
   * holds on from then. However the device's clock is set, a file held longer
   * than LIVE_FRESH_MS is no longer called live.
   */
  const held = $derived(heldSince(generatedAt, clocks));

  const line = $derived.by((): UpdateState | null => {
    try {
      return updateState({
        generatedAt,
        online,
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        // Now, not the last tick: a new file can arrive between two ticks.
        now: new Date(Math.max(ticked, Date.now())),
        // Worked out again at each tick, with the line.
        heldMs: heldFor(held, clocks()),
      });
    } catch {
      // A time zone the formatter does not know: no line rather than a wrong one.
      return null;
    }
  });

  // The moment the file turns stale, by its age or by how long the page has held it, the line
  // stops saying live, not at the next tick.
  $effect(() => {
    const until = liveUntil(generatedAt);
    if (until === null) return;
    const stale = (): void => {
      ticked = Date.now();
    };
    const heldMs = heldFor(held, clocks());
    const timers = [setTimeout(stale, Math.max(0, LIVE_FRESH_MS - heldMs) + 1)];
    const byAge = until - Date.now();
    if (byAge >= 0) timers.push(setTimeout(stale, byAge + 1));
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  });

  onMount(() => {
    const connectivity = createConnectivity();
    // A page in the background may have had its timers held back: work the line out on return.
    const onVisible = (): void => {
      if (document.visibilityState === 'visible') ticked = Date.now();
    };
    document.addEventListener('visibilitychange', onVisible);
    // A device that slept with the page open held its timers back too: never "Live" with a time
    // from before it slept, past the first moment the page can tell.
    const stopWake = watchWake(() => {
      ticked = Date.now();
    });
    const stop = connectivity.subscribe((value) => {
      online = value;
    });
    const timer = setInterval(() => {
      ticked = Date.now();
    }, TICK_MS);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      stopWake();
      clearInterval(timer);
      stop();
      connectivity.destroy();
    };
  });
</script>

<!--
  The time of the live file the map shows, loaded with the first one. "Live"
  only while that file is fresh (LIVE_FRESH_MS, src/state/freshness.ts) and the
  page is online; otherwise when it was updated. The dot breathes while live,
  like the lights on the map.
-->
{#if line !== null}
  <p class="updated" class:is-live={line.live}>
    {#if line.live}<span class="dot" aria-hidden="true"></span>{/if}
    <time datetime={generatedAt}>{line.text}</time>
  </p>
{/if}

<style>
  .updated {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge));
    /* Left of the account control's room, in a build that has one (index.html). */
    right: calc(var(--inset-right) + var(--edge) + var(--account-room, 0px));
    z-index: 1;
    display: flex;
    gap: 8px;
    align-items: center;
    height: var(--bar-height);
    margin: 0;
    padding: 0 2px;
    font-size: 13px;
    font-weight: 450;
    line-height: 16px;
    color: var(--text-2);
    white-space: nowrap;
    pointer-events: none;
    text-shadow:
      0 0 2px #000,
      0 0 8px #000;
    animation: appear 320ms ease-out both;
  }

  .updated.is-live {
    color: var(--text-1);
  }

  .dot {
    flex: none;
    width: 6px;
    height: 6px;
    background: var(--text-1);
    border-radius: 50%;
    box-shadow: 0 0 8px 1px rgb(245 245 245 / 0.55);
    animation: breathe 3s ease-in-out infinite;
  }

  @keyframes appear {
    from {
      opacity: 0;
    }
  }

  @keyframes breathe {
    50% {
      opacity: 0.35;
    }
  }

  /*
    Beside the search field and the menu's button after it, the line keeps to
    the room right of them (the strip's width less the wordmark, the gaps, the
    widest field and the button), and never less than the room the strip keeps
    for it. Longer than that room (a narrow window, offline, a file from
    another day), it wraps to two balanced lines, both inside the strip,
    rather than run under the field or the button.
  */
  @media (min-width: 720px) {
    .updated {
      max-width: max(
        var(--side-width),
        100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge) - var(--brand-width) - 2 *
          var(--brand-gap) - var(--field-width) - var(--menu-room) - var(--account-room, 0px)
      );
      white-space: normal;
      text-align: right;
    }

    time {
      text-wrap: balance;
    }
  }

  /*
    On a phone the line sits across from the wordmark, just before the menu's
    button at the right end of that line, its words 12px clear of it. Longer
    than the room between the two (offline, a file from another day), it wraps
    to two balanced lines there rather than run into the wordmark.
  */
  @media (max-width: 719px) {
    .updated {
      right: calc(
        var(--inset-right) + var(--edge) + var(--menu-size) + 8px + var(--account-room, 0px)
      );
      max-width: calc(
        100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge) - var(--menu-size) - 8px -
          var(--account-room, 0px) - var(--phone-brand-room)
      );
      height: var(--brand-line);
      padding: 0 4px 0 0;
      white-space: normal;
      text-align: right;
      /* The wordmark as a phone sets it, and the gap kept after it. */
      --phone-brand-room: 124px;
    }

    time {
      text-wrap: balance;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .updated,
    .dot {
      animation: none;
    }
  }
</style>
