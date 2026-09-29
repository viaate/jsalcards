<script lang="ts">
  import type { RecordDayView } from '../app/chance';
  import { chanceCopy } from '../copy-chance';

  interface Props {
    days: readonly RecordDayView[];
  }

  let { days }: Props = $props();

  /** The glyph's class for what the district did, as the legend draws each status. */
  const GLYPHS = {
    closed: 'is-closed',
    delayed: 'is-delayed',
    remote: 'is-remote',
    earlyDismissal: 'is-early-dismissal',
    open: 'is-open',
  } as const;
</script>

<!--
  The district's own record under the reason it proves (ui/ChanceSection.svelte):
  its past days like this one, oldest first, in the map's own marks.
-->
<ul class="record" aria-label={chanceCopy.record}>
  {#each days as past (past.key)}
    <li>
      <span class="glyph {GLYPHS[past.tone]}" aria-hidden="true"></span>
      <span aria-hidden="true">{past.label}</span>
      <span class="sr-only">{past.spoken}</span>
    </li>
  {/each}
</ul>

<style>
  .record {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin: 8px 0 2px;
    padding: 0;
    list-style: none;
  }

  .record li {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  .glyph.is-open {
    box-shadow: inset 0 0 0 1.5px var(--text-2);
  }
</style>
