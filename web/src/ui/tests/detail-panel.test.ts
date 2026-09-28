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
  outlook: 'not_enough_data',
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

  it('says “Not enough data yet” and nothing more where no history gives a chance, and no status', () => {
    const { panel } = show(VIEW);
    const outlook = panel.querySelector('.outlook');
    expect(outlook?.querySelector('h3')?.textContent).toBe(copy.predictions.title);
    expect(outlook?.querySelector('.quiet')?.textContent).toBe(copy.empty.notEnoughData);
    expect(outlook?.querySelectorAll('p')).toHaveLength(1);
    expect(panel.querySelector('.status')).toBeNull();
    for (const line of Object.values(copy.statusLine)) {
      expect(panel.textContent).not.toContain(line.today);
    }
    expect(panel.textContent).not.toContain(copy.open.today);
  });

  it('leaves the outlook out when the files cannot say for now', () => {
    const { panel } = show({ ...VIEW, outlook: null });
    expect(panel.querySelector('.outlook')).toBeNull();
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

  it('shows each day’s chance with its bar', () => {
    const { panel } = show({
      ...VIEW,
      outlook: [
        {
          label: copy.days.today,
          chance: '34%',
          line: copy.predictions.noSchool,
          delay: `${copy.predictions.delay} 12%`,
          reasons: copy.reason.ice,
          share: 0.34,
        },
        {
          label: copy.days.tomorrow,
          chance: null,
          line: copy.empty.noThreat,
          delay: null,
          reasons: null,
          share: null,
        },
      ],
    });
    const days = [...panel.querySelectorAll('.day')];
    expect(days.map((day) => day.querySelector('.day-label')?.textContent)).toEqual([
      copy.days.today,
      copy.days.tomorrow,
    ]);
    expect(days[0]?.querySelector('.chance')?.textContent).toBe('34%');
    expect(days[0]?.querySelector<HTMLElement>('.meter-fill')?.style.transform).toBe(
      'scaleX(0.34)',
    );
    expect(days[1]?.querySelector('.day-line')?.textContent).toBe(copy.empty.noThreat);
    expect(days[1]?.querySelector('.meter')).toBeNull();
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

  it('shows the shape of what is coming, and no words, until the school is read', () => {
    const { panel } = show({
      ...VIEW,
      nearby: [],
      name: '',
      kind: null,
      place: null,
      campus: null,
      facts: [],
      outlook: null,
      loading: true,
    });
    expect(panel.getAttribute('aria-busy')).toBe('true');
    expect(panel.querySelector('.skeleton')).not.toBeNull();
    expect(panel.querySelector('.actions')).toBeNull();
    expect(panel.textContent.trim()).toBe('');
  });
});
