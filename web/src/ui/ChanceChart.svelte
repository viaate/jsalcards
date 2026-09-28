<script lang="ts">
  import { placeFlags, placeLit } from '../app/chance';
  import type { ChartView } from '../app/chance';

  interface Props {
    chart: ChartView;
  }

  let { chart }: Props = $props();

  /** The scale's words at the left, and the column right of the last bar for its value (CSS). */
  const GUTTER = 34;
  const END = 64;
  /** A row of the moments' words above the plot, and the room under the last row. */
  const FLAG_ROW = 18;
  const FLAG_FOOT = 12;

  /** The plot's width, and each set of words' width, once laid out. */
  let plotWidth = $state(0);
  let widths = $state<Record<string, number>>({});
  let litWidth = $state(0);
  let litHeight = $state(0);

  const count = $derived(chart.bars.length);

  /** A moment's place across the plot, in pixels: bar `at`'s middle. */
  function across(at: number): number {
    return ((at + 0.5) / count) * plotWidth;
  }

  /** The moments' words, placed once measured; until then each takes its preferred side. */
  const placed = $derived.by(() => {
    const measured = chart.flags.map((flag) => widths[flag.key] ?? 0);
    if (plotWidth <= 0 || measured.some((width) => width <= 0)) return null;
    return placeFlags(
      chart.flags.map((flag, i) => ({
        x: across(flag.at),
        width: measured[i] ?? 0,
        prefer: flag.prefer,
      })),
      -GUTTER,
      plotWidth + END,
    );
  });
  const rows = $derived(placed === null ? 1 : Math.max(1, ...placed.map((item) => item.row + 1)));
  const top = $derived(rows * FLAG_ROW + FLAG_FOOT);

  const lit = $derived.by(() => {
    const words = chart.lit;
    if (words === null || plotWidth <= 0 || litWidth <= 0) return null;
    return placeLit({
      runLeft: (words.first / count) * plotWidth + 4,
      width: litWidth,
      height: litHeight,
      floor: words.floor,
      runTop: words.top,
      plot: chart.plot,
      minLeft: 0,
      maxRight: plotWidth + END,
    });
  });
</script>

<!--
  The night hour by hour, drawn to scale: a bar an hour on a real scale (the
  snow on the ground, rising through the night; or how cold it will feel,
  hanging below 0 F), light rules at a few round values, the hours that
  matter lit, the bus hour's value (or its range) beside the last bar, and the
  two moments a family plans around, each a thin line: when the district
  usually announces, and when the buses run. Their words sit beside their
  lines, on the sides that keep them apart (app/chance.ts placeFlags).
-->
<figure class="chart">
  <figcaption class="title">{chart.title}</figcaption>
  <p class="sr-only">{chart.summary}</p>

  <div class="field" style:height="{top + chart.plot}px" aria-hidden="true">
    {#each chart.ticks as tick (tick.value)}
      <span class="rule" class:is-zero={tick.value === 0} style:bottom="{tick.bottom}px"></span>
      <span class="rule-label" style:bottom="{tick.bottom - 6}px">{tick.label}</span>
    {/each}

    <div class="bars" style:height="{chart.plot}px">
      {#each chart.bars as bar, i (i)}
        <span class="slot">
          <span
            class="col"
            class:is-lit={bar.lit}
            class:is-below={bar.below}
            style:bottom="{bar.bottom}px"
            style:height="{bar.height}px"
          ></span>
        </span>
      {/each}
    </div>

    <div class="over" style:height="{top + chart.plot}px" bind:clientWidth={plotWidth}>
      {#each chart.flags as flag, i (flag.key)}
        {@const at = placed?.[i] ?? null}
        <span class="guide" style:left="{across(flag.at)}px" style:bottom="{flag.downTo}px"></span>
        <span
          class="flag is-{flag.prefer}"
          class:is-placed={at !== null}
          style:left={at === null ? `${String(across(flag.at))}px` : `${String(at.left)}px`}
          style:top="{(at?.row ?? 0) * FLAG_ROW}px"
          bind:offsetWidth={widths[flag.key]}>{flag.label}</span
        >
      {/each}

      {#if chart.range !== null}
        <span
          class="range"
          style:left="{across(count - 1)}px"
          style:bottom="{chart.range.bottom}px"
          style:height="{chart.range.height}px"
        ></span>
      {/if}

      {#if chart.lit !== null}
        <span
          class="lit-label"
          class:is-placed={lit !== null}
          style:left="{lit?.left ?? 0}px"
          style:bottom="{lit?.bottom ?? 0}px"
          bind:offsetWidth={litWidth}
          bind:offsetHeight={litHeight}>{chart.lit.label}</span
        >
      {/if}

      <span class="end" style:bottom="{chart.end.bottom - 9}px">{chart.end.label}</span>
    </div>
  </div>

  <div
    class="times"
    class:has-sub={chart.times.some((time) => time.sub !== null)}
    aria-hidden="true"
  >
    {#each chart.times as time (time.at)}
      <span class="time" style:left="{((time.at + 0.5) / count) * 100}%">
        {time.label}
        {#if time.sub !== null}<span class="time-sub">{time.sub}</span>{/if}
      </span>
    {/each}
  </div>
</figure>

<style>
  .chart {
    /* The scale's words at the left, and the column right of the last bar, for its value. */
    --gutter: 34px;
    --end: 64px;

    margin: 0;
  }

  .title {
    margin-bottom: 6px;
    font-size: 14px;
    font-weight: 600;
    line-height: 20px;
    letter-spacing: -0.005em;
    color: var(--text-1);
  }

  .field {
    position: relative;
  }

  /* Light rules at round values, each named at its left end, above the line. */
  .rule {
    position: absolute;
    right: var(--end);
    left: var(--gutter);
    height: 0;
    border-top: 1px solid var(--border-1);
  }

  .rule.is-zero {
    border-top-color: var(--border-2);
  }

  .rule-label {
    position: absolute;
    left: 0;
    width: calc(var(--gutter) - 6px);
    font-size: 11px;
    line-height: 12px;
    color: var(--text-3);
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .bars {
    position: absolute;
    right: var(--end);
    bottom: 0;
    left: var(--gutter);
    display: flex;
  }

  .slot {
    position: relative;
    flex: 1;
  }

  .col {
    position: absolute;
    right: 4px;
    left: 4px;
    background: color-mix(in srgb, var(--text-1) 26%, transparent);
    border-radius: 3px 3px 0 0;
  }

  .col.is-below {
    border-radius: 0 0 3px 3px;
  }

  .col.is-lit {
    background: var(--text-1);
  }

  /* Everything placed by the hour: the moments, the range mark, the words. */
  .over {
    position: absolute;
    right: var(--end);
    bottom: 0;
    left: var(--gutter);
  }

  .guide {
    position: absolute;
    top: 2px;
    width: 0;
    border-left: 1px dashed color-mix(in srgb, var(--text-2) 70%, transparent);
  }

  .flag {
    position: absolute;
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    color: var(--text-2);
    white-space: nowrap;
  }

  /* Until measured, beside the line on its own side; then where placeFlags puts it. */
  .flag.is-left:not(.is-placed) {
    transform: translateX(calc(-100% - 6px));
  }

  .flag.is-right:not(.is-placed) {
    transform: translateX(6px);
  }

  /* The last bar's range: a thin upright with a cap at each end. */
  .range {
    position: absolute;
    width: 0;
    border-left: 1.5px solid var(--text-1);
    transform: translateX(-0.75px);
  }

  .range::before,
  .range::after {
    position: absolute;
    left: -5.75px;
    width: 10px;
    height: 0;
    content: '';
    border-top: 1.5px solid var(--text-1);
  }

  .range::before {
    top: 0;
  }

  .range::after {
    bottom: -1.5px;
  }

  .lit-label {
    position: absolute;
    font-size: 12px;
    font-weight: 500;
    line-height: 14px;
    color: var(--text-1);
    white-space: nowrap;
    visibility: hidden;
  }

  .lit-label.is-placed {
    visibility: visible;
  }

  .end {
    position: absolute;
    left: 100%;
    padding-left: 4px;
    font-size: 14px;
    font-weight: 600;
    line-height: 18px;
    letter-spacing: -0.005em;
    color: var(--text-1);
    white-space: nowrap;
  }

  .times {
    position: relative;
    height: 16px;
    margin: 7px var(--end) 0 var(--gutter);
  }

  .times.has-sub {
    height: 30px;
  }

  .time {
    position: absolute;
    top: 0;
    font-size: 11px;
    line-height: 14px;
    color: var(--text-2);
    white-space: nowrap;
    transform: translateX(-50%);
  }

  .time-sub {
    display: block;
    color: var(--text-3);
    text-align: center;
  }
</style>
