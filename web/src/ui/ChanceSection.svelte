<script lang="ts">
  import { onMount } from 'svelte';

  import type { ChanceView } from '../app/chance';
  import { copy } from '../copy';
  import ChanceChart from './ChanceChart.svelte';

  interface Props {
    chance: ChanceView;
  }

  let { chance }: Props = $props();

  /** The glyph's class for a status, as the legend draws each status. */
  const GLYPHS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
    open: 'is-open',
  } as const;

  /**
   * A timeline row's marker: a dot in the color of the status a district
   * posted, a gray dot for a weather event, a ring for when this district
   * usually announces.
   */
  const MARKS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
    event: 'is-event',
    announces: 'is-announces',
  } as const;

  /** The clock, a few times a minute, for the countdowns to the usual announcement. */
  let now = $state(Date.now());
  onMount(() => {
    const timer = setInterval(() => {
      now = Date.now();
    }, 20_000);
    return () => {
      clearInterval(timer);
    };
  });

  /** "in 8h 25m", or null once the moment has come. */
  function countdown(at: Date): string | null {
    return chance.countdown(at, new Date(now));
  }
</script>

<!--
  The chance section (app/chance.ts): the school's status lines, decided
  first; then the chance of no school as the headline, what moved it and the
  chance of a delayed start instead; the evening's early signals (and when the
  district usually announces, where the chart does not say it); the night hour
  by hour; and how the chance adds up, always open. On the panel's own scale
  and grid (DetailPanel.svelte): each part a section under one hairline, every
  list two columns.
-->

<section class="chance" aria-labelledby="chance-meaning">
  {#if chance.status.length > 0}
    <div class="block status" role="group" aria-label={copy.detail.status}>
      {#each chance.status as line, n (n)}
        <div class="line">
          <p class="headline">
            {line.headline}<span class="glyph {GLYPHS[line.tone]}" aria-hidden="true"></span>
          </p>
          {#if line.detail !== null}
            <p class="line-detail">{line.detail}</p>
          {/if}
          {#if line.note !== null}
            <p class="line-note">{line.note}</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <div class="block">
    <div class="hero">
      <p class="number" class:is-thin={chance.fewRecords !== null} aria-hidden="true">
        {chance.number}<span class="pct">%</span>
      </p>
      <p class="meaning" id="chance-meaning">
        <span class="sr-only">{chance.number}%</span>
        {chance.meaning}
      </p>
      {#if chance.fewRecords !== null}
        <p class="few">{chance.fewRecords}</p>
      {/if}
      {#if chance.moved !== null}
        <p class="change is-{chance.moved.direction}">
          {#if chance.moved.direction === 'up'}
            <svg viewBox="0 0 14 14" aria-hidden="true" focusable="false">
              <path d="M7 12V2.5M3 6.5l4-4 4 4" />
            </svg>
          {:else if chance.moved.direction === 'down'}
            <svg viewBox="0 0 14 14" aria-hidden="true" focusable="false">
              <path d="M7 2v9.5M3 7.5l4 4 4-4" />
            </svg>
          {/if}
          {chance.moved.text}
        </p>
      {/if}
      {#if chance.delay !== null}
        <p class="delay">{chance.delay}</p>
      {/if}
    </div>

    {#if chance.moments.length > 0}
      <ol class="rows moments">
        {#each chance.moments as moment, i (moment.key)}
          {@const count = moment.at === null ? null : countdown(moment.at)}
          <li class="moment">
            <span class="label">{moment.time}</span>
            <span class="m-text">
              {moment.text}
              {#if count !== null}<span class="m-count">{count}</span>{/if}
            </span>
            <span class="rail" aria-hidden="true">
              <span class="mark {MARKS[moment.mark]}"></span>
              {#if i < chance.moments.length - 1}<span class="link"></span>{/if}
            </span>
          </li>
        {/each}
      </ol>
    {/if}
  </div>

  {#if chance.chart !== null}
    <div class="block">
      <ChanceChart chart={chance.chart} announces={chance.announces(new Date(now))} />
    </div>
  {/if}

  {#if chance.why !== null}
    <div class="block why">
      <h3 class="why-title">{chance.why.title}</h3>
      <ol class="rows sum">
        <li class="row is-start">
          <span class="label"><span class="num">{chance.why.base.number}</span>%</span>
          <p>{chance.why.base.text}</p>
        </li>
        {#each chance.why.lines as line (line.key)}
          <li class="row is-reason">
            <span class="label"><span class="num">{line.points}</span></span>
            <p>{line.text}</p>
            {#if line.help !== undefined}
              <p class="help">{line.help}</p>
            {/if}
          </li>
        {/each}
      </ol>
    </div>
  {/if}
</section>

<style>
  .chance {
    display: flex;
    flex-direction: column;
  }

  p,
  h3 {
    margin: 0;
  }

  /* A section: under one hairline, the same room each side of it (DetailPanel.svelte .block). */
  .block {
    margin-top: var(--section);
    padding-top: var(--section);
    border-top: 1px solid var(--border-1);
  }

  /* A list: rows of the panel's two columns, the first in gray (DetailPanel.svelte .rows). */
  .rows {
    display: flex;
    flex-direction: column;
    gap: var(--row);
    margin: 0;
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
    /* No word left alone on a last line. */
    text-wrap: pretty;
  }

  .label {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  /* The school's status, when the live files state one: a fact, above the chance. */
  .status {
    display: flex;
    flex-direction: column;
    gap: var(--row);
  }

  .headline {
    display: flex;
    gap: 8px;
    align-items: center;
    font: var(--type-title);
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  .glyph.is-open {
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }

  .line-note {
    color: var(--text-2);
  }

  /* The number, then what it means, which way it just moved, and the chance of a delay. */
  .number {
    display: flex;
    align-items: flex-start;
    /* The big digits' own side bearing: their ink starts at the panel's left edge. */
    margin: 0 0 8px -3px;
    font: var(--type-number);
    letter-spacing: -0.04em;
    color: var(--text-1);
  }

  .pct {
    margin: 6px 0 0 2px;
    font: var(--type-title);
    letter-spacing: 0;
    color: var(--text-2);
  }

  .meaning {
    font: var(--type-title);
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  /* Few local records: the number in the gray of the words around it (7.8:1 on the panel). */
  .number.is-thin {
    color: var(--text-2);
  }

  .few,
  .change,
  .delay {
    color: var(--text-2);
  }

  /* What changed: the direction in the mark, the words in gray. */
  .change {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .change svg {
    flex: none;
    width: 12px;
    height: 12px;
    fill: none;
    stroke: var(--status-closed);
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .change.is-down svg {
    stroke: var(--text-2);
  }

  /*
    The evening so far, and what comes next: its time in gray, a marker on a
    thin dotted rail, then plain words. The rail's column takes the room the
    other lists leave between their columns, so with a time like "8:41 PM"
    the words start where every list's words start; a wider time ("11:52 PM")
    moves them over, never under it.
  */
  .rows.moments {
    display: grid;
    grid-template-columns: fit-content(var(--column)) 22px minmax(0, 1fr);
    column-gap: 0;
    margin-top: var(--section);
  }

  .moment {
    display: grid;
    grid-template-columns: subgrid;
    grid-column: 1 / -1;
    align-items: start;
    font: var(--type-body);
    color: var(--text-1);
    text-wrap: pretty;
  }

  /* The words come before the rail for a screen reader, which hears no rail; the eye sees it between. */
  .moment > * {
    grid-row: 1;
  }

  .moment > .label {
    grid-column: 1;
  }

  .m-text {
    grid-column: 3;
  }

  .rail {
    position: relative;
    display: flex;
    grid-column: 2;
    align-self: stretch;
    justify-content: center;
  }

  /* On the first line's middle. */
  .mark {
    box-sizing: border-box;
    width: 8px;
    height: 8px;
    margin-top: 7px;
    border-radius: 50%;
  }

  .mark.is-closed {
    background: var(--status-closed);
  }

  .mark.is-delayed {
    background: var(--status-delayed);
  }

  .mark.is-remote {
    background: var(--status-remote);
  }

  .mark.is-early-dismissal {
    background: var(--status-early-dismissal);
  }

  .mark.is-event {
    background: var(--text-2);
  }

  /* When the district usually announces: its habit, not a post, so a ring. */
  .mark.is-announces {
    border: 1.5px solid var(--text-1);
  }

  /* Dotted down to the next row's marker, 3px clear of each. */
  .link {
    position: absolute;
    top: 18px;
    bottom: calc(-1 * var(--row) - 4px);
    left: calc(50% - 0.5px);
    width: 1px;
    background: linear-gradient(var(--text-3) 50%, transparent 50%) 0 0 / 1px 4px repeat-y;
  }

  .m-count {
    white-space: nowrap;
  }

  /* What an outlook line counted, under it in the sentence's column, quieter. */
  .help {
    grid-column: 2;
    margin-top: 4px;
    font: var(--type-small);
    color: var(--text-2);
  }

  /* How the chance adds up: open, a short sentence a reason, right under the chart. */
  .why-title {
    margin-bottom: var(--row);
    font: var(--type-strong);
    color: var(--text-1);
  }
</style>
