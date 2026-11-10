import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SchoolView } from '../../app/school';
import { copy } from '../../copy';
import { shareCopy } from '../../copy-share';
import DetailPanel from '../DetailPanel.svelte';
import type * as ShareCards from '../share-cards';

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

/** When the live file the closed line below comes from was made. */
const STATUS_AT = new Date('2026-01-12T12:55:00Z');

/** The school closed today, with what its share cards need. */
const CLOSED_VIEW: SchoolView = {
  ...VIEW,
  status: [
    {
      tone: 'closed',
      headline: copy.statusLine.closed.today,
      detail: null,
      note: null,
      said: null,
      day: '2026-01-12',
      reason: null,
    },
  ],
  share: { zone: 'America/Chicago', statusAt: STATUS_AT, chanceAt: null },
};

describe('DetailPanel', () => {
  let component: ReturnType<typeof mount> | undefined;

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
  });

  function show(view: SchoolView, extra: { pinned?: boolean } = {}) {
    const target = document.createElement('div');
    document.body.append(target);
    const props = {
      view,
      pinned: extra.pinned ?? false,
      onclose: vi.fn(),
      onpin: vi.fn(),
      link: vi.fn(() => 'https://snow.test/?school=ZZ000001'),
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
          said: 'No lunch.',
        },
        { tone: 'closed', headline: 'Closed tomorrow', detail: null, note: null, said: null },
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
    // The plain details, in the site's words, below the status; none on a line without.
    expect(lines[0]?.querySelector('.line-said')?.textContent).toBe('No lunch.');
    expect(lines[1]?.querySelector('.line-said')).toBeNull();
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
        onclose: vi.fn(),
        onpin: vi.fn(),
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

  it('pins, shares and closes, and says when it is pinned or the link was copied', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { panel, props } = show(VIEW);
    const [pin, share] = [...panel.querySelectorAll<HTMLButtonElement>('.action')];
    expect(pin?.textContent.trim()).toBe(copy.actions.pin);
    expect(pin?.getAttribute('aria-pressed')).toBe('false');
    expect(share?.textContent.trim()).toBe(copy.actions.share);
    expect(share?.getAttribute('aria-expanded')).toBe('false');
    pin?.click();
    // Share opens its options; without a day to put on a card (no share facts here), the link alone.
    share?.click();
    flushSync();
    expect(share?.getAttribute('aria-expanded')).toBe('true');
    const options = panel.querySelector('.share-options');
    expect(options?.getAttribute('aria-label')).toBe(shareCopy.options);
    const buttons = [...panel.querySelectorAll<HTMLButtonElement>('.option')];
    expect(buttons.map((button) => button.textContent.trim())).toEqual([shareCopy.copyLink]);
    buttons[0]?.click();
    expect(writeText).toHaveBeenCalledWith('https://snow.test/?school=ZZ000001');
    await vi.waitFor(() => {
      flushSync();
      expect(panel.querySelector('.option')?.textContent.trim()).toBe(copy.share.copied);
    });
    panel.querySelector<HTMLButtonElement>('.close')?.click();
    expect(props.onpin).toHaveBeenCalledTimes(1);
    expect(props.onclose).toHaveBeenCalledTimes(1);
    expect(panel.querySelector('.close')?.getAttribute('aria-label')).toBe(copy.detail.close);
    // Share again closes them.
    share?.click();
    flushSync();
    expect(panel.querySelector('.share-options')).toBeNull();

    if (component !== undefined) void unmount(component);
    component = undefined;
    const again = show(VIEW, { pinned: true });
    const [pinned] = [...again.panel.querySelectorAll<HTMLButtonElement>('.action')];
    expect(pinned?.textContent.trim()).toBe(copy.pin.mySchool);
    expect(pinned?.getAttribute('aria-pressed')).toBe('true');
  });

  it('has no Share while the page cannot write a link yet', () => {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(DetailPanel, {
      target,
      props: { view: VIEW, pinned: false, onclose: vi.fn(), onpin: vi.fn() },
    });
    flushSync();
    expect([...target.querySelectorAll('.action')].map((b) => b.textContent.trim())).toEqual([
      copy.actions.pin,
    ]);
  });

  it('offers a Story card and a Post card of the school’s day, loaded with the first press', async () => {
    const share = vi.fn(() => Promise.resolve('saved' as const));
    const prepare = vi.fn();
    const sharer = { prepare, available: () => true, share };
    const createCardSharer = vi.fn(() => sharer);
    const loadCards = vi.fn(() =>
      Promise.resolve({ createCardSharer } as unknown as typeof ShareCards),
    );
    const target = document.createElement('div');
    document.body.append(target);
    const view = CLOSED_VIEW;
    const link = vi.fn(() => 'https://snow.test/?school=ZZ000001');
    component = mount(DetailPanel, {
      target,
      props: {
        view,
        pinned: false,
        onclose: vi.fn(),
        onpin: vi.fn(),
        link,
        loadCards,
      },
    });
    flushSync();
    const panel = target.querySelector('aside.detail');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    // Nothing of the cards is loaded until Share is pressed.
    expect(loadCards).not.toHaveBeenCalled();
    panel.querySelectorAll<HTMLButtonElement>('.action')[1]?.click();
    flushSync();
    const options = [...panel.querySelectorAll<HTMLButtonElement>('.option')];
    expect(options.map((button) => button.textContent.trim())).toEqual([
      shareCopy.story,
      shareCopy.post,
      shareCopy.copyLink,
    ]);
    await vi.waitFor(() => {
      expect(prepare).toHaveBeenCalled();
    });
    expect(loadCards).toHaveBeenCalledTimes(1);
    expect(createCardSharer).toHaveBeenCalledTimes(1);
    options[0]?.click();
    await vi.waitFor(() => {
      expect(share).toHaveBeenCalledWith('story');
    });
    // Saved, with the link copied: said on the card's button.
    await vi.waitFor(() => {
      flushSync();
      expect(panel.querySelector('[data-card="story"]')?.textContent.trim()).toBe(shareCopy.saved);
    });
    options[1]?.click();
    await vi.waitFor(() => {
      expect(share).toHaveBeenCalledWith('post');
    });
  });

  /** Mounts the panel with the share cards' code stubbed; its share options opened. */
  async function withCards(
    view: SchoolView,
    sharer: { prepare: () => void; available: () => boolean; share: (kind: string) => unknown },
  ) {
    const loadCards = vi.fn(() =>
      Promise.resolve({ createCardSharer: () => sharer } as unknown as typeof ShareCards),
    );
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(DetailPanel, {
      target,
      props: {
        view,
        pinned: false,
        onclose: vi.fn(),
        onpin: vi.fn(),
        link: () => 'https://snow.test/?school=ZZ000001',
        loadCards,
      },
    });
    flushSync();
    const panel = target.querySelector('aside.detail');
    if (!(panel instanceof HTMLElement)) throw new Error('no panel');
    panel.querySelectorAll<HTMLButtonElement>('.action')[1]?.click();
    flushSync();
    // The cards' code, where it loads, is here a turn later.
    await new Promise((resolve) => setTimeout(resolve, 0));
    flushSync();
    const labels = (): string[] =>
      [...panel.querySelectorAll<HTMLButtonElement>('.option')].map((b) => b.textContent.trim());
    return { panel, loadCards, labels };
  }

  it('offers no card where none can be made: the link alone, before and after the cards load', async () => {
    const share = vi.fn(() => Promise.resolve('saved' as const));
    // A nameplate alone: the school, with no status and no chance.
    const nameplate = await withCards(
      { ...VIEW, share: { zone: 'America/Chicago', statusAt: STATUS_AT, chanceAt: null } },
      { prepare: vi.fn(), available: () => false, share },
    );
    expect(nameplate.labels()).toEqual([shareCopy.copyLink]);
    // Nothing of the cards is loaded for a panel that offers none.
    expect(nameplate.loadCards).not.toHaveBeenCalled();
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
    // A status whose card's model the cards' own code does not make: no buttons once it is here.
    const refused = await withCards(CLOSED_VIEW, {
      prepare: vi.fn(),
      available: () => false,
      share,
    });
    expect(refused.loadCards).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => {
      flushSync();
      expect(refused.labels()).toEqual([shareCopy.copyLink]);
    });
    expect(share).not.toHaveBeenCalled();
  });

  it('says so when no card could be made, and copies the link in its place', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const share = vi.fn(() => Promise.resolve('failed' as const));
    const { panel } = await withCards(CLOSED_VIEW, {
      prepare: vi.fn(),
      available: () => true,
      share,
    });
    panel.querySelector<HTMLButtonElement>('[data-card="story"]')?.click();
    await vi.waitFor(() => {
      flushSync();
      expect(panel.querySelector('[data-card="story"]')?.textContent.trim()).toBe(
        shareCopy.linkInstead,
      );
    });
    expect(writeText).toHaveBeenCalledWith('https://snow.test/?school=ZZ000001');
    // And where the link cannot be copied either: said all the same.
    writeText.mockImplementation(() => Promise.reject(new Error('denied')));
    panel.querySelector<HTMLButtonElement>('[data-card="post"]')?.click();
    await vi.waitFor(() => {
      flushSync();
      expect(panel.querySelector('[data-card="post"]')?.textContent.trim()).toBe(shareCopy.failed);
    });
  });

  it('shares the link through the phone’s share sheet, as Share did before the cards', async () => {
    const query = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() };
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => query) });
    const sheet = vi.fn<(data: ShareData) => Promise<void>>(() => Promise.resolve());
    Object.defineProperty(navigator, 'share', { configurable: true, value: sheet });
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    try {
      const { panel, labels } = await withCards(CLOSED_VIEW, {
        prepare: vi.fn(),
        available: () => true,
        share: vi.fn(),
      });
      expect(labels()).toEqual([shareCopy.story, shareCopy.post, shareCopy.shareLink]);
      panel.querySelector<HTMLButtonElement>('[data-link]')?.click();
      await vi.waitFor(() => {
        expect(sheet).toHaveBeenCalledWith({
          title: CLOSED_VIEW.name,
          url: 'https://snow.test/?school=ZZ000001',
        });
      });
      // Called off in the sheet: nothing copied, nothing said.
      sheet.mockImplementation(() => Promise.reject(new DOMException('no', 'AbortError')));
      panel.querySelector<HTMLButtonElement>('[data-link]')?.click();
      await vi.waitFor(() => {
        expect(sheet).toHaveBeenCalledTimes(2);
      });
      await Promise.resolve();
      expect(writeText).not.toHaveBeenCalled();
      // A sheet that will not open: the link copied instead, and said so.
      sheet.mockImplementation(() => Promise.reject(new Error('not allowed')));
      panel.querySelector<HTMLButtonElement>('[data-link]')?.click();
      await vi.waitFor(() => {
        flushSync();
        expect(panel.querySelector('[data-link]')?.textContent.trim()).toBe(copy.share.copied);
      });
      expect(writeText).toHaveBeenCalledTimes(1);
    } finally {
      Reflect.deleteProperty(window, 'matchMedia');
      Reflect.deleteProperty(navigator, 'share');
    }
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
