<script lang="ts">
  import { onMount } from 'svelte';

  import { createConnectivity, updateState } from '../state/freshness';
  import type { UpdateState } from '../state/freshness';
  import type { UtcInstant } from '../types/generated';

  interface Props {
    /** The generated_at of the live file the map shows. */
    generatedAt: UtcInstant;
  }

  let { generatedAt }: Props = $props();

  /**
   * A file this recent, read while online, is live. The page reads the live
   * file every five minutes, so a live file is never more than a few reads old.
   */
  const LIVE_WITHIN_MS = 20 * 60_000;
  /** How often the line is worked out again as the file ages. */
  const TICK_MS = 30_000;

  let online = $state(true);
  /** The clock at the last tick, so the line is worked out again as time passes. */
  let ticked = $state(Date.now());

  const line = $derived.by((): UpdateState | null => {
    try {
      return updateState({
        generatedAt,
        online,
        liveWithinMs: LIVE_WITHIN_MS,
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        // Now, not the last tick: a new file can arrive between two ticks.
        now: new Date(Math.max(ticked, Date.now())),
      });
    } catch {
      // A time zone the formatter does not know: no line rather than a wrong one.
      return null;
    }
  });

  onMount(() => {
    const connectivity = createConnectivity();
    const stop = connectivity.subscribe((value) => {
      online = value;
    });
    const timer = setInterval(() => {
      ticked = Date.now();
    }, TICK_MS);
    return () => {
      clearInterval(timer);
      stop();
      connectivity.destroy();
    };
  });
</script>

<!--
  The time of the live file the map shows, loaded with the first one. "Live"
  only while that file is recent and the page is online; otherwise when it was
  updated. The dot breathes while live, like the lights on the map.
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
    right: calc(var(--inset-right) + var(--edge));
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

  /* On a phone the line sits across from the wordmark, over the search field's right end. */
  @media (max-width: 719px) {
    .updated {
      height: var(--brand-line);
      padding: 0 4px 0 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .updated,
    .dot {
      animation: none;
    }
  }
</style>
