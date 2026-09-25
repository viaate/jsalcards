/**
 * Stand-ins for the service worker API and the window, for unit tests. They
 * model what registration relies on: worker states and their events, the
 * page's controller, and the visibility of the tab.
 */
import { vi } from 'vitest';

import type { RegisterHost } from '../register';

export class FakeWorker extends EventTarget {
  state: ServiceWorkerState = 'installing';
  readonly messages: unknown[] = [];

  postMessage(message: unknown): void {
    this.messages.push(message);
  }

  to(state: ServiceWorkerState): void {
    this.state = state;
    this.dispatchEvent(new Event('statechange'));
  }
}

export class FakeRegistration extends EventTarget {
  installing: FakeWorker | null = null;
  waiting: FakeWorker | null = null;
  active: FakeWorker | null = null;
  updates = 0;
  failUpdate = false;

  update(): Promise<void> {
    this.updates += 1;
    return this.failUpdate ? Promise.reject(new TypeError('Failed to fetch')) : Promise.resolve();
  }

  /** A new worker starts installing, as after a deploy. */
  found(): FakeWorker {
    const worker = new FakeWorker();
    this.installing = worker;
    this.dispatchEvent(new Event('updatefound'));
    return worker;
  }

  /** The installing worker finishes installing and waits. */
  installed(): FakeWorker {
    const worker = this.installing;
    if (worker === null) throw new Error('nothing installing');
    this.installing = null;
    this.waiting = worker;
    worker.to('installed');
    return worker;
  }
}

export class FakeContainer extends EventTarget {
  controller: FakeWorker | null = null;
  readonly registration = new FakeRegistration();
  readonly calls: [string, RegistrationOptions | undefined][] = [];
  failRegister = false;

  register(url: string, options?: RegistrationOptions): Promise<FakeRegistration> {
    this.calls.push([url, options]);
    return this.failRegister
      ? Promise.reject(new DOMException('The operation is insecure.', 'SecurityError'))
      : Promise.resolve(this.registration);
  }

  /** `worker` becomes the controller, as clients.claim() or skipWaiting() does. */
  control(worker: FakeWorker): void {
    this.controller = worker;
    this.dispatchEvent(new Event('controllerchange'));
  }

  /** Posts a message to the page, as the worker does. */
  message(data: unknown): void {
    this.dispatchEvent(new MessageEvent('message', { data }));
  }
}

export interface FakeWindowOptions {
  readyState?: DocumentReadyState;
  resources?: string[];
  serviceWorker?: boolean;
}

export class FakeDocument extends EventTarget {
  readyState: DocumentReadyState = 'complete';
  visibilityState: DocumentVisibilityState = 'visible';
}

export class FakeWindow extends EventTarget implements RegisterHost {
  readonly container = new FakeContainer();
  readonly navigator: RegisterHost['navigator'] & { onLine: boolean };
  readonly document = new FakeDocument();
  readonly location = { href: 'https://snow.test/?school=010000500870', reload: vi.fn() };
  readonly performance: Pick<Performance, 'getEntriesByType'>;
  readonly fetch = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
  readonly fetched: string[] = [];
  requestIdleCallback = (callback: () => void): number =>
    setTimeout(callback, 5) as unknown as number;

  constructor(options: FakeWindowOptions = {}) {
    super();
    this.document.readyState = options.readyState ?? 'complete';
    this.navigator = {
      onLine: true,
      ...(options.serviceWorker === false
        ? {}
        : { serviceWorker: this.container as unknown as ServiceWorkerContainer }),
    };
    const resources = options.resources ?? [];
    this.performance = {
      getEntriesByType: (type: string) =>
        type === 'resource' ? resources.map((name) => ({ name }) as PerformanceEntry) : [],
    };
    this.fetch.mockImplementation((input: string) => {
      this.fetched.push(input);
      return Promise.resolve(new Response('{}'));
    });
  }

  setTimeout(handler: () => void, timeout: number): number {
    return setTimeout(handler, timeout) as unknown as number;
  }

  setInterval(handler: () => void, timeout: number): number {
    return setInterval(handler, timeout) as unknown as number;
  }

  clearInterval(id: number | undefined): void {
    clearInterval(id);
  }

  load(): void {
    this.document.readyState = 'complete';
    this.dispatchEvent(new Event('load'));
  }

  setVisibility(state: DocumentVisibilityState): void {
    this.document.visibilityState = state;
    this.document.dispatchEvent(new Event('visibilitychange'));
  }
}
