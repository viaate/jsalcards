/**
 * Where a phone opens (nearby.ts): over its viewer's own area only when they
 * have already let the site know where they are. The page never asks.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { grantedPlace, opensNearby } from '../nearby';
import type { Locator } from '../nearby';

/** A browser whose viewer has, or has not, let the site know, and a phone that answers so. */
function locator(
  state: PermissionState | 'throws',
  answer: 'kansas-city' | 'error' | 'never',
): { locator: Locator; reads: () => number } {
  const getCurrentPosition = vi.fn(
    (found: PositionCallback, failed?: PositionErrorCallback | null) => {
      if (answer === 'kansas-city') {
        found({ coords: { latitude: 39.0997, longitude: -94.5786 } } as GeolocationPosition);
      } else if (answer === 'error') {
        failed?.({ code: 2, message: 'unavailable' } as GeolocationPositionError);
      }
    },
  );
  const query = vi.fn(() =>
    state === 'throws'
      ? Promise.reject(new TypeError('no such permission'))
      : Promise.resolve({ state }),
  );
  return {
    locator: {
      permissions: { query } as unknown as Permissions,
      geolocation: { getCurrentPosition } as unknown as Geolocation,
    },
    reads: () => getCurrentPosition.mock.calls.length,
  };
}

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.style.removeProperty('--home-view');
});

describe('grantedPlace', () => {
  it('reads where the viewer is when they have let the site know', async () => {
    const { locator: allowed, reads } = locator('granted', 'kansas-city');
    expect(await grantedPlace(allowed)).toEqual({ lat: 39.0997, lon: -94.5786 });
    expect(reads()).toBe(1);
  });

  it('never reads it, and so never asks, when they have not', async () => {
    for (const state of ['prompt', 'denied', 'throws'] as const) {
      const { locator: asked, reads } = locator(state, 'kansas-city');
      expect(await grantedPlace(asked), state).toBeNull();
      expect(reads(), state).toBe(0);
    }
    expect(await grantedPlace({})).toBeNull();
  });

  it('opens on the country when the phone cannot say, or is slow to', async () => {
    expect(await grantedPlace(locator('granted', 'error').locator)).toBeNull();
    vi.useFakeTimers();
    const slow = grantedPlace(locator('granted', 'never').locator, 1500);
    await vi.advanceTimersByTimeAsync(1500);
    expect(await slow).toBeNull();
  });
});

describe('opensNearby', () => {
  it('follows the page: a phone opens near its viewer, a wider screen on the country', () => {
    expect(opensNearby(document.documentElement)).toBe(false);
    document.documentElement.style.setProperty('--home-view', 'nearby');
    expect(opensNearby(document.documentElement)).toBe(true);
  });
});
