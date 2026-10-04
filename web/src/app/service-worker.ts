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
 * screen, or unable to start). Data the page reads before the worker takes
 * it over is kept for the worker as it is read (data/files.ts fetchFile).
 */
export function startServiceWorker(
  after: Promise<unknown> = Promise.resolve(),
): Promise<ServiceWorkerHandle | null> {
  const handle = Promise.all([afterLoad(), after.catch(() => undefined)])
    .then(() => import('../pwa/register'))
    .then(({ registerServiceWorker }) => registerServiceWorker({ applyWhenHidden: true }))
    .catch(() => null);
  if (navigator.webdriver) window.snowlightServiceWorker = handle;
  return handle;
}
