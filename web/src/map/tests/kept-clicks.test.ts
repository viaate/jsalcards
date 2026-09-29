// @vitest-environment node
/**
 * Clicks kept before the taps' code is in: handed on where their place is on
 * the screen now, and only while the map shows the view they fell on.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import { keepClicks } from '../kept-clicks';

/** A map whose view is a center and a zoom, a screen point one degree to 100 pixels. */
class FakeMap {
  center = { lng: -94.6, lat: 39 };
  zoom = 14;
  readonly listeners = new Map<string, (event: object) => void>();
  on(type: string, listener: (event: object) => void): void {
    this.listeners.set(type, listener);
  }
  off(type: string): void {
    this.listeners.delete(type);
  }
  getCenter(): { lng: number; lat: number } {
    return this.center;
  }
  getZoom(): number {
    return this.zoom;
  }
  project([lng, lat]: [number, number]): { x: number; y: number } {
    return { x: 400 + (lng - this.center.lng) * 100, y: 300 - (lat - this.center.lat) * 100 };
  }
  unproject(x: number, y: number): { lng: number; lat: number } {
    return { lng: this.center.lng + (x - 400) / 100, lat: this.center.lat - (y - 300) / 100 };
  }
  /** A click at a point on the screen, as MapLibre fires it. */
  click(x: number, y: number): object {
    const originalEvent = { type: 'click', x, y };
    this.listeners.get('click')?.({
      point: { x, y },
      lngLat: this.unproject(x, y),
      originalEvent,
    });
    return originalEvent;
  }
  get map(): MapLibreMap {
    return this as unknown as MapLibreMap;
  }
}

describe('a click kept before the taps are in', () => {
  it('is handed on at the point it fell, on a map that has not moved', async () => {
    const map = new FakeMap();
    const keeper = keepClicks(map.map);
    const original = map.click(450, 250);
    await keeper.heard;
    const [click, ...others] = keeper.stop();
    expect(others).toEqual([]);
    expect(click?.point.x).toBeCloseTo(450, 9);
    expect(click?.point.y).toBeCloseTo(250, 9);
    expect(click?.originalEvent).toBe(original);
    // No longer listened for.
    expect(map.listeners.has('click')).toBe(false);
  });

  it('is dropped once the map has moved, however little: its point is another place now', () => {
    const map = new FakeMap();
    const keeper = keepClicks(map.map);
    map.click(450, 250);
    // A hand drags another school under the point the click fell on.
    map.center = { lng: map.center.lng + 0.5, lat: map.center.lat };
    expect(keeper.stop()).toEqual([]);

    const zoomed = new FakeMap();
    const other = keepClicks(zoomed.map);
    zoomed.click(450, 250);
    zoomed.zoom += 0.001;
    expect(other.stop()).toEqual([]);
  });

  it('keeps only the clicks the map has not moved since', () => {
    const map = new FakeMap();
    const keeper = keepClicks(map.map);
    map.click(100, 100);
    map.center = { lng: map.center.lng + 1, lat: map.center.lat };
    const later = map.click(200, 200);
    const kept = keeper.stop();
    expect(kept.map((click) => click.originalEvent)).toEqual([later]);
    expect(kept[0]?.point).toEqual({ x: 200, y: 200 });
  });
});
