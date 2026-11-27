<script lang="ts">
  import {
    flightsCopy,
    liveWait,
    monthLine,
    skillLine,
    testSpan,
    trackNotShown,
  } from '../../copy-flights';
  import PanelShell from '../../ui/PanelShell.svelte';
  import type { FlightsTrackRecord } from '../../types/generated';
  import { trackRecordFits } from './data';
  import type { FlightsFiles, LiveRead } from './data';

  interface Props {
    files: FlightsFiles;
    /** The live file: the record's scores show only where they can be for its chances. */
    live: LiveRead | null;
    /** Whether the live file could not be read. */
    failed: boolean;
    /** Each airport's time zone, which places the date of its run for the lead check. */
    zones: ReadonlyMap<string, string>;
    onclose: () => void;
    onsettle: () => void;
  }

  let { files, live, failed, zones, onclose, onsettle }: Props = $props();

  const TARGET_KEYS = ['dep_canc', 'dep_late', 'arr_canc', 'arr_late', 'rough'] as const;

  let record = $state<FlightsTrackRecord | null | undefined>(undefined);

  $effect(() => {
    void files.trackRecord().then((read) => (record = read));
  });

  /**
   * Whether the record's scores are for the chances on the map (LR-SF2): a record of other
   * chances would state counts the live file contradicts, so it says less, dated, instead.
   */
  const fits = $derived(
    record === null || record === undefined || live === null || zones.size === 0
      ? null
      : trackRecordFits(record, live.file, zones),
  );
  /** One line a target, at the shortest lead the test scored (the evening before). */
  const tests = $derived(
    record === null || record === undefined
      ? []
      : TARGET_KEYS.flatMap((key, target) => {
          const test = record?.tests
            .filter((t) => t.target === target)
            .sort((a, b) => a.lead - b.lead)[0];
          return test === undefined ? [] : [{ key, test }];
        }),
  );
</script>

<!-- How our flight chances did (flights spec D9): the held-out test, then each month scored. -->
<PanelShell label={flightsCopy.track.title} shows="record" {onclose} {onsettle}>
  {#snippet head()}
    <h2 class="fl-name">{flightsCopy.track.title}</h2>
  {/snippet}

  {#if record === undefined}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if record === null}
    <p class="fl-note">{flightsCopy.track.notReady}</p>
  {:else}
    {#if fits === null}
      <!-- Not yet checked against the map's chances: no score is said before it is. -->
      <p class="fl-note" data-testid="flights-track-wait">{liveWait(failed)}</p>
    {:else if !fits}
      <p class="fl-note" data-testid="flights-track-not-shown">
        {trackNotShown(record.generated_at)}
      </p>
    {:else}
      <p class="fl-note">{testSpan(record.test_first, record.test_last)}</p>
      <div class="fl-rows" data-testid="flights-track">
        {#each tests as row (row.key)}
          <div class="fl-track-row">
            <p class="fl-text">{flightsCopy.track.targets[row.key]}</p>
            <p class="fl-small">
              {skillLine(row.test.skill_published, row.test.published, row.test.tested)}
            </p>
          </div>
        {/each}
      </div>
      <!-- The months are the same record's scores: said only where its scores are (LR-SF2). -->
      <section class="fl-block" data-testid="flights-track-months">
        <h3 class="fl-heading">{flightsCopy.track.months}</h3>
        {#if record.months.length === 0}
          <p class="fl-note">{flightsCopy.track.noMonths}</p>
        {:else}
          <ul class="fl-list">
            {#each record.months.filter((m) => m.target === 4) as month (month.month)}
              <li class="fl-small">
                {monthLine(
                  month.month,
                  month.days_scored,
                  month.days_in_month,
                  month.rough_days,
                  month.caught,
                )}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}
  {/if}
</PanelShell>

<style>
  .fl-track-row {
    padding: 4px 0;
  }
</style>
