<script lang="ts">
  import { onMount } from 'svelte';

  import { copy } from '../copy';
  import { howCopy } from '../copy-how';
  import { legalCopy, type LegalPageName } from '../copy-legal';
  import LegalBlocks from './LegalBlocks.svelte';

  interface Props {
    page: LegalPageName;
    onclose: () => void;
  }

  let { page, onclose }: Props = $props();

  const doc = $derived(page === 'how' ? howCopy : legalCopy.pages[page]);
  let heading = $state<HTMLElement>();

  onMount(() => {
    heading?.focus();
  });

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && !event.defaultPrevented) {
      event.preventDefault();
      onclose();
    }
  }
</script>

<!--
  The privacy policy or the terms of use (app/legal.ts, at ?privacy or ?terms): the owner's
  approved words (copy-legal.ts); or "How Snowlight guesses" (?how, copy-how.ts); full screen over the app in the theme's own colors, its code
  loaded only when the address asks for it.
-->
<div
  class="legal"
  role="dialog"
  aria-modal="true"
  aria-labelledby="legal-title"
  tabindex="-1"
  onkeydown={onKeydown}
>
  <button class="close" type="button" aria-label={copy.detail.close} onclick={onclose}>
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
    </svg>
  </button>
  <article>
    <h1 id="legal-title" tabindex="-1" bind:this={heading}>{doc.title}</h1>
    <LegalBlocks blocks={doc.blocks} lead />
    {#each doc.sections as section, index (index)}
      <section>
        <h2>{section.heading}</h2>
        <LegalBlocks blocks={section.blocks} />
      </section>
    {/each}
  </article>
</div>

<style>
  .legal {
    position: fixed;
    inset: 0;
    z-index: 30;
    overflow-y: auto;
    overscroll-behavior: contain;
    color: var(--text-1);
    background: var(--bg);
    outline: none;
    font-family: var(--font-sans);
  }

  .close {
    position: fixed;
    top: calc(var(--inset-top, 0px) + 16px);
    right: calc(var(--inset-right, 0px) + 16px);
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    padding: 0;
    color: var(--text-2);
    cursor: pointer;
    background: var(--surface-1);
    border: 1px solid var(--border-2);
    border-radius: 50%;
  }

  .close:hover,
  .close:focus-visible {
    color: var(--text-1);
    background: var(--surface-2);
    outline: none;
  }

  .close:focus-visible {
    box-shadow: 0 0 0 2px var(--text-2);
  }

  .close svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
  }

  article {
    max-width: 680px;
    margin: 0 auto;
    padding: calc(var(--inset-top, 0px) + 72px) calc(var(--inset-right, 0px) + 20px)
      calc(var(--inset-bottom, 0px) + 64px) calc(var(--inset-left, 0px) + 20px);
  }

  h1 {
    margin: 0;
    font-size: 32px;
    font-weight: 600;
    line-height: 1.15;
    letter-spacing: -0.03em;
    outline: none;
  }

  section {
    margin-top: 32px;
    padding-top: 24px;
    border-top: 1px solid var(--border-1);
  }

  h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    line-height: 26px;
    letter-spacing: -0.01em;
  }

  @media (max-width: 480px) {
    h1 {
      font-size: 28px;
    }
  }
</style>
