import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { legalCopy } from '../../copy-legal';
import {
  LEGAL_EVENT,
  LEGAL_HREF_EVENT,
  closeLegal,
  legalHref,
  legalPageOf,
  lockUp,
  openLegal,
  startLegal,
} from '../legal';

describe('legalPageOf', () => {
  it.each([
    ['?privacy', 'privacy'],
    ['?terms', 'terms'],
    ['privacy', 'privacy'],
    ['?privacy=', 'privacy'],
    ['?school=0100005&terms', 'terms'],
    ['?v=40.1,-75.2,5&privacy&x=1', 'privacy'],
    ['?%70rivacy', 'privacy'],
  ] as const)('reads %j as the %s page', (search, page) => {
    expect(legalPageOf(search)).toBe(page);
  });

  it.each(['', '?', '?admin', '?privacy-policy', '?q=privacy', '?termsx', '?%E0%A4%A'])(
    'reads %j as neither',
    (search) => {
      expect(legalPageOf(search)).toBeNull();
    },
  );
});

describe('legalHref', () => {
  it('puts the page last and keeps every other part as it is written', () => {
    expect(legalHref('https://snowlightmap.com/', 'privacy')).toBe(
      'https://snowlightmap.com/?privacy',
    );
    expect(legalHref('https://snowlightmap.com/?v=40.1,-75.2,5&school=1', 'terms')).toBe(
      'https://snowlightmap.com/?v=40.1,-75.2,5&school=1&terms',
    );
    expect(legalHref('https://snowlightmap.com/?privacy&v=1#x', 'terms')).toBe(
      'https://snowlightmap.com/?v=1&terms#x',
    );
  });

  it('takes both pages out for null, and leaves no empty query', () => {
    expect(legalHref('https://snowlightmap.com/?privacy', null)).toBe('https://snowlightmap.com/');
    expect(legalHref('https://snowlightmap.com/?a=1&terms=&privacy&b=2', null)).toBe(
      'https://snowlightmap.com/?a=1&b=2',
    );
  });
});

describe('startLegal', () => {
  let stop: (() => void) | undefined;
  let app: HTMLElement;

  beforeEach(() => {
    history.replaceState(null, '', '/');
    app = document.createElement('div');
    app.id = 'app';
    document.body.append(app);
  });

  afterEach(() => {
    stop?.();
    stop = undefined;
    document.body.innerHTML = '';
    history.replaceState(null, '', '/');
  });

  const title = (): string | null | undefined => app.querySelector('h1')?.textContent;

  it('shows nothing and loads nothing where the address asks for neither page', async () => {
    history.replaceState(null, '', '/?v=40,-75,5');
    stop = startLegal(app);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(app.querySelector('[role="dialog"]')).toBeNull();
  });

  it('shows the page the address opens with, and closing it takes it out of the address', async () => {
    history.replaceState(null, '', '/?v=40,-75,5&privacy');
    stop = startLegal(app);
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.privacy.title);
    });
    closeLegal();
    expect(app.querySelector('[role="dialog"]')).toBeNull();
    expect(location.search).toBe('?v=40,-75,5');
  });

  it('opens a page in place with its own history entry, which Back closes, focus back where it was', async () => {
    stop = startLegal(app);
    const link = document.createElement('a');
    link.href = '#';
    document.body.append(link);
    link.focus();
    const entries = history.length;
    openLegal('terms');
    expect(location.search).toBe('?terms');
    expect(history.length).toBe(entries + 1);
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.terms.title);
    });
    history.back();
    await vi.waitFor(() => {
      expect(app.querySelector('[role="dialog"]')).toBeNull();
    });
    expect(location.search).toBe('');
    expect(document.activeElement).toBe(link);
  });

  it('follows Back and Forward between the pages', async () => {
    stop = startLegal(app);
    openLegal('privacy');
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.privacy.title);
    });
    history.replaceState(null, '', '/?terms');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.terms.title);
    });
    expect(app.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  });

  it('opens the page a Settings link names by its event, and ignores any other name', async () => {
    stop = startLegal(app);
    window.dispatchEvent(new CustomEvent(LEGAL_EVENT, { detail: 'admin' }));
    window.dispatchEvent(new Event(LEGAL_EVENT));
    expect(location.search).toBe('');
    window.dispatchEvent(new CustomEvent(LEGAL_EVENT, { detail: 'terms' }));
    expect(location.search).toBe('?terms');
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.terms.title);
    });
  });

  it('writes the address a Settings link asks for, every other part kept, and ignores any other', () => {
    history.replaceState(null, '', '/?v=40,-75,5&ref=x');
    const ask = (detail: unknown): unknown => {
      window.dispatchEvent(new CustomEvent(LEGAL_HREF_EVENT, { detail }));
      return detail;
    };
    // Until the module has started, the link keeps the page's name alone.
    expect(ask({ page: 'terms', href: '?terms' })).toEqual({ page: 'terms', href: '?terms' });
    stop = startLegal(app);
    expect(ask({ page: 'terms', href: '?terms' })).toEqual({
      page: 'terms',
      href: `${location.origin}/?v=40,-75,5&ref=x&terms`,
    });
    expect(ask({ page: 'privacy', href: '?privacy' })).toEqual({
      page: 'privacy',
      href: `${location.origin}/?v=40,-75,5&ref=x&privacy`,
    });
    expect(ask({ page: 'admin', href: '?admin' })).toEqual({ page: 'admin', href: '?admin' });
    expect(ask('terms')).toBe('terms');
    expect(ask(null)).toBeNull();
    stop();
    stop = undefined;
    expect(ask({ page: 'terms', href: '?terms' })).toEqual({ page: 'terms', href: '?terms' });
  });

  /**
   * Any way a file could take in the pages' code: an import of app/legal (any depth, any
   * extension, legal.ts or a module beside it such as legal-page.ts, static or dynamic), the
   * page's component, or the pages' words (copy-legal.ts; the links' own two labels,
   * copy-legal-links.ts, are not the pages').
   */
  const PAGE_CODE =
    /(?:from|import\s*\()\s*['"`](?:\.{1,2}\/)+app\/legal|LegalPage\.svelte|copy-legal(?!-links\b)/u;

  it('knows every way the pages’ code could come in, and lets the links’ own imports through', () => {
    for (const line of [
      "import { startLegal } from '../../app/legal';",
      "import { startLegal } from '../../app/legal.ts';",
      "import { startLegal } from '../../app/legal.js';",
      "import x from '../../app/legal-page.ts';",
      "import { startLegal } from '../app/legal';",
      'import { startLegal } from "../app/legal";',
      "const legal = await import('../app/legal');",
      "import LegalPage from './LegalPage.svelte';",
      "import { legalCopy } from '../copy-legal';",
      "import { legalCopy } from '../../copy-legal.ts';",
    ]) {
      expect(line, line).toMatch(PAGE_CODE);
    }
    for (const line of [
      "import LegalLinks from '../LegalLinks.svelte';",
      "import LegalLinks from './LegalLinks.svelte';",
      "import { legalLinksCopy } from '../copy-legal-links';",
      "import { legalLinksCopy } from '../copy-legal-links.ts';",
    ]) {
      expect(line, line).not.toMatch(PAGE_CODE);
    }
  });

  it('is the events the links send, in Settings and in the menu, with none of the page code', () => {
    const read = (file: string): string =>
      readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), file), 'utf8');
    const links = read('../../ui/LegalLinks.svelte');
    expect(links).toContain(`new CustomEvent('${LEGAL_EVENT}', { detail: page })`);
    expect(links).toContain(`new CustomEvent('${LEGAL_HREF_EVENT}', { detail: ask })`);
    expect(links).not.toMatch(/from '\.\.\/app\/legal/u);
    expect(links).not.toMatch(PAGE_CODE);
    // Settings and the menu show the links, and neither carries the pages' code.
    const sheet = read('../../ui/account/AccountSheet.svelte');
    expect(sheet).not.toMatch(/from '\.\.\/\.\.\/app\/legal/u);
    expect(sheet).not.toMatch(/LegalPage\.svelte/u);
    const menu = read('../../ui/MenuPanel.svelte');
    expect(menu).not.toMatch(/from '\.\.\/app\/legal/u);
    for (const [file, source] of [
      ['ui/account/AccountSheet.svelte', sheet],
      ['ui/MenuPanel.svelte', menu],
    ] as const) {
      expect(source, file).toMatch(
        /import LegalLinks from '\.\.?\/(?:\.\.\/)?LegalLinks\.svelte'/u,
      );
      expect(source, file).toMatch(/<LegalLinks\b/u);
      expect(source, file).not.toMatch(PAGE_CODE);
    }
  });

  it('stops: the page goes and the address is no longer followed', async () => {
    history.replaceState(null, '', '/?privacy');
    stop = startLegal(app);
    await vi.waitFor(() => {
      expect(title()).toBe(legalCopy.pages.privacy.title);
    });
    stop();
    stop = undefined;
    expect(app.querySelector('[role="dialog"]')).toBeNull();
    window.dispatchEvent(new PopStateEvent('popstate'));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(app.querySelector('[role="dialog"]')).toBeNull();
  });
});

describe('behind the code screen', () => {
  let stop: (() => void) | undefined;
  let app: HTMLElement;
  let lock: HTMLElement;
  let input: HTMLInputElement;

  beforeEach(() => {
    history.replaceState(null, '', '/');
    app = document.createElement('div');
    app.id = 'app';
    lock = document.createElement('div');
    lock.id = 'lock';
    input = document.createElement('input');
    input.id = 'lock-input';
    lock.append(input);
    document.body.append(app, lock);
    input.focus();
  });

  afterEach(() => {
    stop?.();
    stop = undefined;
    document.body.innerHTML = '';
    document.documentElement.className = '';
    history.replaceState(null, '', '/');
  });

  const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 30));
  const dialog = (): Element | null => document.querySelector('[role="dialog"]');

  it('reads the screen as up while it is in the page and drawn, and as gone otherwise', () => {
    expect(lockUp()).toBe(true);
    lock.hidden = true;
    expect(lockUp()).toBe(false);
    lock.hidden = false;
    lock.style.display = 'none';
    expect(lockUp()).toBe(false);
    lock.style.display = '';
    lock.style.visibility = 'hidden';
    expect(lockUp()).toBe(false);
    lock.style.visibility = '';
    document.body.style.display = 'none';
    expect(lockUp()).toBe(false);
    document.body.style.display = '';
    lock.remove();
    expect(lockUp()).toBe(false);
  });

  it.each(['privacy', 'terms'] as const)(
    'puts nothing of ?%s in the page while it is up, and leaves the keyboard with the code',
    async (page) => {
      history.replaceState(null, '', `/?${page}`);
      stop = startLegal(app);
      await settle();
      expect(dialog()).toBeNull();
      expect(document.querySelector('.legal')).toBeNull();
      expect(document.body.textContent).not.toContain(legalCopy.pages[page].title);
      expect(document.activeElement).toBe(input);
    },
  );

  it('puts nothing in the page for a Settings link either while it is up', async () => {
    stop = startLegal(app);
    window.dispatchEvent(new CustomEvent(LEGAL_EVENT, { detail: 'terms' }));
    await settle();
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(input);
  });

  it.each([
    [
      'taken out of the page',
      (screen: HTMLElement): void => {
        screen.remove();
      },
    ],
    [
      'hidden',
      (screen: HTMLElement): void => {
        screen.hidden = true;
      },
    ],
    [
      'hidden by a class on the page',
      (): void => {
        const style = document.createElement('style');
        style.textContent = '.is-app #lock { display: none; }';
        document.head.append(style);
        document.documentElement.classList.add('is-app');
      },
    ],
  ] as const)('shows the page asked for once the code is in and the screen %s', async (_, go) => {
    history.replaceState(null, '', '/?privacy');
    stop = startLegal(app);
    await settle();
    expect(dialog()).toBeNull();
    go(lock);
    await vi.waitFor(() => {
      expect(app.querySelector('h1')?.textContent).toBe(legalCopy.pages.privacy.title);
    });
    expect(document.activeElement?.id).toBe('legal-title');
  });

  it('shows nothing once the code is in when the address no longer asks for a page', async () => {
    history.replaceState(null, '', '/?privacy');
    stop = startLegal(app);
    await settle();
    history.replaceState(null, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
    lock.remove();
    await settle();
    expect(dialog()).toBeNull();
  });
});
