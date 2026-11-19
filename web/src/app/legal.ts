/**
 * The privacy policy and the terms of use (?privacy, ?terms): full screen over the app, behind the
 * lock as the app is. The site has one page and no client-side routes (vite.config.ts appType
 * 'mpa'; on GitHub Pages /privacy is the waitlist's own page), so, as ?admin and ?diag=1 do, each
 * is asked for in the address. Started with the app's services (app/boot.ts), after the first
 * paint, so the page's first script carries none of it; the page's code and words
 * (ui/LegalPage.svelte, copy-legal.ts) load only when one is asked for.
 *
 * - The address the page opens with shows one; closing it takes it out of the address, every
 *   other part kept.
 * - The links at the foot of Settings and of the menu's About page (ui/LegalLinks.svelte, by
 *   LEGAL_EVENT) open one in place with a history entry of its own: Back closes it, and so does
 *   closing it.
 * - Back and Forward show what the address then asks for.
 * - While the code screen is up (index.html's #lock), nothing of a page is put in the page: it
 *   would take the keyboard from the code's field and be read out under the lock. The page asked
 *   for shows once the code is in.
 */
import { mount, unmount } from 'svelte';

import type { LegalPageName } from '../copy-legal';

const PAGES: readonly LegalPageName[] = ['privacy', 'terms', 'how'];

/**
 * The events the links at the foot of Settings and of the menu's About page (ui/LegalLinks.svelte,
 * which writes the same names) send on the window: events rather than an import, so the code that
 * shows the links never needs this module's and the page's first script stays as it was.
 *
 * - LEGAL_EVENT, its detail the page's name: opens that page in place.
 * - LEGAL_HREF_EVENT, its detail `{ page, href }`: asks for the page's address, every other part
 *   of the address kept (legalHref), written into `href` before the event returns.
 */
export const LEGAL_EVENT = 'snowlight:legal';
export const LEGAL_HREF_EVENT = 'snowlight:legal-href';

/** The name a part of the query (`privacy`, `terms=`, `a=b`) gives, decoded; null if it has none. */
function partName(part: string): string | null {
  const name = part.split('=', 1)[0] ?? '';
  try {
    return decodeURIComponent(name.replaceAll('+', ' '));
  } catch {
    return null;
  }
}

/** Which page the address asks for (?privacy, ?terms or ?how), or null for none. */
export function legalPageOf(search: string = location.search): LegalPageName | null {
  const names = search.replace(/^\?/u, '').split('&').map(partName);
  return PAGES.find((page) => names.includes(page)) ?? null;
}

/**
 * `href` asking for `page`, or for neither with null: every other part of its query kept as it
 * is written, the page's name last.
 */
export function legalHref(href: string, page: LegalPageName | null): string {
  const url = new URL(href);
  const kept = url.search
    .replace(/^\?/u, '')
    .split('&')
    .filter((part) => {
      if (part === '') return false;
      const name = partName(part);
      return name === null || !(PAGES as readonly string[]).includes(name);
    });
  if (page !== null) kept.push(page);
  url.search = kept.join('&');
  return url.href;
}

/** Opens the page a link's event names; anything else is ignored. */
function onLink(event: Event): void {
  const page = event instanceof CustomEvent ? (event.detail as unknown) : null;
  if (PAGES.includes(page as LegalPageName)) openLegal(page as LegalPageName);
}

/** Writes the address of the page a link asks for into its event's detail; anything else is ignored. */
function onHref(event: Event): void {
  const ask = event instanceof CustomEvent ? (event.detail as unknown) : null;
  if (typeof ask !== 'object' || ask === null) return;
  const page = (ask as { page?: unknown }).page;
  if (!PAGES.includes(page as LegalPageName)) return;
  (ask as { href?: unknown }).href = legalHref(location.href, page as LegalPageName);
}

type View = ReturnType<typeof mount>;

/** The page shown, and where it is shown. */
let target: Element | null = null;
let shown: { readonly page: LegalPageName; readonly view: View } | null = null;
/** The page the address asks for, which the view follows once its code is in. */
let wanted: LegalPageName | null = null;
/** Whether the page shown was opened here, with a history entry of its own that Back undoes. */
let pushed = false;
/** What had the keyboard before the page opened, to have it back after. */
let before: HTMLElement | null = null;

/**
 * Whether the code screen (index.html's #lock) is up: in the page and drawn. A browser that can
 * says (checkVisibility); anywhere else, the screen and every element it sits in are neither
 * hidden nor display: none, and it is not visibility: hidden.
 */
export function lockUp(): boolean {
  const lock = document.getElementById('lock');
  if (lock === null) return false;
  if (typeof lock.checkVisibility === 'function') {
    return lock.checkVisibility({ visibilityProperty: true });
  }
  for (let node: Element | null = lock; node !== null; node = node.parentElement) {
    if ((node instanceof HTMLElement && node.hidden) || getComputedStyle(node).display === 'none') {
      return false;
    }
  }
  return getComputedStyle(lock).visibility !== 'hidden';
}

/** What watches for the code screen to go, while a page waits for it. */
let waiting: { readonly observer: MutationObserver; readonly check: () => void } | null = null;

/** Watches the page until the code screen is gone, then shows what `wanted` names. */
function awaitUnlock(): void {
  if (waiting !== null) return;
  const check = (): void => {
    if (lockUp()) return;
    stopAwaiting();
    render();
  };
  const observer = new MutationObserver(check);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['class', 'hidden', 'style'],
  });
  // A screen that fades out changes no attribute at its end.
  document.addEventListener('transitionend', check, true);
  waiting = { observer, check };
}

function stopAwaiting(): void {
  if (waiting === null) return;
  waiting.observer.disconnect();
  document.removeEventListener('transitionend', waiting.check, true);
  waiting = null;
}

/** Shows what `wanted` names: the page, once its code is in and the code screen gone, or nothing. */
function render(): void {
  if (shown !== null && shown.page !== wanted) {
    void unmount(shown.view);
    shown = null;
    if (wanted === null) {
      before?.focus();
      before = null;
    }
  }
  const page = wanted;
  if (page === null) stopAwaiting();
  if (page === null || shown !== null || target === null) return;
  if (lockUp()) {
    awaitUnlock();
    return;
  }
  const into = target;
  import('../ui/LegalPage.svelte').then(
    ({ default: LegalPage }) => {
      if (wanted !== page || shown !== null || target !== into) return;
      if (lockUp()) {
        awaitUnlock();
        return;
      }
      shown = {
        page,
        view: mount(LegalPage, { target: into, props: { page, onclose: closeLegal } }),
      };
    },
    () => undefined,
  );
}

/** Follows the address: Back, Forward, and the address the page opened with. */
function follow(): void {
  wanted = legalPageOf();
  if (wanted === null) pushed = false;
  render();
}

/**
 * Shows the page the address asks for, in `into`, and from then on follows the address. Returns
 * the function that stops it.
 */
export function startLegal(into: Element | null = document.getElementById('app')): () => void {
  target = into;
  follow();
  window.addEventListener('popstate', follow);
  window.addEventListener(LEGAL_EVENT, onLink);
  window.addEventListener(LEGAL_HREF_EVENT, onHref);
  return () => {
    window.removeEventListener('popstate', follow);
    window.removeEventListener(LEGAL_EVENT, onLink);
    window.removeEventListener(LEGAL_HREF_EVENT, onHref);
    wanted = null;
    stopAwaiting();
    render();
    target = null;
  };
}

/** Opens `page` in place, with a history entry of its own. */
export function openLegal(page: LegalPageName): void {
  if (wanted === page) return;
  if (wanted === null) {
    before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  history.pushState(history.state, '', legalHref(location.href, page));
  pushed = true;
  follow();
}

/** Closes the page: back where it was opened from, or the address without it. */
export function closeLegal(): void {
  if (pushed) {
    // Back to the entry it was opened from; the popstate that follows closes it (follow).
    history.back();
    return;
  }
  history.replaceState(history.state, '', legalHref(location.href, null));
  follow();
}
