// @vitest-environment jsdom
/**
 * School layers hidden under another mode's mark come back whichever way the mark comes off
 * (map/other-mode.ts): the host showing Schools, or no host at all (its chunk failed, no map).
 */
import { afterEach, describe, expect, it } from 'vitest';

import { hideWhileMarked, otherModeMarked, waitsForMarkOff } from '../other-mode';

function fakeMap(ids: readonly string[]) {
  const shown = new Map<string, string>(ids.map((id) => [id, 'visible']));
  return {
    shown,
    getLayer: (id: string) => (shown.has(id) ? { id } : undefined),
    getLayoutProperty: (id: string) => shown.get(id),
    setLayoutProperty: (id: string, _name: string, value: unknown) => {
      shown.set(id, String(value));
    },
  };
}

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  document.documentElement.removeAttribute('data-mode');
});

describe('a school layer under another mode', () => {
  it('goes on hidden only while the mark is on', () => {
    const map = fakeMap(['school-dots']);
    expect(hideWhileMarked(map, 'school-dots')).toBe(false);
    expect(map.shown.get('school-dots')).toBe('visible');
  });

  it('shows again, the glow with it, when the mark comes off with no host', async () => {
    document.documentElement.setAttribute('data-mode', 'flights');
    expect(otherModeMarked()).toBe(true);
    const map = fakeMap(['school-dots', 'snowlight-glow']);
    expect(hideWhileMarked(map, 'school-dots')).toBe(true);
    expect(hideWhileMarked(map, 'snowlight-glow')).toBe(true);
    expect(map.shown.get('snowlight-glow')).toBe('none');
    // The host chunk failed: boot.ts takes the mark off, and nothing else runs.
    document.documentElement.removeAttribute('data-mode');
    await settle();
    expect(map.shown.get('school-dots')).toBe('visible');
    expect(map.shown.get('snowlight-glow')).toBe('visible');
    expect(waitsForMarkOff('school-dots')).toBe(false);
  });

  it('stays hidden while the mark only changes to another mode', async () => {
    document.documentElement.setAttribute('data-mode', 'flights');
    const map = fakeMap(['school-dots']);
    hideWhileMarked(map, 'school-dots');
    document.documentElement.setAttribute('data-mode', 'boats');
    await settle();
    expect(map.shown.get('school-dots')).toBe('none');
    document.documentElement.removeAttribute('data-mode');
    await settle();
    expect(map.shown.get('school-dots')).toBe('visible');
  });

  it('leaves a layer gone with a style change alone', async () => {
    document.documentElement.setAttribute('data-mode', 'flights');
    const map = fakeMap(['school-dots']);
    hideWhileMarked(map, 'school-dots');
    map.shown.delete('school-dots');
    document.documentElement.removeAttribute('data-mode');
    await settle();
    expect(map.shown.has('school-dots')).toBe(false);
  });
});
