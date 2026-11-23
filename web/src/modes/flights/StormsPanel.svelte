<script module lang="ts">
  /** The day's departures cancelled, in tenths of a percent. */
  function cancelledShare(replay: FlightsReplay): number {
    const departures = replay.departures.reduce((sum, n) => sum + n, 0);
    const cancelled = replay.cancelled.reduce((sum, n) => sum + n, 0);
    return departures === 0 ? 0 : Math.round((cancelled / departures) * 1000);
  }
</script>

<script lang="ts">
  import {
    BLOCK_KEYS,
    cancelledOf,
    cancelledWords,
    stormRowLabel,
    flightsCopy,
    heroNumber,
    percent,
    stormCancelled,
    stormFacts,
    stormTitle,
    usualNotePast,
  } from '../../copy-flights';
  import Hero from './Hero.svelte';
  import PanelShell from '../../ui/PanelShell.svelte';
  import type { FlightsReplay, FlightsReplayIndex } from '../../types/generated';
  import type { FlightsFiles } from './data';

  interface Props {
    /** The past storm open, or null for the list. */
    id: string | null;
    files: FlightsFiles;
    onopen: (id: string | null) => void;
    onclose: () => void;
    onsettle: () => void;
  }

  let { id, files, onopen, onclose, onsettle }: Props = $props();

  let index = $state<FlightsReplayIndex | null | undefined>(undefined);
  let replay = $state<FlightsReplay | null | undefined>(undefined);

  $effect(() => {
    void files.replays().then((read) => (index = read));
  });

  $effect(() => {
    const asked = id;
    replay = undefined;
    if (asked === null) return;
    void files.replay(asked).then((read) => {
      if (asked === id) replay = read;
    });
  });
</script>

<!--
  Past storm days (flights spec D14): what the chances said the evening before next to what
  happened, from the held-out days only, always marked as a past day with its date.
-->
<PanelShell label={flightsCopy.storms.title} shows={`storms:${id ?? ''}`} {onclose} {onsettle}>
  {#snippet head()}
    {#if id !== null && replay}
      <button
        type="button"
        class="fl-chip fl-back"
        onclick={() => {
          onopen(null);
        }}>{flightsCopy.back}</button
      >
      <p class="fl-kind">{flightsCopy.storms.pastDay}</p>
      <h2 class="fl-name">{stormTitle(replay.code, replay.day)}</h2>
    {:else}
      <h2 class="fl-name">{flightsCopy.storms.title}</h2>
    {/if}
  {/snippet}

  {#if id === null}
    {#if index === undefined}
      <p class="fl-note">{flightsCopy.live.loading}</p>
    {:else if index === null}
      <p class="fl-note">{flightsCopy.storms.notReady}</p>
    {:else if index.replays.length === 0}
      <p class="fl-note">{flightsCopy.storms.none}</p>
    {:else}
      <div class="fl-rows" data-testid="flights-storms">
        {#each index.replays as summary (summary.id)}
          {@const share = cancelledWords(summary.cancelled)}
          <button
            type="button"
            class="fl-row-button"
            aria-label={stormRowLabel(stormTitle(summary.code, summary.day), share)}
            onclick={() => {
              onopen(summary.id);
            }}
          >
            <span>{stormTitle(summary.code, summary.day)}</span>
            <span>{share}</span>
          </button>
        {/each}
      </div>
    {/if}
  {:else if replay === undefined}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if replay === null}
    <p class="fl-note">{flightsCopy.storms.notReady}</p>
  {:else}
    <!-- A past day, as Schools' chance shows a number (LR-F9): its date always in its line. -->
    <Hero
      number={heroNumber(cancelledShare(replay))}
      meaning={stormCancelled(replay.day)}
      rows={stormFacts(replay.rough_said, replay.rough_usual, replay.apart)}
      testid="flights-storm"
    />
    <div class="fl-blocks fl-storm-blocks">
      <span></span>
      <span class="fl-col">{flightsCopy.storms.said}</span>
      <span class="fl-col">{flightsCopy.storms.happened}</span>
      {#each BLOCK_KEYS as key, i (key)}
        {@const said = replay.said[i] ?? null}
        <span class="fl-when"
          ><span>{flightsCopy.blocks[key]}</span><span>{flightsCopy.blockHours[key]}</span></span
        >
        <span class="fl-value" class:is-none={said === null}>
          {said === null ? flightsCopy.noForecast : percent(said)}
          {#if said !== null && (replay.said_usual & (1 << i)) !== 0}<span class="fl-usual"
              >{flightsCopy.usualMark}</span
            >{/if}
        </span>
        <span class="fl-value"
          >{cancelledOf(replay.cancelled[i] ?? 0, replay.departures[i] ?? 0)}</span
        >
      {/each}
    </div>
    {#if replay.said_usual !== 0}<p class="fl-note">{usualNotePast(replay.code)}</p>{/if}
  {/if}
</PanelShell>

<style>
  .fl-back {
    margin: -4px 0 8px;
  }

  .fl-storm-blocks :global(.fl-col) {
    max-width: 96px;
    text-wrap: balance;
  }
</style>
