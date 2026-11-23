/**
 * Flights mode (flights spec FL-2): its map layer, its search and menu in the top strip, its key,
 * its update line and its panels, over the shared map. Loaded only when Flights first shows
 * (modes/registry.ts); everything it puts on the page goes when it stops.
 */
import { mount, unmount } from 'svelte';

import type { ModeModule } from '../registry';
import FlightsMode from './FlightsMode.svelte';
import { createFlightsFiles } from './data';

export const flightsMode: ModeModule = {
  start({ map, header, stage, signal }) {
    const files = createFlightsFiles();
    const ui = mount(FlightsMode, { target: stage, props: { map, header, files, signal } });
    signal.addEventListener(
      'abort',
      () => {
        void unmount(ui);
      },
      { once: true },
    );
  },
};
