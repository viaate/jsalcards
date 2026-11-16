<script lang="ts">
  import { legalLinksCopy } from '../copy-legal-links';

  interface Props {
    /**
     * Called as a link opens its page in place, just before it does: the menu closes itself
     * here, the keyboard back on its button, so closing the page brings the keyboard back there.
     */
    onopen?: () => void;
  }

  let { onopen = () => undefined }: Props = $props();

  /** The pages linked, in the order they show. */
  const LEGAL_PAGES = ['privacy', 'terms'] as const;
  type LegalLink = (typeof LEGAL_PAGES)[number];

  // The events app/legal.ts hears (LEGAL_EVENT, LEGAL_HREF_EVENT there): events, not an import,
  // so the code that shows these links and the page's first script carry none of the pages' code.

  /**
   * A link's address: the page's own, every other part of the address kept, as app/legal.ts
   * writes it; the page's name alone until that module has started.
   */
  function legalLinkHref(page: LegalLink): string {
    const ask: { page: LegalLink; href: string } = { page, href: `?${page}` };
    window.dispatchEvent(new CustomEvent('snowlight:legal-href', { detail: ask }));
    return ask.href;
  }

  /**
   * A link pressed: the page opens in place, over the app. A press with a modifier key, or with
   * any button but the main one, is left to the browser, as on any link: a new tab or window at
   * the link's own address.
   */
  function openLegalPage(event: MouseEvent, page: LegalLink): void {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onopen();
    window.dispatchEvent(new CustomEvent('snowlight:legal', { detail: page }));
  }

  /** Keeps a link's address current as the pointer or the keyboard comes to it. */
  function freshHref(event: Event, page: LegalLink): void {
    if (event.currentTarget instanceof HTMLAnchorElement) {
      event.currentTarget.href = legalLinkHref(page);
    }
  }
</script>

<!--
  The privacy policy and the terms of use, each a page of its own over the app (app/legal.ts),
  named by the pages' own titles: at the foot of Settings (ui/account/AccountSheet.svelte) and of
  the menu's About page (ui/MenuPanel.svelte), where a visitor who is not logged in finds them.
-->
<p class="legal">
  {#each LEGAL_PAGES as page, index (page)}
    {#if index > 0}<span aria-hidden="true">·</span>{/if}
    <a
      href={legalLinkHref(page)}
      onpointerenter={(event) => {
        freshHref(event, page);
      }}
      onfocus={(event) => {
        freshHref(event, page);
      }}
      onclick={(event) => {
        openLegalPage(event, page);
      }}>{legalLinksCopy[page]}</a
    >
  {/each}
</p>

<style>
  /* Two small links, quieter than the rows above them. */
  .legal {
    display: flex;
    gap: 8px;
    justify-content: center;
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-3);
  }

  /*
    Each link a target 24px tall, as a finger needs (WCAG 2.2 target size): the padding grows the
    box to press, and the margin takes it back out of the layout, so the line stays 18px and sits
    where it did, with at least 16px clear above and below in both places it shows.
  */
  .legal a {
    padding: 3px 0;
    margin: -3px 0;
    color: var(--text-2);
    text-decoration: none;
    border-radius: 4px;
  }

  .legal a:hover,
  .legal a:focus-visible {
    color: var(--text-1);
    text-decoration: underline;
    text-underline-offset: 3px;
    outline: none;
  }
</style>
