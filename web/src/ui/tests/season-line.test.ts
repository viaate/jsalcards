import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SchoolView } from '../../app/school';
import { seasonFormat } from '../../copy-season';
import DetailPanel from '../DetailPanel.svelte';

/** A school's view as app/school.ts makes one, made up for these tests. */
const VIEW: SchoolView = {
  id: 'ZZ000001',
  name: 'The Test Hill School',
  campus: null,
  kind: null,
  place: null,
  status: [],
  chance: null,
  facts: [],
  nearby: [],
  loading: false,
};

describe('the panel’s season line', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(view: SchoolView): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(DetailPanel, {
      target,
      props: { view, pinned: false, copied: false, onclose: vi.fn(), onpin: vi.fn() },
    });
    flushSync();
    const panel = target.querySelector('aside.detail');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    return panel;
  }

  it('shows the line the view gives, once', () => {
    const line = seasonFormat.line(
      { closed: 2, delayed: 1, remote: 0, earlyDismissal: 0 },
      '2026-10-27',
    );
    const panel = show({ ...VIEW, season: line });
    expect([...panel.querySelectorAll('.season')].map((found) => found.textContent)).toEqual([
      line,
    ]);
  });

  it('shows no line where the view has none', () => {
    expect(show({ ...VIEW, season: null }).querySelector('.season')).toBeNull();
    if (component !== undefined) void unmount(component);
    document.body.innerHTML = '';
    expect(show(VIEW).querySelector('.season')).toBeNull();
  });
});
