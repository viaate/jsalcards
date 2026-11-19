<script module lang="ts">
  /** Each fold's ids on the page, so a button names its own help and sentence. */
  let made = 0;
</script>

<script lang="ts">
  interface Props {
    /** The step's one sentence, always shown. */
    text: string;
    /** The button's words: "How this step works". */
    label: string;
    /** What the fold opens to, in place under the button. */
    help: readonly string[];
    /** What this button is for, said after its words to a screen reader alone ("for the
     * snow"), so no two buttons in a panel share a name. */
    name?: string;
  }

  let { text, label, help, name = '' }: Props = $props();

  made += 1;
  const id = `why-fold-${String(made)}`;
  /** Closed every time a panel opens; never stored. */
  let open = $state(false);
</script>

<!-- The button follows the sentence on its line (WHY-TRANSPARENT: the panel's height at 390 px). -->
<p class="said">
  <span id="{id}-text">{text}</span>{#if help.length > 0}<button
      type="button"
      class="fold"
      aria-expanded={open}
      aria-controls="{id}-help"
      aria-describedby="{id}-text"
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
      {label}{#if name !== ''}<span class="sr-only">{` ${name}`}</span>{/if}
    </button>{/if}
</p>
{#if help.length > 0}
  <div class="fold-help" id="{id}-help" hidden={!open}>
    {#each help as line, i (i)}
      <p class="help">{line}</p>
    {/each}
  </div>
{/if}

<style>
  p {
    margin: 0;
  }

  /* The fold's button: the help's colour, a 28px target, a chevron that turns when open. */
  .fold {
    display: inline-flex;
    align-items: center;
    vertical-align: baseline;
    gap: 4px;
    min-height: 24px;
    margin: 0 0 0 8px;
    padding: 2px 0;
    border: 0;
    background: none;
    font: var(--type-small);
    color: var(--text-2);
    cursor: pointer;
    text-align: left;
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
  }

  /* Closed: gone, whatever the display above says (the hidden attribute alone loses to it). */
  .fold-help[hidden] {
    display: none;
  }

  .help {
    font: var(--type-small);
    color: var(--text-2);
  }
</style>
