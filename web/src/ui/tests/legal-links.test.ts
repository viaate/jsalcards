import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { startLegal } from '../../app/legal';
import { accountCopy } from '../../copy-account';
import { legalCopy } from '../../copy-legal';
import { legalLinksCopy } from '../../copy-legal-links';
import LegalLinks from '../LegalLinks.svelte';

describe('LegalLinks', () => {
  let component: ReturnType<typeof mount> | undefined;
  let stop: (() => void) | undefined;
  let app: HTMLElement;

  beforeEach(() => {
    history.replaceState(null, '', '/?ref=x');
    app = document.createElement('div');
    app.id = 'app';
    document.body.append(app);
  });

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    stop?.();
    stop = undefined;
    document.body.innerHTML = '';
    history.replaceState(null, '', '/');
  });

  function show(onopen?: () => void): HTMLAnchorElement[] {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(LegalLinks, { target, props: onopen === undefined ? {} : { onopen } });
    flushSync();
    return [...target.querySelectorAll('a')];
  }

  const dialogTitle = (): string | undefined =>
    app.querySelector('[role="dialog"] h1')?.textContent ?? undefined;

  it('names each page by its own title: Privacy policy, then Terms of use', () => {
    const links = show();
    expect(links.map((link) => link.textContent)).toEqual(['Privacy policy', 'Terms of use']);
    expect(links.map((link) => link.textContent)).toEqual([
      legalCopy.pages.privacy.title,
      legalCopy.pages.terms.title,
    ]);
    expect(legalLinksCopy).toEqual({
      privacy: legalCopy.pages.privacy.title,
      terms: legalCopy.pages.terms.title,
    });
    // Neither is the Privacy row's name in Settings.
    expect(links.map((link) => link.textContent)).not.toContain(accountCopy.settings.privacyTitle);
  });

  it('links to each page’s own address, every other part of the address kept', () => {
    // Before app/legal.ts has started: the page's name alone.
    expect(show().map((link) => link.getAttribute('href'))).toEqual(['?privacy', '?terms']);
    if (component !== undefined) void unmount(component);
    component = undefined;
    stop = startLegal(app);
    expect(show().map((link) => link.href)).toEqual([
      `${location.origin}/?ref=x&privacy`,
      `${location.origin}/?ref=x&terms`,
    ]);
  });

  it('opens a page in place, after asking whoever shows the links to make way', async () => {
    stop = startLegal(app);
    const order: string[] = [];
    const onopen = vi.fn(() => {
      order.push(`onopen ${location.search}`);
    });
    const links = show(onopen);
    window.addEventListener('snowlight:legal', () => order.push('event'), { once: true });
    links[0]?.click();
    expect(order).toEqual(['onopen ?ref=x', 'event']);
    expect(location.search).toBe('?ref=x&privacy');
    await vi.waitFor(() => {
      expect(dialogTitle()).toBe(legalCopy.pages.privacy.title);
    });
    history.back();
    await vi.waitFor(() => {
      expect(app.querySelector('[role="dialog"]')).toBeNull();
    });
    links[1]?.click();
    expect(onopen).toHaveBeenCalledTimes(2);
    expect(location.search).toBe('?ref=x&terms');
    await vi.waitFor(() => {
      expect(dialogTitle()).toBe(legalCopy.pages.terms.title);
    });
  });

  it('leaves a press with a modifier key or another button to the browser', () => {
    stop = startLegal(app);
    const onopen = vi.fn();
    const [privacy] = show(onopen);
    // Heard after the link's own handler: whether it left the press alone, then the press is
    // stopped here, as jsdom follows no link to another page.
    const left: boolean[] = [];
    const after = (event: Event): void => {
      left.push(!event.defaultPrevented);
      event.preventDefault();
    };
    window.addEventListener('click', after);
    try {
      for (const init of [
        { ctrlKey: true },
        { metaKey: true },
        { shiftKey: true },
        { button: 1 },
      ]) {
        privacy?.dispatchEvent(
          new MouseEvent('click', { bubbles: true, cancelable: true, ...init }),
        );
      }
    } finally {
      window.removeEventListener('click', after);
    }
    expect(left).toEqual([true, true, true, true]);
    expect(onopen).not.toHaveBeenCalled();
    expect(location.search).toBe('?ref=x');
  });
});
