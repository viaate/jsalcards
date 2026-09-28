/**
 * Registers the service worker once the page has loaded and the map is on
 * screen. Its code loads then too, so nothing about offline support competes
 * with the first paint or the map: installing the worker downloads and
 * stores every file of the site.
 */

import type { ServiceWorkerHandle } from '../pwa/register';

declare global {
  interface Window {
    /** The registration, for end-to-end tests: set only when navigator.webdriver is true. */
    snowlightServiceWorker?: Promise<ServiceWorkerHandle | null>;
  }
}

/** Resolves after the page's load event. */
export function afterLoad(): Promise<void> {
  if (document.readyState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    window.addEventListener(
      'load',
      () => {
        resolve();
      },
      { once: true },
    );
  });
}

/**
 * Registers the worker after load and once `after` settles (the map on
 * screen, or unable to start). `warmUrls` lists data files loaded outside the
 * page (the search index, by its worker); it is read when the first worker
 * takes over, so files added to it until then are cached for offline use too.
 */
export function startServiceWorker(
  warmUrls: readonly string[],
  after: Promise<unknown> = Promise.resolve(),
): Promise<ServiceWorkerHandle | null> {
  const handle = Promise.all([afterLoad(), after.catch(() => undefined)])
    .then(() => import('../pwa/register'))
    .then(({ registerServiceWorker }) => registerServiceWorker({ warmUrls, applyWhenHidden: true }))
    .catch(() => null);
  if (navigator.webdriver) window.snowlightServiceWorker = handle;
  return handle;
}
