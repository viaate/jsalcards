import { readFileSync } from 'node:fs';
import path from 'node:path';

import type { Plugin } from 'vite';

import { escapeHtml } from './html-copy.ts';

/**
 * The getsnowlight landing (get/index.html), built on its own (vite.get.config.ts) to
 * dist-get/ and served at https://www.getsnowlight.com by its own workflow
 * (.github/workflows/getsnowlight.yml). docs/getsnowlight.md.
 */

/** The list of the landing's phone pictures, from the landing's folder. */
export const PHONES_FILE = 'phones.json';

export interface GetPageSettings {
  /** The App Store page of the iPhone app, or null while it is not out. */
  readonly appStoreUrl: string | null;
}

/** The settings from the build's VITE_ variables (loadEnv). */
export function getPageSettings(
  env: Readonly<Record<string, string | undefined>>,
): GetPageSettings {
  const url = env.VITE_APP_STORE_URL?.trim() ?? '';
  if (url !== '' && !/^https:\/\/apps\.apple\.com\/[^\s"'<>]+$/u.test(url)) {
    throw new Error(`get-page: VITE_APP_STORE_URL is not an App Store link: ${url}`);
  }
  return { appStoreUrl: url === '' ? null : url };
}

/**
 * One slot of the list: the picture's files under get/img/ (and how they were made): `file` at
 * twice the width the page shows it at, and `file3x` as near three times as its source allows,
 * for the iPhones whose screens have three pixels to a point.
 */
export interface Phone {
  readonly from: string;
  readonly file: string;
  readonly width: number;
  readonly file3x: string;
  readonly width3x: number;
}

/** The list of phone pictures, by slot; `root` is the landing's folder. */
export function readPhones(root: string): Readonly<Record<string, Phone>> {
  return JSON.parse(readFileSync(path.join(root, PHONES_FILE), 'utf8')) as Record<string, Phone>;
}

const PHONE_TOKEN = /%phone\.([A-Za-z0-9]+)(\.srcset)?%/gu;
const PICTURE = /^[\w-]+\.(?:webp|png|jpg|avif)$/u;

/**
 * Each %phone.slot% filled with that slot's picture, relative to the page, and each
 * %phone.slot.srcset% with its pictures for two and three pixels to a point.
 */
export function fillPhones(html: string, phones: Readonly<Record<string, Phone>>): string {
  return html.replace(PHONE_TOKEN, (token, slot: string, srcset: string | undefined) => {
    const phone = Object.hasOwn(phones, slot) ? phones[slot] : undefined;
    if (phone === undefined) throw new Error(`get-page: no phone picture for ${token}`);
    for (const file of [phone.file, phone.file3x]) {
      if (!PICTURE.test(file)) throw new Error(`get-page: ${slot} names no picture file: ${file}`);
    }
    return srcset === undefined
      ? `./img/${phone.file}`
      : `./img/${phone.file} 2x, ./img/${phone.file3x} 3x`;
  });
}

const BLOCK = (name: string) =>
  new RegExp(
    `[ \\t]*<!-- appstore:${name}:start -->[\\s\\S]*?<!-- appstore:${name}:end -->\\n?`,
    'gu',
  );
const MARKERS = /[ \t]*<!-- appstore:(?:on|off):(?:start|end) -->\n?/gu;

/**
 * The App Store blocks: with a link, the badge (appstore:on, linking there) and not the live
 * map's stand-ins (appstore:off); without one, the other way round.
 */
export function keepAppStore(html: string, url: string | null): string {
  const kept = html.replace(BLOCK(url === null ? 'on' : 'off'), '').replace(MARKERS, '');
  if (url === null) return kept;
  return kept.replaceAll('%appstore.url%', escapeHtml(url));
}

const MARK_LAST = /(<h1 data-mark-last="(\d)">)([^<]*)(<\/h1>)/u;

/**
 * The heading's last few words on a highlight, its closing stop outside it: "Know about snow
 * days <span class="mark">the night before</span>." The words are copy's (src/copy-get.ts),
 * whole; the page only says how many to mark.
 */
export function markLast(html: string): string {
  return html.replace(
    MARK_LAST,
    (_all, open: string, count: string, text: string, close: string) => {
      const stop = /[.?]$/u.exec(text)?.[0] ?? '';
      const words = text.slice(0, text.length - stop.length).split(' ');
      const n = Number(count);
      if (n < 1 || words.length <= n) throw new Error(`get-page: cannot mark "${text}"`);
      const head = words.slice(0, -n).join(' ');
      const tail = words.slice(-n).join(' ');
      return `${open}${head} <span class="mark">${tail}</span>${stop}${close}`;
    },
  );
}

/**
 * The Vite plugin: fills the landing's pictures and App Store blocks and marks its heading.
 * After html-copy in the plugin list, so the heading's words are in. `root` is the landing's
 * folder.
 */
export function getPage(settings: GetPageSettings, root: string): Plugin {
  const page = path.join(root, 'index.html');
  return {
    name: 'snowlight:get-page',
    transformIndexHtml: {
      order: 'pre',
      handler(html, context) {
        if (path.resolve(context.filename) !== page) return html;
        return markLast(fillPhones(keepAppStore(html, settings.appStoreUrl), readPhones(root)));
      },
    },
  };
}
