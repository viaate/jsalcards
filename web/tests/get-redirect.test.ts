import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import indexHtml from '../index.html?raw';
import {
  GET_REDIRECT,
  GET_URL,
  getRedirectSwitch,
  MARKER,
  putRedirect,
  redirectCode,
  type Switch,
} from '../tools/get-redirect.ts';

/**
 * The phone redirect the build writes into index.html (tools/get-redirect.ts,
 * docs/getsnowlight.md), run as the page runs it, minified as it ships, with a made-up address,
 * storage, browser and history.
 */
const TO = 'https://www.getsnowlight.com/';
const LOCKED_KEY = 'sl-lock';
/** The value the lock stores once passed, as index.html's lock stores it. */
const PASSED = /localStorage\.setItem\('sl-lock', '([^']+)'\)/u.exec(indexHtml)?.[1] ?? '';
const SHIPPED = { '/': redirectCode('/'), '/preview/': redirectCode('/preview/') };

const IPHONE_SAFARI =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1';
const NOT_SENT: Readonly<Record<string, string>> = {
  'Chrome on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1',
  'Firefox on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/132.0 Mobile/15E148 Safari/605.1.15',
  "an app's own browser on iPhone":
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/490.0]',
  'Google crawling as an iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
  'DuckDuckGo on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1 Ddg/18.1',
  'Opera on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1 OPT/5.1.0',
  'Edge on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 EdgiOS/131.2903.68 Mobile/15E148 Safari/605.1.15',
  'the Google app on iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) GSA/343.0.695551749 Mobile/15E148 Safari/604.1',
  "Pinterest's own browser on iPhone":
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [Pinterest/iOS]',
  "LinkedIn's own browser on iPhone":
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1 [LinkedInApp]/9.30.1',
  "Instagram's own browser on iPhone":
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 357.0.0.25.101 (iPhone15,2; iOS 18_1; en_US; en; scale=3.00; 1179x2556; 662436512)',
  'an iPod touch':
    'Mozilla/5.0 (iPod touch; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.6 Mobile/15E148 Safari/604.1',
  Applebot:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1 (Applebot/0.1; +http://www.apple.com/go/applebot)',
  'bingbot as an iPhone':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Version/7.0 Mobile/11A465 Safari/9537.53 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)',
  Lighthouse:
    'Mozilla/5.0 (Linux; Android 11; moto g power (2022)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36 Chrome-Lighthouse',
  'an Android phone':
    'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36',
  'an iPad':
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
  'a desktop':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
};

interface Visit {
  readonly url?: string;
  /** The build's base path. */
  readonly base?: '/' | '/preview/';
  readonly agent?: string;
  readonly switchOn?: boolean;
  readonly storage?: Map<string, string>;
  readonly standalone?: boolean;
  readonly displayStandalone?: boolean;
  /** Storage that throws on every read, or on every write. */
  readonly broken?: 'read' | 'write';
}

interface Result {
  readonly sentTo: string | null;
  readonly address: string;
  readonly storage: Map<string, string>;
}

function unlocked(): Map<string, string> {
  return new Map([[LOCKED_KEY, PASSED]]);
}

function visit(given: Visit = {}): Result {
  const url = new URL(given.url ?? 'https://snowlightmap.com/');
  const storage = given.storage ?? unlocked();
  let sentTo: string | null = null;
  let stopped = false;
  let address = url.href;
  const fail = (what: 'read' | 'write') => {
    if (given.broken === what) throw new Error(`storage ${what} refused`);
  };
  const localStorage = {
    getItem: (key: string) => {
      fail('read');
      return storage.get(key) ?? null;
    },
    setItem: (key: string, value: string) => {
      fail('write');
      storage.set(key, value);
    },
    removeItem: (key: string) => {
      fail('write');
      storage.delete(key);
    },
  };
  const location = {
    hostname: url.hostname,
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
    replace: (to: string) => {
      if (!stopped) throw new Error('sent before the page was stopped');
      sentTo = to;
    },
  };
  const history = {
    state: null,
    replaceState: (_state: unknown, _title: string, to: string) => {
      address = new URL(to, url).href;
    },
  };
  const navigator = {
    userAgent: given.agent ?? IPHONE_SAFARI,
    standalone: given.standalone ?? false,
  };
  const matchMedia = () => ({ matches: given.displayStandalone ?? false });
  const on: Switch = given.switchOn === false ? 'off' : 'on';
  const document = {
    currentScript: {
      getAttribute: (name: string) => (name === 'data-get-redirect' ? on : null),
    },
  };
  const window = {
    stop: () => {
      stopped = true;
    },
  };
  // eslint-disable-next-line @typescript-eslint/no-implied-eval -- the page's own inline script
  const run = new Function(
    'document',
    'location',
    'localStorage',
    'history',
    'navigator',
    'matchMedia',
    'window',
    SHIPPED[given.base ?? '/'],
  ) as (...args: unknown[]) => void;
  run(document, location, localStorage, history, navigator, matchMedia, window);
  return { sentTo, address, storage };
}

describe('the phone redirect (index.html)', () => {
  it('is written by the build, minified, as the first script of the head, switch and all', () => {
    expect(indexHtml.split(MARKER)).toHaveLength(2);
    expect(indexHtml).not.toContain('data-get-redirect');
    const head = indexHtml.slice(0, indexHtml.indexOf('</head>'));
    expect(head.indexOf(MARKER)).toBeLessThan(head.indexOf('<script'));
    for (const on of ['on', 'off'] as const) {
      const built = putRedirect(indexHtml, on, '/');
      expect(built).toContain(`<script data-get-redirect="${on}">${redirectCode('/')}</script>`);
      expect(built).not.toContain(MARKER);
    }
    expect(() => putRedirect('<head></head>', 'off', '/')).toThrow(/needs one/u);
    expect(() => putRedirect(MARKER + MARKER, 'off', '/')).toThrow(/needs one/u);
    // None of its explaining words, and small.
    expect(redirectCode('/')).not.toContain('/*');
    expect(redirectCode('/').length).toBeLessThan(1_100);
    expect(GET_URL).toBe(TO);
  });

  it('has one switch: GET_REDIRECT, which a build can override with VITE_GET_REDIRECT', () => {
    expect(['on', 'off']).toContain(GET_REDIRECT);
    expect(getRedirectSwitch({})).toBe(GET_REDIRECT);
    expect(getRedirectSwitch({ VITE_GET_REDIRECT: '' })).toBe(GET_REDIRECT);
    expect(getRedirectSwitch({ VITE_GET_REDIRECT: 'on' })).toBe('on');
    expect(getRedirectSwitch({ VITE_GET_REDIRECT: ' off ' })).toBe('off');
    expect(() => getRedirectSwitch({ VITE_GET_REDIRECT: 'yes' })).toThrow(/not on or off/u);
    expect(visit({ switchOn: false }).sentTo).toBeNull();
  });

  it('is off in every e2e build of the map, whatever GET_REDIRECT says', () => {
    const web = path.join(import.meta.dirname, '..');
    const config = readFileSync(path.join(web, 'playwright.config.ts'), 'utf8');
    const commands = [...config.matchAll(/command: `([^`]*)`/gu)].map((m) => m[1] ?? '');
    // The workers inherit it too, so a spec's own vite build() is off as well.
    expect(config).toMatch(/^process\.env\.VITE_GET_REDIRECT = 'off';$/mu);
    expect(config.indexOf("process.env.VITE_GET_REDIRECT = 'off'")).toBeLessThan(
      config.indexOf('export default defineConfig'),
    );
    const maps = commands.filter((command) => !command.includes('vite.get.config.ts'));
    expect(maps.length).toBeGreaterThanOrEqual(4);
    for (const command of maps) {
      expect(command).toMatch(
        /^(?:\S+=\S+ )*VITE_GET_REDIRECT=off (?:\S+=\S+ )*(?:npm run build|npx vite build)/u,
      );
    }
  });

  it('sends an iPhone in Safari from the front page to www.getsnowlight.com', () => {
    expect(visit().sentTo).toBe(TO);
    expect(visit({ url: 'https://snowlightmap.com/index.html' }).sentTo).toBe(TO);
    expect(visit({ url: 'http://localhost:4173/', storage: new Map() }).sentTo).toBe(TO);
    // Under a base path, from that front page only.
    expect(visit({ url: 'https://example.com/preview/', base: '/preview/' }).sentTo).toBe(TO);
    expect(visit({ url: 'https://example.com/', base: '/preview/' }).sentTo).toBeNull();
  });

  it('sends it on every visit until it chooses the map, and marks nothing on the way', () => {
    const storage = unlocked();
    expect(visit({ storage }).sentTo).toBe(TO);
    expect(visit({ storage }).sentTo).toBe(TO);
    expect([...storage.keys()]).toEqual([LOCKED_KEY]);
  });

  it('remembers ?map=1 from the landing, takes it out of the address, and never sends again', () => {
    const storage = unlocked();
    const back = visit({ url: 'https://snowlightmap.com/?map=1', storage });
    expect(back.sentTo).toBeNull();
    expect(back.address).toBe('https://snowlightmap.com/');
    expect(storage.get('sl-map')).toBe('1');
    expect(visit({ storage }).sentTo).toBeNull();
    // Another query and a hash stay as they were.
    const kept = visit({
      url: 'https://snowlightmap.com/?map=1&school=123#x',
      storage: unlocked(),
    });
    expect(kept.address).toBe('https://snowlightmap.com/?school=123#x');
    expect(kept.sentTo).toBeNull();
    // With the switch off too, so the address is clean whatever the switch says.
    const off = visit({
      url: 'https://snowlightmap.com/?map=1',
      switchOn: false,
      storage: new Map(),
    });
    expect(off.address).toBe('https://snowlightmap.com/');
    expect(off.storage.get('sl-map')).toBe('1');
  });

  it('never sends a deep link: a school, a shared card, anything with a query or a hash', () => {
    for (const url of [
      'https://snowlightmap.com/?school=0100005',
      'https://snowlightmap.com/?s=abc&d=2026-01-12',
      'https://snowlightmap.com/?map=0',
      'https://snowlightmap.com/#school=0100005',
      'https://snowlightmap.com/privacy.html',
      'https://snowlightmap.com/foo/',
      'https://snowlightmap.com/get/',
      'https://snowlightmap.com/foo/index.html',
      'https://snowlightmap.com//',
    ]) {
      expect(visit({ url }).sentTo, url).toBeNull();
    }
  });

  it('never sends from the home screen', () => {
    expect(visit({ standalone: true }).sentTo).toBeNull();
    expect(visit({ displayStandalone: true }).sentTo).toBeNull();
  });

  it('never sends a crawler, another browser or another device', () => {
    for (const [who, agent] of Object.entries(NOT_SENT)) {
      expect(visit({ agent }).sentTo, who).toBeNull();
    }
  });

  it('never sends before the lock is passed', () => {
    expect(visit({ storage: new Map() }).sentTo).toBeNull();
    expect(visit({ storage: new Map([[LOCKED_KEY, 'wrong']]) }).sentTo).toBeNull();
  });

  it('never sends where the choice could not be remembered', () => {
    expect(visit({ broken: 'read' }).sentTo).toBeNull();
    expect(visit({ broken: 'write' }).sentTo).toBeNull();
  });
});
