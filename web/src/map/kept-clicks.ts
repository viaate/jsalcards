/**
 * Clicks on the map heard before the code that reads them is in
 * (school-taps.ts), from the moment the map takes input.
 *
 * A click is kept by where on the map it fell, with the view it fell on. It
 * is handed on only while the map still shows that view, at the point on the
 * screen that place is at: once the map has moved since (a hand, a flight),
 * the same point on the screen is another place, and the click is dropped.
 */
import type { Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl';

/** A click as the taps read it: where on the screen it is, and the event it came in. */
export type HeardClick = Pick<MapMouseEvent, 'point' | 'originalEvent'>;

export interface ClickKeeper {
  /** Resolves at the first click kept. */
  readonly heard: Promise<void>;
  /** Stops keeping clicks, and gives the ones the map has not moved since, as they are now. */
  stop(): HeardClick[];
}

interface Kept {
  readonly lng: number;
  readonly lat: number;
  /** The view it fell on. */
  readonly view: string;
  readonly originalEvent: MouseEvent;
}

/** The map's view, exactly: two views are one only where nothing has moved. */
function viewOf(map: MapLibreMap): string {
  const { lng, lat } = map.getCenter();
  return `${String(lng)} ${String(lat)} ${String(map.getZoom())}`;
}

export function keepClicks(map: MapLibreMap): ClickKeeper {
  const kept: Kept[] = [];
  let heard: () => void = () => undefined;
  const first = new Promise<void>((resolve) => {
    heard = resolve;
  });
  const onClick = (event: MapMouseEvent): void => {
    const { lng, lat } = event.lngLat;
    kept.push({ lng, lat, view: viewOf(map), originalEvent: event.originalEvent });
    heard();
  };
  map.on('click', onClick);
  return {
    heard: first,
    stop() {
      map.off('click', onClick);
      const now = viewOf(map);
      return kept
        .filter((click) => click.view === now)
        .map((click) => ({
          point: map.project([click.lng, click.lat]),
          originalEvent: click.originalEvent,
        }));
    },
  };
}
