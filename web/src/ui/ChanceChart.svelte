<script lang="ts">
  import type { Attachment } from 'svelte/attachments';
  import type { ChartView } from '../app/chance';
  import { announcesRoom, placeLabels } from './chart-labels';

  interface Props {
    chart: ChartView;
    /** The words at the announcement's line, with their live countdown (ChanceView.announces). */
    announces: string | null;
  }

  let { chart, announces }: Props = $props();

  const count = $derived(chart.bars.length);
  const answer = $derived(chart.key.find((row) => row.mark === 'buses'));
  const announcement = $derived(chart.key.find((row) => row.mark === 'announces'));
  const heavy = $derived(chart.key.filter((row) => row.mark === 'heavy'));

  let width = $state(0);
  let busesWidth = $state(0);
  let busesHeight = $state(0);
  let announcesWidth = $state(0);
  let announcesHeight = $state(0);

  /**
   * Hands `report` the element, now and each time its size changes, as `bind:clientWidth` and
   * its kin would: with an observer of the chart's own, since the shared one those bindings use
   * would load with the page's first script.
   */
  function sized(report: (node: HTMLElement) => void): Attachment<HTMLElement> {
    return (node) => {
      const observer = new ResizeObserver(() => {
        report(node);
      });
      observer.observe(node, { box: 'border-box' });
      report(node);
      return () => {
        observer.disconnect();
      };
    };
  }

  /** A bar's left edge across the plot, as a share of it. */
  function across(at: number): string {
    return `${String((at / count) * 100)}%`;
  }

  /** The middle of a bar (60% of its hour's width, from the left), for a line through it. */
  function middle(at: number): string {
    return `${String(((at + 0.3) / count) * 100)}%`;
  }

  const busesAt = $derived(((count - 1 + 0.3) / count) * width);
  const placed = $derived(
    placeLabels({
      width,
      busesAt,
      // At its time: where its hour's bar starts, and on through the hour.
      announcesAt: chart.announces === null ? null : (chart.announces / count) * width,
      buses: { width: busesWidth, height: busesHeight },
      announces:
        announcement === undefined || chart.announces === null
          ? null
          : { width: announcesWidth, height: announcesHeight },
    }),
  );
</script>

<!--
  The night hour by hour, drawn to scale: a bar an hour (or two or three, on
  a long night) on a real scale (the snow on the ground since the storm
  began, rising through the night; or how cold it will feel, hanging below
  0 F), the heaviest hours lit, the usual announcement's dashed line, and the
  bus hour's, with its range. The two dashed lines' words sit over the plot,
  each where its own line rises to meet it, by one rule at any width
  (chart-labels.ts), the announcement's with its live countdown; the lit
  bars' words are the key under the chart, a row on the panel's two columns,
  the bar drawn small in the first. The announcement's line is at its time,
  the bus hour's through the bar it answers for.
-->
<figure class="chart">
  <figcaption class="title">{chart.title}</figcaption>
  <p class="sr-only">{chart.summary}</p>

  <div
    class="drawing"
    {@attach sized((node) => {
      width = node.clientWidth;
    })}
  >
    <div class="head" style:height="{placed.height}px">
      {#if answer?.mark === 'buses'}
        <p
          class="words is-buses"
          {@attach sized((node) => {
            busesWidth = node.offsetWidth;
            busesHeight = node.offsetHeight;
          })}
          style:left="{placed.buses.left}px"
          style:top="{placed.buses.top}px"
        >
          <span class="value">{answer.value}</span>{answer.rest}
        </p>
      {/if}
      {#if announcement?.mark === 'announces' && placed.announces !== null}
        <p
          class="words is-announces"
          {@attach sized((node) => {
            announcesWidth = node.offsetWidth;
            announcesHeight = node.offsetHeight;
          })}
          style:max-width={width > 0 ? `${String(announcesRoom(busesAt))}px` : null}
          style:left="{placed.announces.left}px"
          style:top="{placed.announces.top}px"
          data-room={announces === null ? null : announcement.widest}
        >
          <span class="live">{announces ?? announcement.text}</span>
        </p>
      {/if}
    </div>

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
      {#if chart.range !== null}
        <span
          class="range"
          style:left={middle(count - 1)}
          style:bottom="{chart.range.bottom}px"
          style:height="{chart.range.height}px"
        ></span>
      {/if}
    </div>

    {#if chart.announces !== null}
      <span
        class="line is-announces"
        aria-hidden="true"
        style:left={across(chart.announces)}
        style:top="{placed.announcesLine ?? 0}px"
      ></span>
    {/if}
    <span
      class="line is-buses"
      aria-hidden="true"
      style:left={middle(count - 1)}
      style:top="{placed.busesLine}px"
      style:bottom="{chart.busTop}px"
    ></span>
  </div>

  <div class="times" aria-hidden="true">
    {#each chart.times as time (time.at)}
      <span class="time" class:is-end={time.end} style:left={time.end ? null : across(time.at)}
        >{time.label}</span
      >
    {/each}
  </div>

  {#if heavy.length > 0}
    <ul class="key">
      {#each heavy as row (row.mark)}
        <li class="row">
          <span class="sample is-bar" aria-hidden="true"></span>
          <span>{row.text}</span>
        </li>
      {/each}
    </ul>
  {/if}
</figure>

<style>
  .chart {
    /* Room above the tallest bar, where the dashed lines rise to their words. */
    --head: 16px;

    margin: 0;
  }

  .title {
    margin: 0 0 var(--row);
    font: var(--type-strong);
    color: var(--text-1);
  }

  .drawing {
    position: relative;
  }

  .head {
    position: relative;
  }

  /* A dashed line's words: at most the plot's width, wrapping only past it. */
  .words {
    position: absolute;
    width: max-content;
    max-width: 100%;
    margin: 0;
    font: var(--type-body);
    color: var(--text-1);
  }

  .value {
    font-weight: 600;
  }

  /* The countdown keeps the room of its longest form, so the chart never jumps as it shortens. */
  .words.is-announces {
    display: grid;
    font-variant-numeric: tabular-nums;
  }

  .live,
  .words.is-announces::after {
    grid-area: 1 / 1;
  }

  .words.is-announces::after {
    visibility: hidden;
    content: attr(data-room);
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

  /* A moment's dashed line, from just under its words: the announcement's down to the foot. */
  .line {
    position: absolute;
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

  /* The key: the panel's two columns, the lit bar drawn small where a list's times go. */
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

  .sample {
    position: relative;
    display: block;
    height: 12px;
    /* On the first line's middle. */
    margin-top: 5px;
  }

  .sample.is-bar {
    width: 8px;
    background: var(--text-1);
    border-radius: 2px 2px 0 0;
  }
</style>
