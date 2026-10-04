import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AreaView } from '../../app/area';
import type { SchoolView } from '../../app/school';
import { copy } from '../../copy';
import AreaPanel from '../AreaPanel.svelte';
import DetailPanel from '../DetailPanel.svelte';

/** An area's view as app/area.ts makes one, made up for these tests. */
const VIEW: AreaView = {
  zip: '64112',
  place: 'Kansas City, MO',
  label: 'Schools around 64112',
  back: 'Back to 64112',
  chance: null,
  counts: [],
  heading: '2 schools in 64112',
  own: [
    {
      id: 'ZZ000001',
      name: 'The Test Hill School',
      kind: `${copy.detail.privateSchool} · PK–12`,
      distance: '0.1 mi',
      tone: null,
      lon: -94.593,
      lat: 39.036,
    },
    {
      id: 'ZZ000002',
      name: 'Visitation Test School',
      kind: `${copy.detail.privateSchool} · K–8`,
      distance: '0.4 mi',
      tone: 'closed',
      lon: -94.6,
      lat: 39.03,
    },
  ],
  nearHeading: '1 more within 2 miles',
  near: [
    {
      id: '290000000003',
      name: 'Test Village High School',
      kind: `${copy.detail.charterSchool} · 9–12`,
      distance: '1.1 mi',
      tone: null,
      lon: -94.58,
      lat: 39.05,
    },
  ],
  noneNear: null,
  loading: false,
};

describe('AreaPanel', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(view: AreaView) {
    const target = document.createElement('div');
    document.body.append(target);
    const props = { view, onclose: vi.fn(), onschool: vi.fn() };
    component = mount(AreaPanel, { target, props });
    flushSync();
    const panel = target.querySelector('aside.detail');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    return { panel, props };
  }

  it('names the ZIP code and its place, and lists its schools, then the others taken in', () => {
    const { panel } = show(VIEW);
    expect(panel.getAttribute('aria-label')).toBe('Schools around 64112');
    expect(panel.querySelector('h2')?.textContent).toBe('64112');
    expect(panel.querySelector('.place')?.textContent).toBe('Kansas City, MO');
    expect([...panel.querySelectorAll('.heading')].map((h) => h.textContent)).toEqual([
      '2 schools in 64112',
      '1 more within 2 miles',
    ]);
    const rows = [...panel.querySelectorAll('button.school')].map((row) => [
      row.querySelector('.label')?.textContent,
      row.querySelector('.name-text')?.textContent,
      row.querySelector('.kind')?.textContent,
      row.querySelector('.glyph')?.className.includes('is-closed') ?? false,
    ]);
    expect(rows).toEqual([
      ['0.1 mi', 'The Test Hill School', VIEW.own[0]?.kind, false],
      ['0.4 mi', 'Visitation Test School', VIEW.own[1]?.kind, true],
      ['1.1 mi', 'Test Village High School', VIEW.near[0]?.kind, false],
    ]);
  });

  it('shows no chance, no number and no words for one, with no chance to give', () => {
    const { panel } = show(VIEW);
    expect(panel.querySelector('.number, .meaning, .why, .chart')).toBeNull();
    expect(panel.textContent).not.toMatch(/%|chance|enough data/iu);
    // No status today: no count of them either.
    expect(panel.querySelector('.counts')).toBeNull();
  });

  it('heads with the chance, who decides, what it leaves out, then counts today’s statuses', () => {
    const { panel } = show({
      ...VIEW,
      counts: [{ status: 'closed', text: '1 closed' }],
      chance: {
        day: '2026-01-13',
        number: '64',
        meaning: 'Chance of no school Tuesday',
        why: [{ key: 'a', number: '64%', text: 'Test Village decides for 1 school here.' }],
        left: '2 of the 3 schools here have no chance given for Tuesday and are left out.',
        chart: null,
        announces: () => null,
      },
    });
    expect(panel.querySelector('.number')?.textContent).toBe('64%');
    expect(panel.querySelector('.meaning')?.textContent.trim()).toBe(
      '64% Chance of no school Tuesday',
    );
    expect(panel.querySelector('.why .row')?.textContent.replace(/\s+/gu, ' ').trim()).toBe(
      '64% Test Village decides for 1 school here.',
    );
    expect(panel.querySelector('.left')?.textContent).toMatch(/^2 of the 3 schools/u);
    expect(panel.querySelector('.tally .label')?.textContent).toBe(copy.days.today);
    expect(panel.querySelector('.counts')?.textContent.trim()).toBe('1 closed');
    // Over the whole list, so above its first heading rather than under it.
    const heading = panel.querySelector('#area-schools');
    expect(heading).not.toBeNull();
    expect(
      (panel.querySelector('.tally')?.compareDocumentPosition(heading as Node) ?? 0) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('opens a school from its row, and closes', () => {
    const { panel, props } = show(VIEW);
    panel.querySelectorAll<HTMLButtonElement>('button.school')[2]?.click();
    expect(props.onschool).toHaveBeenCalledWith(VIEW.near[0]);
    panel.querySelector<HTMLButtonElement>('button.close')?.click();
    expect(props.onclose).toHaveBeenCalled();
  });

  it('shows the shape of the list while it reads', () => {
    const { panel } = show({ ...VIEW, own: [], near: [], nearHeading: null, loading: true });
    expect(panel.getAttribute('aria-busy')).toBe('true');
    expect(panel.querySelectorAll('.bone').length).toBeGreaterThan(0);
    expect(panel.querySelector('.heading')).toBeNull();
  });
});

describe('a school opened from an area', () => {
  it('goes back to the area from the top of its panel', () => {
    const target = document.createElement('div');
    document.body.append(target);
    const onback = vi.fn();
    const view: SchoolView = {
      id: 'ZZ000001',
      name: 'The Test Hill School',
      campus: null,
      kind: copy.detail.privateSchool,
      place: null,
      status: [],
      chance: null,
      facts: [],
      nearby: [],
      loading: false,
    };
    const props = { view, pinned: false, copied: false, onclose: vi.fn(), onpin: vi.fn() };
    const panel = mount(DetailPanel, {
      target,
      props: { ...props, back: { label: 'Back to 64112', onback } },
    });
    flushSync();
    const back = target.querySelector<HTMLButtonElement>('.head button.back');
    expect(back?.textContent.trim()).toBe('Back to 64112');
    back?.click();
    expect(onback).toHaveBeenCalled();
    void unmount(panel);
    const plain = mount(DetailPanel, { target, props });
    flushSync();
    expect(target.querySelector('button.back')).toBeNull();
    void unmount(plain);
  });
});
