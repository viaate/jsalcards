<script lang="ts">
  import { onMount } from 'svelte';

  import type { AreaSchoolView, AreaView } from '../app/area';
  import { copy } from '../copy';
  import ChanceChart from './ChanceChart.svelte';
  import PanelShell from './PanelShell.svelte';

  interface Props {
    view: AreaView;
    onclose: () => void;
    /** Opens a school from the list, as a pick of it would. */
    onschool: (school: AreaSchoolView) => void;
    /** On a phone, the sheet came to rest at another height: the map's labels make room for it. */
    onsettle?: () => void;
    /** The panel's element, for the page to focus after a pick. */
    element?: HTMLElement | undefined;
  }

  let {
    view,
    onclose,
    onschool,
    onsettle = () => undefined,
    element = $bindable(),
  }: Props = $props();

  /** The glyph's class for a status, as the legend draws each status. */
  const GLYPHS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
  } as const;

  /** The ZIP code's own schools, then the others taken in under their heading: one list, one row style. */
  const groups = $derived([
    { heading: null, schools: view.own },
    { heading: view.nearHeading, schools: view.near },
  ]);

  /** The clock, a few times a minute, for the chart's countdown to the usual announcement. */
  let now = $state(Date.now());
  onMount(() => {
    const timer = setInterval(() => {
      now = Date.now();
    }, 20_000);
    return () => {
      clearInterval(timer);
    };
  });
</script>

<!--
  The schools around a ZIP code: where a ZIP code picked in search, typed and
  entered, or linked lands. What it answers first, when the live files give a
  chance for the area's next day, is that one chance, then who decides for
  its schools and the night ahead; then the schools themselves, today's
  statuses counted over them, each a row that opens its own panel. On the
  panels' one scale and grid (PanelShell.svelte): each part a section under
  one hairline, every list two columns. Every line comes from the view
  (app/area.ts); nothing here is made up or filled in.
-->
<PanelShell
  label={view.label}
  busy={view.loading}
  shows={view.zip}
  {onclose}
  {onsettle}
  bind:element
>
  {#snippet head()}
    <h2 class="name">{view.zip}</h2>
    {#if view.place !== null}
      <p class="place">{view.place}</p>
    {/if}
  {/snippet}

  {#if view.chance !== null}
    {@const chance = view.chance}
    <section class="block" aria-labelledby="area-meaning">
      <p class="number" aria-hidden="true">{chance.number}<span class="pct">%</span></p>
      <p class="meaning" id="area-meaning">
        <span class="sr-only">{chance.number}%</span>
        {chance.meaning}
      </p>
      <ol class="rows why">
        {#each chance.why as row (row.key)}
          <li class="row">
            <span class="label">{row.number}</span>
            <p>{row.text}</p>
          </li>
        {/each}
      </ol>
      {#if chance.left !== null}
        <p class="left">{chance.left}</p>
      {/if}
    </section>
    {#if chance.chart !== null}
      <div class="block">
        <ChanceChart chart={chance.chart} announces={chance.announces(new Date(now))} />
        {#if chance.chartOf !== null}
          <p class="whose">{chance.chartOf}</p>
        {/if}
      </div>
    {/if}
  {/if}

  <section class="block" aria-labelledby={view.loading ? undefined : 'area-schools'}>
    {#if view.loading}
      <div class="skeleton" aria-hidden="true">
        <span class="bone is-heading"></span>
        <span class="bone"></span>
        <span class="bone"></span>
        <span class="bone"></span>
      </div>
    {:else}
      <!-- Over every school listed, the ZIP code's own and any others taken in: above both headings. -->
      {#if view.counts.length > 0}
        <div class="row tally">
          <span class="label" id="area-today">{copy.days.today}</span>
          <ul class="counts" aria-labelledby="area-today">
            {#each view.counts as count (count.status)}
              <li>
                <span class="glyph {GLYPHS[count.status]}" aria-hidden="true"></span>{count.text}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      <h3 class="heading" id="area-schools">{view.heading}</h3>
      {#each groups as group, n (n)}
        {#if group.heading !== null}
          <h4 class="heading near-heading">{group.heading}</h4>
        {/if}
        {#if group.schools.length > 0}
          <ul class="list">
            {#each group.schools as school (school.id)}
              <li>
                <button
                  class="row school"
                  type="button"
                  onclick={() => {
                    onschool(school);
                  }}
                >
                  <span class="label">{school.distance}</span>
                  <span class="school-text">
                    <span class="school-name">
                      <span class="name-text">{school.name}</span>
                      {#if school.tone !== null}
                        <span class="glyph {GLYPHS[school.tone]}" aria-hidden="true"></span>
                      {/if}
                    </span>
                    <span class="kind">{school.kind}</span>
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      {/each}
      {#if view.noneNear !== null}
        <p class="none">{view.noneNear}</p>
      {/if}
      {#if view.unread !== null}
        <p class="none">{view.unread}</p>
      {/if}
    {/if}
  </section>
</PanelShell>

<style>
  p,
  h2,
  h3,
  h4 {
    margin: 0;
  }

  /* The ZIP code, the one heading, then where it is: as a school's name and place. */
  .name {
    font: var(--type-title);
    letter-spacing: -0.01em;
    color: var(--text-1);
  }

  .place {
    color: var(--text-2);
  }

  /* A section: under one hairline, the same room each side of it. */
  .block {
    margin-top: var(--section);
    padding-top: var(--section);
    border-top: 1px solid var(--border-1);
  }

  .heading {
    margin-bottom: var(--row);
    font: var(--type-strong);
    color: var(--text-1);
  }

  /* A list: rows of the two columns, the first in gray. */
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

  /* The chance, as the chance section sets it: the number, then what it means. */
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

  /* Who decides, a row each, right under it; then what it leaves out, and whose forecast the chart is. */
  .why {
    margin-top: var(--section);
  }

  .left,
  .whose {
    margin-top: var(--row);
    color: var(--text-2);
    text-wrap: pretty;
  }

  /* Today's statuses over the whole list, a row of the grid, each with the map's mark for it. */
  .tally {
    margin-bottom: var(--section);
  }

  .counts {
    display: flex;
    flex-wrap: wrap;
    gap: 0 var(--row);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .counts li {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  /* The schools, each a row that opens it: how far, its name and status, what it is. */
  .list {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  /* The rows' own gap is inside each button, so the whole of it opens the school. */
  .school {
    width: calc(100% + 16px);
    margin: 0 -8px;
    padding: calc(var(--row) / 2) 8px;
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 8px;
  }

  li:first-child > .school {
    margin-top: calc(var(--row) / -2);
  }

  li:last-child > .school {
    margin-bottom: calc(var(--row) / -2);
  }

  .school:hover,
  .school:focus-visible {
    background: var(--surface-2);
    outline: none;
  }

  .school:focus-visible {
    box-shadow: inset 0 0 0 1px var(--text-3);
  }

  .school .label {
    white-space: nowrap;
  }

  .school-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .school-name {
    display: flex;
    gap: 8px;
    align-items: center;
    min-width: 0;
  }

  .name-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .school .glyph {
    flex: none;
  }

  .school .glyph.is-remote {
    width: 7px;
    height: 7px;
  }

  .kind {
    overflow: hidden;
    font: var(--type-small);
    color: var(--text-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* The others taken in: a heading of the same list, a section's room above it. */
  .near-heading {
    margin-top: var(--section);
  }

  .none {
    margin-top: var(--row);
    color: var(--text-2);
  }

  /* Until the area is read: the shape of the list, without words. */
  .skeleton {
    display: flex;
    flex-direction: column;
    gap: var(--row);
  }

  .bone {
    display: block;
    width: 80%;
    height: 22px;
    background: var(--surface-2);
    border-radius: 6px;
  }

  .bone.is-heading {
    width: 45%;
  }
</style>
