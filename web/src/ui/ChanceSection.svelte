<script lang="ts">
  import { onMount } from 'svelte';

  import type { ChanceView } from '../app/chance';
  import { copy } from '../copy';
  import { chanceCopy, chanceFormat } from '../copy-chance';
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
  first; then the chance of no school as the headline, and what moved it;
  the evening's early signals and when the district usually announces; the
  night hour by hour; how the chance adds up, always open; and the chance of
  a delayed start instead. One column, everything on the left; the map's
  Closed blue is its one accent, the legend's colors only for statuses.
-->

<section class="chance" aria-labelledby="chance-meaning">
  {#if chance.status.length > 0}
    <div class="status" role="group" aria-label={copy.detail.status}>
      {#each chance.status as line, n (n)}
        <div class="line">
          <span class="glyph {GLYPHS[line.tone]}" aria-hidden="true"></span>
          <div class="line-text">
            <p class="headline">{line.headline}</p>
            {#if line.detail !== null}
              <p class="line-detail">{line.detail}</p>
            {/if}
            {#if line.note !== null}
              <p class="line-note">{line.note}</p>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <div class="hero">
    <p class="number" aria-hidden="true">{chance.number}<span class="pct">%</span></p>
    <div class="hero-text">
      <p class="meaning" id="chance-meaning">
        <span class="sr-only">{chance.number}%</span>
        {chanceCopy.noSchool} <br />{chanceFormat.weekday(chance.day)}
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
    </div>
  </div>

  {#if chance.moments.length > 0}
    <ol class="moments">
      {#each chance.moments as moment, i (moment.key)}
        {@const count = moment.at === null ? null : countdown(moment.at)}
        <li
          class="moment"
          class:is-next={moment.mark === 'next'}
          class:is-event={moment.mark === 'event'}
          class:leads-next={chance.moments[i + 1]?.mark === 'next'}
        >
          <span class="m-time">{moment.time}</span>
          <span class="m-mark" aria-hidden="true">
            <span
              class="dot {moment.mark === 'next' || moment.mark === 'event'
                ? ''
                : `glyph ${GLYPHS[moment.mark]}`}"
            ></span>
          </span>
          <span class="m-text">
            {moment.text}
            {#if count !== null}<span class="m-count">{count}</span>{/if}
          </span>
        </li>
      {/each}
    </ol>
  {/if}

  {#if chance.chart !== null}
    <ChanceChart chart={chance.chart} />
  {/if}

  {#if chance.why !== null}
    <div class="why">
      <h3 class="why-title">{chance.why.title}</h3>
      <p class="key">{chance.why.key}</p>
      <ol class="sum">
        <li class="is-start">
          <span class="num">{chance.why.base.number}</span><span class="unit">%</span>
          <div class="said">
            <p><strong>{chance.why.base.lead}</strong>{chance.why.base.rest}</p>
            {#if chance.why.base.record !== null}
              <ChanceRecord days={chance.why.base.record} />
            {/if}
          </div>
        </li>
        {#each chance.why.lines as line (line.key)}
          <li class="is-reason">
            <span class="num">{line.points}</span><span class="unit"></span>
            <div class="said">
              <p><strong>{line.lead}</strong>{line.rest}</p>
              {#if line.record !== null}
                <ChanceRecord days={line.record} />
              {/if}
            </div>
          </li>
        {/each}
        <li class="is-total">
          <span class="num">{chance.why.total.number}</span><span class="unit">%</span>
          <p class="said"><strong>{chance.why.total.text}</strong></p>
        </li>
      </ol>
    </div>
  {/if}

  {#if chance.delay !== null}
    <p class="delay">
      <span class="glyph is-delayed" aria-hidden="true"></span>
      {chance.delay}
    </p>
  {/if}
</section>

<style>
  .chance {
    display: flex;
    flex-direction: column;
    margin: 6px 0 0;
  }

  p {
    margin: 0;
  }

  /* The school's status, when the live files state one: a fact, above the chance. */
  .status {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-bottom: 16px;
    margin-bottom: 18px;
    border-bottom: 1px solid var(--border-1);
  }

  .line {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr);
    column-gap: 12px;
    align-items: start;
  }

  .line .glyph {
    width: 11px;
    height: 11px;
    margin-top: 6px;
  }

  .line .glyph.is-remote {
    width: 9px;
    height: 9px;
    margin: 7px 0 0 1px;
  }

  .glyph.is-open {
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }

  .headline {
    font-size: 17px;
    font-weight: 600;
    line-height: 23px;
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  .line-detail {
    margin-top: 2px;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
  }

  .line-note {
    margin-top: 2px;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  /* The number, and beside it what it means and which way it just moved. */
  .hero {
    display: flex;
    gap: 14px;
    align-items: center;
  }

  .number {
    display: flex;
    flex: none;
    align-items: flex-start;
    margin-left: -2px;
    font-size: 60px;
    font-weight: 600;
    line-height: 60px;
    letter-spacing: -0.05em;
    color: var(--text-1);
    font-variant-numeric: proportional-nums;
  }

  .pct {
    margin: 5px 0 0 3px;
    font-size: 26px;
    font-weight: 500;
    line-height: 26px;
    letter-spacing: 0;
    color: var(--text-2);
  }

  .hero-text {
    min-width: 0;
    padding-top: 2px;
  }

  .meaning {
    font-size: 15px;
    font-weight: 600;
    line-height: 20px;
    letter-spacing: -0.005em;
    color: var(--text-1);
  }

  /* What changed: the direction in the mark, the words in full ink. */
  .change {
    display: flex;
    gap: 5px;
    align-items: center;
    margin-top: 3px;
    font-size: 13px;
    font-weight: 500;
    line-height: 18px;
    color: var(--text-1);
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

  .change.is-same {
    color: var(--text-2);
  }

  /*
    The evening so far, and what comes next: the time first and firm, a mark
    on a thin rail, then plain words. Past times step back; the next one leads.
  */
  .moments {
    display: grid;
    grid-template-columns: minmax(58px, max-content) 20px minmax(0, 1fr);
    row-gap: 12px;
    margin: 22px 0 0;
    padding: 0;
    list-style: none;
  }

  /* Each moment on the list's own columns, so the times line up however wide the widest is. */
  .moment {
    display: grid;
    grid-template-columns: subgrid;
    grid-column: 1 / -1;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-1);
  }

  .m-time {
    font-weight: 600;
    color: var(--text-2);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .is-next .m-time {
    color: var(--text-1);
  }

  .m-mark {
    position: relative;
    display: flex;
    justify-content: center;
    padding-top: 6px;
  }

  /* The rail down to the next moment: solid for what happened, dashed into what is to come. */
  .moment:not(:last-child) .m-mark::after {
    position: absolute;
    top: 17px;
    bottom: -9px;
    left: 50%;
    content: '';
    border-left: 1px solid var(--border-2);
  }

  .moment.leads-next .m-mark::after {
    border-left-style: dashed;
    border-left-color: var(--text-3);
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  .dot.glyph.is-remote {
    width: 7px;
    height: 7px;
    border-radius: 1px;
  }

  .is-event .dot {
    width: 7px;
    height: 7px;
    background: var(--text-2);
  }

  .is-next .dot {
    box-shadow: inset 0 0 0 1.5px var(--text-1);
  }

  .m-count {
    display: block;
    margin-top: 1px;
    font-size: 15px;
    font-weight: 600;
    line-height: 20px;
    letter-spacing: -0.005em;
    color: var(--text-1);
    font-variant-numeric: tabular-nums;
  }

  /* The chart, a step below the timeline (or the number, without one). */
  .chance > :global(.chart) {
    margin-top: 28px;
  }

  /* How the chance adds up: open, in sentences, right under the chart. */
  .why {
    margin-top: 30px;
  }

  .why-title {
    margin: 0 0 14px;
    font-size: 17px;
    font-weight: 600;
    line-height: 23px;
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  strong {
    font-weight: 600;
    color: var(--text-1);
  }

  .key {
    margin: -8px 0 16px;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
  }

  /* The sum as you would write it on paper. Numbers right-aligned so the digits line up. */
  .sum {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .sum > li {
    display: grid;
    grid-template-columns: 30px 14px minmax(0, 1fr);
    font-size: 15px;
    line-height: 22px;
    color: var(--text-1);
  }

  .num {
    font-weight: 600;
    color: var(--text-1);
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .unit {
    padding-left: 1px;
    font-weight: 500;
    color: var(--text-2);
  }

  .said {
    padding-left: 4px;
  }

  .sum .is-start {
    margin-bottom: 4px;
  }

  .sum .is-total {
    position: relative;
    margin-top: 4px;
    padding-top: 12px;
  }

  /* The line you draw under a sum: under the numbers only. */
  .sum .is-total::before {
    position: absolute;
    top: 0;
    left: 0;
    width: 44px;
    content: '';
    border-top: 1px solid var(--text-3);
  }

  .delay {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-top: 22px;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-2);
  }
</style>
