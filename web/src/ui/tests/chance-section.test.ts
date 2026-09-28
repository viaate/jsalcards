import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { chanceView } from '../../app/chance';
import type { ChanceView } from '../../app/chance';
import type { SchoolView } from '../../app/school';
import {
  A_CLOSINGS,
  A_NOW,
  A_OUTLOOK,
  B_NOW,
  B_OUTLOOK,
  CLOSED_TODAY,
  NAMES,
  ZONE,
} from '../../app/tests/chance-fixtures';
import { copy } from '../../copy';
import DetailPanel from '../DetailPanel.svelte';

const NBSP = ' ';

function chance(night: boolean): ChanceView {
  const view = chanceView({
    outlook: night ? A_OUTLOOK : B_OUTLOOK,
    decided: { today: !night, tomorrow: false },
    status: night ? [] : [CLOSED_TODAY],
    district: 'Shawnee Mission',
    closings: night ? A_CLOSINGS : null,
    names: NAMES,
    now: night ? A_NOW : B_NOW,
    timeZone: ZONE,
  });
  if (view === null) throw new Error('no chance');
  return view;
}

/** A public school's view with its chance, made up for these tests. */
function schoolView(section: ChanceView): SchoolView {
  return {
    id: '201164001574',
    name: 'Test Mission East High',
    campus: null,
    kind: `${copy.detail.publicSchool} · 9–12`,
    place: 'Prairie Village, KS · Johnson County',
    status: section.status,
    outlook: null,
    chance: section,
    facts: [],
    nearby: [],
    loading: false,
  };
}

describe('the chance section', () => {
  let component: ReturnType<typeof mount> | undefined;

  beforeAll(() => {
    // jsdom lays nothing out; the chart measures its words with a ResizeObserver.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
      },
    );
  });

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  function show(section: ChanceView): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(DetailPanel, {
      target,
      props: {
        view: schoolView(section),
        pinned: false,
        copied: false,
        onclose: vi.fn(),
        onpin: vi.fn(),
        onshare: vi.fn(),
      },
    });
    flushSync();
    const panel = target.querySelector<HTMLElement>('aside.detail .chance');
    if (panel === null) throw new Error('no section');
    return panel;
  }

  const text = (root: Element, selector: string): string[] =>
    [...root.querySelectorAll(selector)].map((node) =>
      node.textContent.replace(/[\t\n\r ]+/gu, ' ').trim(),
    );

  it('leads with the chance, then the evening, the chart, the sum and the delay, all open', () => {
    vi.useFakeTimers({ now: A_NOW });
    const section = show(chance(true));
    // The old cards give way to it.
    expect(document.querySelector('.card.status')).toBeNull();
    expect(document.querySelector('.outlook')).toBeNull();
    expect(section.querySelector('.status')).toBeNull();
    expect(text(section, '.number')).toEqual(['64%']);
    expect(text(section, '.meaning')).toEqual(['64% Chance of no school Tuesday']);
    expect(text(section, '.change')).toEqual([`Up from 41% at 5${NBSP}PM`]);
    expect(section.querySelectorAll('.change svg')).toHaveLength(1);
    expect(text(section, '.moment')).toEqual([
      `8:41${NBSP}PM Blue Valley canceled Tuesday`,
      `8:52${NBSP}PM Olathe canceled Tuesday`,
      `5:30${NBSP}AM Shawnee Mission usually announces in 8h 25m`,
    ]);
    expect(section.querySelectorAll('.moment .glyph.is-closed')).toHaveLength(2);
    // The countdown keeps time.
    vi.advanceTimersByTime(61_000);
    flushSync();
    expect(text(section, '.m-count')).toEqual(['in 8h 24m']);

    expect(text(section, 'figcaption')).toEqual([copy.chance.snowTitle]);
    expect(section.querySelectorAll('.col')).toHaveLength(11);
    expect(section.querySelectorAll('.col.is-lit')).toHaveLength(3);
    expect(text(section, '.flag')).toEqual([
      `${copy.chance.usuallyAnnounces} 5:30${NBSP}AM`,
      `${copy.chance.buses} 7${NBSP}AM`,
    ]);
    expect(text(section, '.end')).toEqual([`6 to 9${NBSP}in`]);
    expect(section.querySelectorAll('.range')).toHaveLength(1);
    expect(text(section, '.time')).toEqual([
      `9${NBSP}PM ${copy.chance.now}`,
      `11${NBSP}PM`,
      `2${NBSP}AM`,
      `5${NBSP}AM`,
      `7${NBSP}AM`,
    ]);

    expect(text(section, '.why-title')).toEqual(['How we got 64%']);
    expect(text(section, '.sum > li .num')).toEqual(['30', '+16', '+9', '+7', '+5', '−3', '64']);
    expect(text(section, '.is-total')).toEqual(['64% Chance of no school Tuesday']);
    expect(section.querySelectorAll('.record li')).toHaveLength(5);
    expect(section.querySelectorAll('.record .glyph.is-delayed')).toHaveLength(1);
    // Nothing folds away.
    expect(section.querySelectorAll('details, [aria-expanded]')).toHaveLength(0);
    expect(text(section, '.delay')).toEqual(['18% chance of a delayed start instead']);
    expect(section.querySelectorAll('.delay .glyph.is-delayed')).toHaveLength(1);
  });

  it('the next morning, says the decided status first, then the next day’s chance', () => {
    vi.useFakeTimers({ now: B_NOW });
    const section = show(chance(false));
    const status = section.querySelector('.status');
    expect(status?.getAttribute('aria-label')).toBe(copy.detail.status);
    expect(text(section, '.status .headline')).toEqual([copy.statusLine.closed.today]);
    expect(section.querySelectorAll('.status .glyph.is-closed')).toHaveLength(1);
    // The status comes before the chance.
    const hero = section.querySelector('.hero');
    expect(
      status !== null &&
        hero !== null &&
        (status.compareDocumentPosition(hero) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    ).toBe(true);
    expect(text(section, '.number')).toEqual(['22%']);
    expect(text(section, '.change')).toEqual(['Down from 30% last night']);
    expect(text(section, '.moment')).toEqual([
      `6:00${NBSP}AM Snow stopped, 8 inches in all`,
      `5:30${NBSP}AM Shawnee Mission usually announces Wednesday, in 23h 10m`,
    ]);
    expect(text(section, 'figcaption')).toEqual([copy.chance.coldTonight]);
    expect(section.querySelectorAll('.col.is-below')).toHaveLength(11);
    expect(text(section, '.end')).toEqual([`-8${NBSP}F`]);
    expect(text(section, '.is-start .record li')).toEqual([
      `${copy.chance.open} Open, Jan 10, 2024`,
      `${copy.chance.closed} Closed, Jan 7, 2025`,
      `${copy.chance.open} Open, Jan 13, 2025`,
      `${copy.chance.open} Open, Feb 19, 2025`,
    ]);
  });

  it('shows only what is consistent: no sum, no chart, no timeline where the file gives none', () => {
    const bare = { ...chance(true), moved: null, moments: [], chart: null, why: null, delay: null };
    const section = show(bare);
    expect(text(section, '.number')).toEqual(['64%']);
    expect(section.querySelector('.change')).toBeNull();
    expect(section.querySelector('.moments')).toBeNull();
    expect(section.querySelector('.chart')).toBeNull();
    expect(section.querySelector('.why')).toBeNull();
    expect(section.querySelector('.delay')).toBeNull();
  });
});
