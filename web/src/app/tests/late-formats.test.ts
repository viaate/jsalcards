import FORMATS_URL from 'virtual:snowlight/copy-format-url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { lateFormats } from '../late-formats';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Whether a promise has settled, without waiting for it. */
async function settled(promise: Promise<unknown>): Promise<boolean> {
  let done = false;
  void promise.then(
    () => (done = true),
    () => (done = true),
  );
  await vi.advanceTimersByTimeAsync(0);
  return done;
}

describe('lateFormats', () => {
  it('fetches the formatters once the page has painted, then runs them', async () => {
    const steps: string[] = [];
    let paint: () => void = () => undefined;
    const formats = lateFormats({
      after: new Promise<void>((resolve) => {
        paint = resolve;
      }),
      download: (attempt) => {
        steps.push(`download ${String(attempt)}`);
        return Promise.resolve();
      },
      load: () => {
        steps.push('load');
        return Promise.resolve();
      },
    });
    await vi.advanceTimersByTimeAsync(5_000);
    expect(steps).toEqual([]);
    paint();
    await formats;
    expect(steps).toEqual(['download 0', 'load']);
  });

  it('fetches them again after a failed download, and imports them only once one has come', async () => {
    const steps: string[] = [];
    const formats = lateFormats({
      download: (attempt) => {
        steps.push(`download ${String(attempt)}`);
        return attempt < 2 ? Promise.reject(new TypeError('Failed to fetch')) : Promise.resolve();
      },
      load: () => {
        steps.push('load');
        return Promise.resolve();
      },
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(steps).toEqual(['download 0']);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(steps).toEqual(['download 0', 'download 1']);
    expect(await settled(formats)).toBe(false);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(steps).toEqual(['download 0', 'download 1', 'download 2', 'load']);
    expect(await settled(formats)).toBe(true);
  });

  it('settles when they cannot run, so what imports them fails as any code that cannot load', async () => {
    const formats = lateFormats({
      download: () => Promise.resolve(),
      load: () => Promise.reject(new TypeError('Failed to fetch dynamically imported module')),
    });
    await expect(formats).resolves.toBeUndefined();
  });

  it('asks again past a stalled download, from the server, and no more once the page goes', async () => {
    const fetches: [string, RequestInit | undefined][] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        fetches.push([url, init]);
        return new Promise<Response>(() => undefined);
      }),
    );
    const controller = new AbortController();
    const formats = lateFormats({ signal: controller.signal, load: () => Promise.resolve() });
    await vi.advanceTimersByTimeAsync(2_000 + 1_000);
    expect(fetches).toEqual([
      [FORMATS_URL, {}],
      [FORMATS_URL, { cache: 'reload' }],
    ]);
    controller.abort();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetches).toHaveLength(2);
    expect(await settled(formats)).toBe(false);
  });
});
