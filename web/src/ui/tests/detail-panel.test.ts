import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SchoolView } from '../../app/school';
import { copy } from '../../copy';
import DetailPanel from '../DetailPanel.svelte';

/** A school's view as app/school.ts makes one, made up for these tests. */
const VIEW: SchoolView = {
  id: 'ZZ000001',
  name: 'The Test Hill School',
  campus: 'North Campus',
  kind: `${copy.detail.privateSchool} · PK–12`,
  place: 'Kansas City, MO · Jackson County',
  status: [],
  chance: null,
  facts: [
    { label: copy.detail.students, lines: ['1,174'], href: null },
    { label: copy.detail.address, lines: ['400 W 51st St', 'Kansas City, MO 64112'], href: null },
    { label: copy.detail.phone, lines: ['(816) 555-0100'], href: 'tel:+18165550100' },
  ],
  nearby: [],
  loading: false,
};

describe('DetailPanel', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(view: SchoolView, extra: { pinned?: boolean; copied?: boolean } = {}) {
    const target = document.createElement('div');
    document.body.append(target);
    const props = {
      view,
      pinned: extra.pinned ?? false,
      copied: extra.copied ?? false,
      onclose: vi.fn(),
      onpin: vi.fn(),
      onshare: vi.fn(),
    };
    component = mount(DetailPanel, { target, props });
    flushSync();
    const panel = target.querySelector('aside.detail');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    return { panel, props };
  }

  it('names the school first, then what it is and where, and what the directory says', () => {
    const { panel } = show(VIEW);
    expect(panel.getAttribute('aria-label')).toBe(copy.detail.label);
    expect(panel.querySelector('h2')?.textContent.trim()).toBe('The Test Hill SchoolNorth Campus');
    expect(panel.querySelector('.campus')?.textContent).toBe('North Campus');
    expect(panel.querySelector('.kind')?.textContent).toBe(VIEW.kind);
    expect(panel.querySelector('.place')?.textContent).toBe(VIEW.place);
    const facts = [...panel.querySelectorAll('.fact')].map((fact) => [
      fact.querySelector('dt')?.textContent,
      [...fact.querySelectorAll('dd')].map((value) => value.textContent.trim()).join(''),
    ]);
    expect(facts).toEqual([
      [copy.detail.students, '1,174'],
      [copy.detail.address, '400 W 51st StKansas City, MO 64112'],
      [copy.detail.phone, '(816) 555-0100'],
    ]);
    expect(panel.querySelector('.fact a')?.getAttribute('href')).toBe('tel:+18165550100');
  });

  it('has no chance and no status where there is no chance to give and no day stated', () => {
    const { panel } = show(VIEW);
    expect(panel.querySelector('.outlook, .chance')).toBeNull();
    expect(panel.querySelector('.status')).toBeNull();
    for (const line of Object.values(copy.statusLine)) {
      expect(panel.textContent).not.toContain(line.today);
    }
    expect(panel.textContent).not.toContain(copy.open.today);
  });

  it('keys each status line with its glyph, today first', () => {
    const { panel } = show({
      ...VIEW,
      status: [
        {
          tone: 'earlyDismissal',
          headline: 'Early dismissal today',
          detail: 'Dismissal at 12:30 PM',
          note: null,
        },
        { tone: 'closed', headline: 'Closed tomorrow', detail: null, note: null },
      ],
    });
    const lines = [...panel.querySelectorAll('.status .line')];
    expect(lines.map((line) => line.querySelector('.headline')?.textContent)).toEqual([
      'Early dismissal today',
      'Closed tomorrow',
    ]);
    expect(lines[0]?.querySelector('.glyph')?.classList.contains('is-early-dismissal')).toBe(true);
    expect(lines[1]?.querySelector('.glyph')?.classList.contains('is-closed')).toBe(true);
    expect(lines[0]?.querySelector('.line-detail')?.textContent).toBe('Dismissal at 12:30 PM');
  });

  it('lists the nearest schools, each with its status glyph where it has one, and opens them', () => {
    const target = document.createElement('div');
    document.body.append(target);
    const onnearby = vi.fn();
    const nearby = [
      {
        id: 'ZZ000003',
        name: 'Visitation Test School',
        distance: '0.3 mi',
        tone: null,
        lon: 1,
        lat: 2,
      },
      {
        id: 'ZZ000004',
        name: 'St Test’s Academy',
        distance: '0.7 mi',
        tone: 'closed' as const,
        lon: 3,
        lat: 4,
      },
    ];
    component = mount(DetailPanel, {
      target,
      props: {
        view: { ...VIEW, nearby },
        pinned: false,
        copied: false,
        onclose: vi.fn(),
        onpin: vi.fn(),
        onshare: vi.fn(),
        onnearby,
      },
    });
    flushSync();
    const section = target.querySelector('.nearby');
    expect(section?.querySelector('h3')?.textContent).toBe(copy.detail.nearby);
    const rows = [...(section?.querySelectorAll<HTMLButtonElement>('.near') ?? [])];
    expect(rows.map((row) => row.querySelector('.near-name')?.textContent)).toEqual([
      'Visitation Test School',
      'St Test’s Academy',
    ]);
    expect(rows.map((row) => row.querySelector('.near-distance')?.textContent)).toEqual([
      '0.3 mi',
      '0.7 mi',
    ]);
    expect(rows[0]?.querySelector('.glyph')).toBeNull();
    expect(rows[1]?.querySelector('.glyph.is-closed')).not.toBeNull();
    // The light is drawn for the eye; a screen reader hears the status in words.
    expect(rows.map((row) => row.querySelector('.sr-only')?.textContent ?? null)).toEqual([
      null,
      copy.status.closed,
    ]);
    rows[1]?.click();
    expect(onnearby).toHaveBeenCalledWith(nearby[1]);
  });

  it('pins, shares and closes, and says when it is pinned or the link was copied', () => {
    const { panel, props } = show(VIEW);
    const [pin, share] = [...panel.querySelectorAll<HTMLButtonElement>('.action')];
    expect(pin?.textContent.trim()).toBe(copy.actions.pin);
    expect(pin?.getAttribute('aria-pressed')).toBe('false');
    expect(share?.textContent.trim()).toBe(copy.actions.share);
    pin?.click();
    share?.click();
    panel.querySelector<HTMLButtonElement>('.close')?.click();
    expect(props.onpin).toHaveBeenCalledTimes(1);
    expect(props.onshare).toHaveBeenCalledTimes(1);
    expect(props.onclose).toHaveBeenCalledTimes(1);
    expect(panel.querySelector('.close')?.getAttribute('aria-label')).toBe(copy.detail.close);

    if (component !== undefined) void unmount(component);
    component = undefined;
    const again = show(VIEW, { pinned: true, copied: true });
    const [pinned, copied] = [...again.panel.querySelectorAll('.action')];
    expect(pinned?.textContent.trim()).toBe(copy.pin.mySchool);
    expect(pinned?.getAttribute('aria-pressed')).toBe('true');
    expect(copied?.textContent.trim()).toBe(copy.share.copied);
  });

  it('is a sheet on a phone: it opens part way, and its grip takes it up and back down', () => {
    const query = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() };
    const matchMedia = vi.fn(() => query);
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: matchMedia });
    try {
      const { panel } = show(VIEW);
      expect(matchMedia).toHaveBeenCalledWith('(max-width: 719px)');
      const grip = panel.querySelector<HTMLButtonElement>('.grip');
      expect(panel.dataset.detent).toBe('open');
      expect(grip?.getAttribute('aria-label')).toBe(copy.detail.more);
      expect(grip?.getAttribute('aria-expanded')).toBe('false');
      grip?.click();
      flushSync();
      expect(panel.dataset.detent).toBe('full');
      expect(grip?.getAttribute('aria-label')).toBe(copy.detail.less);
      expect(grip?.getAttribute('aria-expanded')).toBe('true');
      grip?.click();
      flushSync();
      expect(panel.dataset.detent).toBe('open');
      // The grip says nothing a sighted reader sees.
      expect(grip?.textContent).toBe('');
    } finally {
      Reflect.deleteProperty(window, 'matchMedia');
    }
  });

  it('is a panel beside the map on a wide screen: no sheet', () => {
    const { panel } = show(VIEW);
    expect(panel.dataset.detent).toBeUndefined();
    expect(panel.style.transform).toBe('');
  });

  it('shows the shape of what is coming, and no words, until the school is read', () => {
    const { panel } = show({
      ...VIEW,
      nearby: [],
      name: '',
      kind: null,
      place: null,
      campus: null,
      facts: [],
      loading: true,
    });
    expect(panel.getAttribute('aria-busy')).toBe('true');
    expect(panel.querySelector('.skeleton')).not.toBeNull();
    expect(panel.querySelector('.actions')).toBeNull();
    expect(panel.textContent.trim()).toBe('');
  });

  it('keeps the kind’s place over what a pick knew while the record is read, and none after', () => {
    const picked = { ...VIEW, kind: null, facts: [], outlook: null, loading: true };
    const { panel } = show(picked);
    expect(panel.querySelector('.head .bone.is-kind')).not.toBeNull();
    expect(panel.querySelector('.kind')).toBeNull();
    if (component !== undefined) void unmount(component);
    // The record was not found: what the pick knew, and no place kept for words that will not come.
    const { panel: settled } = show({ ...picked, loading: false });
    expect(settled.querySelector('.bone')).toBeNull();
  });
});
