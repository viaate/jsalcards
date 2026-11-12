/**
 * The key's line for the later-day rings (ui/LaterKey.svelte): the days and
 * their counts, none with none, and the same line kept, not drawn anew, for a
 * file whose days and counts are the same. Every view here is SYNTHETIC.
 */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { NO_LATER } from '../../data/later-days';
import type { LaterView } from '../../data/later-days';
import LaterKey from '../LaterKey.svelte';

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
  if (mounted !== null) void unmount(mounted);
  mounted = null;
  document.body.innerHTML = '';
});

function start(): { show(view: LaterView): void } {
  const key = mount(LaterKey, { target: document.body }) as unknown as {
    show(view: LaterView): void;
  };
  mounted = key;
  return key;
}

/** A view of Friday with this many schools, as each new file would make it afresh. */
function friday(count: number): LaterView {
  return {
    days: [{ day: '2026-11-13', count }],
    marks: [{ school: 0, day: '2026-11-13', status: 0, near: Infinity }],
    from: '2026-11-12',
  };
}

describe('the later days’ key line', () => {
  it('names the days with their counts, and shows nothing with none', () => {
    const key = start();
    key.show(friday(8));
    flushSync();
    expect(document.querySelector('.later-key .sr-only')?.textContent).toBe(
      'Later days: Friday, 8 schools',
    );
    expect(document.querySelector('.later-key .count')?.textContent).toBe('8');
    // The day and its count apart, so the count never reads as the day's date.
    expect(document.querySelector('.later-key .day')?.textContent).toBe('Fri: 8');
    key.show(NO_LATER);
    flushSync();
    expect(document.querySelector('.later-key')).toBeNull();
  });

  it('keeps the same line for a new file with the same days and counts, and redraws a new count', () => {
    const key = start();
    key.show(friday(8));
    flushSync();
    const first = document.querySelector('.later-key');
    expect(first).not.toBeNull();
    // A new poll: new arrays, the same words; and a new mark alone changes no word either.
    key.show(friday(8));
    key.show({ ...friday(8), marks: [] });
    flushSync();
    expect(document.querySelector('.later-key')).toBe(first);
    key.show(friday(9));
    flushSync();
    expect(document.querySelector('.later-key')).not.toBe(first);
    expect(document.querySelector('.later-key .count')?.textContent).toBe('9');
  });
});
