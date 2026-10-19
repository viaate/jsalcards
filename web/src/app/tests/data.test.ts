import { afterEach, describe, expect, it, vi } from 'vitest';

import { createAppData } from '../data';

const LIVE = 'https://live.snow.test/v1/';

describe('createAppData', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('reads live/closings.json from the live root the build names, and every other file from data/', () => {
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', LIVE);
    const { files } = createAppData(['live/covered.json', 'schools/meta.0123456789.json'], '/');
    expect(files.has('live/closings.json')).toBe(true);
    expect(files.url('live/closings.json')).toBe(`${LIVE}live/closings.json`);
    expect(files.url('live/covered.json')).toBe(
      new URL('/data/live/covered.json', location.href).href,
    );
    expect(files.url('schools/meta.json')).toBe(
      new URL('/data/schools/meta.0123456789.json', location.href).href,
    );
  });

  it('reads its own data/ without a live root, or with one the page cannot read from', () => {
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', undefined);
    expect(createAppData(['live/closings.json'], '/').files.url('live/closings.json')).toBe(
      new URL('/data/live/closings.json', location.href).href,
    );
    expect(createAppData([], '/').files.has('live/closings.json')).toBe(false);
    // The preview workflow sets it empty until the owner turns live closings on.
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', '');
    expect(createAppData([], '/').files.has('live/closings.json')).toBe(false);
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', 'http://live.snow.test/v1/');
    expect(createAppData([], '/').files.has('live/closings.json')).toBe(false);
  });

  it('reads a root on this machine over plain http only in a build that allows it (the e2e’s)', () => {
    const local = 'http://127.0.0.1:4180/v1/';
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', local);
    expect(createAppData([], '/').files.has('live/closings.json')).toBe(false);
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_LOOPBACK', '1');
    expect(createAppData([], '/').files.url('live/closings.json')).toBe(
      `${local}live/closings.json`,
    );
    vi.stubEnv('VITE_SNOWLIGHT_LIVE_ROOT', 'http://live.snow.test/v1/');
    expect(createAppData([], '/').files.has('live/closings.json')).toBe(false);
  });
});
