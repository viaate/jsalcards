/**
 * The waitlist page's behaviour (index.html's waitlist blocks), in a build
 * with VITE_WAITLIST_KIT_FORM set. tools/waitlist.ts bundles src/waitlist/
 * inline.ts, which runs startWaitlist(), into a classic script at the end of
 * the page, so the page asks the network for nothing it has not drawn.
 *
 * - A device that has entered the access code (localStorage 'sl-lock', the
 *   key and value the code screen has always used) goes straight to the app:
 *   index.html's head marks it `is-app` before anything paints and starts
 *   fetching the app's script, and this runs it once the page is in. The
 *   waitlist stays in its inert <template id="wl-page">, so none of its
 *   pictures load there.
 * - Anyone else sees the waitlist, put in the page from that template. The
 *   app's script is never fetched, so the map does not start behind it.
 * - The email goes to Kit's form endpoint only when the person submits:
 *   POST https://app.kit.com/forms/{form}/subscriptions with the one field
 *   email_address, the request Kit's own embed makes (its answer is JSON, and
 *   Kit allows it from any site). No key is needed and none is in the page.
 * - Every word shown is already in the page, from the copy modules; this
 *   only shows and hides it.
 */

/** Where the access code is kept, and its value, as the code screen has always kept it. */
export const CODE_KEY = 'sl-lock';
export const CODE_VALUE = 'MjM4MQ==';

/**
 * How long a signup waits for Kit's answer. Past it the page stops waiting and
 * says it cannot tell whether the signup went through: it may have reached Kit.
 */
export const SUBMIT_TIMEOUT_MS = 20_000;

/**
 * How long after the page has loaded the band of light starts: its pictures
 * then never share the network with the map picture and the words.
 */
export const SWEEP_DELAY_MS = 1500;

/** The hosts Kit's spam check page can be on. */
const KIT_HOST = /(?:^|\.)(?:kit\.com|convertkit\.com)$/u;

/**
 * What became of a signup, as far as the page knows it:
 *
 * - `done`: Kit took the address.
 * - `check`: Kit holds it until the person passes its spam check, at `url`.
 * - `rejected`: Kit refused the address itself.
 * - `server`: Kit answered that it is not taking signups (`reason` says what
 *   it named, for the console).
 * - `unknown`: the request went out but no answer came back that could be
 *   read: it took too long, the connection dropped, or Kit answered 2xx with
 *   a body that is not JSON (`reason` says so, for the console). Kit may have
 *   the address or not; the page cannot tell, so it says only that.
 */
export type Outcome =
  | { readonly kind: 'done' }
  | { readonly kind: 'check'; readonly url: string }
  | { readonly kind: 'rejected' }
  | { readonly kind: 'server'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly reason?: string };

/**
 * The error states, each a line of the page's error block. `offline` is the
 * device saying it has no connection, before anything is sent.
 */
export type ErrorKind = 'invalid' | 'rejected' | 'offline' | 'unknown' | 'server';

/** The errors that are about the address itself: only these mark the field as wrong. */
export const addressErrors: ReadonlySet<ErrorKind> = new Set(['invalid', 'rejected']);

/** Kit's form endpoint for a form id. */
export function kitEndpoint(form: string): string {
  return `https://app.kit.com/forms/${encodeURIComponent(form)}/subscriptions`;
}

/** Whether the code was entered on this device. */
export function hasCode(storage: Pick<Storage, 'getItem'> | null): boolean {
  try {
    return storage?.getItem(CODE_KEY) === CODE_VALUE;
  } catch {
    return false;
  }
}

/** Whether `typed` is the access code. */
export function isCode(typed: string): boolean {
  try {
    return btoa(typed) === CODE_VALUE;
  } catch {
    // btoa throws on characters outside Latin-1: not the code.
    return false;
  }
}

/**
 * Whether text reads as a whole email address: something, an @, and a domain
 * with a dot in it, with no spaces. Kit checks it again; this only catches
 * what is plainly not one before anything is sent.
 */
export function isEmail(text: string): boolean {
  return text.length <= 254 && /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/u.test(text);
}

/** Whether a value is a plain object. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * What Kit's answer means. Kit answers 200 with JSON whose `status` is
 * `success`, `quarantined` (held for a spam check on Kit's own page, at
 * `url`) or `failed`, with `errors.fields` naming what failed. Anything
 * else, or an answer that is not a 2xx, is Kit not taking signups. A form
 * id Kit does not know answers `failed` with the field `form`, on every
 * signup: `reason` names it, so the console says what to fix.
 */
export function readKitAnswer(ok: boolean, status: number, body: unknown): Outcome {
  if (!ok) return { kind: 'server', reason: `HTTP ${String(status)}` };
  if (!isRecord(body)) return { kind: 'server', reason: 'an answer that is not an object' };
  switch (body.status) {
    case 'success':
      return { kind: 'done' };
    case 'quarantined': {
      const url = typeof body.url === 'string' ? safeKitUrl(body.url) : null;
      return url === null
        ? { kind: 'server', reason: 'a spam check with no Kit address' }
        : { kind: 'check', url };
    }
    case 'failed': {
      const errors = body.errors;
      const fields: unknown[] =
        isRecord(errors) && Array.isArray(errors.fields) ? errors.fields : [];
      if (fields.includes('email_address')) return { kind: 'rejected' };
      return { kind: 'server', reason: `failed on the fields ${JSON.stringify(fields)}` };
    }
    default:
      return { kind: 'server', reason: `the status ${JSON.stringify(body.status)}` };
  }
}

/** What the console says when Kit is not taking signups, for whoever runs the site. */
export function serverWarning(form: string, reason: string): string {
  const hint = reason.includes('"form"')
    ? ` Kit does not know the form ${form}: check the repository variable WAITLIST_KIT_FORM.`
    : '';
  return `waitlist: Kit did not take the signup (${reason}).${hint}`;
}

/** The link to Kit's spam check, if it is an https page on Kit's own hosts. */
export function safeKitUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && KIT_HOST.test(parsed.hostname) ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * Sends one signup to Kit. Never throws. A request that fails, takes longer
 * than SUBMIT_TIMEOUT_MS, or whose answer cannot be read is `unknown`: once
 * it is on its way the page cannot tell whether Kit got it. Only an answer
 * Kit sent with an error status, read whole, is `server`.
 */
export async function subscribe(
  form: string,
  email: string,
  fetchImpl: typeof fetch,
  timeoutMs = SUBMIT_TIMEOUT_MS,
): Promise<Outcome> {
  const body = new FormData();
  body.append('email_address', email);
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  let response: Response;
  try {
    response = await fetchImpl(kitEndpoint(form), {
      method: 'POST',
      body,
      headers: { Accept: 'application/json' },
      // Nothing of this site's goes with it: no cookies, no referring page.
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      signal: controller.signal,
    });
  } catch {
    clearTimeout(timer);
    return { kind: 'unknown' };
  }
  try {
    const parsed: unknown = await response.json();
    return readKitAnswer(response.ok, response.status, parsed);
  } catch {
    // A body cut off or past the time limit is no answer. A 2xx whose body is not JSON is an
    // answer the page cannot read: Kit may well have taken the address. An error status whose
    // body is not JSON is still Kit's answer.
    if (controller.signal.aborted) return { kind: 'unknown' };
    return response.ok
      ? { kind: 'unknown', reason: `HTTP ${String(response.status)} with a body that is not JSON` }
      : { kind: 'server', reason: `HTTP ${String(response.status)}` };
  } finally {
    clearTimeout(timer);
  }
}

/** What startWaitlist needs from the page around it; tests pass their own. */
export interface WaitlistEnv {
  readonly document: Document;
  readonly storage: Storage | null;
  readonly fetch: typeof fetch;
  /** Whether the person asked for less motion. */
  readonly reducedMotion: boolean;
  /** False when the device says it has no connection (navigator.onLine). */
  readonly online: () => boolean;
  /** Where a note for whoever runs the site goes (the console). */
  readonly warn: (message: string) => void;
  /** Removes service workers and caches left by an earlier visit to the app (retireWorkers). */
  readonly retireWorkers: () => void;
  /** Runs `start` once the page has loaded and settled (SWEEP_DELAY_MS later). */
  readonly afterLoad: (start: () => void) => void;
  /**
   * Scrolls an element into view, as little as it takes: an error line, so it shows above a
   * phone's keyboard and on a short screen.
   */
  readonly reveal: (element: HTMLElement) => void;
}

/** The page's own environment. */
export function pageEnv(win: Window): WaitlistEnv {
  let storage: Storage | null;
  try {
    storage = win.localStorage;
  } catch {
    // Blocked site data: the code is asked for on each visit.
    storage = null;
  }
  return {
    document: win.document,
    storage,
    fetch: win.fetch.bind(win),
    reducedMotion: win.matchMedia('(prefers-reduced-motion: reduce)').matches,
    online: () => win.navigator.onLine,
    warn: (message) => {
      console.warn(message);
    },
    retireWorkers: () => {
      retireWorkers(win.navigator, 'caches' in win ? win.caches : null);
    },
    afterLoad: (start) => {
      const later = (): void => {
        win.setTimeout(start, SWEEP_DELAY_MS);
      };
      if (win.document.readyState === 'complete') later();
      else win.addEventListener('load', later, { once: true });
    },
    reveal: (element) => {
      element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    },
  };
}

/**
 * Puts the waitlist in the page from its template, unless it is there already
 * (index.html's script after the template does it as the page is read).
 */
export function mountWaitlist(doc: Document): HTMLElement | null {
  const shown = doc.getElementById('waitlist');
  if (shown !== null) return shown;
  const page = doc.getElementById('wl-page');
  if (!(page instanceof HTMLTemplateElement)) return null;
  page.after(doc.importNode(page.content, true));
  return doc.getElementById('waitlist');
}

/**
 * The waitlist page has no service worker of its own. A browser that ran the
 * app here before (behind the old code screen) keeps that app's worker, which
 * would serve its stored copy of the old page and download the whole app again
 * on each update. On a visitor's device, the waitlist unregisters it and
 * deletes its caches; the app registers a new one on a device with the code.
 * Never throws, and asks the network for nothing.
 */
export function retireWorkers(
  nav: Pick<Navigator, 'serviceWorker'> | undefined,
  caches: Pick<CacheStorage, 'keys' | 'delete'> | null,
): void {
  const container = nav && 'serviceWorker' in nav ? nav.serviceWorker : undefined;
  void container
    ?.getRegistrations()
    .then((registrations) => Promise.all(registrations.map((r) => r.unregister())))
    .catch(() => undefined);
  void caches
    ?.keys()
    .then((names) => Promise.all(names.map((name) => caches.delete(name))))
    .catch(() => undefined);
}

/** Starts the app: its module script, which the waitlist build takes out of the page. */
export function bootApp(doc: Document, entry: string): void {
  if (entry === '' || doc.querySelector('script[data-app-entry]') !== null) return;
  const script = doc.createElement('script');
  script.type = 'module';
  script.crossOrigin = 'anonymous';
  script.src = entry;
  script.setAttribute('data-app-entry', '');
  doc.head.append(script);
}

/** Finds an element the page must have, of the kind it must be. */
function required<T extends Element>(
  root: ParentNode,
  selector: string,
  kind: abstract new () => T,
): T {
  const element = root.querySelector(selector);
  if (!(element instanceof kind)) throw new Error(`waitlist: missing ${selector}`);
  return element;
}

/**
 * Runs the waitlist page, or, on a device with the code, starts the app.
 * Returns what it did, for tests.
 */
export function startWaitlist(env: WaitlistEnv): 'app' | 'waitlist' | 'absent' {
  const doc = env.document;
  const html = doc.documentElement;
  const page = doc.getElementById('wl-page');
  if (page === null) return 'absent';
  const entry = page.getAttribute('data-entry') ?? '';
  const appTitle = page.getAttribute('data-app-title') ?? '';

  // The app's own tab title comes back with it: the head carries the waitlist's.
  const openApp = (): void => {
    html.classList.add('is-app');
    doc.getElementById('waitlist')?.remove();
    if (appTitle !== '') doc.title = appTitle;
    bootApp(doc, entry);
  };

  if (html.classList.contains('is-app') || hasCode(env.storage)) {
    openApp();
    return 'app';
  }
  const root = mountWaitlist(doc);
  if (root === null) return 'absent';
  const form = root.getAttribute('data-form') ?? '';
  html.classList.add('is-waitlist');
  env.retireWorkers();

  // Once the page has settled, and never for less motion: one glint across the wordmark, and
  // the band of light that crosses the map, its pictures fetched only then.
  if (!env.reducedMotion) {
    env.afterLoad(() => {
      for (const image of root.querySelectorAll<HTMLImageElement>('img[data-sweep]')) {
        const source = image.getAttribute('data-sweep');
        if (source !== null && source !== '') image.src = source;
      }
      root.classList.add('is-sweeping', 'is-glinting');
    });
  }

  const signup = required(root, '#wl-form', HTMLFormElement);
  const email = required(root, '#wl-email', HTMLInputElement);
  const button = required(root, '.wl-join', HTMLButtonElement);
  const errorBlock = required(root, '#wl-error', HTMLElement);
  const done = required(root, '.wl-done', HTMLElement);
  const check = required(root, '.wl-check', HTMLElement);
  const checkTemplate = required(root, '.wl-check-template', HTMLTemplateElement);

  // Only an address that needs fixing marks the field: a lost connection or Kit turning signups
  // away says nothing about what was typed.
  const showError = (kind: ErrorKind | null): void => {
    for (const line of errorBlock.querySelectorAll<HTMLElement>('[data-error]')) {
      line.hidden = line.getAttribute('data-error') !== kind;
    }
    errorBlock.hidden = kind === null;
    if (kind !== null && addressErrors.has(kind)) email.setAttribute('aria-invalid', 'true');
    else email.removeAttribute('aria-invalid');
  };

  /**
   * Shows an error where the person can read it. When the address itself needs fixing
   * (`invalid`, `rejected`), the field keeps or takes the focus; otherwise the focus goes to the
   * button, which drops a phone's keyboard and leaves "try again" one press away. Either way the
   * line is then scrolled into view, so a keyboard or a short screen never hides it.
   */
  const fail = (kind: ErrorKind): void => {
    showError(kind);
    if (addressErrors.has(kind)) email.focus({ preventScroll: true });
    else button.focus({ preventScroll: true });
    env.reveal(errorBlock);
  };

  let busy = false;
  const setBusy = (on: boolean): void => {
    busy = on;
    root.classList.toggle('is-busy', on);
    button.setAttribute('aria-disabled', on ? 'true' : 'false');
    signup.setAttribute('aria-busy', on ? 'true' : 'false');
  };

  // The link to Kit's check is only in the page once it has an address to go to.
  const showCheckLink = (url: string): void => {
    const shown = check.querySelector('.wl-check-link');
    let link: HTMLAnchorElement;
    if (shown instanceof HTMLAnchorElement) {
      link = shown;
    } else {
      const fragment = doc.importNode(checkTemplate.content, true);
      link = required(fragment, '.wl-check-link', HTMLAnchorElement);
      checkTemplate.before(fragment);
    }
    link.href = url;
  };

  const finish = (outcome: Outcome): void => {
    switch (outcome.kind) {
      case 'done':
        signup.hidden = true;
        done.hidden = false;
        root.classList.add('is-done');
        done.focus();
        return;
      case 'check':
        signup.hidden = true;
        showCheckLink(outcome.url);
        check.hidden = false;
        check.focus();
        return;
      case 'server':
        env.warn(serverWarning(form, outcome.reason));
        fail('server');
        return;
      case 'unknown':
        if (outcome.reason !== undefined) {
          env.warn(
            `waitlist: Kit answered ${outcome.reason}; the page cannot tell whether it took the signup.`,
          );
        }
        fail('unknown');
        return;
      default:
        fail(outcome.kind);
    }
  };

  signup.addEventListener('submit', (event) => {
    event.preventDefault();
    if (busy) return;
    const typed = email.value.trim();
    if (!isEmail(typed)) {
      fail('invalid');
      return;
    }
    if (!env.online()) {
      // Nothing is sent: the device itself says there is no connection.
      fail('offline');
      return;
    }
    showError(null);
    setBusy(true);
    void subscribe(form, typed, env.fetch).then((outcome) => {
      setBusy(false);
      finish(outcome);
    });
  });
  email.addEventListener('input', () => {
    if (!errorBlock.hidden) showError(null);
  });

  // The access code: a quiet link that opens the code field in the form's place, and closes it.
  const codeOpen = required(root, '.wl-code-open', HTMLButtonElement);
  const codeForm = required(root, '#code-form', HTMLFormElement);
  const codeInput = required(root, '#code-input', HTMLInputElement);
  const codeWrong = required(root, '.wl-code-wrong', HTMLElement);
  const unlock = (): void => {
    try {
      env.storage?.setItem(CODE_KEY, CODE_VALUE);
    } catch {
      // Kept for this visit only; the next one asks again.
    }
    html.classList.remove('is-waitlist');
    openApp();
  };
  codeOpen.addEventListener('click', () => {
    const opening = codeForm.hidden === true;
    codeForm.hidden = !opening;
    root.classList.toggle('is-code', opening);
    codeOpen.setAttribute('aria-expanded', opening ? 'true' : 'false');
    if (opening) codeInput.focus({ preventScroll: true });
  });
  codeForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (isCode(codeInput.value)) {
      unlock();
      return;
    }
    codeInput.value = '';
    codeForm.classList.add('is-wrong');
    codeWrong.hidden = false;
  });
  codeInput.addEventListener('input', () => {
    codeForm.classList.remove('is-wrong');
    codeWrong.hidden = true;
    if (isCode(codeInput.value)) unlock();
  });
  return 'waitlist';
}
