/**
 * The event the theme engine (engine.ts) dispatches on `document` once a
 * theme's properties are on the page, for the map to take its colors again
 * (map/basemap/index.ts, map/glow-mount.ts). Its own module, so the map's
 * code carries no theme of its own.
 */
export const THEME_EVENT = 'snowlight:theme';

/** Where a device keeps the theme it uses: its id and its CSS, for index.html to apply first. */
export const THEME_STORAGE_KEY = 'snowlight:theme';
