import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { format } from '../../copy-format';
import { LIVE_FRESH_MS } from '../../state/freshness';
import UpdateTime from '../UpdateTime.svelte';

const GENERATED = '2026-01-12T12:42:00Z';
const MINUTE = 60_000;

describe('UpdateTime', () => {
  let component: ReturnType<typeof mount> | undefined;
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const generated = new Date(GENERATED);

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-12T12:50:00Z'));
  });

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  function show(generatedAt = GENERATED): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(UpdateTime, { target, props: { generatedAt } });
    flushSync();
    return target;
  }

  it('says live, with the file’s own time and a dot, while the file is recent', () => {
    const target = show();
    const line = target.querySelector('.updated');
    expect(line?.textContent.trim()).toBe(format.liveAt(generated, zone));
    expect(line?.classList.contains('is-live')).toBe(true);
    expect(line?.querySelector('.dot')?.getAttribute('aria-hidden')).toBe('true');
    expect(line?.querySelector('time')?.getAttribute('datetime')).toBe(GENERATED);
  });

  it('turns to when it was updated as the file ages, without a new file', async () => {
    const target = show();
    await vi.advanceTimersByTimeAsync(25 * MINUTE);
    flushSync();
    const line = target.querySelector('.updated');
    expect(line?.textContent.trim()).toBe(format.updatedAt(generated, zone, new Date()));
    expect(line?.classList.contains('is-live')).toBe(false);
    expect(line?.querySelector('.dot')).toBeNull();
  });

  it('stops saying live the moment the file is older than the live threshold, between ticks', async () => {
    // Ticks fall at :10 and :40 past each minute from here; the file turns stale at 13:02:00.
    vi.setSystemTime(new Date('2026-01-12T12:50:10Z'));
    const target = show();
    const stale = new Date(GENERATED).getTime() + LIVE_FRESH_MS;
    await vi.advanceTimersByTimeAsync(stale - Date.now() - 1000);
    flushSync();
    expect(target.querySelector('.updated')?.classList.contains('is-live')).toBe(true);
    await vi.advanceTimersByTimeAsync(1000 + 5);
    flushSync();
    const line = target.querySelector('.updated');
    expect(line?.classList.contains('is-live')).toBe(false);
    expect(line?.textContent.trim()).toBe(format.updatedAt(generated, zone, new Date()));
  });

  it('never says live for a file already older than the threshold', () => {
    vi.setSystemTime(new Date(new Date(GENERATED).getTime() + LIVE_FRESH_MS + 1));
    const target = show();
    expect(target.querySelector('.updated')?.classList.contains('is-live')).toBe(false);
    expect(target.querySelector('.dot')).toBeNull();
  });

  it('says offline while the page is offline, and live again once back', () => {
    const target = show();
    const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    window.dispatchEvent(new Event('offline'));
    flushSync();
    expect(target.querySelector('.updated')?.textContent.trim()).toBe(
      format.offline(generated, zone, new Date()),
    );
    expect(target.querySelector('.dot')).toBeNull();
    online.mockReturnValue(true);
    window.dispatchEvent(new Event('online'));
    flushSync();
    expect(target.querySelector('.updated')?.textContent.trim()).toBe(
      format.liveAt(generated, zone),
    );
    online.mockRestore();
  });

  it('shows nothing for a time that is not an instant', () => {
    const target = show('2026-01-12T12:42');
    expect(target.querySelector('.updated')).toBeNull();
  });
});
