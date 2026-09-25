/**
 * Registers the service worker, once the page has loaded and gone idle, so
 * it never competes with the first paint or the map for the network.
 *
 * Updates follow the browser's own lifecycle by default: a new version
 * installs in the background and takes over once every Snowlight tab has
 * closed, so a page never mixes old code with new files. `onUpdateReady` hears
 * about it; `applyUpdate` switches at once and reloads; `applyWhenHidden`
 * switches the next time the tab is hidden, where the reload is not seen and
 * the address bar (src/state) brings back the same view and school.
 */

import { warmDataCache } from './data';
import type { DataCacheHost } from './data';
import { SKIP_WAITING_MESSAGE, SW_FILE } from './config';

type Container = Pick<
  ServiceWorkerContainer,
  'controller' | 'register' | 'addEventListener' | 'removeEventListener'
>;

/** The parts of `window` registration uses, so tests can hand it a fake. */
export interface RegisterHost extends DataCacheHost {
  readonly navigator: DataCacheHost['navigator'] & {
    readonly serviceWorker?: Container;
    readonly onLine: boolean;
  };
  readonly document: Pick<
    Document,
    'readyState' | 'visibilityState' | 'addEventListener' | 'removeEventListener'
  >;
  readonly location: { readonly href: string; reload(): void };
  addEventListener(type: string, listener: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: string, listener: () => void): void;
  setTimeout(handler: () => void, timeout: number): number;
  setInterval(handler: () => void, timeout: number): number;
  clearInterval(id: number | undefined): void;
  requestIdleCallback?(callback: () => void, options?: IdleRequestOptions): number;
}

export interface RegisterOptions {
  /** Defaults to `window`. */
  host?: RegisterHost;
  /** Defaults to true in a production build only. */
  enabled?: boolean;
  /** The site base the worker is served from and controls. Defaults to Vite's base. */
  base?: string;
  /** Data files loaded outside this page (by a web worker) to cache on the first visit. */
  warmUrls?: readonly string[];
  /** Called once a new version is installed and waiting. */
  onUpdateReady?: () => void;
  /** Switch to a waiting version the next time the tab is hidden. Default false. */
  applyWhenHidden?: boolean;
  /** How often an open, visible page looks for a new version. Default one hour. */
  checkEveryMs?: number;
}

export interface ServiceWorkerHandle {
  readonly registration: ServiceWorkerRegistration;
  /**
   * Resolves once the first worker has taken this page and the data files the
   * page loaded before it have been requested again through it (see
   * warmDataCache), to how many were; to 0 at once when a worker already
   * controlled the page. It stays pending while no worker has taken the page.
   */
  readonly warmed: Promise<number>;
  /** True once a new version is installed and waiting. */
  readonly updateReady: boolean;
  /** Switches to the waiting version now and reloads the page. */
  applyUpdate(): void;
  /** Asks the server for a newer worker. Never rejects. */
  checkForUpdate(): Promise<void>;
  /** Stops the update checks and listeners. The worker stays registered. */
  stop(): void;
}

const HOUR_MS = 3_600_000;
/** Longest wait for an idle moment after load. */
const IDLE_TIMEOUT_MS = 2_000;

/** Resolves after the load event, then an idle moment (or IDLE_TIMEOUT_MS). */
function afterLoadAndIdle(host: RegisterHost): Promise<void> {
  const loaded =
    host.document.readyState === 'complete'
      ? Promise.resolve()
      : new Promise<void>((resolve) => {
          host.addEventListener(
            'load',
            () => {
              resolve();
            },
            { once: true },
          );
        });
  return loaded.then(
    () =>
      new Promise<void>((resolve) => {
        if (host.requestIdleCallback !== undefined) {
          host.requestIdleCallback(
            () => {
              resolve();
            },
            { timeout: IDLE_TIMEOUT_MS },
          );
        } else {
          host.setTimeout(resolve, 0);
        }
      }),
  );
}

/**
 * Registers the worker at `<base>sw.js` after load. Resolves to null where
 * service workers are unavailable (dev builds, insecure origins, old or
 * locked-down browsers) or registration fails; the site works without one.
 */
export async function registerServiceWorker(
  options: RegisterOptions = {},
): Promise<ServiceWorkerHandle | null> {
  const host: RegisterHost = options.host ?? window;
  const enabled = options.enabled ?? import.meta.env.PROD;
  const base = options.base ?? import.meta.env.BASE_URL;
  const checkEveryMs = options.checkEveryMs ?? HOUR_MS;
  const container = host.navigator.serviceWorker;
  if (!enabled || container === undefined) return null;

  await afterLoadAndIdle(host);
  let registration: ServiceWorkerRegistration;
  try {
    registration = await container.register(`${base}${SW_FILE}`, {
      scope: base,
      updateViaCache: 'none',
    });
  } catch (error) {
    console.warn('Snowlight: offline support unavailable', error);
    return null;
  }

  let controlled = container.controller !== null;
  let warmedCount: (count: number) => void = () => undefined;
  const warmed = controlled
    ? Promise.resolve(0)
    : new Promise<number>((resolve) => {
        warmedCount = resolve;
      });
  let updateReady = false;
  let reloadWhenHidden = false;
  let reloading = false;
  let lastCheck = Date.now();
  const hidden = (): boolean => host.document.visibilityState === 'hidden';

  const reload = (): void => {
    if (reloading) return;
    reloading = true;
    host.location.reload();
  };
  const skipWaiting = (): void => {
    registration.waiting?.postMessage(SKIP_WAITING_MESSAGE);
  };
  const markReady = (): void => {
    if (updateReady) return;
    updateReady = true;
    options.onUpdateReady?.();
    if (options.applyWhenHidden === true && hidden()) skipWaiting();
  };
  /** A worker that finishes installing while an older one controls the page is an update. */
  const track = (worker: ServiceWorker | null): void => {
    if (worker === null) return;
    const check = (): void => {
      if (worker.state === 'installed' && container.controller !== null) markReady();
    };
    worker.addEventListener('statechange', check);
    check();
  };

  const onUpdateFound = (): void => {
    track(registration.installing);
  };
  const onControllerChange = (): void => {
    if (!controlled) {
      // The first worker just claimed this page: cache what the page loaded before it.
      controlled = true;
      void warmDataCache(base, options.warmUrls, host).then(warmedCount, () => {
        warmedCount(0);
      });
      return;
    }
    // A new version took over (applyUpdate, or another tab switched).
    if (hidden()) reload();
    else reloadWhenHidden = true;
  };
  const checkForUpdate = async (): Promise<void> => {
    lastCheck = Date.now();
    if (!host.navigator.onLine) return;
    try {
      await registration.update();
    } catch {
      // Offline or the server is unreachable; the next check tries again.
    }
  };
  const onVisibilityChange = (): void => {
    if (hidden()) {
      if (reloadWhenHidden) reload();
      else if (updateReady && options.applyWhenHidden === true) skipWaiting();
    } else if (Date.now() - lastCheck >= checkEveryMs) {
      void checkForUpdate();
    }
  };

  if (registration.waiting !== null && container.controller !== null) markReady();
  track(registration.installing);
  registration.addEventListener('updatefound', onUpdateFound);
  container.addEventListener('controllerchange', onControllerChange);
  host.document.addEventListener('visibilitychange', onVisibilityChange);
  const interval = host.setInterval(() => {
    if (!hidden()) void checkForUpdate();
  }, checkEveryMs);

  return {
    registration,
    warmed,
    get updateReady() {
      return updateReady;
    },
    applyUpdate() {
      if (registration.waiting === null) return;
      reloadWhenHidden = false;
      container.addEventListener('controllerchange', reload, { once: true });
      skipWaiting();
    },
    checkForUpdate,
    stop() {
      host.clearInterval(interval);
      registration.removeEventListener('updatefound', onUpdateFound);
      container.removeEventListener('controllerchange', onControllerChange);
      host.document.removeEventListener('visibilitychange', onVisibilityChange);
    },
  };
}
