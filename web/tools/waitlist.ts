/**
 * The waitlist build: with VITE_WAITLIST_KIT_FORM set to a Kit form's id, the
 * site's front page is the waitlist (src/waitlist/gate.ts says how it works);
 * unset or empty, the build is the site as it was, byte for byte.
 *
 * index.html keeps both, in blocks between markers:
 *
 *   <!-- waitlist:off:start --> … <!-- waitlist:off:end -->  the code screen, kept when off
 *   <!-- waitlist:on:start -->  … <!-- waitlist:on:end -->   the waitlist, kept when on
 *
 * The markers themselves never reach the build. With the waitlist on, the
 * plugin also:
 *
 * - takes the app's module script out of the page and hands its address to
 *   the waitlist (data-entry), which starts it only on a device with the code,
 *   so a visitor without it never downloads or runs the map;
 * - bundles src/waitlist/inline.ts into a classic script in place of
 *   <script data-waitlist-gate></script>, so the page makes no request for it;
 * - writes the pictures (src/waitlist/art/, from scripts/build-waitlist-art.mjs)
 *   under assets/waitlist/ with their content's hash in their names, and fills
 *   in %waitlist.…% tokens: the form id, its Kit address, the pictures, and the
 *   share card's absolute address;
 * - puts the waitlist's own cut of Geist (src/waitlist/art/geist-waitlist.woff2,
 *   from scripts/build-waitlist-font.mjs) into the page as a data: address,
 *   so the words paint in Geist at once and no font arrives later to move them;
 * - builds privacy.html, the page the waitlist links to.
 *
 * On GitHub Pages these come from the repository variables of the same names
 * without VITE_ (WAITLIST_KIT_FORM, WAITLIST_CONFIRM, WAITLIST_CONTACT,
 * WAITLIST_HEADLINE), which .github/workflows/preview.yml passes to the build.
 *
 * VITE_WAITLIST_CONFIRM must match the Kit form's double opt-in: unset (or on)
 * while it is on, Kit's default, so the page says a confirmation email is on
 * its way; off only when the form's double opt-in is off, and the page then
 * says nothing about confirming.
 *
 * VITE_WAITLIST_CONTACT, an email address the owner reads, puts a way to ask
 * for removal (or to report a signup by someone under 13) on the privacy
 * page, between <!-- contact:on:… --> markers; unset, those lines are dropped.
 *
 * VITE_WAITLIST_HEADLINE picks how the headline is set under the chrome
 * SNOWLIGHT wordmark: `text` (the default) in white type, `chrome` in the
 * wordmark's chrome lettering (pictures from scripts/build-waitlist-chrome.mjs,
 * the words kept as text for screen readers). index.html keeps both, between
 * <!-- headline:text:… --> and <!-- headline:chrome:… --> markers.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { build } from 'vite';
import type { Plugin, ResolvedConfig } from 'vite';

/** The site's address, for the share card: scrapers need it absolute. */
export const SITE_URL = 'https://snowlightmap.com';

/** The pictures the page uses, in src/waitlist/art/. */
export const ART = Object.freeze({
  map: 'map.webp',
  mapSmall: 'map-small.webp',
  sweep0: 'sweep-0.webp',
  sweep1: 'sweep-1.webp',
  sweep2: 'sweep-2.webp',
  sweep3: 'sweep-3.webp',
  social: 'social.jpg',
  chrome: 'chrome-wordmark.webp',
  chromeSmall: 'chrome-wordmark-small.webp',
  chromeHeadline: 'chrome-headline.webp',
  chromeHeadlineSmall: 'chrome-headline-small.webp',
});
export type ArtName = keyof typeof ART;

const ART_DIR = 'src/waitlist/art';
/** The waitlist's cut of Geist, in ART_DIR. */
const FONT = 'geist-waitlist.woff2';
const GATE_ENTRY = 'src/waitlist/inline.ts';
const GATE_TAG = '<script data-waitlist-gate></script>';
const TOKEN = /%waitlist\.([A-Za-z0-9.]+)%/gu;

/** The waitlist's settings from the build's environment, or null when it is off. */
export interface WaitlistSettings {
  /** The Kit form's id: digits only. */
  readonly form: string;
  /** Whether the Kit form asks each new subscriber to confirm by email. */
  readonly confirm: boolean;
  /** How the headline is set: in white type, or in the wordmark's chrome lettering. */
  readonly headline: HeadlineLook;
  /** An email address for removal requests, shown on the privacy page; null for none. */
  readonly contact: string | null;
}

/** The headline's two looks (VITE_WAITLIST_HEADLINE). */
export type HeadlineLook = 'text' | 'chrome';

/**
 * Reads VITE_WAITLIST_KIT_FORM and VITE_WAITLIST_CONFIRM. Unset or empty is
 * off. A form id that is not all digits fails the build, rather than ship a
 * form that cannot work.
 */
export function waitlistSettings(
  env: Readonly<Record<string, string | undefined>>,
): WaitlistSettings | null {
  const form = (env.VITE_WAITLIST_KIT_FORM ?? '').trim();
  if (form === '') return null;
  if (!/^\d{1,20}$/u.test(form)) {
    throw new Error(
      `VITE_WAITLIST_KIT_FORM must be a Kit form's id (digits only), not ${JSON.stringify(form)}`,
    );
  }
  const confirm = (env.VITE_WAITLIST_CONFIRM ?? '').trim().toLowerCase();
  if (!['', 'on', 'off'].includes(confirm)) {
    throw new Error(`VITE_WAITLIST_CONFIRM must be on or off, not ${JSON.stringify(confirm)}`);
  }
  const headline = (env.VITE_WAITLIST_HEADLINE ?? '').trim().toLowerCase();
  if (!['', 'text', 'chrome'].includes(headline)) {
    throw new Error(
      `VITE_WAITLIST_HEADLINE must be text or chrome, not ${JSON.stringify(headline)}`,
    );
  }
  const contact = (env.VITE_WAITLIST_CONTACT ?? '').trim();
  if (contact !== '' && !/^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/u.test(contact)) {
    throw new Error(
      `VITE_WAITLIST_CONTACT must be an email address, not ${JSON.stringify(contact)}`,
    );
  }
  return {
    form,
    confirm: confirm !== 'off',
    headline: headline === 'chrome' ? 'chrome' : 'text',
    contact: contact === '' ? null : contact,
  };
}

/**
 * Keeps the blocks named `keep` of a kind (`<!-- kind:name:start -->` …
 * `<!-- kind:name:end -->`) and drops the others, with their markers and the
 * line each marker sits on. Throws on a marker out of place, so a broken
 * index.html never builds into half of each.
 */
function keepNamed(html: string, kind: string, names: readonly string[], keep: string): string {
  const block = new RegExp(`<!-- ${kind}:(${names.join('|')}):(start|end) -->`, 'gu');
  let out = '';
  let at = 0;
  let open: string | null = null;
  for (const match of html.matchAll(block)) {
    const [, which, edge] = match as unknown as [string, string, 'start' | 'end'];
    const index = match.index;
    if (edge === 'start' ? open !== null : open !== which) {
      throw new Error(`waitlist: ${match[0]} out of place in index.html`);
    }
    // The marker's whole line goes: its indent before it and its line break after.
    const lineStart = html.lastIndexOf('\n', index - 1) + 1;
    const lineEnd = html.indexOf('\n', index) + 1 || html.length;
    if (open === null || open === keep) out += html.slice(at, lineStart);
    at = lineEnd;
    open = edge === 'start' ? which : null;
  }
  if (open !== null) throw new Error(`waitlist: the ${open} block in index.html is not closed`);
  return out + html.slice(at);
}

/** Keeps the waitlist's blocks when `on`, the code screen's when not (see keepNamed). */
export function keepBlocks(html: string, on: boolean): string {
  return keepNamed(html, 'waitlist', ['on', 'off'], on ? 'on' : 'off');
}

/** Keeps the headline's blocks for its look (see keepNamed). */
export function keepHeadline(html: string, look: HeadlineLook): string {
  return keepNamed(html, 'headline', ['text', 'chrome'], look);
}

/** Keeps the privacy page's contact lines when there is an address to show (see keepNamed). */
export function keepContact(html: string, contact: string | null): string {
  return keepNamed(html, 'contact', ['on'], contact === null ? 'none' : 'on');
}

/** A chrome picture's size, from src/waitlist/art/chrome.json. */
interface ChromePicture {
  readonly file: string;
  readonly width: number;
  readonly height: number;
}

/** The sizes of the chrome pictures, as tokens: chrome.wordmark.width and so on. */
export function chromeTokens(manifest: unknown): Record<string, string> {
  const pictures: Record<string, ChromePicture | undefined> = {};
  const m = manifest as Record<
    string,
    { large?: ChromePicture; small?: ChromePicture } | undefined
  >;
  pictures.wordmark = m.wordmark?.large;
  pictures.wordmarkSmall = m.wordmark?.small;
  pictures.headline = m.headline?.large;
  pictures.headlineSmall = m['headline-small']?.large;
  const out: Record<string, string> = {};
  for (const [name, picture] of Object.entries(pictures)) {
    if (
      picture === undefined ||
      !Number.isInteger(picture.width) ||
      !Number.isInteger(picture.height)
    ) {
      throw new Error(`waitlist: chrome.json has no size for ${name}`);
    }
    out[`chrome.${name}.width`] = String(picture.width);
    out[`chrome.${name}.height`] = String(picture.height);
  }
  return out;
}

/** The app's module script, as the build (or the dev server) writes it into the head. */
const APP_SCRIPT =
  /[ \t]*<script type="module" (?:crossorigin )?src="([^"]*(?:\/src\/main\.ts|\/assets\/index-[\w-]+\.js))"><\/script>\n?/u;

/**
 * Takes the app's module script out of the page, and gives its address to
 * every data-entry="" in it: the head's script, which fetches it at once on a
 * device with the code, and the waitlist's template, from which the waitlist
 * starts it there once the page is in.
 */
export function deferApp(html: string): string {
  const found = APP_SCRIPT.exec(html);
  if (found?.[1] === undefined) throw new Error('waitlist: no app module script in index.html');
  if (!html.includes('data-entry=""')) throw new Error('waitlist: no data-entry="" in index.html');
  return html.replace(APP_SCRIPT, '').replaceAll('data-entry=""', `data-entry="${found[1]}"`);
}

/** A file's name with its content's hash in it, as Vite names assets: map.1a2b3c4d5e.webp. */
export function hashedName(name: string, bytes: Uint8Array): string {
  const hash = createHash('sha256').update(bytes).digest('hex').slice(0, 10);
  const dot = name.lastIndexOf('.');
  return `assets/waitlist/${name.slice(0, dot)}.${hash}${name.slice(dot)}`;
}

/** A woff2 font's bytes as a data: address, for a @font-face inline in the page. */
export function fontDataUrl(bytes: Uint8Array): string {
  return `data:font/woff2;base64,${Buffer.from(bytes).toString('base64')}`;
}

/** Fills %waitlist.…% tokens. Throws on one it does not know. */
export function fillTokens(html: string, values: Readonly<Record<string, string>>): string {
  return html.replace(TOKEN, (token, key: string) => {
    const value = values[key];
    if (value === undefined) throw new Error(`waitlist: unknown token ${token}`);
    return value;
  });
}

/** The waitlist's script, bundled into one classic script with nothing outside it. */
export async function gateScript(root: string): Promise<string> {
  const result = await build({
    configFile: false,
    root,
    logLevel: 'silent',
    publicDir: false,
    build: {
      write: false,
      emptyOutDir: false,
      minify: true,
      sourcemap: false,
      target: 'es2022',
      lib: { entry: path.join(root, GATE_ENTRY), formats: ['iife'], name: 'snowlightWaitlist' },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as { output?: unknown[] }[];
  for (const out of outputs) {
    for (const item of out.output ?? []) {
      const chunk = item as { type?: string; code?: string };
      if (chunk.type === 'chunk' && typeof chunk.code === 'string') {
        // A script's text ends at the first "</script", wherever it is.
        return chunk.code.trim().replaceAll('</script', '<\\/script');
      }
    }
  }
  throw new Error('waitlist: bundling src/waitlist/inline.ts gave no script');
}

/** The plugin. `settings` null builds the site without the waitlist, as before. */
export function waitlist(settings: WaitlistSettings | null, root: string): Plugin {
  let config: ResolvedConfig | undefined;
  /** Each picture's address in the build, and its bytes. */
  const art = new Map<ArtName, { fileName: string; bytes: Uint8Array }>();

  const artUrl = (name: ArtName): string => {
    const base = config?.base ?? '/';
    if (config?.command !== 'build') return `${base}${ART_DIR}/${ART[name]}`;
    const file = art.get(name);
    if (file === undefined) throw new Error(`waitlist: no picture ${name}`);
    return `${base}${file.fileName}`;
  };

  let font: string | undefined;
  const fontUrl = (): string =>
    (font ??= fontDataUrl(readFileSync(path.join(root, ART_DIR, FONT))));

  let chrome: Record<string, string> | undefined;
  const chromeSizes = (): Record<string, string> =>
    (chrome ??= chromeTokens(
      JSON.parse(readFileSync(path.join(root, ART_DIR, 'chrome.json'), 'utf8')) as unknown,
    ));

  const tokens = (): Record<string, string> => {
    if (settings === null) return {};
    const social = artUrl('social');
    return {
      ...chromeSizes(),
      'art.chrome': artUrl('chrome'),
      'art.chromeSmall': artUrl('chromeSmall'),
      'art.chromeHeadline': artUrl('chromeHeadline'),
      'art.chromeHeadlineSmall': artUrl('chromeHeadlineSmall'),
      form: settings.form,
      action: `https://app.kit.com/forms/${settings.form}/subscriptions`,
      confirm: settings.confirm ? 'on' : 'off',
      'art.map': artUrl('map'),
      'art.mapSmall': artUrl('mapSmall'),
      'art.sweep0': artUrl('sweep0'),
      'art.sweep1': artUrl('sweep1'),
      'art.sweep2': artUrl('sweep2'),
      'art.sweep3': artUrl('sweep3'),
      'art.social': /^https?:/u.test(social) ? social : `${SITE_URL}${social}`,
      font: fontUrl(),
      site: `${SITE_URL}${config?.base ?? '/'}`,
      contact: settings.contact ?? '',
    };
  };

  return {
    name: 'snowlight:waitlist',
    config() {
      if (settings === null) return undefined;
      return {
        build: {
          rolldownOptions: {
            input: {
              index: path.join(root, 'index.html'),
              privacy: path.join(root, 'privacy.html'),
            },
          },
        },
      };
    },
    configResolved(resolved) {
      config = resolved;
      if (settings === null || resolved.command !== 'build') return;
      for (const name of Object.keys(ART) as ArtName[]) {
        const bytes = readFileSync(path.join(root, ART_DIR, ART[name]));
        art.set(name, { fileName: hashedName(ART[name], bytes), bytes });
      }
    },
    generateBundle() {
      for (const [name, { fileName, bytes }] of art) {
        // The chrome headline's pictures ship only with the look that shows them.
        if (settings?.headline !== 'chrome' && name.startsWith('chromeHeadline')) continue;
        this.emitFile({ type: 'asset', fileName, source: bytes });
      }
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html, context) {
        if (path.basename(context.filename) !== 'index.html') {
          return settings === null
            ? html
            : fillTokens(keepContact(html, settings.contact), tokens());
        }
        const kept = keepBlocks(html, settings !== null);
        if (settings === null) return kept;
        return fillTokens(keepHeadline(kept, settings.headline), tokens());
      },
    },
  };
}

/** The second half: after Vite has written the app's script into the page. */
export function waitlistPost(settings: WaitlistSettings | null, root: string): Plugin {
  let gate: Promise<string> | undefined;
  return {
    name: 'snowlight:waitlist-post',
    transformIndexHtml: {
      order: 'post',
      async handler(html, context) {
        if (settings === null || path.basename(context.filename) !== 'index.html') return html;
        gate ??= gateScript(root);
        const script = await gate;
        if (!html.includes(GATE_TAG)) throw new Error(`waitlist: no ${GATE_TAG} in index.html`);
        return deferApp(html).replace(GATE_TAG, () => `<script>${script}</script>`);
      },
    },
  };
}
