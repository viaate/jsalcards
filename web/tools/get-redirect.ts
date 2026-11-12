import { minifySync, type Plugin } from 'vite';

/**
 * The map's phone redirect to the getsnowlight landing (docs/getsnowlight.md): an iPhone in
 * Safari that opens the map's front page is sent to https://www.getsnowlight.com/, on every
 * visit until it chooses the map there. The landing's "Open the live map" comes back with
 * ?map=1, which the map remembers (sl-map) and takes out of the address bar, and that device is
 * never sent again.
 *
 * The build writes the script, minified and with none of these words, as the first script in
 * index.html's head, in place of its <!-- get-redirect --> marker, so the map's page stays
 * within its size budget (e2e/shell.spec.ts PAGE_GZIP_BUDGET).
 */

/**
 * THE SWITCH. "off" sends no one; "on" sends as above. Going live is this one line (after the
 * owner's two GoDaddy steps are in and https://www.getsnowlight.com serves the page). A build
 * can still say VITE_GET_REDIRECT=on or off, as every e2e build of the map does (off), so the
 * flip changes no test.
 */
export const GET_REDIRECT: Switch = 'off';

export type Switch = 'on' | 'off';

/** The switch for a build: VITE_GET_REDIRECT if it says on or off, else GET_REDIRECT. */
export function getRedirectSwitch(env: Readonly<Record<string, string | undefined>>): Switch {
  const given = env.VITE_GET_REDIRECT?.trim() ?? '';
  if (given === '') return GET_REDIRECT;
  if (given !== 'on' && given !== 'off') {
    throw new Error(`get-redirect: VITE_GET_REDIRECT is "${given}", not on or off`);
  }
  return given;
}

/** Where the landing is. */
export const GET_URL = 'https://www.getsnowlight.com/';

/**
 * Who is sent: Safari itself on an iPhone, and nothing else. The whole user agent must be
 * Safari's own, word for word but for its version numbers, so every other browser and every
 * app's own browser (Chrome, Firefox, Edge, Opera, DuckDuckGo, Google, Facebook, Instagram,
 * Pinterest, LinkedIn...), each of which adds or swaps a word, an iPod or an iPad, an Android
 * phone, a desktop, and every crawler that says its name (Googlebot, Applebot, bingbot,
 * Lighthouse...) is left on the map. This is the one test of who is sent: widen it here.
 */
export const WHO =
  /^Mozilla\/5\.0 \(iPhone; CPU iPhone OS \d+(?:_\d+)* like Mac OS X\) AppleWebKit\/[\d.]+ \(KHTML, like Gecko\) Version\/[\d.]+ Mobile\/\w+ Safari\/[\d.]+$/u;

/**
 * The script, as the page runs it (then minified). HOME is the map's front page under the
 * build's base path. In order: ?map=1 is remembered and taken out of the address bar whatever
 * the switch says; then no one is sent while the switch is off, before the site's lock is passed
 * (that line goes with the lock at go-live), from any link but the bare front page (a school or
 * a shared card has a query or a hash), once the device has chosen the map, by anything but
 * WHO, or from the home screen; and never where the choice could not be remembered. Sending
 * stops the map's page first, so nothing more of it loads or paints.
 */
const SOURCE = String.raw`
(function (script) {
  var WHO = __WHO__;
  var HOME = __HOME__;
  var KEY = 'sl-map';
  try {
    var query = new URLSearchParams(location.search);
    if (query.get('map') === '1') {
      localStorage.setItem(KEY, '1');
      query.delete('map');
      var rest = query.toString();
      history.replaceState(
        history.state,
        '',
        location.pathname + (rest === '' ? '' : '?' + rest) + location.hash,
      );
      return;
    }
    if (script.getAttribute('data-get-redirect') !== 'on') return;
    var host = location.hostname;
    var local = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
    if (!local && localStorage.getItem('sl-lock') !== 'MjM4MQ==') return;
    if (location.search !== '' || location.hash !== '') return;
    if (location.pathname !== HOME && location.pathname !== HOME + 'index.html') return;
    if (localStorage.getItem(KEY) !== null) return;
    if (!WHO.test(navigator.userAgent)) return;
    if (navigator.standalone === true) return;
    if (matchMedia('(display-mode: standalone), (display-mode: fullscreen)').matches) return;
    localStorage.setItem(KEY + '-try', '1');
    localStorage.removeItem(KEY + '-try');
    window.stop();
    location.replace(__TO__);
  } catch (e) {}
})(document.currentScript);
`;

/** The script's code for a build whose base path is `base`, minified. */
export function redirectCode(base: string): string {
  const code = SOURCE.replace('__WHO__', WHO.toString())
    .replace('__HOME__', JSON.stringify(base))
    .replace('__TO__', JSON.stringify(GET_URL));
  const out = minifySync('get-redirect.js', code, { compress: true, mangle: true });
  if (out.errors.length > 0) throw new Error(`get-redirect: ${out.errors[0]?.message ?? ''}`);
  return out.code.trim();
}

/** The marker in index.html's head that the build replaces with the script. */
export const MARKER = '<!-- get-redirect -->';

/** The script element, switch and all. */
export function redirectTag(on: Switch, base: string): string {
  return `<script data-get-redirect="${on}">${redirectCode(base)}</script>`;
}

/** index.html with its marker replaced by the script; anything else is refused. */
export function putRedirect(html: string, on: Switch, base: string): string {
  const parts = html.split(MARKER);
  if (parts.length !== 2) throw new Error(`get-redirect: index.html needs one ${MARKER}`);
  return parts.join(redirectTag(on, base));
}

/** The Vite plugin: writes the script into the map's own index.html (and no other page). */
export function getRedirect(on: Switch): Plugin {
  let base = '/';
  return {
    name: 'snowlight:get-redirect',
    configResolved(config) {
      base = config.base;
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html, context) {
        if (context.path !== '/index.html') return html;
        return putRedirect(html, on, base);
      },
    },
  };
}
