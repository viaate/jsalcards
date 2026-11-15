import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { legalCopy, type LegalPageName } from '../../copy-legal';
import LegalPage from '../LegalPage.svelte';
import { APPROVED, approvedWords, words } from './legal-words';

const CONTACT = 'hello@snowlightmap.com';

/** The page as shown, as words: each heading, paragraph, list item and table cell in order. */
function shownWords(root: ParentNode): string {
  const parts = [...root.querySelectorAll('h1, h2, p, li, th, td')].map((node) => node.textContent);
  return words(parts.join(' '));
}

describe('LegalPage', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(page: LegalPageName, onclose = vi.fn()): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(LegalPage, { target, props: { page, onclose } });
    flushSync();
    return target;
  }

  it('holds the approved text whole: the split file is the spec’s two pages', () => {
    expect(APPROVED.startsWith('# Privacy policy\n')).toBe(true);
    expect(APPROVED).toContain('\n# Terms of use\n');
    expect(approvedWords('privacy')).toContain('Questions or requests: hello@snowlightmap.com.');
    expect(approvedWords('terms')).toMatch(/^Terms of use Snowlight shows school closings/u);
  });

  it.each(['privacy', 'terms'] as const)('shows the %s page word for word as approved', (page) => {
    const target = show(page);
    expect(shownWords(target)).toBe(approvedWords(page));
  });

  it.each(['privacy', 'terms'] as const)(
    'gives the %s page its heading, its sections and the contact address',
    (page) => {
      const target = show(page);
      const doc = legalCopy.pages[page];
      const dialog = target.querySelector('[role="dialog"]');
      expect(dialog?.getAttribute('aria-labelledby')).toBe('legal-title');
      expect(target.querySelector('h1')?.textContent).toBe(doc.title);
      expect([...target.querySelectorAll('h2')].map((h) => h.textContent)).toEqual(
        doc.sections.map((section) => section.heading),
      );
      expect(target.textContent).toContain(CONTACT);
      // The heading has the keyboard, so a screen reader starts at the top.
      expect(document.activeElement).toBe(target.querySelector('h1'));
    },
  );

  it('shows the privacy table with its heading row and an empty cell where the draft has one', () => {
    const target = show('privacy');
    const table = target.querySelector('table');
    expect([...(table?.querySelectorAll('thead th') ?? [])].map((th) => th.textContent)).toEqual([
      'When',
      'What we keep',
      'Why',
    ]);
    const rows = [...(table?.querySelectorAll('tbody tr') ?? [])];
    expect(rows).toHaveLength(6);
    expect(rows[0]?.querySelector('th')?.getAttribute('scope')).toBe('row');
    expect(rows[0]?.querySelectorAll('td')[1]?.textContent).toBe('');
  });

  it('bolds each lead, with a space before the words that follow it and none before a comma', () => {
    const target = show('privacy');
    const items = [...target.querySelectorAll('li')].filter((li) => li.querySelector('strong'));
    expect(items.map((li) => li.querySelector('strong')?.textContent)).toEqual([
      'Cloudflare',
      'GitHub',
      'Apple, Google, Microsoft or Mozilla',
      'Kit',
      'OpenFreeMap',
    ]);
    expect(items[0]?.textContent.trim()).toBe(
      'Cloudflare runs our accounts service and its database.',
    );
    expect(items[2]?.textContent.trim()).toMatch(/^Apple, Google, Microsoft or Mozilla, through /u);
  });

  it('closes on Escape and on its close button', () => {
    const onclose = vi.fn();
    const target = show('terms', onclose);
    target
      .querySelector('h1')
      ?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(onclose).toHaveBeenCalledTimes(1);
    target.querySelector<HTMLButtonElement>('button.close')?.click();
    expect(onclose).toHaveBeenCalledTimes(2);
  });
});
