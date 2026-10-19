import { statSync } from 'node:fs';
import path from 'node:path';

import sharp from 'sharp';
import { describe, expect, it } from 'vitest';

import { copy } from '../src/copy';
import { waitlistCopy } from '../src/copy-waitlist';
import chromeManifest from '../src/waitlist/art/chrome.json';
import artManifest from '../src/waitlist/art/art.json';
import {
  ART,
  chromeTokens,
  deferApp,
  fillTokens,
  fontDataUrl,
  hashedName,
  keepBlocks,
  keepContact,
  keepHeadline,
  waitlistSettings,
} from '../tools/waitlist';
import indexHtml from '../index.html?raw';
import privacyHtml from '../privacy.html?raw';

const ART_DIR = path.join(import.meta.dirname, '..', 'src', 'waitlist', 'art');

describe('waitlistSettings', () => {
  it('is off when VITE_WAITLIST_KIT_FORM is unset or empty', () => {
    expect(waitlistSettings({})).toBeNull();
    expect(waitlistSettings({ VITE_WAITLIST_KIT_FORM: '' })).toBeNull();
    expect(waitlistSettings({ VITE_WAITLIST_KIT_FORM: '  ' })).toBeNull();
  });

  it('takes a Kit form id, and the confirmation email unless it is off', () => {
    expect(waitlistSettings({ VITE_WAITLIST_KIT_FORM: '8675309' })).toEqual({
      form: '8675309',
      confirm: true,
      headline: 'text',
      contact: null,
    });
    expect(
      waitlistSettings({ VITE_WAITLIST_KIT_FORM: ' 42 ', VITE_WAITLIST_CONFIRM: 'off' }),
    ).toEqual({ form: '42', confirm: false, headline: 'text', contact: null });
    expect(waitlistSettings({ VITE_WAITLIST_KIT_FORM: '42', VITE_WAITLIST_CONFIRM: 'ON' })).toEqual(
      { form: '42', confirm: true, headline: 'text', contact: null },
    );
  });

  it('takes an email address for removal requests, and fails the build on anything else', () => {
    const on = { VITE_WAITLIST_KIT_FORM: '42' };
    expect(waitlistSettings({ ...on, VITE_WAITLIST_CONTACT: ' hi@example.com ' })?.contact).toBe(
      'hi@example.com',
    );
    expect(waitlistSettings({ ...on, VITE_WAITLIST_CONTACT: '' })?.contact).toBeNull();
    for (const bad of ['hi', 'hi@example', 'a b@c.co', 'x@y.co"><script>', 'mailto:hi@x.co']) {
      expect(() => waitlistSettings({ ...on, VITE_WAITLIST_CONTACT: bad }), bad).toThrow(
        /email address/,
      );
    }
  });

  it('sets the headline as text unless VITE_WAITLIST_HEADLINE asks for chrome', () => {
    const on = { VITE_WAITLIST_KIT_FORM: '42' };
    expect(waitlistSettings({ ...on, VITE_WAITLIST_HEADLINE: '' })?.headline).toBe('text');
    expect(waitlistSettings({ ...on, VITE_WAITLIST_HEADLINE: 'text' })?.headline).toBe('text');
    expect(waitlistSettings({ ...on, VITE_WAITLIST_HEADLINE: ' Chrome ' })?.headline).toBe(
      'chrome',
    );
    expect(() => waitlistSettings({ ...on, VITE_WAITLIST_HEADLINE: 'gold' })).toThrow(
      /text or chrome/,
    );
  });

  it('fails the build on a form id or a confirm setting it cannot use', () => {
    expect(() => waitlistSettings({ VITE_WAITLIST_KIT_FORM: 'abc' })).toThrow(/digits only/);
    expect(() => waitlistSettings({ VITE_WAITLIST_KIT_FORM: '12/../x' })).toThrow(/digits/);
    expect(() =>
      waitlistSettings({ VITE_WAITLIST_KIT_FORM: '1', VITE_WAITLIST_CONFIRM: 'maybe' }),
    ).toThrow(/on or off/);
  });
});

describe('keepBlocks', () => {
  it('keeps the code screen and drops the waitlist and every marker when off', () => {
    const off = keepBlocks(indexHtml, false);
    expect(off).not.toContain('waitlist:');
    expect(off).not.toContain('id="waitlist"');
    expect(off).not.toContain('data-waitlist-gate');
    expect(off).not.toContain('og:image');
    expect(off.match(/lock-form/g)).toHaveLength(3);
    expect(off).toContain('<script type="module" src="/src/main.ts"></script>');
  });

  it('is index.html as it was, line for line, when off', () => {
    // Off removes whole lines only: the markers' and the waitlist's.
    const kept = keepBlocks(indexHtml, false).split('\n');
    const source = indexHtml.split('\n');
    let at = 0;
    for (const line of kept) {
      while (at < source.length && source[at] !== line) at += 1;
      expect(at).toBeLessThan(source.length);
      at += 1;
    }
    expect(kept.some((line) => line.includes('wl-'))).toBe(false);
  });

  it('keeps the waitlist and drops the code screen when on', () => {
    const on = keepBlocks(indexHtml, true);
    expect(on).not.toContain('waitlist:');
    expect(on).toContain('id="waitlist"');
    expect(on).toContain('<script data-waitlist-gate></script>');
    expect(on).not.toContain('lock-form');
    expect(on).not.toContain('content="%copy.meta.description%"');
    expect(on).toContain('content="%copy.waitlist.meta.description%"');
  });

  it('titles the waitlist with its share title, and the site as before without it', () => {
    expect(keepBlocks(indexHtml, true).match(/<title>[^<]*<\/title>/g)).toEqual([
      '<title>%copy.waitlist.meta.shareTitle%</title>',
    ]);
    expect(keepBlocks(indexHtml, false).match(/<title>[^<]*<\/title>/g)).toEqual([
      '<title>%copy.appName%</title>',
    ]);
  });

  it('refuses markers out of place', () => {
    const start = '<!-- waitlist:on:start -->\n';
    const end = '<!-- waitlist:on:end -->\n';
    expect(() => keepBlocks(`a\n${start}b\n`, true)).toThrow(/not closed/);
    expect(() => keepBlocks(`a\n${end}`, true)).toThrow(/out of place/);
    expect(() => keepBlocks(`${start}${start}${end}`, true)).toThrow(/out of place/);
    expect(() => keepBlocks(`${start}<!-- waitlist:off:end -->\n`, true)).toThrow(/out of place/);
    expect(keepBlocks(`a\n  ${start}b\n  ${end}c\n`, false)).toBe('a\nc\n');
  });
});

describe('keepHeadline', () => {
  const on = keepBlocks(indexHtml, true);

  it('keeps one headline: in white type by default, in chrome when asked', () => {
    const text = keepHeadline(on, 'text');
    const chrome = keepHeadline(on, 'chrome');
    for (const page of [text, chrome]) {
      expect(page).not.toContain('headline:');
      // One headline for a browser running scripts; the plain cut for one without them
      // (in <noscript>) sets it as text in both looks.
      const scripted = page.replace(/<noscript>[\s\S]*?<\/noscript>/u, '');
      expect(scripted.match(/<h1 class="wl-title/g)).toHaveLength(1);
      expect(page.match(/<noscript>/g)).toHaveLength(1);
    }
    expect(text).toContain('<h1 class="wl-title">%copy.waitlist.headline%</h1>');
    expect(text).not.toContain('%waitlist.art.chromeHeadline');
    expect(chrome).toContain('wl-title-chrome');
    expect(chrome).toContain('%waitlist.art.chromeHeadlineSmall%');
    // Both looks carry the chrome wordmark.
    expect(text).toContain('%waitlist.art.chromeSmall%');
    expect(chrome).toContain('%waitlist.art.chromeSmall%');
  });

  it('leaves a build without the waitlist untouched', () => {
    const off = keepBlocks(indexHtml, false);
    expect(off).not.toContain('headline:');
    expect(keepHeadline(off, 'text')).toBe(off);
  });

  it('refuses markers out of place', () => {
    expect(() => keepHeadline('<!-- headline:text:start -->\n', 'text')).toThrow(/not closed/);
    expect(() =>
      keepHeadline('<!-- headline:text:start -->\n<!-- headline:chrome:end -->\n', 'text'),
    ).toThrow(/out of place/);
  });
});

describe('the chrome pictures', () => {
  it('say what the copy says, so a change of words means drawing them again', () => {
    // scripts/build-waitlist-chrome.mjs draws these words; run it again after changing them.
    expect(chromeManifest.wordmark.text).toBe(copy.appName.toLocaleUpperCase('en-US'));
    expect(chromeManifest.headline.text).toBe(waitlistCopy.headline);
    expect(chromeManifest['headline-small'].text).toBe(waitlistCopy.headline);
    expect(chromeManifest.headline.lines.join(' ')).toBe(waitlistCopy.headline);
    expect(chromeManifest['headline-small'].lines.join(' ')).toBe(waitlistCopy.headline);
  });

  it('make a share card that apps show: a 1200 x 630 JPEG under 300 KB', async () => {
    const file = path.join(ART_DIR, 'social.jpg');
    expect(statSync(file).size).toBeLessThan(300_000);
    const meta = await sharp(file).metadata();
    expect([meta.format, meta.width, meta.height]).toEqual(['jpeg', 1200, 630]);
  });

  it('and the share card say what the copy says', () => {
    // scripts/build-waitlist-art.mjs draws these words into social.jpg; run it again after changing them.
    expect(artManifest.social).toEqual({
      wordmark: copy.appName,
      headline: waitlistCopy.headline,
      when: waitlistCopy.when,
    });
  });

  it("give the build each picture's size, for the box it holds", () => {
    const tokens = chromeTokens(chromeManifest);
    expect(tokens['chrome.wordmark.width']).toBe(String(chromeManifest.wordmark.large.width));
    expect(tokens['chrome.wordmarkSmall.height']).toBe(
      String(chromeManifest.wordmark.small.height),
    );
    expect(tokens['chrome.headlineSmall.width']).toBe(
      String(chromeManifest['headline-small'].large.width),
    );
    expect(Object.keys(tokens)).toHaveLength(8);
    expect(() => chromeTokens({ wordmark: {} })).toThrow(/no size for wordmark/);
  });

  it('are the files the plugin ships', () => {
    expect(ART.chrome).toBe(chromeManifest.wordmark.large.file);
    expect(ART.chromeSmall).toBe(chromeManifest.wordmark.small.file);
    expect(ART.chromeHeadline).toBe(chromeManifest.headline.large.file);
    expect(ART.chromeHeadlineSmall).toBe(chromeManifest['headline-small'].large.file);
  });
});

describe('deferApp', () => {
  const page = (script: string) =>
    `<head>\n    ${script}\n</head><template id="wl-page" data-entry=""></template>`;

  it('takes the built app script out and hands its address to the waitlist', () => {
    const out = deferApp(
      page('<script type="module" crossorigin src="/assets/index-Mi2t3z6g.js"></script>'),
    );
    expect(out).not.toContain('<script');
    expect(out).toContain('data-entry="/assets/index-Mi2t3z6g.js"');
  });

  it('gives the address to the head, which fetches it at once on a device with the code', () => {
    const on = keepBlocks(indexHtml, true);
    expect(on.match(/data-entry=""/g)).toHaveLength(2);
    const out = deferApp(on);
    expect(out.match(/data-entry="\/src\/main\.ts"/g)).toHaveLength(2);
    const head = out.slice(0, out.indexOf('</head>'));
    expect(head).toContain('<script data-entry="/src/main.ts">');
    expect(head).toContain("link.rel = 'modulepreload'");
    expect(out).toContain('<template id="wl-page" data-entry="/src/main.ts" data-app-title=');
  });

  it('works under a base path and on the dev server, and leaves other scripts', () => {
    expect(
      deferApp(page('<script type="module" crossorigin src="/repo/assets/index-a_B.js"></script>')),
    ).toContain('data-entry="/repo/assets/index-a_B.js"');
    const dev = deferApp(
      page(
        '<script type="module" src="/@vite/client"></script>\n<script type="module" src="/src/main.ts"></script>',
      ),
    );
    expect(dev).toContain('/@vite/client');
    expect(dev).toContain('data-entry="/src/main.ts"');
  });

  it('fails without the app script or the place to put it', () => {
    expect(() => deferApp('<template data-entry=""></template>')).toThrow(/no app module/);
    expect(() =>
      deferApp('<script type="module" crossorigin src="/assets/index-x.js"></script>'),
    ).toThrow(/data-entry/);
  });
});

describe('the privacy page', () => {
  it('shows a way to write in only when the build has an address for it', () => {
    const none = keepContact(privacyHtml, null);
    expect(none).not.toContain('contact:');
    expect(none).not.toContain('%waitlist.contact%');
    expect(none).not.toContain('remove.contact%');
    const shown = keepContact(privacyHtml, 'hi@example.com');
    expect(shown).not.toContain('contact:');
    expect(shown).toContain('href="mailto:%waitlist.contact%"');
    expect(shown).toContain('%copy.waitlist.privacy.sections.remove.contactLink%');
  });

  it('says what the list sends, with or without a confirmation email', () => {
    expect(privacyHtml).toContain('<body data-confirm="%waitlist.confirm%">');
    expect(privacyHtml).toContain(
      '<p data-confirm="off">%copy.waitlist.privacy.sections.why.body%</p>',
    );
    expect(privacyHtml).toContain(
      '<p data-confirm="on">%copy.waitlist.privacy.sections.why.bodyConfirm%</p>',
    );
  });
});

describe('fillTokens and hashedName', () => {
  it('fills known tokens and refuses unknown ones', () => {
    expect(
      fillTokens('a %waitlist.form% b %waitlist.art.map%', { form: '1', 'art.map': 'm' }),
    ).toBe('a 1 b m');
    expect(() => fillTokens('%waitlist.nope%', {})).toThrow(/unknown token/);
  });

  it('names a picture by its content', () => {
    const a = hashedName('map.webp', new Uint8Array([1, 2, 3]));
    expect(a).toMatch(/^assets\/waitlist\/map\.[0-9a-f]{10}\.webp$/);
    expect(hashedName('map.webp', new Uint8Array([1, 2, 3]))).toBe(a);
    expect(hashedName('map.webp', new Uint8Array([1, 2, 4]))).not.toBe(a);
  });

  it('puts a font into the page as a woff2 data: address', () => {
    expect(fontDataUrl(new Uint8Array([119, 79, 70, 50]))).toBe('data:font/woff2;base64,d09GMg==');
  });

  it('preloads the site font only without the waitlist, whose words have their own inline cut', () => {
    const preload = 'rel="preload"';
    expect(keepBlocks(indexHtml, false)).toContain(preload);
    expect(keepBlocks(indexHtml, true)).not.toContain(preload);
    expect(keepBlocks(indexHtml, true)).toContain(
      "font-family: 'Geist Waitlist', var(--font-sans);",
    );
  });

  it('leaves no token in index.html that the plugin does not fill', () => {
    const tokens = new Set(
      [...keepBlocks(indexHtml, true).matchAll(/%waitlist\.([A-Za-z0-9.]+)%/g)].map((m) => m[1]),
    );
    expect([...tokens].sort()).toEqual(
      [
        'action',
        'art.chrome',
        'art.chromeHeadline',
        'art.chromeHeadlineSmall',
        'art.chromeSmall',
        'chrome.headline.height',
        'chrome.headline.width',
        'chrome.headlineSmall.height',
        'chrome.headlineSmall.width',
        'chrome.wordmark.height',
        'chrome.wordmark.width',
        'chrome.wordmarkSmall.height',
        'chrome.wordmarkSmall.width',
        'art.map',
        'art.mapSmall',
        'art.social',
        'art.sweep0',
        'art.sweep1',
        'art.sweep2',
        'art.sweep3',
        'confirm',
        'font',
        'form',
        'site',
      ].sort(),
    );
  });
});
