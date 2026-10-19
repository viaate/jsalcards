import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { format } from '../../copy-format';
import { LIVE_FRESH_MS, forgetHolds } from '../../state/freshness';
import { WAKE_CHECK_MS } from '../../state/wake';
import UpdateTime from '../UpdateTime.svelte';
import { reactiveProps } from './reactive-props.svelte';

const GENERATED = '2026-01-12T12:42:00Z';
const MINUTE = 60_000;

describe('UpdateTime', () => {
  let component: ReturnType<typeof mount> | undefined;
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const generated = new Date(GENERATED);

  beforeEach(() => {
    // Each test is a page just loaded: no file held yet.
    forgetHolds();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-12T12:50:00Z'));
  });

  afterEach(() => {
    if (component !== undefined) void unmount(component);
    component = undefined;
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  function show(generatedAt = GENERATED, props = reactiveProps({ generatedAt })): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    component = mount(UpdateTime, { target, props });
    flushSync();
    return target;
  }

  const isLive = (target: HTMLElement): boolean =>
    target.querySelector('.updated')?.classList.contains('is-live') ?? false;
  const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

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

  it('stops saying live within seconds of a device waking from a sleep that held its timers back', async () => {
    const target = show();
    expect(target.querySelector('.updated')?.classList.contains('is-live')).toBe(true);
    // The device sleeps overnight: its clock moves on, the page's timers do not.
    vi.setSystemTime(new Date('2026-01-13T13:00:00Z'));
    await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
    flushSync();
    const line = target.querySelector('.updated');
    expect(line?.classList.contains('is-live')).toBe(false);
    expect(line?.textContent.trim()).toBe(format.updatedAt(generated, zone, new Date()));
  });

  it('works the line out again when the page is shown again from the back-forward cache', () => {
    const target = show();
    vi.setSystemTime(new Date('2026-01-12T13:30:00Z'));
    window.dispatchEvent(new Event('pageshow'));
    flushSync();
    expect(target.querySelector('.updated')?.classList.contains('is-live')).toBe(false);
  });

  it('works the line out again when the page is shown, without waiting for a tick', () => {
    const target = show();
    expect(isLive(target)).toBe(true);
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    // Hidden while the file ages past the threshold, with no timer run since.
    vi.setSystemTime(new Date(generated.getTime() + LIVE_FRESH_MS + MINUTE));
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    flushSync();
    expect(isLive(target)).toBe(false);
    expect(target.querySelector('.updated')?.textContent.trim()).toBe(
      format.updatedAt(generated, zone, new Date()),
    );
    visibility.mockRestore();
  });

  it('judges a file that comes between two ticks by the time it comes, not the last tick', async () => {
    const props = reactiveProps({ generatedAt: GENERATED });
    const target = show(GENERATED, props);
    // 29 s past the last tick, a file already 20 minutes and 10 s old comes.
    await vi.advanceTimersByTimeAsync(29_000);
    props.generatedAt = stamp(Date.now() - LIVE_FRESH_MS - 10_000);
    flushSync();
    expect(isLive(target)).toBe(false);
    // And a fresh one is live at once.
    props.generatedAt = stamp(Date.now() - MINUTE);
    flushSync();
    expect(isLive(target)).toBe(true);
  });

  it('stops saying live once the page has held one file for the threshold, on a clock 15 minutes slow', async () => {
    const slow = 15 * MINUTE;
    // True time 13:00; the device says 12:45. The last file came at 12:59, and then the ingest
    // stopped: the device first sees it stamped ahead, then, as its slow clock passes the stamp,
    // as recent.
    const realStart = Date.parse('2026-01-12T13:00:00Z');
    vi.setSystemTime(realStart - slow);
    const file = stamp(realStart - MINUTE);
    const target = show(file);
    const start = performance.now();
    let lastLive = -1;
    for (let step = 0; step <= 80; step += 1) {
      const held = performance.now() - start;
      if (isLive(target)) lastLive = held;
      if (held > LIVE_FRESH_MS)
        expect(isLive(target), `held ${String(held / MINUTE)} min`).toBe(false);
      await vi.advanceTimersByTimeAsync(30_000);
      flushSync();
    }
    // It was live for a while, and stopped within the threshold of the page taking it.
    expect(lastLive).toBeGreaterThan(0);
    expect(lastLive).toBeLessThanOrEqual(LIVE_FRESH_MS);
  });

  it('stops saying live the moment the hold passes the threshold, between ticks', async () => {
    // Taken a minute old; five minutes on, the device's clock is put back ten minutes, so the
    // file reads as recent again until the page has held it for the threshold.
    const target = show(stamp(Date.now() - MINUTE));
    expect(isLive(target)).toBe(true);
    await vi.advanceTimersByTimeAsync(5 * MINUTE);
    vi.setSystemTime(Date.now() - 10 * MINUTE);
    await vi.advanceTimersByTimeAsync(LIVE_FRESH_MS - 5 * MINUTE - 1000);
    flushSync();
    expect(isLive(target)).toBe(true);
    await vi.advanceTimersByTimeAsync(1000 + 5);
    flushSync();
    expect(isLive(target)).toBe(false);
  });

  it('counts a sleep in the hold, though the forward clock stood still through it', async () => {
    const slow = 15 * MINUTE;
    // The device's clock runs 15 minutes slow; it took a file a minute old, stamped ahead of it.
    const realStart = Date.parse('2026-01-12T13:00:00Z');
    vi.setSystemTime(realStart - slow);
    const target = show(stamp(realStart - MINUTE));
    expect(isLive(target)).toBe(false);
    // Asleep 25 minutes: the wall clock moves on, the timers and the forward clock do not. By
    // its slow clock the file reads 11 minutes old, but the page has held it for 25.
    vi.setSystemTime(Date.now() + 25 * MINUTE);
    await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
    flushSync();
    expect(isLive(target)).toBe(false);
    expect(target.querySelector('.updated')?.textContent.trim()).toBe(
      format.updatedAt(new Date(realStart - MINUTE), zone, new Date()),
    );
  });

  it('never says live for a file held past the threshold after the clock is set back an hour', async () => {
    const target = show();
    expect(isLive(target)).toBe(true);
    const start = performance.now();
    // Network time puts a clock that ran an hour fast back; the ingest stops meanwhile.
    vi.setSystemTime(Date.now() - 60 * MINUTE);
    for (let step = 0; step <= 240; step += 1) {
      const held = performance.now() - start;
      if (held > LIVE_FRESH_MS)
        expect(isLive(target), `held ${String(held / MINUTE)} min`).toBe(false);
      await vi.advanceTimersByTimeAsync(30_000);
      flushSync();
    }
  });

  it('holds on from when the page first took the file, though the line was taken down and shown again', async () => {
    const slow = 15 * MINUTE;
    // The device's clock runs 15 minutes slow; the last file came at 12:59, and the ingest stopped.
    const realStart = Date.parse('2026-01-12T13:00:00Z');
    vi.setSystemTime(realStart - slow);
    const file = stamp(realStart - MINUTE);
    let target = show(file);
    const start = performance.now();
    await vi.advanceTimersByTimeAsync(15 * MINUTE);
    flushSync();
    // By the slow clock the file is a minute old.
    expect(isLive(target)).toBe(true);
    // A replay is opened and closed: the line is taken down, then shown again.
    if (component !== undefined) void unmount(component);
    document.body.innerHTML = '';
    await vi.advanceTimersByTimeAsync(MINUTE);
    target = show(file);
    flushSync();
    // Still within the hold, so live; past it, live no more, though the line is new.
    expect(isLive(target)).toBe(true);
    await vi.advanceTimersByTimeAsync(LIVE_FRESH_MS - (performance.now() - start) + 5);
    flushSync();
    expect(performance.now() - start).toBeLessThan(LIVE_FRESH_MS + 1000);
    expect(isLive(target)).toBe(false);
  });

  it('holds a newer file from when it came, not from the first file', async () => {
    const target = show(stamp(Date.now() - MINUTE));
    await vi.advanceTimersByTimeAsync(10 * MINUTE);
    if (component !== undefined) void unmount(component);
    document.body.innerHTML = '';
    // A newer file, stamped a minute before the device's clock: live, and held from now.
    const next = show(stamp(Date.now() - MINUTE));
    expect(isLive(next)).toBe(true);
    await vi.advanceTimersByTimeAsync(15 * MINUTE);
    flushSync();
    expect(isLive(next)).toBe(true);
    expect(target.isConnected).toBe(false);
  });

  it('shows nothing for a time that is not an instant', () => {
    const target = show('2026-01-12T12:42');
    expect(target.querySelector('.updated')).toBeNull();
  });
});
