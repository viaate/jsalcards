import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { searchOptions } from '../../app/search';
import type { SearchOption } from '../../app/search';
import { copy } from '../../copy';
import type { SearchHit } from '../../search';
import SearchResults from '../SearchResults.svelte';

/** A hit whose name matched "Kansas City" where it has those words. */
function hit(kind: SearchHit['kind'], id: string, name: string, sub: string): SearchHit {
  const at = name.toUpperCase().indexOf('KANSAS CITY');
  return {
    kind,
    id,
    name,
    sub,
    state: 'MO',
    lat: 39.1,
    lon: -94.6,
    match: 'exact',
    highlight: [[at, at + 'KANSAS CITY'.length]],
  };
}

/** "Kansas City" as the real index answers it, shortened: places, then districts and schools. */
const OPTIONS = searchOptions(
  {
    query: 'Kansas City',
    cities: [
      hit('city', '2938000', 'Kansas City', 'Missouri'),
      { ...hit('city', '2036000', 'Kansas City', 'Kansas'), state: 'KS' },
    ],
    schools: [
      hit('district', '2916400', 'KANSAS CITY 33', 'Kansas City, MO'),
      hit('school', '292280001284', 'NORTH KANSAS CITY HIGH', 'Kansas City, MO'),
    ],
    zips: [],
    order: ['cities', 'schools', 'zips'],
  },
  'list',
);

describe('SearchResults', () => {
  let component: ReturnType<typeof mount> | undefined;

  function clear(): void {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  }

  afterEach(clear);

  function show(
    options: readonly SearchOption[],
    active = -1,
    onpick = vi.fn(),
    onactive = vi.fn(),
  ): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(SearchResults, {
      target,
      props: { id: 'list', options, active, onpick, onactive },
    });
    flushSync();
    return target;
  }

  it('lists each kind of result as a group under its heading, in list order', () => {
    const target = show(OPTIONS);
    const listbox = target.querySelector('[role="listbox"]');
    expect(listbox?.id).toBe('list');
    expect(listbox?.getAttribute('aria-label')).toBe(copy.search.results);
    const groups = [...target.querySelectorAll('[role="listbox"] > [role="group"]')];
    const headings = groups.map((group) => {
      const heading = document.getElementById(group.getAttribute('aria-labelledby') ?? '');
      return heading?.textContent.trim();
    });
    expect(headings).toEqual([
      copy.search.sections.city,
      copy.search.sections.district,
      copy.search.sections.school,
    ]);
    // The heading names its group once, to a screen reader, through the group.
    for (const group of groups) {
      expect(group.querySelector('.heading')?.getAttribute('aria-hidden')).toBe('true');
    }
    const ids = [...target.querySelectorAll('[role="option"]')].map((option) => option.id);
    expect(ids).toEqual(['list-0', 'list-1', 'list-2', 'list-3']);
    expect(groups.map((group) => group.querySelectorAll('[role="option"]').length)).toEqual([
      2, 1, 1,
    ]);
  });

  it('shows each name as shown, what matched in bold, and its place under it', () => {
    const target = show(OPTIONS);
    const school = target.querySelector('#list-3');
    expect(school?.querySelector('.name')?.textContent).toBe('North Kansas City High');
    expect(school?.querySelector('.name b')?.textContent).toBe('Kansas City');
    expect(school?.querySelector('.sub')?.textContent).toBe('Kansas City, MO');
    expect(target.querySelector('#list-0 .sub')?.textContent).toBe('Missouri');
  });

  it('marks the option Enter picks: the first, then the highlighted one', () => {
    let target = show(OPTIONS);
    const marked = (): string[] =>
      [...target.querySelectorAll('.is-target')].map((option) => option.id);
    expect(marked()).toEqual(['list-0']);
    expect(target.querySelector('#list-0')?.getAttribute('aria-selected')).toBe('false');
    clear();
    target = show(OPTIONS, 2);
    expect(marked()).toEqual(['list-2']);
    expect(target.querySelector('#list-2')?.getAttribute('aria-selected')).toBe('true');
  });

  it('picks on a click and highlights under the pointer, keeping focus where it is', () => {
    const onpick = vi.fn();
    const onactive = vi.fn();
    const target = show(OPTIONS, -1, onpick, onactive);
    const option = target.querySelector<HTMLElement>('#list-2');
    const press = new Event('pointerdown', { bubbles: true, cancelable: true });
    option?.dispatchEvent(press);
    expect(press.defaultPrevented).toBe(true);
    option?.dispatchEvent(new Event('pointermove', { bubbles: true }));
    expect(onactive).toHaveBeenCalledWith(2);
    option?.click();
    expect(onpick).toHaveBeenCalledWith(OPTIONS[2]);
  });

  it('says plainly when nothing matches', () => {
    const target = show([]);
    expect(target.querySelector('[role="listbox"]')).toBeNull();
    expect(target.querySelector('.empty')?.textContent).toBe(copy.search.noResults);
  });
});
