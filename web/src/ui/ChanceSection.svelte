<script lang="ts">
  import { onMount } from 'svelte';

  import type { ChanceView } from '../app/chance';
  import { copy } from '../copy';
  import { chanceFormat } from '../copy-chance';
  import ChanceChart from './ChanceChart.svelte';
  import ChanceRecord from './ChanceRecord.svelte';

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

  /** The clock, a few times a minute, for the countdown to the usual announcement. */
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
    try {
      return chanceFormat.countdown(at, new Date(now), chance.timeZone);
    } catch {
      return null;
    }
  }
</script>

<!--
  The chance section (app/chance.ts): the school's status lines, decided
  first; then the chance of no school as the headline, what moved it and the
  chance of a delayed start instead; the evening's early signals and when the
  district usually announces; the night hour by hour; and how the chance adds
  up, always open. On the panel's own scale and grid (DetailPanel.svelte):
  each part a section under one hairline, every list two columns.
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
      <p class="number" aria-hidden="true">{chance.number}<span class="pct">%</span></p>
      <p class="meaning" id="chance-meaning">
        <span class="sr-only">{chance.number}%</span>
        {chance.meaning}
      </p>
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
        {#each chance.moments as moment (moment.key)}
          {@const count = moment.at === null ? null : countdown(moment.at)}
          <li class="row moment">
            <span class="label">{moment.time}</span>
            <span>
              {moment.text}
              {#if count !== null}<span class="m-count">{count}</span>{/if}
            </span>
          </li>
        {/each}
      </ol>
    {/if}
  </div>

  {#if chance.chart !== null}
    <div class="block">
      <ChanceChart chart={chance.chart} />
    </div>
  {/if}

  {#if chance.why !== null}
    <div class="block why">
      <h3 class="why-title">{chance.why.title}</h3>
      <p class="key">{chance.why.key}</p>
      <ol class="rows sum">
        <li class="row is-start">
          <span class="label"><span class="num">{chance.why.base.number}</span>%</span>
          <div>
            <p>{chance.why.base.lead}{chance.why.base.rest}</p>
            {#if chance.why.base.record !== null}
              <ChanceRecord days={chance.why.base.record} />
            {/if}
          </div>
        </li>
        {#each chance.why.lines as line (line.key)}
          <li class="row is-reason">
            <span class="label"><span class="num">{line.points}</span></span>
            <div>
              <p>{line.lead}{line.rest}</p>
              {#if line.record !== null}
                <ChanceRecord days={line.record} />
              {/if}
            </div>
          </li>
        {/each}
        <li class="row is-total">
          <span class="label"><span class="num">{chance.why.total.number}</span>%</span>
          <p>{chance.why.total.text}</p>
        </li>
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

  /* The evening so far, and what comes next: its time, then plain words. */
  .moments {
    margin-top: var(--section);
  }

  .m-count {
    white-space: nowrap;
  }

  /* How the chance adds up: open, in sentences, right under the chart. */
  .why-title {
    font: var(--type-strong);
    color: var(--text-1);
  }

  .key {
    margin-bottom: var(--row);
    color: var(--text-2);
  }
</style>
