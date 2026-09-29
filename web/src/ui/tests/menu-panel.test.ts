import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MenuView } from '../../app/menu';
import { STATUS_KEYS, copy, format } from '../../copy';
import type { StatusCounts } from '../../data/closings';
import { SHOW_ALL, withKind, withStatus } from '../../state/filter';
import type { MapFilter } from '../../state/filter';
import { Status } from '../../types/generated';
import MenuPanel from '../MenuPanel.svelte';

/** A menu's view as app/menu.ts makes one, made up for these tests. */
const FULL: MenuView = {
  season: {
    title: copy.nav.seasonStats,
    note: '2025–26 · Through Jan 13',
    rows: [
      { label: copy.season.schoolsAffected, value: '51', tone: null },
      { label: copy.season.closures, value: '60', tone: 'closed' },
      { label: copy.season.delays, value: '26', tone: 'delayed' },
    ],
  },
  record: {
    title: copy.nav.trackRecord,
    note: 'Dec 1, 2025 to Jan 13, 2026',
    caption: copy.trackRecord.caption,
    columns: [copy.trackRecord.chanceGiven, 'Same morning', 'Day before'],
    rows: [
      { label: '0–10%', cells: ['1 of 40', '2 of 38'] },
      { label: '10–20%', cells: ['2 of 12', null] },
    ],
  },
  map: {
    title: copy.menu.onMap,
    note: null,
    rows: [
      { label: copy.menu.schools, value: '3', tone: null },
      { label: copy.menu.districts, value: '1', tone: null },
    ],
  },
};

const NOTHING: MenuView = { season: null, record: null, map: null };

interface Shown {
  panel: HTMLElement;
  onfilter: ReturnType<typeof vi.fn<(filter: MapFilter) => void>>;
}

describe('MenuPanel', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(
    view: MenuView,
    filter: MapFilter = SHOW_ALL,
    counts: StatusCounts | null = null,
  ): Shown {
    const target = document.createElement('div');
    document.body.append(target);
    const onfilter = vi.fn<(filter: MapFilter) => void>();
    component = mount(MenuPanel, { target, props: { view, id: 'menu', filter, counts, onfilter } });
    flushSync();
    const panel = target.querySelector('aside.menu');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    return { panel, onfilter };
  }

  const headings = (panel: HTMLElement): string[] =>
    [...panel.querySelectorAll('h2')].map((heading) => heading.textContent.trim());

  /** Each row of the list: its name, what it counts at the right, and whether it is in use. */
  const items = (panel: HTMLElement): [string, string, boolean][] =>
    [...panel.querySelectorAll('.item')].map((item) => [
      item.querySelector('.name')?.textContent.trim() ?? '',
      item.querySelector('.value')?.textContent.trim() ?? '',
      item.classList.contains('is-on'),
    ]);

  const radios = (panel: HTMLElement): HTMLInputElement[] => [
    ...panel.querySelectorAll<HTMLInputElement>('input[type="radio"]'),
  ];

  const checkboxes = (panel: HTMLElement): HTMLInputElement[] => [
    ...panel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
  ];

  it('lists what the map shows today and which schools, then About, with nothing to count', () => {
    const { panel } = show(NOTHING);
    expect(panel.id).toBe('menu');
    expect(panel.getAttribute('aria-label')).toBe(copy.menu.label);
    expect(headings(panel)).toEqual([copy.menu.today, copy.menu.kinds]);
    // All four statuses on a filled pill, each status after it with the legend's mark; both
    // kinds of school shown; About opens a page of its own.
    expect(items(panel)).toEqual([
      [copy.menu.all, '', true],
      ...STATUS_KEYS.map((key): [string, string, boolean] => [copy.status[key], '', false]),
      [copy.menu.public, '', false],
      [copy.menu.private, '', false],
      [copy.nav.about, '', false],
    ]);
    const marks = [...panel.querySelectorAll('[role="radiogroup"] .glyph')].map(
      (glyph) => [...glyph.classList].find((name) => name.startsWith('is-')) ?? null,
    );
    expect(marks).toEqual(['is-closed', 'is-delayed', 'is-remote', 'is-early-dismissal']);
    // Every row has its 16px icon, ahead of its name.
    for (const item of panel.querySelectorAll('.item')) {
      expect(item.querySelector('.icon')?.getAttribute('aria-hidden')).toBe('true');
    }

    // The statuses are one choice, named by their heading; the kinds are each on or off.
    const group = panel.querySelector('[role="radiogroup"]');
    expect(document.getElementById(group?.getAttribute('aria-labelledby') ?? '')?.textContent).toBe(
      copy.menu.today,
    );
    expect(radios(panel).map((radio) => radio.checked)).toEqual([true, false, false, false, false]);
    expect(new Set(radios(panel).map((radio) => radio.name)).size).toBe(1);
    expect(checkboxes(panel).map((box) => box.checked)).toEqual([true, true]);
    // Each control is named by its row's words.
    for (const control of [...radios(panel), ...checkboxes(panel)]) {
      expect(control.closest('label')?.querySelector('.name')?.textContent).not.toBe('');
    }

    // Never the site's name (the wordmark says it), how to search (the field says it), or an
    // apology for what is not there.
    expect(panel.textContent).not.toContain(copy.appName);
    expect(panel.textContent).not.toMatch(/search/iu);
    expect(panel.textContent).not.toMatch(/not enough|no data|yet/iu);
  });

  it('gives each status its count today, and all of them theirs together', () => {
    const { panel } = show(NOTHING, SHOW_ALL, [1204, 310, 0, 7]);
    expect(items(panel).slice(0, 5)).toEqual([
      [copy.menu.all, format.number(1521), true],
      [copy.status.closed, format.number(1204), false],
      [copy.status.delayed, format.number(310), false],
      [copy.status.remote, '', false],
      [copy.status.earlyDismissal, format.number(7), false],
    ]);
  });

  it('puts the pill on the status the map shows, and takes the tick off a kind it hides', () => {
    const { panel } = show(
      NOTHING,
      withKind(withStatus(SHOW_ALL, Status.delayed), 'private', false),
    );
    expect(items(panel).filter(([, , on]) => on)).toEqual([[copy.status.delayed, '', true]]);
    expect(radios(panel).map((radio) => radio.checked)).toEqual([false, false, true, false, false]);
    expect(checkboxes(panel).map((box) => box.checked)).toEqual([true, false]);
    const kinds = [...panel.querySelectorAll('.check')];
    expect(kinds.map((row) => row.classList.contains('is-off'))).toEqual([false, true]);
  });

  it('asks the page to show one status, all four, or a kind of school on or off', () => {
    const { panel, onfilter } = show(NOTHING);
    radios(panel)[1]?.click();
    expect(onfilter).toHaveBeenLastCalledWith(withStatus(SHOW_ALL, Status.closed));
    radios(panel)[4]?.click();
    expect(onfilter).toHaveBeenLastCalledWith(withStatus(SHOW_ALL, Status.early_dismissal));
    checkboxes(panel)[1]?.click();
    expect(onfilter).toHaveBeenLastCalledWith(withKind(SHOW_ALL, 'private', false));
    checkboxes(panel)[0]?.click();
    expect(onfilter).toHaveBeenLastCalledWith(withKind(SHOW_ALL, 'public', false));
    expect(onfilter).toHaveBeenCalledTimes(4);
  });

  it('opens the season, the track record and About, each on a page with its way back', async () => {
    const { panel } = show(FULL);
    expect(items(panel).slice(7)).toEqual([
      [copy.nav.seasonStats, '', false],
      [copy.nav.trackRecord, '', false],
      [copy.nav.about, '', false],
    ]);
    const open = (page: string): void => {
      panel.querySelector<HTMLButtonElement>(`button[data-page="${page}"]`)?.click();
      flushSync();
    };
    const back = (): HTMLButtonElement => {
      const found = panel.querySelector<HTMLButtonElement>('button.back');
      if (found === null) throw new Error('no way back');
      return found;
    };
    const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

    // The season: its heading beside the way back, the season it counts, and its rows.
    open('season');
    await settle();
    expect(back().getAttribute('aria-label')).toBe(copy.detail.back);
    expect(document.activeElement).toBe(back());
    const page = panel.querySelector('section.page');
    expect(document.getElementById(page?.getAttribute('aria-labelledby') ?? '')?.textContent).toBe(
      copy.nav.seasonStats,
    );
    expect(panel.querySelector('.note')?.textContent).toBe('2025–26 · Through Jan 13');
    const rows = [...panel.querySelectorAll('.row')].map((row) => [
      row.querySelector('dt')?.textContent.trim(),
      row.querySelector('dd')?.textContent.trim(),
      [...(row.querySelector('.glyph')?.classList ?? [])].find((name) => name.startsWith('is-')) ??
        null,
    ]);
    expect(rows).toEqual([
      [copy.season.schoolsAffected, '51', null],
      [copy.season.closures, '60', 'is-closed'],
      [copy.season.delays, '26', 'is-delayed'],
    ]);
    expect(panel.querySelector('[role="radiogroup"]')).toBeNull();

    // Back to the list, the keyboard on the row it went from.
    back().click();
    flushSync();
    await settle();
    expect(panel.querySelector('section.page')).toBeNull();
    expect(document.activeElement).toBe(panel.querySelector('button[data-page="season"]'));

    // The track record's table: the chance given, then a column for each lead.
    open('record');
    await settle();
    const table = panel.querySelector('table');
    expect(table?.querySelector('caption')?.textContent).toBe(copy.trackRecord.caption);
    expect([...(table?.querySelectorAll('thead th') ?? [])].map((th) => th.textContent)).toEqual(
      FULL.record?.columns,
    );
    const cells = [...(table?.querySelectorAll('tbody tr') ?? [])].map((row) =>
      [...row.children].map((cell) => [cell.tagName, cell.textContent.trim()]),
    );
    expect(cells).toEqual([
      [
        ['TH', '0–10%'],
        ['TD', '1 of 40'],
        ['TD', '2 of 38'],
      ],
      [
        ['TH', '10–20%'],
        ['TD', '2 of 12'],
        ['TD', ''],
      ],
    ]);
    expect(table?.querySelector('tbody th')?.getAttribute('scope')).toBe('row');
    back().click();
    flushSync();

    // About: what the site is and how to read its lights, then what the map holds.
    open('about');
    await settle();
    expect(panel.querySelector('.lead')?.textContent).toBe(copy.about.what);
    expect([...panel.querySelectorAll('.text')].map((line) => line.textContent)).toEqual([
      copy.about.glow,
    ]);
    const map = [...panel.querySelectorAll('.row')].map((row) =>
      row.textContent.replace(/\s+/gu, ' ').trim(),
    );
    expect(map).toEqual([`${copy.menu.schools} 3`, `${copy.menu.districts} 1`]);
  });

  it('shows About alone when nothing is counted: its two lines, no rows', () => {
    const { panel } = show(NOTHING);
    panel.querySelector<HTMLButtonElement>('button[data-page="about"]')?.click();
    flushSync();
    expect(panel.querySelector('.lead')?.textContent).toBe(copy.about.what);
    expect(panel.querySelector('dl, table')).toBeNull();
  });

  it('can take focus when it opens, without being a stop in the tab order', () => {
    const { panel } = show(FULL);
    expect(panel.getAttribute('tabindex')).toBe('-1');
    panel.focus();
    expect(document.activeElement).toBe(panel);
  });
});
