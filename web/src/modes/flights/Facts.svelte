<!--
  Rows under a Flights answer (flights spec LR-F18.2), as Schools' detail rows (DetailPanel.svelte
  .rows): a label on the left in gray and its value on the right, one size, one weight, one line
  height, the same room between each.
-->
<script lang="ts">
  import type { Fact } from '../../copy-flights';

  interface Props {
    rows: readonly Fact[];
    /** Under its own hairline, as a block of the panel. */
    block?: boolean;
    testid?: string;
  }

  let { rows, block = false, testid }: Props = $props();
</script>

{#if rows.length > 0}
  <dl class="fl-facts" class:fl-block={block} data-testid={testid}>
    {#each rows as row, i (i)}
      <div class="fl-fact">
        <dt>{row.label}</dt>
        <dd>{row.value}</dd>
      </div>
    {/each}
  </dl>
{/if}
