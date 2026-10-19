import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WAKE_CHECK_MS, WAKE_GAP_MS, watchWake } from '../wake';
import type { WakeHost } from '../wake';

/** A window of its own: counts the intervals and listeners it holds. */
function fakeHost() {
  const page = new EventTarget();
  const doc = new EventTarget();
  const live = new Set<number>();
  const listeners = { page: 0, document: 0 };
  const host: WakeHost = {
    document: {
      addEventListener: (type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.document += 1;
        doc.addEventListener(type, listener);
      },
      removeEventListener: (type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.document -= 1;
        doc.removeEventListener(type, listener);
      },
    } as WakeHost['document'],
    setInterval: (handler, timeout) => {
      const id = setInterval(handler, timeout) as unknown as number;
      live.add(id);
      return id;
    },
    clearInterval: (id) => {
      if (id !== undefined) live.delete(id);
      clearInterval(id);
    },
    addEventListener: ((type: string, listener: EventListenerOrEventListenerObject) => {
      listeners.page += 1;
      page.addEventListener(type, listener);
    }) as Window['addEventListener'],
    removeEventListener: ((type: string, listener: EventListenerOrEventListenerObject) => {
      listeners.page -= 1;
      page.removeEventListener(type, listener);
    }) as Window['removeEventListener'],
  };
  return { host, page, doc, live, listeners };
}

/** The device sleeps: the wall clock jumps, and the check runs once after. */
async function sleep(ms: number): Promise<void> {
  vi.setSystemTime(Date.now() + ms);
  await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-01-12T18:00:00Z'));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('the wake watch', () => {
  it('calls on a gap in the wall clock of more than the check and its margin, not less', async () => {
    const { host } = fakeHost();
    const onWake = vi.fn();
    const stop = watchWake(onWake, host);
    await vi.advanceTimersByTimeAsync(10 * WAKE_CHECK_MS);
    expect(onWake).not.toHaveBeenCalled();
    await sleep(WAKE_GAP_MS);
    expect(onWake).not.toHaveBeenCalled();
    await sleep(WAKE_GAP_MS + 1);
    expect(onWake).toHaveBeenCalledTimes(1);
    stop();
  });

  it('calls on pageshow, focus and resume', () => {
    const { host, page, doc } = fakeHost();
    const onWake = vi.fn();
    const stop = watchWake(onWake, host);
    page.dispatchEvent(new Event('pageshow'));
    page.dispatchEvent(new Event('focus'));
    doc.dispatchEvent(new Event('resume'));
    expect(onWake).toHaveBeenCalledTimes(3);
    stop();
  });

  it('once stopped, holds no interval or listener and calls nothing', async () => {
    const { host, page, doc, live, listeners } = fakeHost();
    const onWake = vi.fn();
    const stop = watchWake(onWake, host);
    expect(live.size).toBe(1);
    expect(listeners).toEqual({ page: 2, document: 1 });
    stop();
    expect(live.size).toBe(0);
    expect(listeners).toEqual({ page: 0, document: 0 });
    expect(vi.getTimerCount()).toBe(0);
    await sleep(WAKE_CHECK_MS + WAKE_GAP_MS + 60_000);
    page.dispatchEvent(new Event('pageshow'));
    page.dispatchEvent(new Event('focus'));
    doc.dispatchEvent(new Event('resume'));
    expect(onWake).not.toHaveBeenCalled();
    // Stopping twice is stopping once.
    stop();
    expect(live.size).toBe(0);
  });

  it('is one check for the page, however many listen, and stops with the last', async () => {
    const { host, live, listeners } = fakeHost();
    const map = vi.fn();
    const panel = vi.fn();
    const line = vi.fn();
    const stops = [watchWake(map, host), watchWake(panel, host), watchWake(line, host)];
    expect(live.size).toBe(1);
    expect(listeners).toEqual({ page: 2, document: 1 });
    await sleep(60 * 60_000);
    expect([map, panel, line].map((fn) => fn.mock.calls.length)).toEqual([1, 1, 1]);
    // The panel closes: it hears no more, the others do.
    stops[1]?.();
    expect(live.size).toBe(1);
    await sleep(60 * 60_000);
    expect([map, panel, line].map((fn) => fn.mock.calls.length)).toEqual([2, 1, 2]);
    stops[0]?.();
    stops[2]?.();
    expect(live.size).toBe(0);
    expect(listeners).toEqual({ page: 0, document: 0 });
    // A listener after that starts the check again.
    const late = vi.fn();
    const stop = watchWake(late, host);
    expect(live.size).toBe(1);
    await sleep(60 * 60_000);
    expect(late).toHaveBeenCalledTimes(1);
    stop();
  });
});
