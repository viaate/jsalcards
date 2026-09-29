<script lang="ts">
  import type { ChartView } from '../app/chance';

  interface Props {
    chart: ChartView;
  }

  let { chart }: Props = $props();

  const count = $derived(chart.bars.length);

  /** A bar's left edge across the plot, as a share of it. */
  function across(at: number): string {
    return `${String((at / count) * 100)}%`;
  }
</script>

<!--
  The night hour by hour, drawn to scale: a bar an hour on a real scale (the
  snow on the ground, rising through the night; or how cold it will feel,
  hanging below 0 F), the hours that matter lit, the times under the bars,
  and beside the last bar when the buses run and the value (or its range)
  then. Every word is at the left of its place, as the panel's are.
-->
<figure class="chart">
  <figcaption class="title">{chart.title}</figcaption>
  <p class="sr-only">{chart.summary}</p>

  <div class="field" style:height="{chart.plot}px" aria-hidden="true">
    <div class="plot" style:--hours={count}>
      <span class="rule" style:bottom="{chart.zero}px"></span>
      {#each chart.bars as bar, i (i)}
        <span
          class="col"
          class:is-lit={bar.lit}
          class:is-below={bar.below}
          style:left={across(i)}
          style:bottom="{bar.bottom}px"
          style:height="{bar.height}px"
        ></span>
      {/each}
      {#if chart.range !== null}
        <span
          class="range"
          style:left={across(count - 1)}
          style:bottom="{chart.range.bottom}px"
          style:height="{chart.range.height}px"
        ></span>
      {/if}
    </div>
    <p class="aside">
      <span class="flag">{chart.buses}</span>
      <span class="end">{chart.end}</span>
    </p>
  </div>

  <div class="times" aria-hidden="true">
    {#each chart.times as time (time.at)}
      <span class="time" style:left={across(time.at)}>{time.label}</span>
    {/each}
  </div>
</figure>

<style>
  .chart {
    /* The column right of the plot, for when the buses run and the value then. */
    --aside: 88px;

    margin: 0;
  }

  .title {
    margin: 0 0 16px;
    font: var(--type-strong);
    color: var(--text-1);
  }

  .field {
    position: relative;
  }

  .plot {
    position: absolute;
    inset: 0 var(--aside) 0 0;
  }

  /* The zero rule, the one line: the foot of the snow, or what the cold hangs from. */
  .rule {
    position: absolute;
    right: 0;
    left: 0;
    height: 0;
    border-top: 1px solid var(--border-2);
  }

  /* A bar is 60% of its hour's width, from the hour's left edge, where its time starts. */
  .col {
    position: absolute;
    width: calc(100% / var(--hours) * 0.6);
    background: color-mix(in srgb, var(--text-1) 26%, transparent);
    border-radius: 2px 2px 0 0;
  }

  .col.is-below {
    border-radius: 0 0 2px 2px;
  }

  .col.is-lit {
    background: var(--text-1);
  }

  /* The last bar's range: a thin upright through its middle, with a cap at each end. */
  .range {
    position: absolute;
    width: 0;
    margin-left: calc(100% / var(--hours) * 0.3 - 0.75px);
    border-left: 1.5px solid var(--text-1);
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

  /* When the buses run, and the value then: beside the last bar, from the top. */
  .aside {
    position: absolute;
    top: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    width: calc(var(--aside) - 12px);
    margin: 0;
  }

  .flag {
    font: var(--type-small);
    color: var(--text-2);
  }

  .end {
    font: var(--type-strong);
    color: var(--text-1);
    white-space: nowrap;
  }

  .times {
    position: relative;
    height: 18px;
    margin: 8px var(--aside) 0 0;
  }

  .time {
    position: absolute;
    top: 0;
    font: var(--type-small);
    color: var(--text-2);
    white-space: nowrap;
  }
</style>
