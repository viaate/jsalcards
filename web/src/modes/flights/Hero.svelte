<!--
  A Flights answer, as Schools' panel gives its chance (ChanceSection.svelte .hero; flights spec
  LR-F9): the big digits with the raised %, the line that says what they are, then every other
  fact as one block of rows, each a label and its value (LR-F18.2). With no number (an old file,
  a flight that does not fly that day), only the line, in gray where the file is old.
-->
<script lang="ts">
  import type { Fact } from '../../copy-flights';
  import Facts from './Facts.svelte';

  interface Props {
    /** The big digits without their sign ("4", "<1"), or null for none. */
    number: string | null;
    meaning: string;
    rows?: readonly Fact[];
    old?: boolean;
    testid?: string;
  }

  let { number, meaning, rows = [], old = false, testid }: Props = $props();
</script>

<div class="fl-hero" class:is-old={old} data-testid={testid}>
  {#if number !== null}
    <p class="fl-hero-number" aria-hidden="true">{number}<span class="fl-hero-pct">%</span></p>
  {/if}
  <p class="fl-hero-meaning">
    {#if number !== null}<span class="sr-only">{number}%</span>{/if}
    {meaning}
  </p>
  <Facts {rows} block />
</div>
