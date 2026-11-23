<script lang="ts">
  import { flightsCopy, kindName, recordLine, recordSince } from '../../copy-flights';
  import type { FlightsRecord } from '../../types/generated';
  import type { FlightsFiles } from './data';

  interface Props {
    code: string;
    files: FlightsFiles;
    /** Its heading, the record's own unless a panel names it otherwise. */
    title?: string;
    /** A line over the record (a flight's own record not in yet, say). */
    note?: string | null;
  }

  let { code, files, title = flightsCopy.record.title, note = null }: Props = $props();

  let record = $state<FlightsRecord | null | undefined>(undefined);

  $effect(() => {
    const asked = code;
    record = undefined;
    void files.record(asked).then((read) => {
      if (asked === code) record = read;
    });
  });
</script>

<!-- The airport's own record in bad weather (D8, the lead's rulings LR-F1 to LR-F5). -->
<section class="fl-block" data-testid="flights-record">
  <h3 class="fl-heading">{title}</h3>
  {#if note !== null}<p class="fl-text">{note}</p>{/if}
  {#if record === undefined}
    <p class="fl-note">{flightsCopy.live.loading}</p>
  {:else if record === null}
    <p class="fl-note">{flightsCopy.record.notReady}</p>
  {:else}
    <p class="fl-note">{recordSince(record.first)}</p>
    <div class="fl-rows">
      {#each record.lines.filter((line) => line.days > 0) as line (line.kind)}
        <div class="fl-record-line">
          <p class="fl-text">
            {kindName(line.kind)}{#if line.verdict === 2}: {flightsCopy.record
                .sooner}{:else if line.verdict === 3}: {flightsCopy.record.longer}{/if}
          </p>
          <p class="fl-small">{recordLine(line.share, line.others, line.days)}</p>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .fl-record-line {
    padding: 4px 0;
  }
</style>
