/**
 * The Snowlight tile: the clipped group of the lockup, on a 0 0 128 128 box. The lockup is
 * built as its file says: this tile, then the word as real text.
 */
export const TILE =
  '<svg class="tile" viewBox="0 0 128 128" width="32" height="32" aria-hidden="true" focusable="false">' +
  '<clipPath id="lk-tile"><rect width="128" height="128" rx="28.7"/></clipPath>' +
  '<g clip-path="url(#lk-tile)">' +
  '<defs>' +
  '<linearGradient id="lk-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0f17"/><stop offset="1" stop-color="#04060a"/></linearGradient>' +
  '<linearGradient id="lk-snow" gradientUnits="userSpaceOnUse" x1="0" y1="91.55" x2="0" y2="128"><stop offset="0" stop-color="#ffffff"/><stop offset="0.3" stop-color="#f3f9fd"/><stop offset="1" stop-color="#bdd9ee"/></linearGradient>' +
  '<path id="lk-arm" d="M-5 0V-32.75L-16.75 -39.53V-49.53L-5 -42.75V-54.11L0 -57L5 -54.11V-42.75L16.75 -49.53V-39.53L5 -32.75V0Z"/>' +
  '<path id="lk-foot" d="M-5 0V-18.36L0 -21.25L5 -18.36V0Z"/>' +
  '<clipPath id="lk-above"><path d="M0 92.75Q64 73.75 128 92.75V0H0Z"/></clipPath>' +
  '</defs>' +
  '<rect width="128" height="128" fill="url(#lk-sky)"/>' +
  '<g clip-path="url(#lk-above)"><g transform="translate(64 75.5)" fill="#7fd4ff">' +
  '<use href="#lk-arm"/><use href="#lk-arm" transform="rotate(60)"/><use href="#lk-arm" transform="rotate(-60)"/>' +
  '<use href="#lk-foot" transform="rotate(120)"/><use href="#lk-foot" transform="rotate(-120)"/><use href="#lk-foot" transform="rotate(180)"/>' +
  '</g></g>' +
  '<path d="M0 99Q64 80 128 99V128H0Z" fill="url(#lk-snow)"/>' +
  '</g></svg>';
