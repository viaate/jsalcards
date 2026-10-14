<script lang="ts">
  import { copy } from '../copy';
  import { format } from '../copy-format';
  import type { LocalDate } from '../types/generated';

  interface Props {
    /** The past day the map shows. */
    day: LocalDate;
    /** Back to live. */
    onexit: () => void;
  }

  let { day, onexit }: Props = $props();

  /** Back to live; the keyboard goes on from the menu's button, where a day is picked. */
  function exit(): void {
    onexit();
    document.querySelector<HTMLElement>('.menu-button')?.focus();
  }
</script>

<!--
  In the update time's place while a past day is on the map: the day, with
  its weekday and year, and the way back to live. No dot, no box: words over
  the map, as the update time is. On a phone, where the wordmark's line has
  no room for both, it sits under the search field instead, on one line.
-->
<p class="updated replay" role="status" aria-live="polite">
  <span class="day">{format.replayLine(day)}</span>
  <button class="exit" type="button" onclick={exit}>{copy.replay.exit}</button>
</p>

<style>
  .replay {
    position: absolute;
    top: calc(var(--inset-top) + var(--edge));
    right: calc(var(--inset-right) + var(--edge));
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    column-gap: 12px;
    align-items: center;
    justify-content: flex-end;
    height: var(--bar-height);
    margin: 0;
    padding: 0 2px;
    font-size: 13px;
    font-weight: 450;
    line-height: 16px;
    color: var(--text-1);
    text-align: right;
    pointer-events: none;
    text-shadow:
      0 0 2px #000,
      0 0 8px #000;
    animation: appear 320ms ease-out both;
  }

  .day {
    white-space: nowrap;
  }

  .exit {
    position: relative;
    margin: 0;
    padding: 0;
    font: inherit;
    color: inherit;
    white-space: nowrap;
    text-decoration: underline;
    text-decoration-color: var(--text-3);
    text-underline-offset: 3px;
    text-shadow: inherit;
    cursor: pointer;
    background: none;
    border: 0;
    pointer-events: auto;
  }

  /* A thumb's worth of target around the words. */
  .exit::after {
    position: absolute;
    inset: -12px -6px;
    content: '';
  }

  .exit:focus-visible {
    border-radius: 2px;
    outline: 1px solid var(--text-2);
    outline-offset: 3px;
  }

  @media (hover: hover) {
    .exit:hover {
      text-decoration-color: var(--text-1);
    }
  }

  @keyframes appear {
    from {
      opacity: 0;
    }
  }

  /* Beside the field and the menu's button, in the room the update time keeps right of them. */
  @media (min-width: 720px) {
    .replay {
      max-width: max(
        var(--side-width),
        100vw - var(--inset-left) - var(--inset-right) - 2 * var(--edge) - var(--brand-width) - 2 *
          var(--brand-gap) - var(--field-width) - var(--menu-room)
      );
    }
  }

  /* On a phone: one line under the field, at its right end, clear of the wordmark and the button. */
  @media (max-width: 719px) {
    .replay {
      top: calc(var(--inset-top) + var(--edge) + var(--brand-stack) + var(--bar-height) + 6px);
      left: calc(var(--inset-left) + var(--edge));
      height: auto;
      min-height: 20px;
      padding: 0 2px 0 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .replay {
      animation: none;
    }
  }
</style>
