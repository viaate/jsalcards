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

  /** The middle of a bar (60% of its hour's width, from the left), for a line through it. */
  function middle(at: number): string {
    return `${String(((at + 0.3) / count) * 100)}%`;
  }
</script>

<!--
  The night hour by hour, drawn to scale: a bar an hour (or two or three, on
  a long night) on a real scale (the snow on the ground since the storm
  began, rising through the night; or how cold it will feel, hanging below
  0 F), the heaviest hours lit, the usual announcement's dashed line, and the
  bus hour's, with its range. The plot carries marks only, and the hours
  under it; a key under the chart says each mark, a row each on the panel's
  two columns, its mark drawn small in the first. Nothing written can meet.
-->
<figure class="chart">
  <figcaption class="title">{chart.title}</figcaption>
  <p class="sr-only">{chart.summary}</p>

  <div class="plot" style:height="{chart.plot}px" style:--bars={count} aria-hidden="true">
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
    {#if chart.announces !== null}
      <span class="line is-announces" style:left={middle(chart.announces)}></span>
    {/if}
    <span class="line is-buses" style:left={middle(count - 1)} style:bottom="{chart.busTop}px"
    ></span>
    {#if chart.range !== null}
      <span
        class="range"
        style:left={middle(count - 1)}
        style:bottom="{chart.range.bottom}px"
        style:height="{chart.range.height}px"
      ></span>
    {/if}
  </div>

  <div class="times" aria-hidden="true">
    {#each chart.times as time (time.at)}
      <span class="time" class:is-end={time.end} style:left={time.end ? null : across(time.at)}
        >{time.label}</span
      >
    {/each}
  </div>

  <ul class="key">
    {#each chart.key as row (row.mark)}
      <li class="row">
        <span
          class="sample is-{row.mark === 'buses'
            ? row.glyph
            : row.mark === 'heavy'
              ? 'bar'
              : 'line'}"
          aria-hidden="true"
        ></span>
        {#if row.mark === 'buses'}
          <span><span class="value">{row.value}</span>{row.rest}</span>
        {:else}
          <span>{row.text}</span>
        {/if}
      </li>
    {/each}
  </ul>
</figure>

<style>
  .chart {
    /* Room above the tallest bar, where the dashed lines start. */
    --head: 16px;

    margin: 0;
  }

  .title {
    margin: 0 0 var(--row);
    font: var(--type-strong);
    color: var(--text-1);
  }

  .plot {
    position: relative;
    box-sizing: content-box;
    padding-top: var(--head);
  }

  /* The zero rule, the one rule: the foot of the snow, or what the cold hangs from. */
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
    width: calc(100% / var(--bars) * 0.6);
    /* 3:1 against the panel, lit or not. */
    background: color-mix(in srgb, var(--text-1) 40%, var(--surface-1));
    border-radius: 2px 2px 0 0;
  }

  .col.is-below {
    border-radius: 0 0 2px 2px;
  }

  .col.is-lit {
    background: var(--text-1);
  }

  /* A moment's dashed line, from above the bars: the announcement's down to the foot. */
  .line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 0;
    margin-left: -0.5px;
    border-left: 1px dashed var(--text-2);
  }

  /* The bus hour's range: a thin upright through the last bar, with a cap at each end. */
  .range {
    position: absolute;
    width: 0;
    margin-left: -0.75px;
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

  /* The hours, each from its bar's left edge; the bus hour's ends where the plot ends. */
  .times {
    position: relative;
    height: 18px;
    margin-top: 8px;
  }

  .time {
    position: absolute;
    top: 0;
    font: var(--type-small);
    color: var(--text-2);
    white-space: nowrap;
  }

  .time.is-end {
    right: 0;
  }

  /* The key: the panel's two columns, the mark drawn small where a list's times go. */
  .key {
    display: flex;
    flex-direction: column;
    gap: var(--row);
    margin: var(--row) 0 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: grid;
    grid-template-columns: var(--column) minmax(0, 1fr);
    column-gap: var(--gutter);
    align-items: start;
    font: var(--type-body);
    color: var(--text-1);
    text-wrap: pretty;
  }

  .value {
    font-weight: 600;
  }

  .sample {
    position: relative;
    display: block;
    height: 12px;
    /* On the first line's middle. */
    margin-top: 5px;
  }

  .sample.is-line {
    width: 0;
    margin-left: 5px;
    border-left: 1px dashed var(--text-2);
  }

  .sample.is-bar {
    width: 8px;
    background: var(--text-1);
    border-radius: 2px 2px 0 0;
  }

  .sample.is-range {
    width: 0;
    margin-left: 5px;
    border-left: 1.5px solid var(--text-1);
  }

  .sample.is-range::before,
  .sample.is-range::after {
    position: absolute;
    left: -5.75px;
    width: 10px;
    height: 0;
    content: '';
    border-top: 1.5px solid var(--text-1);
  }

  .sample.is-range::before {
    top: 0;
  }

  .sample.is-range::after {
    bottom: -1.5px;
  }
</style>
