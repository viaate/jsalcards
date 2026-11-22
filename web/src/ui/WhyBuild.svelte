<script lang="ts">
  /**
   * The Why card as the build-up (WHY-V2, Direction A; app/steps.ts): "Why 56%", then one bar a
   * step on one 0 to 100 scale, from the start to "All together": gray is what came before a
   * step, white is what it adds, and hatching is what it takes away. Only a part that moved the
   * chance gets a row; one quiet line says the rest. Then the district's past days of the kind
   * as squares in the map's own colors (closed blue, remote purple, school a hollow mark) with a
   * counted key, what is different first, and the link to "How Snowlight guesses".
   */
  import type { PlainWhyView } from '../app/steps';
  import { chanceCopy, chanceFormat } from '../copy-chance';
  import LegalLinks from './LegalLinks.svelte';
  import WhyFold from './WhyFold.svelte';

  interface Props {
    why: PlainWhyView;
    /** The habit box's title id, so its group names it. */
    habitId: string;
  }

  let { why, habitId }: Props = $props();

  const scale = chanceFormat.plain.build.scale();
  const percent = $derived(why.rows.reduce((sum, one) => sum + one.points, 0));

  /** The running total before each step (the start's is 0). */
  const before = $derived.by(() => {
    const out: number[] = [];
    let run = 0;
    for (const one of why.rows) {
      out.push(run);
      run += one.points;
    }
    return out;
  });

  /** A take-away under this many points draws its strike at a width of its own (LR-V3). */
  const SMALL = 3;

  /** A share of the 0 to 100 track, kept on it. */
  const pct = (n: number): string => `${String(Math.max(0, Math.min(100, n)))}%`;
</script>

<div class="block why-card">
  <div class="why">
    <h3 class="why-title">{why.title}</h3>
    <ol class="build sum">
      {#each why.rows as step, i (step.key)}
        {@const from = before[i] ?? 0}
        {@const to = from + step.points}
        <li class="step {i === 0 ? 'is-start' : 'is-reason'}" class:is-down={step.points < 0}>
          <div class="head">
            <span class="name">{step.title}</span>
            <span class="amount num">{step.number}</span>
          </div>
          {#if step.text !== ''}<p class="says">{step.text}</p>{/if}
          {#if step.help !== undefined}<p class="help">{step.help}</p>{/if}
          <div class="track" aria-hidden="true">
            {#if i === 0}
              <span class="seg is-base" style:width={pct(step.points)}></span>
            {:else}
              <span class="seg is-base" style:width={pct(Math.min(from, to))}></span>
              {#if step.points > 0}
                <span class="seg is-up" style:left={pct(from)} style:width={pct(step.points)}
                ></span>
              {:else if step.points < 0}
                {@const small = -step.points < SMALL}
                <!-- A small take-away ends where the row above ended, its 8 px reaching back. -->
                <span
                  class="seg is-off"
                  class:is-small={small}
                  style:left={small ? null : pct(to)}
                  style:right={small ? pct(100 - from) : null}
                  style:width={pct(-step.points)}
                ></span>
              {/if}
            {/if}
          </div>
          <!-- Under its own bar, so each bar stays right under its own words. -->
          {#if step.parts !== null}
            <WhyFold label={chanceCopy.fold} parts={step.parts} />
          {/if}
        </li>
      {/each}
    </ol>
    <div class="total">
      <div class="head">
        <span class="name">{why.total.label}</span>
        <span class="amount">{why.total.number}</span>
      </div>
      <div class="track is-total" aria-hidden="true">
        <span class="seg is-up" style:width={pct(percent)}></span>
      </div>
    </div>
    <div class="scale" aria-hidden="true">
      {#each scale as mark (mark)}<span>{mark}</span>{/each}
    </div>
    {#if why.still !== null}<p class="quiet">{why.still}</p>{/if}
  </div>

  <!-- The past days, a box of their own under the build-up's hairline. -->
  <div class="habit" role="group" aria-labelledby={habitId}>
    <h4 class="habit-title" id={habitId}>{why.habit.title}</h4>
    {#if why.habit.days !== null && why.habit.days.length > 0}
      <div class="cells" aria-hidden="true">
        {#each why.habit.days as mark, i (i)}<span class="cell is-{mark}"></span>{/each}
      </div>
    {/if}
    {#if why.habit.key.length > 0}
      <p class="habit-key">
        {#each why.habit.key as item (item.mark)}
          <span class="key-item"
            ><span class="key is-{item.mark}" aria-hidden="true"></span>{item.label}</span
          >
        {/each}
      </p>
    {/if}
    {#if why.habit.lead !== null || why.habit.text !== null}
      <p class="habit-text">
        {#if why.habit.lead !== null}<strong>{why.habit.lead}</strong>{/if}
        {#if why.habit.text !== null}{why.habit.text}{/if}
      </p>
    {/if}
    {#if why.habit.end !== null}<p class="habit-end">{why.habit.end}</p>{/if}
  </div>
  <div class="how">
    <LegalLinks pages={['how']} />
  </div>
</div>

<style>
  p,
  h3,
  h4,
  ol {
    margin: 0;
    padding: 0;
  }

  ol {
    list-style: none;
  }

  /* A section: under one hairline, the same room each side of it (ChanceSection .block). */
  .block {
    margin-top: var(--section);
    padding-top: var(--section);
    border-top: 1px solid var(--border-1);
  }

  .why-card {
    --why-type: 400 14px / 20px var(--font-sans);
    --lit: var(--text-1);
    --dim: color-mix(in srgb, var(--text-1) 40%, var(--surface-1));
    --well: var(--border-1);

    text-wrap: pretty;
  }

  .why-title {
    margin-bottom: 12px;
    font: var(--type-strong);
    color: var(--text-1);
  }

  /* The build-up: one step a row, each on the same 0 to 100 track. */
  .build {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .head {
    display: flex;
    gap: 12px;
    align-items: baseline;
    justify-content: space-between;
  }

  .name {
    font: var(--type-strong);
    color: var(--text-1);
  }

  .amount {
    flex: none;
    font: var(--type-strong);
    font-variant-numeric: tabular-nums;
    color: var(--text-1);
  }

  .step.is-down .amount {
    color: var(--text-2);
  }

  .says {
    margin-top: 2px;
    font: var(--why-type);
    color: var(--text-2);
  }

  /* What an outlook line counted, under it, quieter. */
  .help {
    margin-top: 4px;
    font: var(--type-small);
    color: var(--text-2);
  }

  .track {
    position: relative;
    height: 8px;
    margin-top: 6px;
    overflow: hidden;
    background: var(--well);
    border-radius: 4px;
  }

  .track.is-total {
    height: 12px;
    border-radius: 6px;
  }

  .seg {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
  }

  .seg.is-base {
    background: var(--dim);
  }

  .seg.is-up {
    background: var(--lit);
  }

  /* What a part takes away: the room it leaves, struck through in gray. */
  .seg.is-off {
    background: repeating-linear-gradient(-45deg, var(--text-3) 0 1.5px, transparent 1.5px 4px);
    border-radius: 0 4px 4px 0;
    box-shadow: inset 0 0 0 1px var(--text-3);
  }

  /* A small take-away (LR-V3): the same strike at least 8 px wide, drawn in the stronger gray
     with its own outline, so it never reads as the carried base or as an up step. */
  .seg.is-off.is-small {
    left: auto;
    min-width: 8px;
    background: repeating-linear-gradient(-45deg, var(--text-2) 0 1.5px, transparent 1.5px 4px);
    box-shadow: inset 0 0 0 1px var(--text-2);
  }

  /* "All together", said once, over the steps' hairline. */
  .total {
    margin-top: 12px;
    padding-top: 14px;
    border-top: 1px solid var(--border-1);
  }

  .scale {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    font: var(--type-small);
    color: var(--text-2);
  }

  /* What did not move the chance: one quiet line, never a row. Not "still": index.html's
     static map picture owns that class page-wide. */
  .quiet {
    margin-top: 12px;
    font: var(--type-small);
    color: var(--text-2);
  }

  /* The district's past days of the kind. */
  .habit {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border-1);
  }

  .habit-title {
    font: var(--type-strong);
    color: var(--text-1);
  }

  /* Status marks, in the map's own colors for the same meanings. */
  .is-closed {
    --mark: var(--status-closed);
  }

  .is-remote {
    --mark: var(--status-remote);
  }

  .cells {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 10px 0;
  }

  .cell {
    width: 20px;
    height: 20px;
    background: var(--mark, transparent);
    border-radius: 5px;
  }

  .cell.is-school {
    box-shadow: inset 0 0 0 1.5px var(--text-3);
  }

  .habit-key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    margin: -2px 0 8px;
    font: var(--type-small);
    color: var(--text-2);
  }

  .key-item {
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }

  .key {
    width: 10px;
    height: 10px;
    background: var(--mark, transparent);
    border-radius: 3px;
  }

  .key.is-school {
    box-shadow: inset 0 0 0 1.5px var(--text-3);
  }

  .habit-text {
    margin-top: 4px;
    font: var(--why-type);
    color: var(--text-1);
  }

  .habit-key + .habit-text {
    margin-top: 0;
  }

  strong {
    font-weight: 600;
  }

  .habit-end {
    margin-top: 6px;
    font: var(--type-small);
    color: var(--text-2);
  }

  .how {
    margin-top: 10px;
  }

  /* The How link's hit area reaches 44 px tall without moving the layout (LR-V7). */
  .how :global(.legal a) {
    position: relative;
  }

  .how :global(.legal a)::before {
    content: '';
    position: absolute;
    inset: -10px 0;
  }
</style>
