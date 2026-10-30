/**
 * The words of the themes (theme/themes.ts) and of a theme's preview tile
 * (ui/themes/ThemeTile.svelte), which load with them, never with the page's
 * first script. The same rules hold here as in src/copy.ts, and
 * `npm run lint:copy` reads this file as the site's copy
 * (scripts/check-copy.mjs COPY_MODULES).
 */

/** Recursively freezes an object graph so no string can be changed at runtime. */
function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

export const themesCopy = /* @__PURE__ */ deepFreeze({
  /** Each theme's name, as the shop and a picker show it. */
  names: {
    midnight: 'Midnight',
    daylight: 'Daylight',
    aurora: 'Aurora',
    ember: 'Ember',
    glacier: 'Glacier',
    dusk: 'Dusk',
    bronze: 'Bronze',
    silver: 'Silver',
    gold: 'Gold',
    snowball: 'Snowball',
  },
  /** A tile's picture of the theme: a corner of a school's panel, and the four marks. */
  preview: {
    chance: '34',
    percent: '%',
    status: 'Snow day',
    /** The marks, as a screen reader names them. */
    marks: 'Closed, delayed, open, chance',
  },
  /** What a tile's button says. */
  action: {
    try: 'Try it',
    use: 'Use',
    inUse: 'In use',
  },
  /** What a tile says beside the name. */
  badge: {
    free: 'Free',
    owned: 'Owned',
    locked: 'Locked',
  },
});
