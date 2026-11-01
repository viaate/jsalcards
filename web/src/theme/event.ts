/**
 * The event the theme engine (engine.ts) dispatches on `document` once a
 * theme's properties are on the page, for the map to take its colors again
 * (map/basemap/index.ts, map/glow-mount.ts). Its own module, so the map's
 * code carries no theme of its own.
 */
export const THEME_EVENT = 'snowlight:theme';

/** Where a device keeps the theme it uses: its id and its CSS, for index.html to apply first. */
export const THEME_STORAGE_KEY = 'snowlight:theme';

/**
 * The root's mark that a kept theme's own style sheet could not load as the
 * page opened: index.html's first script shows Midnight in its place and
 * sets it, and the page (app/boot.ts) then starts the engine, which tries
 * the sheet again and puts the theme on once it loads.
 */
export const THEME_RETRY = 'data-theme-retry';
