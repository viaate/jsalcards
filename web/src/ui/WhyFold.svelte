<script module lang="ts">
  /** Each fold's ids on the page, so a button names its own list. */
  let made = 0;
</script>

<script lang="ts">
  import type { PartView } from '../app/steps';

  interface Props {
    /** The button's words: "See each part". */
    label: string;
    /** Each part the row adds, then the row's total, in place under the button when open. */
    parts: readonly PartView[];
  }

  let { label, parts }: Props = $props();

  made += 1;
  const id = `why-fold-${String(made)}`;
  /** Closed every time a panel opens; never stored. */
  let open = $state(false);
</script>

<!-- WHY-PLAIN: the one fold, under a row that joins more than one published amount. -->
<button
  type="button"
  class="fold"
  aria-expanded={open}
  aria-controls="{id}-parts"
  onclick={() => {
    open = !open;
  }}
>
  <svg
    class="chevron"
    class:is-open={open}
    viewBox="0 0 12 12"
    aria-hidden="true"
    focusable="false"
  >
    <path d="M3 4.5l3 3 3-3" />
  </svg>
  {label}
</button>
<ul class="fold-help" id="{id}-parts" hidden={!open}>
  {#each parts as part, i (i)}
    <li class="part" class:is-sum={i === parts.length - 1}>
      <span class="part-label">{part.label}</span><span class="part-num">{part.number}</span>
    </li>
  {/each}
</ul>

<style>
  /* The fold's button: the help's colour, a 28px target, a chevron that turns when open. */
  .fold {
    display: inline-flex;
    align-items: center;
    vertical-align: baseline;
    gap: 4px;
    position: relative;
    min-height: 24px;
    margin: 4px 0 0;
    padding: 2px 0;
    border: 0;
    background: none;
    font: var(--type-small);
    color: var(--text-2);
    cursor: pointer;
    text-align: left;
  }

  /* A 44 px tall hit area around the 24 px button, without moving the layout (LR-V7). */
  .fold::before {
    content: '';
    position: absolute;
    inset: -10px 0;
  }

  .fold:focus-visible {
    outline: 2px solid var(--focus, var(--text-1));
    outline-offset: 2px;
    border-radius: 4px;
  }

  .chevron {
    width: 12px;
    height: 12px;
    flex: none;
    fill: none;
    stroke: currentcolor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 0.15s ease;
  }

  .chevron.is-open {
    transform: rotate(180deg);
  }

  @media (prefers-reduced-motion: reduce) {
    .chevron {
      transition: none;
    }
  }

  .fold-help {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 6px 0 0;
    padding: 0;
    list-style: none;
  }

  /* A part and its amount, on one line; the row's total last, over a hairline. */
  .part {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font: var(--type-small);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  .part.is-sum {
    padding-top: 4px;
    border-top: 1px solid var(--border-1);
    color: var(--text-1);
  }

  /* Closed: gone, whatever the display above says (the hidden attribute alone loses to it). */
  .fold-help[hidden] {
    display: none;
  }
</style>
