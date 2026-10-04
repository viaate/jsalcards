/**
 * Registers the service worker once the page has loaded and the map is on
 * screen. Its code loads then too, so nothing about offline support competes
 * with the first paint or the map: installing the worker downloads and
 * stores every file of the site.
 */

import { DATA_FILES } from 'virtual:snowlight/data-files';

import type { ServiceWorkerHandle } from '../pwa/register';

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
 * Then, whatever came of it, the worker's caches drop the copies of data
 * files a deploy has replaced, which this build (`ships`) no longer reads
 * (pwa/data.ts dropOldData).
 */
export function startServiceWorker(
  after: Promise<unknown> = Promise.resolve(),
  ships: readonly string[] = DATA_FILES,
): Promise<ServiceWorkerHandle | null> {
  const handle = Promise.all([afterLoad(), after.catch(() => undefined)])
    .then(() => import('../pwa/register'))
    .then(({ registerServiceWorker }) => registerServiceWorker({ applyWhenHidden: true }))
    .catch(() => null);
  if (import.meta.env.PROD) {
    void handle
      .then(() => import('../pwa/data'))
      .then(({ dropOldData }) => dropOldData(ships))
      .catch(() => undefined);
  }
  return handle;
}
