/**
 * The day line over the map's key (ui/MapDay.svelte), started by the app's
 * services with the first days the live glow shows (app/boot.ts): the page's
 * first script holds none of it. It goes on the page's stage and words what
 * it is handed by the one formatter (copy-format.ts mapDays).
 */

import { mount, unmount } from 'svelte';

import { format } from '../copy-format';
import { regionOf } from '../data/map-day';
import type { MapDays } from '../data/live';
import MapDay from './MapDay.svelte';

export interface DayLine {
  /** Names the days the map shows, or none (null). */
  show(days: MapDays | null): void;
  destroy(): void;
}

/** The words for the days the map shows; null where none are needed or can be had. */
export function dayWords(days: MapDays | null): string | null {
  if (days === null) return null;
  try {
    return format.mapDays(
      days.days.map((shown) => ({
        day: shown.day,
        regions: shown.zones.map(regionOf),
        today: shown.today,
      })),
      days.viewerToday,
    );
  } catch {
    // A day the formatter refuses: no line rather than a wrong one.
    return null;
  }
}

export function startDayLine(stage: HTMLElement): DayLine {
  // What MapDay.svelte exports.
  const host: { show(next: string | null): void } = mount(MapDay, {
    target: stage,
    props: { stage },
  });
  return {
    show: (days) => {
      host.show(dayWords(days));
    },
    destroy: () => {
      void unmount(host);
    },
  };
}
