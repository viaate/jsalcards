<script lang="ts">
  /*
   * The screen check, shown with ?diag=1 in the address (mounted by
   * app/diagnostics.ts, started from app/boot.ts): the numbers that tell why
   * a device shows the page as it does, for its owner to send in a
   * screenshot. Read again whenever the window, its zoom or its shift change.
   */
  import { onMount } from 'svelte';

  import { diagCopy, diagFormat } from '../copy-diag';

  interface Reading {
    window: string;
    visible: string;
    zoom: string;
    shift: string;
    page: string;
    safe: string;
    pixels: string;
    screen: string;
    browser: string;
  }

  let probe = $state<HTMLDivElement>();
  let reading = $state<Reading | null>(null);

  /** What env(safe-area-inset-*) gives, read through the probe's padding. */
  function insets(): [number, number, number, number] {
    if (probe === undefined) return [0, 0, 0, 0];
    const style = getComputedStyle(probe);
    return [
      Number.parseFloat(style.paddingTop),
      Number.parseFloat(style.paddingRight),
      Number.parseFloat(style.paddingBottom),
      Number.parseFloat(style.paddingLeft),
    ];
  }

  function read(): void {
    const view = window.visualViewport;
    const root = document.documentElement;
    const [top, right, bottom, left] = insets();
    reading = {
      window: diagFormat.size(window.innerWidth, window.innerHeight),
      visible:
        view === null
          ? diagFormat.size(Number.NaN, Number.NaN)
          : diagFormat.size(view.width, view.height),
      zoom: diagFormat.number(view?.scale ?? Number.NaN),
      shift: diagFormat.pair(view?.offsetLeft ?? Number.NaN, view?.offsetTop ?? Number.NaN),
      page: diagFormat.over(root.scrollWidth, root.clientWidth),
      safe: diagFormat.sides(top, right, bottom, left),
      pixels: diagFormat.number(window.devicePixelRatio),
      screen: diagFormat.size(screen.width, screen.height),
      browser: navigator.userAgent,
    };
  }

  onMount(() => {
    let frame = 0;
    const later = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(read);
    };
    read();
    const controller = new AbortController();
    const { signal } = controller;
    window.addEventListener('resize', later, { signal });
    window.addEventListener('scroll', later, { signal });
    window.visualViewport?.addEventListener('resize', later, { signal });
    window.visualViewport?.addEventListener('scroll', later, { signal });
    return () => {
      cancelAnimationFrame(frame);
      controller.abort();
    };
  });
</script>

<div class="probe" bind:this={probe} aria-hidden="true"></div>
{#if reading !== null}
  <section class="diag" aria-label={diagCopy.label}>
    <dl>
      <dt>{diagCopy.window}</dt>
      <dd data-diag="window">{reading.window}</dd>
      <dt>{diagCopy.visible}</dt>
      <dd data-diag="visible">{reading.visible}</dd>
      <dt>{diagCopy.zoom}</dt>
      <dd data-diag="zoom">{reading.zoom}</dd>
      <dt>{diagCopy.shift}</dt>
      <dd data-diag="shift">{reading.shift}</dd>
      <dt>{diagCopy.page}</dt>
      <dd data-diag="page">{reading.page}</dd>
      <dt>{diagCopy.safe}</dt>
      <dd data-diag="safe">{reading.safe}</dd>
      <dt>{diagCopy.pixels}</dt>
      <dd data-diag="pixels">{reading.pixels}</dd>
      <dt>{diagCopy.screen}</dt>
      <dd data-diag="screen">{reading.screen}</dd>
      <dt>{diagCopy.browser}</dt>
      <dd data-diag="browser">{reading.browser}</dd>
    </dl>
  </section>
{/if}

<style>
  .probe {
    position: fixed;
    top: 0;
    left: 0;
    width: 0;
    height: 0;
    padding: env(safe-area-inset-top, 0px) env(safe-area-inset-right, 0px)
      env(safe-area-inset-bottom, 0px) env(safe-area-inset-left, 0px);
    pointer-events: none;
    visibility: hidden;
  }

  /* Flat, under the strip at the right, clear of the safe areas and never wider than the screen. */
  .diag {
    position: fixed;
    top: calc(var(--inset-top) + var(--edge) + var(--brand-stack) + var(--bar-height) + 12px);
    right: calc(var(--inset-right) + var(--edge));
    z-index: 30;
    width: 300px;
    max-width: calc(100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge));
    padding: 12px 14px;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-1);
    pointer-events: none;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 12px;
  }

  dl {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: 4px 12px;
    margin: 0;
  }

  dt {
    color: var(--text-2);
  }

  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
</style>
