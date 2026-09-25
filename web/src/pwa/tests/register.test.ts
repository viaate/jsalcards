import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerServiceWorker } from '../register';
import type { RegisterOptions, ServiceWorkerHandle } from '../register';
import { SKIP_WAITING_MESSAGE } from '../config';
import { FakeWindow, FakeWorker } from './fakes';
import type { FakeWindowOptions } from './fakes';

const HOUR = 3_600_000;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Registers on a fake window and runs timers until registration settles. */
async function start(
  options: Omit<RegisterOptions, 'host'> = {},
  windowOptions: FakeWindowOptions = {},
): Promise<{ win: FakeWindow; handle: ServiceWorkerHandle | null }> {
  const win = new FakeWindow(windowOptions);
  const pending = registerServiceWorker({ enabled: true, base: '/', ...options, host: win });
  await vi.advanceTimersByTimeAsync(10);
  return { win, handle: await pending };
}

/** A page whose worker is already installed and in control, as on a second visit. */
async function startControlled(options: Omit<RegisterOptions, 'host'> = {}) {
  const win = new FakeWindow();
  const active = new FakeWorker();
  active.state = 'activated';
  win.container.controller = active;
  win.container.registration.active = active;
  const pending = registerServiceWorker({ enabled: true, base: '/', ...options, host: win });
  await vi.advanceTimersByTimeAsync(10);
  return { win, handle: await pending };
}

describe('when there is nothing to register', () => {
  it('returns null in a development build', async () => {
    const win = new FakeWindow();
    expect(await registerServiceWorker({ host: win })).toBeNull();
    expect(win.container.calls).toEqual([]);
  });

  it('returns null without service worker support', async () => {
    const { win, handle } = await start({}, { serviceWorker: false });
    expect(handle).toBeNull();
    expect(win.container.calls).toEqual([]);
  });

  it('returns null and warns once when registration fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const win = new FakeWindow();
    win.container.failRegister = true;
    const pending = registerServiceWorker({ enabled: true, base: '/', host: win });
    await vi.advanceTimersByTimeAsync(10);
    expect(await pending).toBeNull();
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });
});

describe('registration', () => {
  it('waits for the load event and an idle moment', async () => {
    const win = new FakeWindow({ readyState: 'loading' });
    const pending = registerServiceWorker({ enabled: true, base: '/', host: win });
    await vi.advanceTimersByTimeAsync(1000);
    expect(win.container.calls).toEqual([]);
    win.load();
    await vi.advanceTimersByTimeAsync(1);
    expect(win.container.calls).toEqual([]);
    await vi.advanceTimersByTimeAsync(10);
    expect(await pending).not.toBeNull();
    expect(win.container.calls).toHaveLength(1);
  });

  it('registers the worker at the base, bypassing the HTTP cache for updates', async () => {
    const { win } = await start({ base: '/snowlight/' });
    expect(win.container.calls).toEqual([
      ['/snowlight/sw.js', { scope: '/snowlight/', updateViaCache: 'none' }],
    ]);
  });
});

describe('the first visit', () => {
  it('caches the data the page loaded before the worker took over', async () => {
    const { win } = await start(
      { warmUrls: ['/data/search-index.bin', 'https://elsewhere.example/data/x.json'] },
      {
        resources: [
          'https://snow.test/data/live/closings.json',
          'https://snow.test/data/schools/meta.json',
          'https://snow.test/data/live/closings.json',
          'https://snow.test/assets/index-abc.js',
          'https://tiles.openfreemap.org/planet',
          'https://snow.test/other/data/x.json',
        ],
      },
    );
    expect(win.fetched).toEqual([]);
    const worker = new FakeWorker();
    win.container.registration.installing = worker;
    worker.to('installed');
    worker.to('activated');
    win.container.control(worker);
    await vi.advanceTimersByTimeAsync(0);
    expect(win.fetched.sort()).toEqual([
      'https://snow.test/data/live/closings.json',
      'https://snow.test/data/schools/meta.json',
      'https://snow.test/data/search-index.bin',
    ]);
    expect(win.location.reload).not.toHaveBeenCalled();
  });

  it('says when that is done, and never fetches the school tiles whole', async () => {
    const { win, handle } = await start(
      { warmUrls: ['/data/schools/schools.pmtiles'] },
      {
        resources: [
          'https://snow.test/data/live/closings.json',
          'https://snow.test/data/schools/schools.pmtiles',
        ],
      },
    );
    let warmed: number | undefined;
    void handle?.warmed.then((count) => {
      warmed = count;
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(warmed).toBeUndefined();
    const worker = new FakeWorker();
    worker.state = 'activated';
    win.container.control(worker);
    await vi.advanceTimersByTimeAsync(0);
    expect(warmed).toBe(1);
    expect(win.fetched).toEqual(['https://snow.test/data/live/closings.json']);
  });

  it('has nothing to warm when a worker already controls the page', async () => {
    const { win, handle } = await startControlled();
    await expect(handle?.warmed).resolves.toBe(0);
    expect(win.fetched).toEqual([]);
  });

  it('is not an update, so nothing waits and nothing reloads', async () => {
    const onUpdateReady = vi.fn();
    const { win, handle } = await start({ onUpdateReady, applyWhenHidden: true });
    const worker = win.container.registration.found();
    win.container.registration.installed();
    expect(worker.state).toBe('installed');
    expect(onUpdateReady).not.toHaveBeenCalled();
    expect(handle?.updateReady).toBe(false);
    win.setVisibility('hidden');
    expect(worker.messages).toEqual([]);
  });
});

describe('updates', () => {
  it('reports a new version once it is installed and waiting', async () => {
    const onUpdateReady = vi.fn();
    const { win, handle } = await startControlled({ onUpdateReady });
    const next = win.container.registration.found();
    expect(onUpdateReady).not.toHaveBeenCalled();
    win.container.registration.installed();
    expect(onUpdateReady).toHaveBeenCalledOnce();
    expect(handle?.updateReady).toBe(true);
    // By default the new version waits for every tab to close.
    win.setVisibility('hidden');
    expect(next.messages).toEqual([]);
    expect(win.location.reload).not.toHaveBeenCalled();
  });

  it('reports a version that was already waiting when the page opened', async () => {
    const win = new FakeWindow();
    const active = new FakeWorker();
    win.container.controller = active;
    win.container.registration.waiting = new FakeWorker();
    const onUpdateReady = vi.fn();
    const pending = registerServiceWorker({ enabled: true, base: '/', host: win, onUpdateReady });
    await vi.advanceTimersByTimeAsync(10);
    expect((await pending)?.updateReady).toBe(true);
    expect(onUpdateReady).toHaveBeenCalledOnce();
  });

  it('with applyWhenHidden, switches while the tab is hidden and reloads unseen', async () => {
    const { win } = await startControlled({ applyWhenHidden: true });
    const next = win.container.registration.found();
    win.container.registration.installed();
    expect(next.messages).toEqual([]);
    win.setVisibility('hidden');
    expect(next.messages).toEqual([SKIP_WAITING_MESSAGE]);
    win.container.control(next);
    expect(win.location.reload).toHaveBeenCalledOnce();
  });

  it('when another tab switches while this one is in view, reloads once it is hidden', async () => {
    const { win } = await startControlled();
    const next = win.container.registration.found();
    win.container.registration.installed();
    win.container.control(next);
    expect(win.location.reload).not.toHaveBeenCalled();
    win.setVisibility('hidden');
    expect(win.location.reload).toHaveBeenCalledOnce();
  });

  it('applyUpdate switches now and reloads', async () => {
    const { win, handle } = await startControlled();
    const next = win.container.registration.found();
    win.container.registration.installed();
    handle?.applyUpdate();
    expect(next.messages).toEqual([SKIP_WAITING_MESSAGE]);
    win.container.control(next);
    expect(win.location.reload).toHaveBeenCalledOnce();
  });

  it('applyUpdate does nothing with no version waiting', async () => {
    const { win, handle } = await startControlled();
    handle?.applyUpdate();
    win.container.control(new FakeWorker());
    expect(win.location.reload).not.toHaveBeenCalled();
  });

  it('looks for a new version every hour while the tab is in view and online', async () => {
    const { win } = await startControlled();
    const registration = win.container.registration;
    await vi.advanceTimersByTimeAsync(HOUR);
    expect(registration.updates).toBe(1);
    win.document.visibilityState = 'hidden';
    await vi.advanceTimersByTimeAsync(HOUR);
    expect(registration.updates).toBe(1);
    win.document.visibilityState = 'visible';
    win.navigator.onLine = false;
    await vi.advanceTimersByTimeAsync(HOUR);
    expect(registration.updates).toBe(1);
    win.navigator.onLine = true;
    registration.failUpdate = true;
    await vi.advanceTimersByTimeAsync(HOUR);
    expect(registration.updates).toBe(2);
  });

  it('checks on return to a tab that was away for an hour or more', async () => {
    const { win } = await startControlled();
    win.setVisibility('hidden');
    await vi.advanceTimersByTimeAsync(HOUR - 1000);
    win.setVisibility('visible');
    expect(win.container.registration.updates).toBe(0);
    win.setVisibility('hidden');
    vi.setSystemTime(Date.now() + 2 * HOUR);
    win.setVisibility('visible');
    expect(win.container.registration.updates).toBe(1);
  });

  it('stop ends the checks and listeners', async () => {
    const { win, handle } = await startControlled();
    handle?.stop();
    await vi.advanceTimersByTimeAsync(3 * HOUR);
    expect(win.container.registration.updates).toBe(0);
    win.container.control(new FakeWorker());
    win.setVisibility('hidden');
    expect(win.location.reload).not.toHaveBeenCalled();
  });
});
