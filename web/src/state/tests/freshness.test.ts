// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { format } from '../../copy';
import { createConnectivity, parseInstant, updateLine } from '../freshness';
import type { ConnectivityHost } from '../freshness';

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../scripts/check-copy.mjs',
);
const { problems } = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string) => string[];
};

const ZONE = 'America/Chicago';
const MINUTE = 60_000;
/** A file generated at 6:42 AM Chicago time on Monday, Jan 12, 2026. */
const GENERATED = '2026-01-12T12:42:00Z';

function line(now: string, online: boolean, liveWithinMs = 20 * MINUTE): string | null {
  return updateLine({
    generatedAt: GENERATED,
    online,
    liveWithinMs,
    timeZone: ZONE,
    now: new Date(now),
  });
}

describe('parseInstant', () => {
  it('reads a UtcInstant', () => {
    expect(parseInstant(GENERATED)?.toISOString()).toBe('2026-01-12T12:42:00.000Z');
  });

  it.each([
    '',
    '2026-01-12',
    '2026-01-12T12:42:00',
    '2026-01-12T12:42:00.000Z',
    '2026-01-12T12:42:00+00:00',
    '2026-02-30T12:00:00Z',
    '2026-01-12T24:00:00Z',
    'garbage',
    1768221720000,
    null,
  ])('rejects %j', (value) => {
    expect(parseInstant(value)).toBeNull();
  });
});

describe('updateLine', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows when the file was generated, not the time now', () => {
    // The clock says 3:15 PM; the line still says 6:42 AM.
    vi.setSystemTime(new Date('2026-01-12T21:15:00Z'));
    expect(line('2026-01-12T21:15:00Z', false)).toBe('Offline · Updated 6:42 AM');
    expect(line('2026-01-12T21:15:00Z', true)).toBe('Updated 6:42 AM');
  });

  it('says live only while the file is recent and the page is online', () => {
    expect(line('2026-01-12T12:50:00Z', true)).toBe('Live · 6:42 AM');
    expect(line('2026-01-12T13:02:00Z', true)).toBe('Live · 6:42 AM');
    expect(line('2026-01-12T13:03:00Z', true)).toBe('Updated 6:42 AM');
    expect(line('2026-01-12T12:50:00Z', false)).toBe('Offline · Updated 6:42 AM');
  });

  it('never calls a file from the future live', () => {
    expect(line('2026-01-12T12:30:00Z', true)).toBe('Updated 6:42 AM');
  });

  it('adds the date when the file is from another day', () => {
    expect(line('2026-01-14T15:00:00Z', false)).toBe('Offline · Updated Mon, Jan 12, 6:42 AM');
    expect(line('2026-01-14T15:00:00Z', true)).toBe('Updated Mon, Jan 12, 6:42 AM');
  });

  it('matches the copy formatters and the house style', () => {
    const now = new Date('2026-01-13T08:00:00Z');
    const generated = new Date(GENERATED);
    expect(line(now.toISOString(), false)).toBe(format.offline(generated, ZONE, now));
    for (const text of [
      line('2026-01-12T12:50:00Z', true),
      line('2026-01-12T21:15:00Z', true),
      line('2026-01-14T15:00:00Z', false),
    ]) {
      expect(text).not.toBeNull();
      expect(problems(text ?? '')).toEqual([]);
    }
  });

  it('shows nothing for a file without a valid time', () => {
    expect(
      updateLine({
        generatedAt: '2026-01-12T12:42',
        online: true,
        liveWithinMs: MINUTE,
        timeZone: ZONE,
        now: new Date(),
      }),
    ).toBeNull();
  });
});

describe('createConnectivity', () => {
  class FakeWindow extends EventTarget implements ConnectivityHost {
    readonly navigator = { onLine: true };

    set(online: boolean): void {
      this.navigator.onLine = online;
      this.dispatchEvent(new Event(online ? 'online' : 'offline'));
    }
  }

  it('follows the online and offline events', () => {
    const host = new FakeWindow();
    const connectivity = createConnectivity(host);
    const seen: boolean[] = [];
    connectivity.subscribe((online) => seen.push(online));
    host.set(false);
    host.set(false);
    host.set(true);
    expect(seen).toEqual([true, false, true]);
    expect(connectivity.online).toBe(true);
    connectivity.destroy();
    host.set(false);
    expect(seen).toEqual([true, false, true]);
  });
});
