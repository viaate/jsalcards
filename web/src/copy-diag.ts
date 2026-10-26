/**
 * The words of the screen check (ui/Diagnostics.svelte), shown only with
 * ?diag=1 in the address: how big the page's window is, how far it is zoomed
 * and shifted, its safe areas and its screen, for a device the site looks
 * wrong on. It loads with that box, never with the page's first script. The
 * same rules hold here as in src/copy.ts, and `npm run lint:copy` reads this
 * file as the site's copy (scripts/check-copy.mjs COPY_MODULES).
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

export const diagCopy = /* @__PURE__ */ deepFreeze({
  /** The box, as a screen reader names it. */
  label: 'Screen check',
  /** window.innerWidth × innerHeight. */
  window: 'Window',
  /** The visual viewport's width × height. */
  visible: 'Visible',
  /** The visual viewport's scale. */
  zoom: 'Zoom',
  /** The visual viewport's offsetLeft, offsetTop. */
  shift: 'Shift',
  /** The page's scrollWidth over its clientWidth. */
  page: 'Page width',
  /** env(safe-area-inset-*): top, right, bottom, left. */
  safe: 'Safe area',
  pixels: 'Pixel ratio',
  /** screen.width × screen.height. */
  screen: 'Screen',
  /** The user agent. */
  browser: 'Browser',
});

/** A number as the box shows it: whole, or to two places. */
function number(value: number): string {
  if (!Number.isFinite(value)) return '–';
  return String(Math.round(value * 100) / 100);
}

/** A size: "951 × 543". */
function size(width: number, height: number): string {
  return `${number(width)} × ${number(height)}`;
}

/** Two numbers apart: "59.4, 0". */
function pair(x: number, y: number): string {
  return `${number(x)}, ${number(y)}`;
}

/** One width over another: "951 / 951". */
function over(a: number, b: number): string {
  return `${number(a)} / ${number(b)}`;
}

/** The four safe areas, top, right, bottom and left: "0 · 59 · 21 · 59". */
function sides(top: number, right: number, bottom: number, left: number): string {
  return [top, right, bottom, left].map(number).join(' · ');
}

export const diagFormat = /* @__PURE__ */ deepFreeze({ number, size, pair, over, sides });

export type DiagCopy = typeof diagCopy;
