import { afterEach, describe, expect, it, vi } from 'vitest';

import { copy } from '../src/copy';
import { waitlistCopy } from '../src/copy-waitlist';
import {
  CODE_KEY,
  CODE_VALUE,
  hasCode,
  isCode,
  isEmail,
  kitEndpoint,
  mountWaitlist,
  pageEnv,
  readKitAnswer,
  retireWorkers,
  safeKitUrl,
  serverWarning,
  startWaitlist,
  SWEEP_DELAY_MS,
  subscribe,
} from '../src/waitlist/gate';
import type { WaitlistEnv } from '../src/waitlist/gate';
import { pageCopy, renderHtmlCopy } from '../tools/html-copy';
import { chromeTokens, fillTokens, keepBlocks, keepHeadline } from '../tools/waitlist';
import type { HeadlineLook } from '../tools/waitlist';
import chromeManifest from '../src/waitlist/art/chrome.json';
import indexHtml from '../index.html?raw';

const FORM = '8675309';
const ENTRY = '/assets/index-test.js';
/** The access code, from its stored form, so the code itself is written nowhere in the tests. */
const CODE = atob(CODE_VALUE);

/** index.html as a waitlist build fills it in (the app script is left in; the page never runs it here). */
function waitlistPage(confirm: 'on' | 'off' = 'on', look: HeadlineLook = 'text'): string {
  const filled = fillTokens(keepHeadline(keepBlocks(indexHtml, true), look), {
    ...chromeTokens(chromeManifest),
    'art.chrome': '/chrome.webp',
    'art.chromeSmall': '/chrome-small.webp',
    'art.chromeHeadline': '/chrome-headline.webp',
    'art.chromeHeadlineSmall': '/chrome-headline-small.webp',
    form: FORM,
    action: kitEndpoint(FORM),
    confirm,
    'art.map': '/map.webp',
    'art.mapSmall': '/map-small.webp',
    'art.sweep0': '/s0.webp',
    'art.sweep1': '/s1.webp',
    'art.sweep2': '/s2.webp',
    'art.sweep3': '/s3.webp',
    'art.social': 'https://snowlightmap.com/social.jpg',
    font: 'data:font/woff2;base64,AAAA',
    site: 'https://snowlightmap.com/',
  }).replaceAll('data-entry=""', `data-entry="${ENTRY}"`);
  return renderHtmlCopy(filled, pageCopy(copy, waitlistCopy));
}

/**
 * A page parsed as a browser running scripts reads it: a <noscript> is text there, so its
 * plain cut of the waitlist is no part of the page. (DOMParser parses without scripting,
 * as a browser with JavaScript off does, so it is taken out here.)
 */
function scriptedPage(html: string): Document {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  for (const element of doc.querySelectorAll('noscript')) element.remove();
  return doc;
}

/** A Storage in memory. */
function memoryStorage(initial: Record<string, string> = {}): Storage {
  const items = new Map(Object.entries(initial));
  return {
    get length() {
      return items.size;
    },
    clear: () => {
      items.clear();
    },
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => {
      items.delete(key);
    },
    setItem: (key, value) => {
      items.set(key, value);
    },
  };
}

function kitResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

interface Setup {
  doc: Document;
  reveal: ReturnType<typeof vi.fn<(element: HTMLElement) => void>>;
  warn: ReturnType<typeof vi.fn<(message: string) => void>>;
  retire: ReturnType<typeof vi.fn<() => void>>;
  storage: Storage;
  fetch: ReturnType<typeof vi.fn<typeof fetch>>;
  result: ReturnType<typeof startWaitlist>;
  waitlist: () => HTMLElement | null;
  q: <T extends Element>(selector: string, kind: abstract new () => T) => T;
}

function setup(
  options: {
    storage?: Storage;
    answer?: () => Promise<Response>;
    confirm?: 'on' | 'off';
    isApp?: boolean;
    online?: boolean | (() => boolean);
  } = {},
): Setup {
  // The test window's own document, so focus moves as in a page.
  const doc = document;
  const parsed = scriptedPage(waitlistPage(options.confirm));
  doc.documentElement.className = '';
  doc.documentElement.innerHTML = parsed.documentElement.innerHTML;
  if (options.isApp === true) doc.documentElement.classList.add('is-app');
  const storage = options.storage ?? memoryStorage();
  const answer = options.answer ?? (() => Promise.resolve(kitResponse({ status: 'success' })));
  const fetchMock = vi.fn<typeof fetch>(() => answer());
  const warn = vi.fn<(message: string) => void>();
  const retire = vi.fn<() => void>();
  const reveal = vi.fn<(element: HTMLElement) => void>();
  const env: WaitlistEnv = {
    document: doc,
    storage,
    fetch: fetchMock,
    reducedMotion: false,
    online: () =>
      typeof options.online === 'function' ? options.online() : (options.online ?? true),
    warn,
    retireWorkers: retire,
    afterLoad: (start) => {
      start();
    },
    reveal,
  };
  const result = startWaitlist(env);
  return {
    doc,
    reveal,
    warn,
    retire,
    storage,
    fetch: fetchMock,
    result,
    waitlist: () => doc.getElementById('waitlist'),
    q: <T extends Element>(selector: string, kind: abstract new () => T): T => {
      const found = doc.querySelector(selector);
      if (!(found instanceof kind)) throw new Error(`no ${selector}`);
      return found;
    },
  };
}

function submit(page: Setup, email: string): void {
  page.q('#wl-email', HTMLInputElement).value = email;
  page.q('#wl-form', HTMLFormElement).requestSubmit();
}

/** The error lines shown. */
function shownErrors(page: Setup): string[] {
  if (page.q('#wl-error', HTMLElement).hidden) return [];
  return [...page.doc.querySelectorAll<HTMLElement>('[data-error]')]
    .filter((line) => !line.hidden)
    .map((line) => line.getAttribute('data-error') ?? '');
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.useRealTimers();
});

describe('checks', () => {
  it('reads an email address as whole or not', () => {
    for (const good of ['a@b.co', 'name.last+tag@school.k12.ny.us', 'x@sub.example.com']) {
      expect(isEmail(good), good).toBe(true);
    }
    for (const bad of ['', 'name', 'name@', '@b.co', 'a@b', 'a b@c.co', 'a@b.', 'a@@b.co']) {
      expect(isEmail(bad), bad).toBe(false);
    }
    expect(isEmail(`${'a'.repeat(250)}@b.co`)).toBe(false);
  });

  it('knows the access code and where a device keeps it', () => {
    expect(isCode(CODE)).toBe(true);
    expect(CODE).toMatch(/^\d+$/);
    expect(isCode('2380')).toBe(false);
    expect(isCode('☃')).toBe(false);
    expect(hasCode(memoryStorage({ [CODE_KEY]: CODE_VALUE }))).toBe(true);
    expect(hasCode(memoryStorage({ [CODE_KEY]: 'x' }))).toBe(false);
    expect(hasCode(null)).toBe(false);
    expect(
      hasCode({
        getItem: () => {
          throw new Error('blocked');
        },
      }),
    ).toBe(false);
  });

  it('reads each of Kit’s answers', () => {
    const server = { kind: 'server' };
    expect(readKitAnswer(true, 200, { status: 'success', consent: null })).toEqual({
      kind: 'done',
    });
    expect(
      readKitAnswer(true, 200, {
        status: 'quarantined',
        url: 'https://app.kit.com/forms/1/check',
      }),
    ).toEqual({ kind: 'check', url: 'https://app.kit.com/forms/1/check' });
    expect(
      readKitAnswer(true, 200, { status: 'quarantined', url: 'https://evil.example/kit.com' }),
    ).toMatchObject(server);
    expect(readKitAnswer(true, 200, { status: 'quarantined' })).toMatchObject(server);
    expect(
      readKitAnswer(true, 200, {
        status: 'failed',
        errors: { fields: ['email_address'], messages: ['Email address is invalid'] },
      }),
    ).toEqual({ kind: 'rejected' });
    // What Kit answers for a form id it does not know.
    expect(
      readKitAnswer(true, 200, {
        consent: null,
        status: 'failed',
        errors: { fields: ['form'], messages: ['Form Couldn’t find a form for this request'] },
      }),
    ).toEqual({ kind: 'server', reason: 'failed on the fields ["form"]' });
    expect(readKitAnswer(false, 503, { status: 'success' })).toEqual({
      kind: 'server',
      reason: 'HTTP 503',
    });
    expect(readKitAnswer(true, 200, 'success')).toMatchObject(server);
    expect(readKitAnswer(true, 200, null)).toMatchObject(server);
    expect(readKitAnswer(true, 200, { status: 'new' })).toEqual({
      kind: 'server',
      reason: 'the status "new"',
    });
  });

  it('tells whoever runs the site what Kit refused, naming a form id Kit does not know', () => {
    expect(serverWarning(FORM, 'failed on the fields ["form"]')).toBe(
      `waitlist: Kit did not take the signup (failed on the fields ["form"]). Kit does not know the form ${FORM}: check the repository variable WAITLIST_KIT_FORM.`,
    );
    expect(serverWarning(FORM, 'HTTP 503')).toBe(
      'waitlist: Kit did not take the signup (HTTP 503).',
    );
  });

  it('only follows https links to Kit’s own hosts', () => {
    expect(safeKitUrl('https://app.kit.com/x')).toBe('https://app.kit.com/x');
    expect(safeKitUrl('https://app.convertkit.com/x')).toBe('https://app.convertkit.com/x');
    expect(safeKitUrl('http://app.kit.com/x')).toBeNull();
    expect(safeKitUrl('https://kit.com.evil.example/x')).toBeNull();
    expect(safeKitUrl('https://notkit.com/x')).toBeNull();
    expect(safeKitUrl('javascript:alert(1)')).toBeNull();
    expect(safeKitUrl('not a url')).toBeNull();
  });
});

describe('subscribe', () => {
  it('posts only the email address to the form’s Kit endpoint, asking for JSON', async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(kitResponse({ status: 'success' })),
    );
    await expect(subscribe(FORM, 'a@b.co', fetchMock)).resolves.toEqual({ kind: 'done' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`https://app.kit.com/forms/${FORM}/subscriptions`);
    expect(init?.method).toBe('POST');
    expect(init?.credentials).toBe('omit');
    expect(init?.headers).toEqual({ Accept: 'application/json' });
    const body = init?.body;
    expect(body).toBeInstanceOf(FormData);
    expect([...(body as FormData).entries()]).toEqual([['email_address', 'a@b.co']]);
  });

  it('is unknown when no answer comes back, since Kit may have the signup all the same', async () => {
    // The request failed on its way or on the way back: the page cannot tell which.
    await expect(
      subscribe(FORM, 'a@b.co', () => Promise.reject(new TypeError('Failed to fetch'))),
    ).resolves.toEqual({ kind: 'unknown' });
    // No answer within the time limit.
    const hanging: typeof fetch = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    await expect(subscribe(FORM, 'a@b.co', hanging, 5)).resolves.toEqual({ kind: 'unknown' });
    // An answer that started, then stopped past the time limit.
    const slowBody: typeof fetch = (_url, init) =>
      Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              init?.signal?.addEventListener('abort', () => {
                controller.error(new DOMException('aborted', 'AbortError'));
              });
            },
          }),
          { status: 200 },
        ),
      );
    await expect(subscribe(FORM, 'a@b.co', slowBody, 5)).resolves.toEqual({ kind: 'unknown' });
    // A 2xx whose body cannot be read as Kit's answer: Kit may well have the address, and the
    // console says what came back.
    await expect(
      subscribe(FORM, 'a@b.co', () => Promise.resolve(new Response('<html>', { status: 200 }))),
    ).resolves.toEqual({ kind: 'unknown', reason: 'HTTP 200 with a body that is not JSON' });
    await expect(
      subscribe(FORM, 'a@b.co', () => Promise.resolve(new Response(null, { status: 204 }))),
    ).resolves.toEqual({ kind: 'unknown', reason: 'HTTP 204 with a body that is not JSON' });
  });

  it('is server only on an answer Kit sent with an error, read whole', async () => {
    await expect(
      subscribe(FORM, 'a@b.co', () => Promise.resolve(kitResponse({ error: 'x' }, 503))),
    ).resolves.toEqual({ kind: 'server', reason: 'HTTP 503' });
    await expect(
      subscribe(FORM, 'a@b.co', () => Promise.resolve(new Response('<html>', { status: 502 }))),
    ).resolves.toEqual({ kind: 'server', reason: 'HTTP 502' });
  });
});

describe('the waitlist page', () => {
  it('shows the waitlist, its 13 or older line and the privacy link, and leaves the app unloaded', () => {
    const page = setup();
    expect(page.result).toBe('waitlist');
    expect(page.doc.documentElement.classList.contains('is-waitlist')).toBe(true);
    expect(page.doc.documentElement.classList.contains('is-app')).toBe(false);
    // The line for a list that sends a confirmation email first, and the one for a list that does not.
    expect(page.q('#wl-terms [data-confirm="on"]', HTMLElement).textContent).toBe(
      waitlistCopy.form.termsConfirm,
    );
    expect(page.q('#wl-terms [data-confirm="off"]', HTMLElement).textContent).toBe(
      waitlistCopy.form.terms,
    );
    for (const terms of [waitlistCopy.form.terms, waitlistCopy.form.termsConfirm]) {
      expect(terms).toMatch(/^You must be 13 or older\. /);
    }
    // The privacy link is in the footer, out of the form, so every state shows it.
    const privacy = page.q('.wl-foot a.wl-privacy', HTMLAnchorElement);
    expect(privacy.getAttribute('href')).toBe('privacy.html');
    expect(privacy.textContent).toBe(waitlistCopy.form.privacy);
    expect(privacy.closest('.wl-act')).toBeNull();
    expect(page.doc.querySelectorAll('a[href="privacy.html"]')).toHaveLength(1);
    expect(page.q('h1', HTMLElement).textContent).toBe(waitlistCopy.headline);
    expect(page.q('.wl-when', HTMLElement).textContent).toBe('Coming this winter.');
    expect(page.doc.querySelector('script[data-app-entry]')).toBeNull();
    expect(page.fetch).not.toHaveBeenCalled();
    // Without JavaScript the form still posts the address to Kit itself.
    const form = page.q('#wl-form', HTMLFormElement);
    expect(form.getAttribute('action')).toBe(kitEndpoint(FORM));
    expect(page.q('#wl-email', HTMLInputElement).name).toBe('email_address');
    // No field but the email address.
    expect(form.querySelectorAll('input')).toHaveLength(1);
    // The form, the done block, Kit's check and the access code share one place; the error line
    // has its own room, right under the field and its button, where a phone keeps it in view.
    expect([...page.q('.wl-act', HTMLElement).children].map((child) => child.className)).toEqual([
      'wl-form',
      'wl-done',
      'wl-check',
      'wl-code',
    ]);
    expect(page.q('.wl-row', HTMLElement).nextElementSibling?.id).toBe('wl-error');
    expect(page.q('#wl-error', HTMLElement).nextElementSibling?.id).toBe('wl-terms');
  });

  it('retires a service worker an earlier visit to the app left, only on a visitor’s device', async () => {
    expect(setup().retire).toHaveBeenCalledOnce();
    expect(
      setup({ storage: memoryStorage({ [CODE_KEY]: CODE_VALUE }) }).retire,
    ).not.toHaveBeenCalled();
    expect(setup({ isApp: true }).retire).not.toHaveBeenCalled();

    const unregister = vi.fn(() => Promise.resolve(true));
    const nav = {
      serviceWorker: {
        getRegistrations: () => Promise.resolve([{ unregister }, { unregister }]),
      },
    } as unknown as Navigator;
    const deleted: string[] = [];
    const caches = {
      keys: () => Promise.resolve(['workbox-precache-v2', 'snowlight-data-v1']),
      delete: (name: string) => {
        deleted.push(name);
        return Promise.resolve(true);
      },
    };
    retireWorkers(nav, caches);
    await flush();
    expect(unregister).toHaveBeenCalledTimes(2);
    expect(deleted).toEqual(['workbox-precache-v2', 'snowlight-data-v1']);
    // Without service workers or caches, and when they fail, it does nothing and never throws.
    expect(() => {
      retireWorkers({} as Navigator, null);
    }).not.toThrow();
    retireWorkers(
      {
        serviceWorker: { getRegistrations: () => Promise.reject(new Error('blocked')) },
      } as unknown as Navigator,
      { keys: () => Promise.reject(new Error('blocked')), delete: () => Promise.resolve(false) },
    );
    await flush();
  });

  it('is put in the page from its template, once', () => {
    const page = setup();
    expect(page.doc.querySelectorAll('#waitlist')).toHaveLength(1);
    expect(page.q('#wl-page', HTMLTemplateElement).nextElementSibling?.id).toBe('waitlist');
    expect(mountWaitlist(page.doc)).toBe(page.waitlist());
    expect(page.doc.querySelectorAll('#waitlist')).toHaveLength(1);
  });

  it('starts the sweep of light only after load, and never for less motion', () => {
    const page = setup();
    const sweeps = [...page.doc.querySelectorAll<HTMLImageElement>('img[data-sweep]')];
    expect(sweeps).toHaveLength(4);
    expect(sweeps.map((image) => image.getAttribute('src'))).toEqual([
      '/s0.webp',
      '/s1.webp',
      '/s2.webp',
      '/s3.webp',
    ]);
    expect(page.waitlist()?.classList.contains('is-sweeping')).toBe(true);
    expect(page.waitlist()?.classList.contains('is-glinting')).toBe(true);

    const doc = scriptedPage(waitlistPage());
    startWaitlist({
      document: doc,
      storage: memoryStorage(),
      fetch: vi.fn<typeof fetch>(),
      reducedMotion: true,
      online: () => true,
      warn: () => undefined,
      retireWorkers: () => undefined,
      afterLoad: (start) => {
        start();
      },
      reveal: () => undefined,
    });
    expect(doc.querySelector('img[data-sweep][src]')).toBeNull();
    expect(doc.querySelector('.is-sweeping, .is-glinting')).toBeNull();
  });

  it('shows the chrome wordmark as a picture with its box held, and says the word as text', () => {
    const page = setup();
    const hero = page.q('.wl-hero', HTMLElement);
    expect(hero.querySelector('.sr-only')?.textContent).toBe(copy.appName);
    expect(hero.querySelector('.wl-chrome')?.getAttribute('aria-hidden')).toBe('true');
    const image = page.q('.wl-hero img', HTMLImageElement);
    expect(image.alt).toBe('');
    expect(image.getAttribute('src')).toBe('/chrome-small.webp');
    expect(Number(image.getAttribute('width'))).toBe(chromeManifest.wordmark.small.width);
    expect(Number(image.getAttribute('height'))).toBe(chromeManifest.wordmark.small.height);
    const wide = page.q('.wl-hero source', HTMLSourceElement);
    expect(wide.media).toBe('(min-width: 640px)');
    expect(wide.getAttribute('srcset')).toBe('/chrome.webp');
    expect(Number(wide.getAttribute('width'))).toBe(chromeManifest.wordmark.large.width);
    expect(Number(wide.getAttribute('height'))).toBe(chromeManifest.wordmark.large.height);
    // The default look sets the headline as text, with no chrome headline picture.
    expect(page.doc.querySelectorAll('#waitlist h1')).toHaveLength(1);
    expect(page.doc.querySelector('.wl-title-chrome')).toBeNull();
  });

  it('sets the headline in chrome, its words kept as text, in the chrome look', () => {
    const doc = scriptedPage(waitlistPage('on', 'chrome'));
    mountWaitlist(doc);
    const headings = doc.querySelectorAll('#waitlist h1');
    expect(headings).toHaveLength(1);
    const heading = headings[0];
    expect(heading?.classList.contains('wl-title-chrome')).toBe(true);
    expect(heading?.querySelector('.sr-only')?.textContent).toBe(waitlistCopy.headline);
    expect(heading?.textContent.trim()).toBe(waitlistCopy.headline);
    expect(heading?.querySelector('picture')?.getAttribute('aria-hidden')).toBe('true');
    const image = heading?.querySelector('img');
    expect(image?.getAttribute('alt')).toBe('');
    expect(image?.getAttribute('src')).toBe('/chrome-headline-small.webp');
    expect(Number(image?.getAttribute('width'))).toBe(chromeManifest['headline-small'].large.width);
    expect(heading?.querySelector('source')?.getAttribute('srcset')).toBe('/chrome-headline.webp');
  });

  it('starts the sweep a while after the page has loaded, so its pictures wait for the rest', () => {
    vi.useFakeTimers();
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query }));
    try {
      const start = vi.fn();
      pageEnv(window).afterLoad(start);
      vi.advanceTimersByTime(SWEEP_DELAY_MS - 1);
      expect(start).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(start).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  it('refuses an address that is not whole, without sending anything', () => {
    const page = setup();
    submit(page, 'name@');
    expect(shownErrors(page)).toEqual(['invalid']);
    expect(page.q('[data-error="invalid"]', HTMLElement).textContent).toBe(
      waitlistCopy.errors.invalid,
    );
    expect(page.q('#wl-email', HTMLElement).getAttribute('aria-invalid')).toBe('true');
    expect(page.fetch).not.toHaveBeenCalled();
    // Typing clears it.
    page.q('#wl-email', HTMLInputElement).dispatchEvent(new Event('input'));
    expect(shownErrors(page)).toEqual([]);
    expect(page.q('#wl-email', HTMLElement).hasAttribute('aria-invalid')).toBe(false);
  });

  it('thanks the person once Kit takes the address, with the confirm line, when Kit asks new addresses to confirm', async () => {
    const page = setup();
    submit(page, '  name@example.com ');
    expect(page.waitlist()?.classList.contains('is-busy')).toBe(true);
    await flush();
    expect(page.fetch).toHaveBeenCalledTimes(1);
    const body = page.fetch.mock.calls[0]?.[1]?.body as FormData;
    expect(body.get('email_address')).toBe('name@example.com');
    expect(page.q('#wl-form', HTMLElement).hidden).toBe(true);
    expect(page.q('.wl-done', HTMLElement).hidden).toBe(false);
    // A new address is not on the list until it is confirmed: the title claims only the signup.
    expect(page.q('.wl-done-title[data-confirm="on"]', HTMLElement).textContent).toBe(
      waitlistCopy.done.titleConfirm,
    );
    expect(page.q('.wl-done-title[data-confirm="off"]', HTMLElement).textContent).toBe(
      waitlistCopy.done.title,
    );
    expect(page.waitlist()?.getAttribute('data-confirm')).toBe('on');
    expect(page.q('.wl-done-line[data-confirm="on"]', HTMLElement).textContent).toBe(
      waitlistCopy.done.confirm,
    );
    expect(page.waitlist()?.classList.contains('is-busy')).toBe(false);
    expect(page.doc.activeElement).toBe(page.q('.wl-done', HTMLElement));
  });

  it('marks a form without the confirmation email, so the page shows the other title and line', async () => {
    const page = setup({ confirm: 'off' });
    submit(page, 'name@example.com');
    await flush();
    expect(page.waitlist()?.getAttribute('data-confirm')).toBe('off');
    expect(page.q('.wl-done-line[data-confirm="off"]', HTMLElement).textContent).toBe(
      waitlistCopy.done.noConfirm,
    );
  });

  it('sends one signup however many times the button is pressed while it is on its way', async () => {
    let release: (response: Response) => void = () => undefined;
    const page = setup({
      answer: () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    });
    submit(page, 'name@example.com');
    page.q('#wl-form', HTMLFormElement).requestSubmit();
    page.q('.wl-join', HTMLButtonElement).click();
    expect(page.fetch).toHaveBeenCalledTimes(1);
    expect(page.q('.wl-join', HTMLElement).getAttribute('aria-disabled')).toBe('true');
    release(kitResponse({ status: 'success' }));
    await flush();
    expect(page.fetch).toHaveBeenCalledTimes(1);
    expect(page.q('.wl-done', HTMLElement).hidden).toBe(false);
  });

  it('says it cannot tell whether the signup went through when no answer comes, keeps the form, and lets the person try again', async () => {
    let fail = true;
    const page = setup({
      answer: () =>
        fail
          ? Promise.reject(new TypeError('Failed to fetch'))
          : Promise.resolve(kitResponse({ status: 'success' })),
    });
    submit(page, 'name@example.com');
    await flush();
    expect(shownErrors(page)).toEqual(['unknown']);
    expect(page.q('[data-error="unknown"]', HTMLElement).textContent).toBe(
      waitlistCopy.errors.unknown,
    );
    expect(page.q('#wl-form', HTMLElement).hidden).toBe(false);
    expect(page.q('.wl-done', HTMLElement).hidden).toBe(true);
    expect(page.waitlist()?.classList.contains('is-busy')).toBe(false);
    fail = false;
    submit(page, 'name@example.com');
    await flush();
    expect(page.fetch).toHaveBeenCalledTimes(2);
    expect(shownErrors(page)).toEqual([]);
    expect(page.q('.wl-done', HTMLElement).hidden).toBe(false);
  });

  it('says the device is offline, and sends nothing, when the device says it has no connection', () => {
    const page = setup({ online: false });
    submit(page, 'name@example.com');
    expect(shownErrors(page)).toEqual(['offline']);
    expect(page.q('[data-error="offline"]', HTMLElement).textContent).toBe(
      waitlistCopy.errors.offline,
    );
    expect(page.fetch).not.toHaveBeenCalled();
    expect(page.waitlist()?.classList.contains('is-busy')).toBe(false);
  });

  it('has a line for every error the page can show, and no other', () => {
    const page = setup();
    const lines = [...page.doc.querySelectorAll<HTMLElement>('#wl-error [data-error]')];
    const kinds = lines.map((line) => line.getAttribute('data-error') ?? '');
    expect(kinds.sort()).toEqual(Object.keys(waitlistCopy.errors).sort());
    for (const line of lines) {
      const kind = line.getAttribute('data-error') as keyof typeof waitlistCopy.errors;
      expect(line.textContent).toBe(waitlistCopy.errors[kind]);
    }
  });

  it('scrolls every error into view, and leaves the keyboard up only when the address needs fixing', async () => {
    interface Case {
      kind: string;
      answer?: () => Promise<Response>;
      online?: boolean;
      email: string;
    }
    const cases: Case[] = [
      { kind: 'invalid', email: 'name@' },
      { kind: 'offline', online: false, email: 'name@example.com' },
      {
        kind: 'rejected',
        answer: () =>
          Promise.resolve(kitResponse({ status: 'failed', errors: { fields: ['email_address'] } })),
        email: 'name@example.com',
      },
      {
        kind: 'unknown',
        answer: () => Promise.reject(new TypeError('Failed to fetch')),
        email: 'name@example.com',
      },
      { kind: 'server', answer: () => Promise.resolve(kitResponse({}, 500)), email: 'a@b.co' },
    ];
    for (const { kind, answer, online, email } of cases) {
      const page = setup({
        ...(answer ? { answer } : {}),
        ...(online === false ? { online } : {}),
      });
      submit(page, email);
      await flush();
      expect(shownErrors(page), kind).toEqual([kind]);
      expect(page.reveal, kind).toHaveBeenCalledWith(page.q('#wl-error', HTMLElement));
      // The field, to fix the address; else the button, which drops a phone's keyboard and
      // leaves trying again one press away.
      const focused = kind === 'invalid' || kind === 'rejected' ? '#wl-email' : '.wl-join';
      expect(page.doc.activeElement, kind).toBe(page.q(focused, HTMLElement));
    }
    // Nothing to reveal when Kit takes the address.
    const done = setup();
    submit(done, 'name@example.com');
    await flush();
    expect(done.reveal).not.toHaveBeenCalled();
  });

  it('marks the field as wrong only for an error in the address, never for the connection or Kit', async () => {
    let answer: () => Promise<Response> = () =>
      Promise.resolve(kitResponse({ status: 'failed', errors: { fields: ['email_address'] } }));
    let online = true;
    const page = setup({ answer: () => answer(), online: () => online });
    const field = page.q('#wl-email', HTMLInputElement);
    const marked = () => field.getAttribute('aria-invalid');

    submit(page, 'name@');
    expect(shownErrors(page)).toEqual(['invalid']);
    expect(marked()).toBe('true');
    // A connection that fails after an address error clears the mark: the address was fine.
    answer = () => Promise.reject(new TypeError('Failed to fetch'));
    submit(page, 'name@example.com');
    await flush();
    expect(shownErrors(page)).toEqual(['unknown']);
    expect(marked()).toBeNull();

    answer = () => Promise.resolve(kitResponse({}, 503));
    submit(page, 'name@example.com');
    await flush();
    expect(shownErrors(page)).toEqual(['server']);
    expect(marked()).toBeNull();

    online = false;
    submit(page, 'name@example.com');
    expect(shownErrors(page)).toEqual(['offline']);
    expect(marked()).toBeNull();

    online = true;
    answer = () =>
      Promise.resolve(kitResponse({ status: 'failed', errors: { fields: ['email_address'] } }));
    submit(page, 'name@example.com');
    await flush();
    expect(shownErrors(page)).toEqual(['rejected']);
    expect(marked()).toBe('true');
  });

  it('says it cannot tell when Kit answers 2xx with a body it cannot read, and tells the console', async () => {
    const page = setup({ answer: () => Promise.resolve(new Response('<html>', { status: 200 })) });
    submit(page, 'name@example.com');
    await flush();
    expect(shownErrors(page)).toEqual(['unknown']);
    expect(page.warn.mock.calls[0]?.[0]).toContain('HTTP 200 with a body that is not JSON');
    // No answer at all: nothing for the console.
    const lost = setup({ answer: () => Promise.reject(new TypeError('Failed to fetch')) });
    submit(lost, 'name@example.com');
    await flush();
    expect(lost.warn).not.toHaveBeenCalled();
  });

  it('gives a browser without JavaScript the waitlist, with a form that posts to Kit itself', () => {
    for (const confirm of ['on', 'off'] as const) {
      // DOMParser parses as a browser with JavaScript off does: <noscript> is markup.
      const doc = new DOMParser().parseFromString(waitlistPage(confirm), 'text/html');
      const plain = doc.querySelector('noscript #waitlist');
      if (!(plain instanceof HTMLElement)) throw new Error('no plain waitlist');
      expect(plain.getAttribute('data-confirm')).toBe(confirm);
      expect(plain.querySelector('.wl-hero .sr-only')?.textContent).toBe(copy.appName);
      expect(plain.querySelector('h1')?.textContent).toBe(waitlistCopy.headline);
      expect(plain.querySelector('.wl-when')?.textContent).toBe(waitlistCopy.when);
      const form = plain.querySelector('form');
      expect(form?.getAttribute('action')).toBe(kitEndpoint(FORM));
      expect(form?.getAttribute('method')).toBe('post');
      expect(form?.getAttribute('rel')).toBe('noreferrer');
      const inputs = [...(form?.querySelectorAll('input') ?? [])];
      expect(inputs.map((input) => [input.name, input.type, input.required])).toEqual([
        ['email_address', 'email', true],
      ]);
      expect(form?.querySelector('button[type="submit"]')?.textContent).toBe(
        waitlistCopy.form.join,
      );
      expect(plain.querySelector('.wl-terms [data-confirm="on"]')?.textContent).toBe(
        waitlistCopy.form.termsConfirm,
      );
      expect(plain.querySelector('.wl-terms [data-confirm="off"]')?.textContent).toBe(
        waitlistCopy.form.terms,
      );
      expect(plain.querySelector('a[href="privacy.html"]')?.textContent).toBe(
        waitlistCopy.form.privacy,
      );
      // Only what works without a script: no code field, no error lines.
      expect(plain.querySelector('#code-form, #wl-error, [data-error], script')).toBeNull();
    }
  });

  it('tells a rejected address from Kit not taking signups', async () => {
    const rejected = setup({
      answer: () =>
        Promise.resolve(
          kitResponse({ status: 'failed', errors: { fields: ['email_address'], messages: [] } }),
        ),
    });
    submit(rejected, 'name@example.com');
    await flush();
    expect(shownErrors(rejected)).toEqual(['rejected']);

    const down = setup({ answer: () => Promise.resolve(kitResponse({}, 500)) });
    submit(down, 'name@example.com');
    await flush();
    expect(shownErrors(down)).toEqual(['server']);
    expect(down.q('.wl-done', HTMLElement).hidden).toBe(true);
    expect(down.warn).toHaveBeenCalledWith(serverWarning(FORM, 'HTTP 500'));
    expect(rejected.warn).not.toHaveBeenCalled();

    // A form id Kit does not know: every signup fails the same way, and the console says why.
    const unknownForm = setup({
      answer: () =>
        Promise.resolve(kitResponse({ status: 'failed', errors: { fields: ['form'] } })),
    });
    submit(unknownForm, 'name@example.com');
    await flush();
    expect(shownErrors(unknownForm)).toEqual(['server']);
    expect(unknownForm.warn.mock.calls[0]?.[0]).toContain(`Kit does not know the form ${FORM}`);
  });

  it('sends the person to Kit’s spam check when Kit holds the signup', async () => {
    const page = setup({
      answer: () =>
        Promise.resolve(
          kitResponse({ status: 'quarantined', url: 'https://app.kit.com/forms/1/check?x=1' }),
        ),
    });
    // Until Kit asks, the page has no link without an address.
    expect(page.doc.querySelector('.wl-check-link')).toBeNull();
    submit(page, 'name@example.com');
    await flush();
    expect(page.q('#wl-form', HTMLElement).hidden).toBe(true);
    expect(page.q('.wl-done', HTMLElement).hidden).toBe(true);
    expect(page.q('.wl-check', HTMLElement).hidden).toBe(false);
    expect(page.doc.querySelectorAll('.wl-check-link')).toHaveLength(1);
    expect(page.q('.wl-check-link', HTMLAnchorElement).href).toBe(
      'https://app.kit.com/forms/1/check?x=1',
    );
    expect(page.q('.wl-check-link', HTMLAnchorElement).textContent.trim()).toBe(
      waitlistCopy.check.link,
    );
    // The page's one strong button, in the room held for it, in the same tab.
    const link = page.q('.wl-check-link', HTMLAnchorElement);
    expect(link.classList.contains('wl-join')).toBe(true);
    expect(link.parentElement?.classList.contains('wl-check-slot')).toBe(true);
    expect(link.target).toBe('');
  });

  it('opens the code field from the quiet link, refuses a wrong code and opens the app on the right one', () => {
    const page = setup();
    const form = page.q('#code-form', HTMLFormElement);
    expect(form.hidden).toBe(true);
    // It opens in the form's own place, so the page around it stays where it is.
    expect(form.parentElement?.classList.contains('wl-act')).toBe(true);
    expect(page.doc.title).toBe(waitlistCopy.meta.shareTitle);
    const open = page.q('.wl-code-open', HTMLButtonElement);
    open.click();
    expect(form.hidden).toBe(false);
    expect(page.waitlist()?.classList.contains('is-code')).toBe(true);
    expect(open.getAttribute('aria-expanded')).toBe('true');
    const input = page.q('#code-input', HTMLInputElement);
    expect(page.doc.activeElement).toBe(input);
    // Closed again, the form is back.
    open.click();
    expect(form.hidden).toBe(true);
    expect(page.waitlist()?.classList.contains('is-code')).toBe(false);
    expect(open.getAttribute('aria-expanded')).toBe('false');
    open.click();

    input.value = '1111';
    form.requestSubmit();
    expect(form.classList.contains('is-wrong')).toBe(true);
    expect(page.q('.wl-code-wrong', HTMLElement).hidden).toBe(false);
    expect(input.value).toBe('');
    expect(page.storage.getItem(CODE_KEY)).toBeNull();
    expect(page.doc.querySelector('script[data-app-entry]')).toBeNull();

    input.value = CODE;
    input.dispatchEvent(new Event('input'));
    expect(page.storage.getItem(CODE_KEY)).toBe(CODE_VALUE);
    expect(page.waitlist()).toBeNull();
    expect(page.doc.documentElement.classList.contains('is-app')).toBe(true);
    expect(page.doc.documentElement.classList.contains('is-waitlist')).toBe(false);
    // The tab says the app's own name again.
    expect(page.doc.title).toBe(copy.appName);
    const script = page.doc.querySelector<HTMLScriptElement>('script[data-app-entry]');
    expect(script?.type).toBe('module');
    expect(script?.getAttribute('src')).toBe(ENTRY);
    expect(page.doc.querySelectorAll('script[data-app-entry]')).toHaveLength(1);
  });

  it('opens the app on a submitted right code too, even where the device keeps nothing', () => {
    const blocked = memoryStorage();
    blocked.setItem = () => {
      throw new Error('blocked');
    };
    const page = setup({ storage: blocked });
    page.q('.wl-code-open', HTMLButtonElement).click();
    page.q('#code-input', HTMLInputElement).value = CODE;
    page.q('#code-form', HTMLFormElement).requestSubmit();
    expect(page.waitlist()).toBeNull();
    expect(page.doc.querySelector('script[data-app-entry]')?.getAttribute('src')).toBe(ENTRY);
  });

  it('takes a device that has the code straight to the app', () => {
    const page = setup({ storage: memoryStorage({ [CODE_KEY]: CODE_VALUE }) });
    expect(page.result).toBe('app');
    expect(page.waitlist()).toBeNull();
    expect(page.doc.documentElement.classList.contains('is-app')).toBe(true);
    expect(page.doc.querySelector('script[data-app-entry]')?.getAttribute('src')).toBe(ENTRY);
    expect(page.fetch).not.toHaveBeenCalled();
    expect(page.doc.title).toBe(copy.appName);

    // As the head's own check marked it: the waitlist never leaves its template, so none of
    // its pictures are in the page to load.
    const marked = setup({ isApp: true });
    expect(marked.result).toBe('app');
    expect(marked.waitlist()).toBeNull();
    expect(marked.doc.querySelectorAll('img')).toHaveLength(0);
    expect(marked.q('#wl-page', HTMLTemplateElement).content.querySelector('#waitlist')).not.toBe(
      null,
    );
    expect(marked.doc.querySelector('script[data-app-entry]')?.getAttribute('src')).toBe(ENTRY);
    expect(marked.doc.title).toBe(copy.appName);
  });

  it('does nothing on a page without the waitlist', () => {
    const doc = new DOMParser().parseFromString('<p>x</p>', 'text/html');
    expect(
      startWaitlist({
        document: doc,
        storage: null,
        fetch: vi.fn<typeof fetch>(),
        reducedMotion: true,
        online: () => true,
        warn: () => undefined,
        retireWorkers: () => undefined,
        afterLoad: () => undefined,
        reveal: () => undefined,
      }),
    ).toBe('absent');
    expect(doc.querySelector('script')).toBeNull();
  });
});
